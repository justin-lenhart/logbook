"""The one-click export endpoint: what it will and will not do.

The service is reachable (over Tailscale) by anything in the browser, so the
tests that matter here are the refusals: no target but a known one, no Host
but its own, no page but the ones it is framed in, and nothing that could
write to Grist.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import pytest

from logbook_import import export_service, profiles
from logbook_import.export_service import LABELS, ServiceConfig, build_server, render_page
from logbook_import.profile_export import ExportResult, deliver, prepare_outbox

HOST = "127.0.0.1"


@pytest.fixture
def outbox(tmp_path: Path) -> Path:
    return tmp_path / "Logbook-Outbox"


@pytest.fixture
def config(outbox: Path) -> ServiceConfig:
    return ServiceConfig(host=HOST, port=0, outbox=outbox)


@pytest.fixture
def service(config: ServiceConfig, monkeypatch, tmp_path: Path):
    """A running server plus the list of (target, kwargs) exports it ran."""
    calls: list[tuple[str, dict]] = []

    def fake_build_export(client, target, **kwargs):
        calls.append((target, kwargs))
        path = tmp_path / f"logbook-{target}-2026-11-12.html"
        path.write_text("<!doctype html>", encoding="utf-8")
        delivered = deliver(path, kwargs["outbox"]) if kwargs.get("outbox") else None
        return ExportResult(
            target=target, as_of=date(2026, 11, 12), path=path,
            delivered=delivered, flights=2, hours=3.0, pic=1.0, sic=2.0,
            dual=0.0, warnings=("flight 7 has no Aircraft link",),
        )

    monkeypatch.setattr(export_service, "build_export", fake_build_export)
    server = build_server(config, client_factory=lambda: object())
    port = server.server_address[1]
    # The handler's config carries the port it was built with, so rebuild it
    # on the port the OS actually handed out.
    server.RequestHandlerClass.config = ServiceConfig(
        host=HOST, port=port, outbox=config.outbox)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{HOST}:{port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request(url: str, *, method: str = "GET", body: bytes | None = None,
            headers: dict[str, str] | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    for name, value in (headers or {}).items():
        req.add_header(name, value)
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, res.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def export(url: str, target: str, **kwargs) -> tuple[int, dict]:
    status, text = request(f"{url}/export", method="POST",
                           body=f"target={target}".encode(), **kwargs)
    return status, json.loads(text)


# -- the page ---------------------------------------------------------------

def test_every_target_has_a_button_label() -> None:
    """A new target must be named before it can appear on the page."""
    assert set(LABELS) == set(profiles.TARGETS)


def test_page_offers_one_button_per_target(config: ServiceConfig) -> None:
    html = render_page(config)
    for target in profiles.TARGETS:
        assert f'data-target="{target}"' in html, target
        assert LABELS[target] in html
    assert "Generic logbook" in html


def test_page_is_self_contained(config: ServiceConfig) -> None:
    """It is framed inside Grist: no external script, style or font."""
    html = render_page(config)
    for marker in ("http://", "https://", "//cdn", "<link"):
        assert marker not in html, marker


def test_page_is_served(service) -> None:
    url, _ = service
    status, html = request(f"{url}/")
    assert status == 200
    assert html.startswith("<!doctype html>")


def test_healthz_lists_the_targets(service) -> None:
    url, _ = service
    status, text = request(f"{url}/healthz")
    assert status == 200
    assert json.loads(text) == {"ok": True, "targets": list(profiles.TARGETS)}


# -- running an export ------------------------------------------------------

def test_a_click_exports_and_delivers(service, outbox: Path) -> None:
    url, calls = service
    status, payload = export(url, "jetblue")
    assert status == 200
    assert payload["ok"] and payload["target"] == "jetblue"
    assert payload["summary"] == "2 flights, total 3.0 h (PIC 1.0 / SIC 2.0 / dual 0.0)"
    assert payload["warnings"] == ["flight 7 has no Aircraft link"]
    assert calls == [("jetblue", {"output_dir": None, "pilot_path": None,
                                 "include_log": True, "outbox": outbox})]
    landed = outbox / "logbook-jetblue-2026-11-12.html"
    assert landed.is_file()
    assert payload["file"] == str(landed)


def test_the_generic_logbook_is_one_click_too(service) -> None:
    url, calls = service
    status, payload = export(url, "generic")
    assert status == 200 and payload["ok"]
    assert [target for target, _ in calls] == ["generic"]


@pytest.mark.parametrize("target", ["delta", "", "faa jetblue", "../etc/passwd",
                                    "faa;import-actual", "FAA"])
def test_only_a_known_target_is_ever_run(service, target: str) -> None:
    """Nothing the caller sends reaches an export unless it is a real target."""
    url, calls = service
    status, payload = export(url, target)
    assert status == 400
    assert not payload["ok"] and "Unknown target" in payload["error"]
    assert calls == []


def test_a_pending_target_cannot_be_exported(service) -> None:
    url, _ = service
    for target in profiles.PENDING_TARGETS:
        status, _payload = export(url, target)
        assert status == 400, target


def test_two_targets_in_one_request_are_refused(service) -> None:
    url, calls = service
    status, _ = request(f"{url}/export", method="POST", body=b"target=faa&target=ual")
    assert status == 400
    assert calls == []


def test_json_bodies_work_too(service) -> None:
    url, calls = service
    status, text = request(f"{url}/export", method="POST",
                           body=b'{"target": "swa"}',
                           headers={"Content-Type": "application/json"})
    assert status == 200 and json.loads(text)["ok"]
    assert [target for target, _ in calls] == ["swa"]


def test_an_oversized_body_is_refused(service) -> None:
    url, calls = service
    status, _ = request(f"{url}/export", method="POST",
                        body=b"target=" + b"a" * (export_service.MAX_BODY + 1))
    assert status == 400
    assert calls == []


def test_no_other_path_does_anything(service) -> None:
    url, calls = service
    for path, method in (("/import-actual", "POST"), ("/export-map", "POST"),
                         ("/exports/logbook-faa-2026-11-12.html", "GET"),
                         ("/../pilot.toml", "GET")):
        status, _ = request(f"{url}{path}", method=method,
                            body=b"" if method == "POST" else None)
        assert status in (400, 404), path
    assert calls == []


def test_export_is_refused_on_a_get(service) -> None:
    url, calls = service
    status, _ = request(f"{url}/export?target=faa")
    assert status == 404
    assert calls == []


# -- who is allowed to ask --------------------------------------------------

def test_another_hostname_is_refused(service) -> None:
    """Like Grist: this service answers to its own address and nothing else."""
    url, calls = service
    status, payload = export(url, "faa", headers={"Host": "logbook.example.com"})
    assert status == 400
    assert "Host validation failed" in payload["error"]
    assert calls == []


def test_grist_and_the_homepage_may_drive_the_button(service) -> None:
    url, _ = service
    for port in (export_service.GRIST_PORT, export_service.HOMEPAGE_PORT):
        status, payload = export(url, "faa",
                                 headers={"Origin": f"http://{HOST}:{port}"})
        assert status == 200 and payload["ok"], port


def test_a_sandboxed_frame_may_drive_the_button(service) -> None:
    url, _ = service
    status, payload = export(url, "faa", headers={"Origin": "null"})
    assert status == 200 and payload["ok"]


def test_another_site_cannot_drive_the_button(service) -> None:
    url, calls = service
    status, payload = export(url, "faa",
                             headers={"Origin": "http://evil.example.com"})
    assert status == 403
    assert "Origin not allowed" in payload["error"]
    assert calls == []


def test_allowed_hosts_and_origins_are_the_service_and_its_frames() -> None:
    config = ServiceConfig(host="100.78.232.7", port=8486,
                           outbox=Path("/tmp/outbox"))
    assert config.allowed_hosts == {"100.78.232.7:8486"}
    assert config.allowed_origins == {
        "null", "http://100.78.232.7:8486",
        "http://100.78.232.7:8484", "http://100.78.232.7:3001",
    }
    extra = ServiceConfig(host="100.78.232.7", port=8486,
                          outbox=Path("/tmp/outbox"),
                          extra_hosts=("mintbox:8486",),
                          extra_origins=("http://mintbox:8484",))
    assert "mintbox:8486" in extra.allowed_hosts
    assert "http://mintbox:8484" in extra.allowed_origins


def test_the_service_binds_one_address_not_every_interface(config, monkeypatch) -> None:
    bound: list[tuple[str, int]] = []

    class FakeServer:
        def __init__(self, address, handler):
            bound.append(address)
            self.RequestHandlerClass = handler

    monkeypatch.setattr(export_service, "ThreadingHTTPServer", FakeServer)
    build_server(config, client_factory=lambda: object())
    assert bound == [(HOST, 0)]
    assert "0.0.0.0" not in {host for host, _ in bound}


# -- delivery ---------------------------------------------------------------

def test_delivery_is_atomic_and_private(tmp_path: Path, outbox: Path) -> None:
    export_file = tmp_path / "logbook-faa-2026-11-12.html"
    export_file.write_text("<!doctype html>x", encoding="utf-8")
    landed = deliver(export_file, outbox)
    assert landed.read_text() == "<!doctype html>x"
    assert oct(landed.stat().st_mode)[-3:] == "600"
    # No half-written file is left for Syncthing to pick up.
    assert [p.name for p in sorted(outbox.iterdir())] == [
        ".stignore", "logbook-faa-2026-11-12.html"]


def test_the_outbox_tells_syncthing_to_skip_part_files(outbox: Path) -> None:
    prepare_outbox(outbox)
    assert "*.part" in (outbox / ".stignore").read_text()
    assert oct(outbox.stat().st_mode)[-3:] == "700"


def test_re_exporting_the_same_day_replaces_the_file(tmp_path: Path, outbox: Path) -> None:
    export_file = tmp_path / "logbook-faa-2026-11-12.html"
    export_file.write_text("first", encoding="utf-8")
    deliver(export_file, outbox)
    export_file.write_text("second", encoding="utf-8")
    assert deliver(export_file, outbox).read_text() == "second"
