from __future__ import annotations

import json
import subprocess
import sys
import traceback
from datetime import date
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for

from logbook_import.app_config import is_configured, load_app_config, save_app_config
from logbook_import.parsers.registry import get_parser_choices


def create_app() -> Flask:
    template_dir = Path(__file__).parent / "web"
    app = Flask(__name__, template_folder=str(template_dir))
    app.secret_key = "logbook-local-only"

    # --- Page routes ---

    @app.route("/")
    def dashboard():
        if not is_configured():
            return redirect(url_for("config_page") + "?first_run=1")
        cfg = load_app_config()
        inbox = Path(cfg["paths"]["inbox"])
        inbox_files = sorted(inbox.glob("*")) if inbox.exists() else []
        inbox_count = len([f for f in inbox_files if f.suffix.lower() in {".txt", ".csv"}])
        map_url = cfg["map"].get("url", "")
        return render_template(
            "dashboard.html",
            inbox_count=inbox_count,
            map_url=map_url,
            cfg=cfg,
        )

    @app.route("/import")
    def import_page():
        if not is_configured():
            return redirect(url_for("config_page") + "?first_run=1")
        cfg = load_app_config()
        inbox = Path(cfg["paths"]["inbox"])
        inbox_files = []
        if inbox.exists():
            inbox_files = sorted(
                [f.name for f in inbox.iterdir() if f.suffix.lower() in {".txt", ".csv"}]
            )
        return render_template(
            "import_page.html",
            inbox_files=inbox_files,
            cfg=cfg,
        )

    @app.route("/map")
    def map_page():
        if not is_configured():
            return redirect(url_for("config_page") + "?first_run=1")
        cfg = load_app_config()
        return render_template("map.html", map_url=cfg["map"].get("url", ""))

    @app.route("/config")
    def config_page():
        cfg = load_app_config()
        first_run = request.args.get("first_run") == "1"
        parser_choices = get_parser_choices()
        return render_template(
            "config.html",
            cfg=cfg,
            first_run=first_run,
            parser_choices=parser_choices,
        )

    # --- API routes ---

    @app.route("/api/config", methods=["GET"])
    def api_config_get():
        cfg = load_app_config()
        # Never expose the API key in the response body
        safe = json.loads(json.dumps(cfg))
        safe["airtable"]["api_key"] = "***" if cfg["airtable"]["api_key"] else ""
        return jsonify(safe)

    @app.route("/api/config", methods=["POST"])
    def api_config_save():
        data = request.get_json(force=True)
        cfg = load_app_config()

        # Only update API key if a real value was submitted (not the masked placeholder)
        if data.get("airtable", {}).get("api_key", "").strip("*"):
            cfg["airtable"]["api_key"] = data["airtable"]["api_key"].strip()
        if data.get("airtable", {}).get("base_id"):
            cfg["airtable"]["base_id"] = data["airtable"]["base_id"].strip()
        if data.get("paths", {}).get("inbox"):
            cfg["paths"]["inbox"] = data["paths"]["inbox"].strip()
        if data.get("pilot", {}).get("role"):
            cfg["pilot"]["role"] = data["pilot"]["role"].strip().lower()
        if data.get("pilot", {}).get("operator"):
            cfg["pilot"]["operator"] = data["pilot"]["operator"].strip().lower()
        if data.get("import", {}).get("format"):
            cfg["import"]["format"] = data["import"]["format"].strip()
        cfg["map"]["url"] = data.get("map", {}).get("url", "").strip()

        save_app_config(cfg)
        return jsonify({"ok": True})

    @app.route("/api/inbox")
    def api_inbox():
        cfg = load_app_config()
        inbox = Path(cfg["paths"]["inbox"])
        if not inbox.exists():
            return jsonify({"files": [], "warning": f"Inbox folder not found: {inbox}"})
        files = sorted(
            [f.name for f in inbox.iterdir() if f.suffix.lower() in {".txt", ".csv"}]
        )
        return jsonify({"files": files, "inbox_path": str(inbox)})

    @app.route("/api/import/dry-run", methods=["POST"])
    def api_dry_run():
        return _run_import_api(commit=False)

    @app.route("/api/import/commit", methods=["POST"])
    def api_commit():
        return _run_import_api(commit=True)

    @app.route("/api/map/geojson")
    def api_map_geojson():
        try:
            from logbook_import.airport_map import (
                aggregate_route_stats,
                build_geojson,
                fetch_flight_records,
                resolve_airports,
            )
            from logbook_import.airtable_airports import fetch_airport_index
            from logbook_import.airtable_settings import load_airtable_settings

            settings = load_airtable_settings()
            airport_index = fetch_airport_index(settings.api_key, settings.base_id)
            flight_records = fetch_flight_records(settings.api_key, settings.base_id, airport_index)
            if not flight_records:
                return jsonify({"type": "FeatureCollection", "features": []})
            route_stats = aggregate_route_stats(flight_records)
            resolved, _ = resolve_airports(route_stats, airport_index)
            geojson = build_geojson(resolved, route_stats)
            return jsonify(geojson)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    return app


def _run_import_api(*, commit: bool):
    try:
        body = request.get_json(force=True) or {}
        role_str = body.get("role", "").strip().lower()
        operator_str = body.get("operator", "").strip().lower()
        mode_str = body.get("mode", "actual").strip().lower()

        from logbook_import.airtable_airports import fetch_airport_index
        from logbook_import.airtable_settings import load_airtable_settings
        from logbook_import.app_config import load_app_config
        from logbook_import.config import RECORDED_DIR, discover_pairing_file_sets, move_processed_files
        from logbook_import.dry_run import format_run_summary
        from logbook_import.import_planner import build_plans_for_exports
        from logbook_import.models import CrewRole, ImportMode, Operator
        from logbook_import.parsers.merge import load_pairing_export

        cfg = load_app_config()
        if not role_str:
            role_str = cfg["pilot"].get("role", "sic")
        if not operator_str:
            operator_str = cfg["pilot"].get("operator", "skw")

        mode = ImportMode.ACTUAL if mode_str == "actual" else ImportMode.PLANNED
        crew_role = CrewRole(role_str)
        op = Operator(operator_str) if operator_str else None

        inbox_path = Path(cfg["paths"]["inbox"])
        file_sets, inbox_warnings = discover_pairing_file_sets(inbox=inbox_path)
        if not file_sets:
            return jsonify({"ok": False, "output": "No valid pairing files found in inbox."})

        pairings = []
        warnings = list(inbox_warnings)
        for fs in file_sets:
            pairing, w = load_pairing_export(fs)
            pairings.append(pairing)
            warnings.extend(w)

        try:
            settings = load_airtable_settings()
            airport_index = fetch_airport_index(settings.api_key, settings.base_id)
        except Exception as exc:
            if commit:
                return jsonify({"ok": False, "output": f"Cannot reach Airtable: {exc}"})
            settings = None
            airport_index = None
            warnings.append(f"Could not load airport index — times will be NAIVE LOCAL, NOT UTC: {exc}")

        plans = build_plans_for_exports(
            pairings, mode, role=crew_role, operator=op, airport_index=airport_index
        )
        for plan in plans:
            warnings.extend(plan.warnings)

        if not commit:
            output = format_run_summary(plans, warnings)
            return jsonify({"ok": True, "output": output})

        # Abort commit if naive times detected
        if mode == ImportMode.ACTUAL:
            naive = [w for w in warnings if "times left naive" in w]
            if naive:
                return jsonify({"ok": False, "output": "\n".join(naive) + "\n\nAborting: flight times could not be converted to UTC."})

        from logbook_import.airtable_sync import AirtableImporter, format_commit_summary

        assert settings is not None
        importer = AirtableImporter(settings, include_equipment_family=True, airport_index=airport_index)
        results = [importer.sync_plan(plan) for plan in plans]
        summary = format_commit_summary(results)

        if warnings:
            warn_block = "\n".join(f"WARN: {w}" for w in warnings)
            summary = f"{warn_block}\n\n{summary}"

        dest_dir = RECORDED_DIR / mode.value
        moved = move_processed_files(plans, dest_dir)
        if moved:
            summary += f"\n\nMoved {len(moved)} file(s) to recorded/{mode.value}/"

        return jsonify({"ok": True, "output": summary})

    except Exception as exc:
        tb = traceback.format_exc()
        return jsonify({"ok": False, "output": f"Unexpected error:\n{exc}\n\n{tb}"}), 500
