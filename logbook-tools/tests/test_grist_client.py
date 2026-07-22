"""Unit tests for GristClient upsert semantics, using a fake transport."""

from __future__ import annotations

from typing import Any

from logbook_import.grist_client import GristClient
from logbook_import.grist_settings import GristSettings


class FakeClient(GristClient):
    """GristClient with the HTTP layer replaced by canned responses."""

    def __init__(self, existing: dict[str, int], next_id: int = 100) -> None:
        super().__init__(GristSettings(url="http://test", api_key="k", doc_id="d"))
        self._existing = dict(existing)
        self._next_id = next_id
        self.calls: list[tuple[str, str, Any]] = []

    def _request(self, method: str, path: str, body: Any | None = None) -> Any:
        self.calls.append((method, path, body))
        if path.endswith("/sql"):
            key_col = "Trip_Key"  # tests use one key column
            keys = body["args"]
            return {
                "records": [
                    {"fields": {"id": rid, key_col: key}}
                    for key, rid in self._existing.items()
                    if key in keys
                ]
            }
        if method == "POST" and path.endswith("/records"):
            ids = []
            for _ in body["records"]:
                ids.append(self._next_id)
                self._next_id += 1
            return {"records": [{"id": i} for i in ids]}
        if method == "PATCH":
            return None
        raise AssertionError(f"unexpected call {method} {path}")


def test_upsert_all_new() -> None:
    client = FakeClient(existing={})
    result = client.upsert_by_key(
        "Trips",
        [{"Trip_Key": "A|1"}, {"Trip_Key": "B|2"}],
        "Trip_Key",
    )
    assert result.created == 2
    assert result.updated == 0
    assert result.key_to_id == {"A|1": 100, "B|2": 101}


def test_upsert_all_existing() -> None:
    client = FakeClient(existing={"A|1": 7, "B|2": 8})
    result = client.upsert_by_key(
        "Trips",
        [{"Trip_Key": "A|1", "Base": "MSP"}, {"Trip_Key": "B|2", "Base": "MSP"}],
        "Trip_Key",
    )
    assert result.created == 0
    assert result.updated == 2
    assert result.key_to_id == {"A|1": 7, "B|2": 8}
    # updates went to PATCH with the existing row ids
    patch = next(c for c in client.calls if c[0] == "PATCH")
    assert [r["id"] for r in patch[2]["records"]] == [7, 8]


def test_upsert_mixed_create_and_update() -> None:
    client = FakeClient(existing={"A|1": 7})
    result = client.upsert_by_key(
        "Trips",
        [{"Trip_Key": "A|1"}, {"Trip_Key": "NEW|9"}],
        "Trip_Key",
    )
    assert result.created == 1
    assert result.updated == 1
    assert result.key_to_id["A|1"] == 7
    assert result.key_to_id["NEW|9"] == 100


def test_upsert_empty_payloads_no_calls() -> None:
    client = FakeClient(existing={})
    result = client.upsert_by_key("Trips", [], "Trip_Key")
    assert result.created == 0 and result.updated == 0
    assert client.calls == []
