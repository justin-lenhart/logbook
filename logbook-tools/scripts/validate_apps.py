"""
Validate the application-report aggregation against the legacy Excel oracles.

The live logbook = the legacy AnytimeLogbook snapshot (one aggregate row per
aircraft type) PLUS live time logged since. We can therefore validate the
aggregation exactly on the *legacy subset* (Legacy Summary = true), which must
reproduce the trusted worksheet figures, and separately report the current
full-logbook totals.

Runs offline against the most recent backups/airtable-* dump (no Airtable
calls). Usage:

    .venv/bin/python scripts/validate_apps.py
"""

from __future__ import annotations

import datetime
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from logbook_import import app_report as R  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

# Oracles from LEN2J-AnytimeLogbook2025.12.01.xlsx (legacy subset only) that
# reconcile exactly with the Airtable data's role definitions.
ORACLES = {
    "Total flight time": 1506.3,
    "Converted PIC (x0.3)": 377.8,
    "Total military sorties": 516,
    "Rotorcraft total": 824.6,
}
# Per-family military SIC reconstruction (block - PIC - instructor) must match
# the SWA worksheet's per-aircraft SIC for military types.
MIL_SIC_ORACLE = {"AH1Z": 449.8, "UC12W": 469.6, "H57": 123.3, "T6": 68.2}
TOL = 0.15  # hours; legacy values are rounded to 0.1 per family

# The legacy SWA worksheet's converted PIC+SIC headline was 1665.3. It does not
# reconcile exactly because that sheet counted civilian light-piston dual time
# (C172/PA-44) as SIC, whereas the Airtable import recorded it as PIC. The
# ~41.6 hr residual is entirely from those two civilian types.
LEGACY_SWA_CONVERTED_TOTAL = 1665.3


def _latest_backup() -> Path:
    dirs = sorted(glob.glob(str(REPO_ROOT / "backups" / "airtable-*")))
    if not dirs:
        sys.exit("No backup found. Run scripts/backup_airtable.py first.")
    return Path(dirs[-1])


def main() -> None:
    bdir = _latest_backup()
    flights = json.loads((bdir / "Flights.json").read_text())["records"]
    aircraft = json.loads((bdir / "Aircraft.json").read_text())["records"]
    ac_by_id = {r["id"]: r["fields"].get("Aircraft") for r in aircraft}
    print(f"Backup: {bdir.name}  ({len(flights)} flights, {len(aircraft)} aircraft)\n")

    legacy = [r for r in flights if r["fields"].get("Legacy Summary")]
    rows = R.normalize(legacy, ac_by_id)
    unknown = [r for r in rows if not r.family]
    aggs = R.aggregate(rows)
    t = R.grand_totals(aggs)

    got = {
        "Total flight time": t.total_time,
        "Converted PIC (x0.3)": t.conv_pic,
        "Total military sorties": float(t.sorties),
        "Rotorcraft total": t.rotorcraft,
    }

    print("LEGACY SUBSET vs Excel oracle (exact-reconcile metrics)")
    print(f"  {'metric':28} {'expected':>10} {'got':>10} {'Δ':>8}  status")
    ok = True
    for k, exp in ORACLES.items():
        g = got[k]
        d = g - exp
        passed = abs(d) <= TOL
        ok = ok and passed
        print(f"  {k:28} {exp:>10.1f} {g:>10.1f} {d:>8.2f}  {'PASS' if passed else 'FAIL'}")

    print("\nMilitary SIC reconstruction (block - PIC - instructor) per family")
    for code, exp in MIL_SIC_ORACLE.items():
        g = aggs[code].app_sic
        passed = abs(g - exp) <= TOL
        ok = ok and passed
        print(f"  {code:8} expected {exp:>8.1f}  got {g:>8.1f}  {'PASS' if passed else 'FAIL'}")

    print("\nLegacy SWA converted PIC+SIC headline (informational)")
    resid = LEGACY_SWA_CONVERTED_TOTAL - t.conv_total
    print(f"  old sheet {LEGACY_SWA_CONVERTED_TOTAL:.1f}  ·  generator {t.conv_total:.1f}"
          f"  ·  residual {resid:.1f}")
    print("  residual = civilian C172/PA-44 dual time the old sheet counted as SIC")
    print("  but Airtable records as PIC. Decision flagged for review.")

    if unknown:
        print(f"\n  [WARN] {len(unknown)} legacy rows had no family mapping")

    # Full logbook (legacy + live) for reference.
    full_rows = R.normalize(flights, ac_by_id)
    full = R.grand_totals(R.aggregate(full_rows))
    print("\nFULL LOGBOOK (legacy + live, current)")
    print(f"  Total time         {full.total_time:>10.1f}")
    print(f"  PIC                 {full.pic:>10.1f}")
    print(f"  SIC                 {full.sic:>10.1f}")
    print(f"  Converted PIC+SIC  {full.conv_total:>10.1f}")
    print(f"  FW turbine          {full.fw_turbine:>10.1f}")
    print(f"  Rotorcraft          {full.rotorcraft:>10.1f}")

    print("\nNOTE: Excel FAA 'Airplane total' = 681.7 includes V-22 (0.6, powered")
    print("lift) erroneously; clean computation yields 681.1. This is expected.")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
