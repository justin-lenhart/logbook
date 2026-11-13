"""The one-click export endpoint that runs on the home server.

An export used to mean SSH-ing to crushbox, typing a command and then
hunting for the file. This serves a small page with one button per target —
added to the Grist doc as a custom widget, and linked from the homepage
dashboard — and on a click renders the export and drops it in the Syncthing
outbox, which carries it to the Mac.

Safety, in the order it matters:

- **Read-only.** The only thing a caller can start is one ``export-profile``
  run, which never writes to Grist. There is no importer here, no
  ``--commit`` and no path the caller gets to name.
- **Tailscale only.** It binds one address — the tailnet IP, like Grist —
  and refuses any request whose ``Host`` header is not that address, so a
  page elsewhere cannot reach it through a name that resolves here. Grist
  does the same ("Domain not recognized"); the error reads the same way.
- **Nothing from the caller reaches a shell.** The target is looked up in
  ``profiles.TARGETS`` and the export runs in this process — there is no
  subprocess to quote and nothing to escape.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from logbook_import import profiles
from logbook_import.profile_export import ExportError, build_export, prepare_outbox

# What each button says. A target with no label here would reach the page as
# a bare id, so test_export_service.py asserts this covers profiles.TARGETS.
LABELS: dict[str, str] = {
    "generic": "Generic logbook",
    "faa": "FAA 8710 / IACRA",
    "ual": "United",
    "swa": "Southwest",
    "allegiant": "Allegiant",
    "jetblue": "JetBlue",
    "aal": "American",
}

# Button grid geometry. BUTTON_MIN is the narrowest a button may be before
# the grid reflows; GRID_MAX is sized to fit exactly GRID_COLUMNS of them with
# GRID_GAP between, and nothing wider. test_export_service.py checks that
# arithmetic, so the row cannot quietly become four wide or one long row again.
GRID_COLUMNS = 3
GRID_GAP = 8
BUTTON_MIN = 140
GRID_MAX = GRID_COLUMNS * BUTTON_MIN + (GRID_COLUMNS - 1) * GRID_GAP + 40

# A click posts a form body, so no preflight and no CORS to get wrong.
MAX_BODY = 4096

# Ports of the two front ends this page is meant to be opened from, both
# Tailscale-only on the same host (see /srv/homelab/stacks/).
GRIST_PORT = 8484
HOMEPAGE_PORT = 3001


@dataclass(frozen=True)
class ServiceConfig:
    host: str
    port: int
    outbox: Path
    output_dir: Path | None = None
    pilot_path: Path | None = None
    include_log: bool = True
    extra_hosts: tuple[str, ...] = ()
    extra_origins: tuple[str, ...] = ()
    targets: tuple[str, ...] = field(default_factory=lambda: profiles.TARGETS)

    @property
    def allowed_hosts(self) -> frozenset[str]:
        """Host headers this service answers to — its own address, no more."""
        return frozenset({f"{self.host}:{self.port}", *self.extra_hosts})

    @property
    def allowed_origins(self) -> frozenset[str]:
        """Pages allowed to drive the button: this page, Grist, the homepage.

        A sandboxed iframe sends ``null``, which is allowed too: Grist frames
        a custom widget without a sandbox attribute in the deployed build,
        but a later version that adds one should not break the button.
        """
        return frozenset({
            "null",
            f"http://{self.host}:{self.port}",
            f"http://{self.host}:{GRIST_PORT}",
            f"http://{self.host}:{HOMEPAGE_PORT}",
            *self.extra_origins,
        })


ClientFactory = Callable[[], object]


def _default_client_factory() -> object:
    from logbook_import.grist_client import GristClient
    from logbook_import.grist_settings import load_grist_settings

    return GristClient(load_grist_settings())


def render_page(config: ServiceConfig) -> str:
    """The picker: one button per target, no external resources.

    Self-contained on purpose — it is framed inside Grist and opened from the
    homepage, neither of which should have to reach the internet for it.
    """
    buttons = "".join(
        f'<button type="button" data-target="{t}">{LABELS.get(t, t)}</button>'
        for t in config.targets
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Export logbook</title>
<style>
  :root {{ color-scheme: light dark; --edge: #c7ccd1; --ink: #1d2125; --bg: #fff;
           --accent: #1a73a8; --muted: #5b6670; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --edge: #3a4149; --ink: #e8eaed; --bg: #1b1f24;
             --accent: #6db3e0; --muted: #9aa5b1; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 14px; background: var(--bg); color: var(--ink);
         font: 14px/1.45 -apple-system, "Segoe UI", system-ui, sans-serif; }}
  h1 {{ font-size: 14px; font-weight: 600; margin: 0 0 2px; }}
  p.lede {{ margin: 0 0 12px; color: var(--muted); font-size: 12px; }}
  /* Three buttons to a row. The width cap is what holds it to three: the
     widget is framed in a pane far wider than this page needs, and without
     it auto-fit spreads every target across one long row. Narrower than
     GRID_MAX and auto-fit drops to two columns, then one, instead of
     squeezing a label until it clips. */
  .grid {{ display: grid; gap: 8px; max-width: {GRID_MAX}px;
          grid-template-columns: repeat(auto-fit, minmax({BUTTON_MIN}px, 1fr)); }}
  /* 13px over a {BUTTON_MIN}px minimum leaves the longest label
     ("FAA 8710 / IACRA") room to sit on one line inside the padding. */
  button {{ font: inherit; font-size: 13px; font-weight: 500; padding: 9px 11px;
           cursor: pointer;
           color: var(--ink); background: transparent; border: 1px solid var(--edge);
           border-radius: 7px; text-align: left; }}
  button:hover:not(:disabled) {{ border-color: var(--accent); color: var(--accent); }}
  button:disabled {{ opacity: .45; cursor: progress; }}
  #status {{ margin-top: 12px; font-size: 12.5px; min-height: 2.6em;
            white-space: pre-line; }}
  #status.err {{ color: #b3261e; }}
  @media (prefers-color-scheme: dark) {{ #status.err {{ color: #f2b8b5; }} }}
  code {{ font-size: 12px; }}
</style></head>
<body>
<h1>Export logbook</h1>
<p class="lede">Reads the live logbook and drops the printable HTML in
Logbook-Outbox, which syncs to the Mac. Nothing is written to Grist.</p>
<div class="grid">{buttons}</div>
<div id="status" role="status" aria-live="polite"></div>
<script>
const status = document.getElementById('status');
const buttons = [...document.querySelectorAll('button[data-target]')];
async function run(button) {{
  const target = button.dataset.target;
  buttons.forEach(b => b.disabled = true);
  status.className = '';
  status.textContent = 'Exporting ' + button.textContent + '\\u2026';
  try {{
    const res = await fetch('export', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
      body: new URLSearchParams({{target}}),
    }});
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || ('HTTP ' + res.status));
    status.textContent = data.file.split('/').pop() + ' \\u2192 Logbook-Outbox\\n'
      + data.summary + (data.warnings.length ? '\\n' + data.warnings.join('\\n') : '');
  }} catch (err) {{
    status.className = 'err';
    status.textContent = 'Export failed: ' + err.message;
  }} finally {{
    buttons.forEach(b => b.disabled = false);
  }}
}}
buttons.forEach(b => b.addEventListener('click', () => run(b)));
</script>
</body></html>
"""


class ExportHandler(BaseHTTPRequestHandler):
    """GET / for the page, POST /export to run one, GET /healthz for systemd."""

    server_version = "logbook-export"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # Set by build_server().
    config: ServiceConfig
    client_factory: ClientFactory
    run_lock: threading.Lock

    # -- helpers -------------------------------------------------------------

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # Nothing here is cacheable: every click should read Grist again.
        self.send_header("Cache-Control", "no-store")
        origin = self.headers.get("Origin")
        if origin in self.config.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, status: HTTPStatus, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._send_json(status, {"ok": False, "error": message})

    def _caller_allowed(self) -> bool:
        """Reject a request aimed at some other name, or sent by another site."""
        host = self.headers.get("Host", "")
        if host not in self.config.allowed_hosts:
            self._error(HTTPStatus.BAD_REQUEST,
                        f"Host validation failed: {host or '(none)'} is not "
                        f"{', '.join(sorted(self.config.allowed_hosts))}")
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin not in self.config.allowed_origins:
            self._error(HTTPStatus.FORBIDDEN, f"Origin not allowed: {origin}")
            return False
        return True

    def _requested_target(self) -> str | None:
        """The target from the POST body or the query string, or None."""
        fields = parse_qs(urlsplit(self.path).query)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            # The body is never read, so the connection cannot be reused.
            self.close_connection = True
            return None
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        content_type = (self.headers.get("Content-Type") or "").lower()
        if raw and "json" in content_type:
            try:
                parsed = json.loads(raw)
            except ValueError:
                return None
            if isinstance(parsed, dict) and isinstance(parsed.get("target"), str):
                fields["target"] = [parsed["target"]]
        elif raw:
            fields.update(parse_qs(raw))
        values = fields.get("target") or []
        return values[0] if len(values) == 1 else None

    # -- routes --------------------------------------------------------------

    def do_GET(self) -> None:          # noqa: N802  (http.server API)
        if not self._caller_allowed():
            return
        route = urlsplit(self.path).path
        if route == "/":
            self._send(HTTPStatus.OK, render_page(self.config).encode("utf-8"),
                       "text/html; charset=utf-8")
        elif route == "/healthz":
            self._send_json(HTTPStatus.OK,
                            {"ok": True, "targets": list(self.config.targets)})
        else:
            self._error(HTTPStatus.NOT_FOUND, f"No such path: {route}")

    do_HEAD = do_GET                   # noqa: N815  (http.server API)

    def do_POST(self) -> None:         # noqa: N802  (http.server API)
        if not self._caller_allowed():
            return
        route = urlsplit(self.path).path
        if route != "/export":
            self._error(HTTPStatus.NOT_FOUND, f"No such path: {route}")
            return
        target = self._requested_target()
        # The caller never names anything but a target, and a target is only
        # ever one of these: an unknown one stops here, unused.
        if target not in self.config.targets:
            self._error(HTTPStatus.BAD_REQUEST,
                        f"Unknown target: {target!r}. Pick one of "
                        f"{', '.join(self.config.targets)}")
            return

        # One export at a time: two clicks would otherwise read Grist twice
        # over and race for the same output file.
        with self.run_lock:
            try:
                result = build_export(
                    self.client_factory(),
                    target,
                    output_dir=self.config.output_dir,
                    pilot_path=self.config.pilot_path,
                    include_log=self.config.include_log,
                    outbox=self.config.outbox,
                )
            except ExportError as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            except Exception as exc:                        # noqa: BLE001
                self.log_error("export %s failed: %r", target, exc)
                self._error(HTTPStatus.BAD_GATEWAY,
                            f"{type(exc).__name__}: {exc}")
                return

        for warning in result.warnings:
            self.log_message("WARN: %s", warning)
        self.log_message("exported %s -> %s (%s)", target,
                         result.delivered, result.summary)
        self._send_json(HTTPStatus.OK, {
            "ok": True,
            "target": result.target,
            "as_of": result.as_of.isoformat(),
            "file": str(result.delivered or result.path),
            "export": str(result.path),
            "summary": result.summary,
            "warnings": list(result.warnings),
        })


def build_server(
    config: ServiceConfig,
    client_factory: ClientFactory | None = None,
) -> ThreadingHTTPServer:
    """A server bound to ``config.host`` only — never 0.0.0.0."""
    handler = type("BoundExportHandler", (ExportHandler,), {
        "config": config,
        "client_factory": staticmethod(client_factory or _default_client_factory),
        "run_lock": threading.Lock(),
    })
    server = ThreadingHTTPServer((config.host, config.port), handler)
    server.daemon_threads = True
    return server


def serve(config: ServiceConfig,
          client_factory: ClientFactory | None = None) -> None:
    """Run until stopped. The outbox is made up front so Syncthing can see it."""
    prepare_outbox(config.outbox)
    server = build_server(config, client_factory)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
