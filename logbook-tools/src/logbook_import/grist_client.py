"""Thin Grist REST client (stdlib only) with Airtable-style upsert semantics.

Grist's native PUT-records upsert returns no record ids, but the import flow
needs ids and created/updated counts (``PlanSyncResult``). So ``upsert_by_key``
does it manually: read the existing ``key -> row id`` map, split payloads into
creates (POST) and updates (PATCH), and return both counts and the merged map.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from logbook_import.grist_settings import GristSettings


class GristApiError(RuntimeError):
    def __init__(self, status: int, method: str, path: str, detail: str) -> None:
        super().__init__(f"Grist API {status} on {method} {path}: {detail}")
        self.status = status


@dataclass
class UpsertResult:
    created_ids: list[int] = field(default_factory=list)
    updated_ids: list[int] = field(default_factory=list)
    key_to_id: dict[str, int] = field(default_factory=dict)

    @property
    def created(self) -> int:
        return len(self.created_ids)

    @property
    def updated(self) -> int:
        return len(self.updated_ids)


class GristClient:
    def __init__(self, settings: GristSettings, *, timeout: int = 120) -> None:
        self._settings = settings
        self._timeout = timeout

    # -- transport (overridden in tests) ------------------------------------
    def _request(self, method: str, path: str, body: Any | None = None) -> Any:
        url = f"{self._settings.url}{path}"
        req = urllib.request.Request(
            url,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {self._settings.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:  # pragma: no cover - network path
            raise GristApiError(
                exc.code, method, path, exc.read().decode(errors="replace")[:400]
            ) from exc
        return json.loads(raw) if raw else None

    # -- basic endpoints -----------------------------------------------------
    def _doc_path(self, suffix: str) -> str:
        return f"/api/docs/{self._settings.doc_id}{suffix}"

    def get_records(
        self, table: str, *, filter_: dict[str, list[Any]] | None = None
    ) -> list[dict[str, Any]]:
        path = self._doc_path(f"/tables/{table}/records")
        if filter_:
            path += "?filter=" + urllib.parse.quote(json.dumps(filter_))
        return self._request("GET", path)["records"]

    def add_records(self, table: str, fields_list: list[dict[str, Any]]) -> list[int]:
        if not fields_list:
            return []
        resp = self._request(
            "POST",
            self._doc_path(f"/tables/{table}/records"),
            {"records": [{"fields": f} for f in fields_list]},
        )
        return [r["id"] for r in resp["records"]]

    def update_records(
        self, table: str, updates: list[tuple[int, dict[str, Any]]]
    ) -> None:
        if not updates:
            return
        # Grist requires every record in one PATCH to share the same field set.
        # Payloads legitimately differ (e.g. deadhead flights omit tail/aircraft),
        # so group by field-key-set and send one PATCH per group — never
        # null-fill, which would clear real values.
        groups: dict[frozenset[str], list[tuple[int, dict[str, Any]]]] = {}
        for rid, fields in updates:
            groups.setdefault(frozenset(fields), []).append((rid, fields))
        for group in groups.values():
            self._request(
                "PATCH",
                self._doc_path(f"/tables/{table}/records"),
                {"records": [{"id": rid, "fields": f} for rid, f in group]},
            )

    def sql(self, query: str, args: list[Any] | None = None) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"sql": query}
        if args is not None:
            body["args"] = args
        resp = self._request("POST", self._doc_path("/sql"), body)
        return [r["fields"] for r in resp["records"]]

    # -- Airtable-style upsert ----------------------------------------------
    def fetch_key_index(self, table: str, key_col: str, keys: list[str]) -> dict[str, int]:
        """Map existing key values -> Grist row ids (only for the given keys)."""
        if not keys:
            return {}
        placeholders = ", ".join("?" for _ in keys)
        rows = self.sql(
            f'SELECT id, "{key_col}" FROM "{table}" WHERE "{key_col}" IN ({placeholders})',
            list(keys),
        )
        return {str(r[key_col]): int(r["id"]) for r in rows if r.get(key_col)}

    def upsert_by_key(
        self, table: str, payloads: list[dict[str, Any]], key_col: str
    ) -> UpsertResult:
        result = UpsertResult()
        if not payloads:
            return result
        keys = [str(p[key_col]) for p in payloads]
        existing = self.fetch_key_index(table, key_col, keys)

        creates = [p for p in payloads if str(p[key_col]) not in existing]
        updates = [
            (existing[str(p[key_col])], p) for p in payloads if str(p[key_col]) in existing
        ]

        created_ids = self.add_records(table, creates)
        self.update_records(table, updates)

        result.created_ids = created_ids
        result.updated_ids = [rid for rid, _ in updates]
        result.key_to_id = dict(existing)
        for payload, rid in zip(creates, created_ids):
            result.key_to_id[str(payload[key_col])] = rid
        return result
