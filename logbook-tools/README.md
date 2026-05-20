# logbook-tools

Utilities for turning SkedPlus exports into logbook import plans.

## Current status

- `import-planned` reads pairing exports from the workspace `inbox/` folder.
- `import-actual` builds planned Flight rows from the same exports.
- Both commands are dry-run only right now.
- The `recorded/planned` and `recorded/actual` folders exist, but this tool does not write to them yet.
- Airtable commit mode is not implemented yet.

## Local usage

From the `logbook-tools` directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ."[dev]"
python -m logbook_import.cli import-planned --role sic --operator skw
```

The source checkout includes a small bootstrap package so `python -m logbook_import.cli ...`
works even before an editable install has been set up.

## Known Limitations

### Night time — short overnight flights

Night time calculation uses civil twilight end at the origin airport (for the UTC
departure date) as the start of night, and civil twilight begin at the destination
airport (for the UTC arrival date) as the end of night.  For flights that depart
just before local midnight and arrive just after (e.g., a 23:50 CDT departure arriving
at 00:20 CDT the next morning), the UTC departure and arrival dates may coincide in a
way that underestimates the night window by a few minutes.  This is an acceptable
tradeoff: such legs are rare in SkyWest regional operations.
