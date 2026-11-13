# Logbook

A personal Part 121 logbook. It imports your **SkedPlus** trip exports into a
self-hosted **Grist** doc (your real logbook, on the home server), and keeps a
public **flight map** up to date. (It began life on Airtable; cutover to Grist
happened 2026-07-23 — Airtable survives only as a frozen pre-cutover backup.)

The whole thing is built around one habit: **drag your SkedPlus files into a
folder. That's it.** The synced folder auto-imports on the server — no terminal.
Everything below the Quick Start is reference material you can ignore on a
normal day.

---

## BLUF — Quick Start

You do this twice a month: once when the schedule drops (planned), and again after
you fly (actual).

**Drag the SkedPlus export pair (txt + csv) into the synced inbox folder on your
Mac** (Syncthing shares it with the server):

- schedule just dropped → the **`planned/`** subfolder
- trips flown → the **`actual/`** subfolder

Files are named `<prefix>_<YYYYMMDD>_<PairingID>.<txt|csv>` — e.g.
`121807_20260601_E3405.txt` (SkedPlus names them this way already; `<prefix>` is your
employee number). The `.txt` carries the data and is required; the `.csv` is optional.
Within a minute or two the files vanish (= imported into Grist) and land in `recorded/`
on the server. If an import fails,
the files reappear in the **`failed/`** subfolder with an `import-log.txt`
explaining why. See [Automatic imports](#automatic-imports-server) for how it works.

**Manual fallback** (server terminal — same engine the watcher uses):

```sh
cd logbook/logbook-tools && source .venv/bin/activate

# After you've FLOWN the trips (files at inbox/ top level)
logbook-import import-actual --role sic --operator skw --commit

# When the schedule DROPS — writes planned trips (no flights yet)
logbook-import import-planned --role sic --operator skw --commit
```

> **Tip:** Drop `--commit` from any manual command to do a **dry run** first — it
> prints exactly what *would* be imported without writing to the logbook. Worth a
> glance if a trip looks unusual.

---

## What it does

1. **Import planned trips** — when your monthly schedule drops, load the pairings as
   planned trips (planned block/credit, no flight rows yet).
2. **Import actual trips** — after you fly, load the flown legs as real flight rows.
3. **Publish** — refresh the [flight map](https://justin-lenhart.github.io/logbook/).

You *view and analyze* everything in the Grist doc (`http://100.78.232.7:8484`,
Tailscale-only) and its embedded Metabase dashboards (see the `logbook-visualize`
repo). This tool only does the import and publish steps — it never asks you
questions and has no reporting mode.

---

## Detailed usage

### One-time setup

The tool is a Python CLI. You only set it up once.

```sh
cd logbook/logbook-tools
uv sync                        # first time only (uv-managed; builds .venv from uv.lock)
source .venv/bin/activate      # activate for the session
# no-uv fallback: python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

Create `logbook-tools/.env` with the backend credentials (needed for `--commit`):

```sh
LOGBOOK_BACKEND=grist
GRIST_URL=http://100.78.232.7:8484
GRIST_API_KEY=...your key...
GRIST_DOC=...the live doc id...
```

See `.env.example` for the template. (`LOGBOOK_BACKEND=airtable` +
`AIRTABLE_API_KEY`/`AIRTABLE_BASE_ID` still selects the legacy backend — only
useful against the frozen pre-cutover base.) **After setup, you only ever need
`source .venv/bin/activate` once per terminal session.**

### The normal workflow (manual runs)

Day to day you don't run these — the [auto-importer](#automatic-imports-server)
does. For manual runs on the server:

| When | Command |
|------|---------|
| Schedule drops | `logbook-import import-planned --role sic --operator skw --commit` |
| After you fly | `logbook-import import-actual --role sic --operator skw --commit --update-map` |

- `--role` defaults to `sic` (`pic` when that day comes).
- `--operator` defaults to `skw`, so it's optional — shown above for clarity.
- `--commit` writes to the logbook. **Without it, every command is a safe dry run.**
- `--update-map` (actual only) refreshes the public flight map and pushes it to
  GitHub Pages. See [Publishing](#publishing-map--app-pages) for the finer-grained flags.

### Dry run first (optional)

Before committing, run the same command **without `--commit`** to preview:

```sh
logbook-import import-actual --role sic --operator skw
```

It prints every trip, duty period, and leg it would create, plus the current map
state. Nothing is written. Eyeball it against your trip report, then re-run with
`--commit`.

### Where files go

```
logbook/
├── inbox/                 # ← you drop SkedPlus exports here (manual runs scan the top level)
│   ├── planned/           #   auto-import watch folder — schedule-drop exports
│   ├── actual/            #   auto-import watch folder — flown-trip exports
│   └── failed/            #   auto-import quarantine (bad files + the import log)
└── recorded/
    ├── planned/           # import-planned moves files here
    └── actual/            # import-actual moves files here
```

File naming convention: `<prefix>_<YYYYMMDD>_<PairingID>.<txt|csv>`
(e.g. `121807_20260601_E3405.txt`; `<prefix>` is your employee number). The `.txt` is
required; a lone `.csv` is skipped. Anything not matching that pattern is ignored with a
warning, so it's safe to have other junk in `inbox/`.

### Automatic imports (server)

On the home server (mintbox) the two subfolders are watched by systemd path
units: drop a txt/csv export pair into **`inbox/planned/`** or **`inbox/actual/`**
and the matching import runs by itself with `--commit` — no terminal needed.
Syncthing shares `inbox/` with the Mac (folder id `logbook-inbox`), so the daily
habit is *drag the files into the right folder, walk away*. Processed files disappear
into `recorded/<mode>/` as usual; anything that fails lands in
`inbox/failed/<timestamp>-<mode>/` together with `import-log.txt`, which syncs
back to the Mac so you'll see it.

A third folder, **`inbox/rsr/`**, takes SkyWest RSR report PDFs. System-wide
reports are parsed into the Grist `RSR_Metrics` table (13-month history per fleet;
see `logbook-import import-rsr --help`); domicile reports carry no efficiency
metrics and are just archived. Processed PDFs move to `recorded/rsr/`.

The pieces, all in this repo:

| Piece | Where |
|---|---|
| Watcher wrapper (settle delay, pair-wait, quarantine) | `scripts/process-inbox.sh` |
| systemd path + service units (planned, actual, rsr) | `deploy/systemd/` |
| Backend/credentials the auto-import uses | `logbook-tools/.env` (`LOGBOOK_BACKEND`, `GRIST_*`) |

Install (once, needs sudo):

```sh
sudo cp deploy/systemd/logbook-import-*.{path,service} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now logbook-import-planned.path logbook-import-actual.path logbook-import-rsr.path
```

Watch a run / debug: `journalctl -u logbook-import-actual.service -f`.
Auto-imports run with the default flags (`--role sic --operator skw`).
**Actual** imports also regenerate the public flight map and push it to GitHub
Pages automatically (planned imports skip this — no flown legs, nothing to map).
If the map push ever fails after a successful import, the journal says so —
recover with `logbook-import export-map --update`.

> **Backend:** the importer writes to the live Grist doc (`GRIST_DOC` in
> `logbook-tools/.env`) — cutover from Airtable happened 2026-07-23. Airtable
> remains only as a frozen last-resort backup of pre-cutover data.

### Publishing (map & app pages)

| Flag (on `import-actual`) | What it does |
|---|---|
| `--update-map` | Regenerate the flight map and push to GitHub Pages |
| `--update-apps` | *(legacy, Airtable-only — skipped under Grist)* regenerate the app reference pages |
| `--update-all`  | Both of the above |

You can also publish **without** importing anything:

```sh
logbook-import export-map --update      # refresh just the map
```

(`export-apps` still reads Airtable and has not been ported — the Metabase
**Application Reference** dashboard in `logbook-visualize` replaced it.)

GitHub Pages redeploys ~1 minute after the push. The map fetches its data with
`no-cache`, so a page reload picks up the new flights.

### Printable logbook exports (FAA 8710 / airline applications)

`export-profile` turns the live logbook into one printable HTML file per target.
It only **reads** Grist — there is no `--commit`, and nothing in the logbook changes.

**1. One-time: tell it who you are.** Your name and certificate details are not in
Grist. From the repo root:

```sh
cp pilot.toml.example pilot.toml
```

Edit `pilot.toml`:

| Key | What it is | Where it shows up |
|---|---|---|
| `name` | Your printed name | Page headers; under the signature line on every log page |
| `certificate` | e.g. `"Airline Transport Pilot"` | Summary header |
| `certificate_number` | Your certificate number | Summary header |
| `ratings` | List of ratings | Summary header |
| `type_ratings` | List of `FAA_Type` codes from the Grist Aircraft table, e.g. `["CL65"]` | United's "Type rated: Yes/No" |

`pilot.toml` is gitignored — it never leaves this machine. Without it the export
still runs, with a warning and a blank name.

**2. Run it** (on the server, where `logbook-tools/.env` has the Grist credentials):

```sh
cd logbook/logbook-tools
source .venv/bin/activate
logbook-import export-profile --target generic    # your own logbook, no target sheet
logbook-import export-profile --target faa        # FAA 8710 / IACRA Section III
logbook-import export-profile --target ual        # United
logbook-import export-profile --target swa        # Southwest
logbook-import export-profile --target allegiant  # Allegiant
logbook-import export-profile --target jetblue    # JetBlue
logbook-import export-profile --target aal        # American
```

On the server you do not have to type any of this: the **one-click export
button** below runs the same thing from Grist (or the homepage) and drops the
file in a folder that syncs to the Mac.

Every target ends with the same three-table **Application Reference** sheet, so a
figure quoted on one application can be traced on any other:

| Table | What it answers |
|---|---|
| Totals by FAA Type | One row per `Aircraft.FAA_Type` — CL65 collapses the CRJ variants, H1 the AH-1Z / AH-1W / UH-1Y, H57 the TH-57B / C. Includes SIC-to-PIC and last-flown |
| Hours by Category | Airplane / Rotorcraft / Powered Lift, by role and condition |
| Class Hours | ASEL / ASES / AMEL / AMES / Helicopter / Gyroplane with PIC, SIC, Instruction Received and Total — the Total column reconciles against Hours by Category |

The one exception is SIC-to-PIC (§61.51): the JetBlue export drops those two rows,
because that application has no field for supervised SIC time and the sheet goes to
a recruiter. Every other target keeps them — Allegiant's fields 7–9 are answered
from them.

The per-aircraft **Summary by Aircraft Type** on the first sheet is kept as well:
it groups by individual aircraft rather than by type rating, which is a different
question.

Night, instrument and cross-country are printed **as stored** in Grist and never
recomputed here, so a change to how the importer defines them flows straight
through to these tables.

**Allegiant** applies no conversions of any kind. Its own instruction is "enter
exact flight times as of the application date; do not round", and it accepts no
conversions, substitutions, landing credits, simulator or UAS time. The Southwest
sortie conversion lives in the same module and must never reach it — there is a
test that guards exactly that.

**JetBlue** asks for almost nothing as an exact figure: total time and the time on
each aircraft are picked from dropdown **bands**, and the recency questions are
yes/no. So that sheet prints the band or the answer with, in brackets, the hours it
was read from, so every entry traces back to the certified log pages. Only band
labels actually seen on the application are encoded — anything outside them prints
the hours and defers to the dropdown rather than inventing a label. Its aircraft
rows group by type rating (the CRJ variants are one CL-65 row, the H-1s one row),
and the recency questions are measured from the export's as-of date, so re-run it
on the day the application goes in.

**American** is one table of the application's repeating per-aircraft entry, and
only that block — the rest of the form has not been transcribed, so none of it is
guessed. Two of American's own instructions shape the sheet:

- *"For aircraft operated under multiple operating rules (e.g., Part 121, Part 135,
  etc), please create separate entries for each."* So a row is one `FAA_Type` under
  **one operating rule**, and a type flown under two rules splits into two rows.
  Nothing in the logbook does today — every type has exactly one rule — but the
  split is built in, not left for someone to notice.
- *"Round hours to the nearest whole number."* So every hours figure on the sheet
  is a whole number, rounded half **up** and never truncated: 41.8 h of instruction
  is 42, not 41. (`round()` would make 42.5 h into 42, which is why the sheet uses
  its own `_half_up`.) The exact tenths are deliberately not repeated beside them —
  the Application Reference sheet at the back already carries every one of these
  figures to the tenth, grouped the same way, so nothing is lost and no figure on
  the American sheet can disagree with the number typed into the form. For the same
  reason the table has **no totals row**: a column of rounded entries does not add
  up to a rounded total.

The three H-1 variants are one entry, filed as the **AH-1Z**, with a note beneath
the table giving the hours in the other two and the role they were flown in — read
from the logbook, not assumed, so a mixed-role variant is reported as the split it
actually is. Landings are day and night landings added together (one field on the
form); the sortie checkbox is the sortie count being non-zero; the type-rating
answer comes from `pilot.toml`, not from recent flying; "last 12 / 24 months" end
on the export's as-of date, so re-run it on the day the application goes in. Time
flown as a student under instruction has no field on this form, so a note names
those hours rather than letting a trainer read 0 in every hours column.

Each run prints a one-line total (flights, total / PIC / SIC / dual) and the file
it wrote: `logbook/exports/logbook-<target>-<date>.html`. `exports/` is gitignored
and owner-only — it is **not** `docs/`, which is public.

**3. Print it.** Open the file in a browser (Chrome prints it best) and print /
"Save as PDF". The page sizes are built in: summary and target pages are portrait
letter, log pages are landscape letter. In the print dialog leave margins on
"Default" and scale at 100%. Sign each log page on the line above your name.

**What is in the file**, in order:

1. **Flight Time Summary** — headline totals, 1/2/3-year history, and a
   table by aircraft type. Same in every export.
2. **The target's pages** — `faa`: the 8710 Section III grid (Airplane / Rotorcraft /
   Powered Lift) plus Class Hours; `ual`: one form block per aircraft to copy into
   pilothiring.united.com; `swa`: one block per aircraft with the 0.3-per-sortie
   military conversion. `generic` has no target sheet at all: a target sheet is
   shaped by one organisation's form, and the generic export is aimed at nobody,
   so it is the summary, the reference tables and the log pages — your logbook.
3. **Certified log pages** — every flight, 50 per page, with page totals, amount
   forwarded, totals to date, and the certification/signature block.

**Options**

| Flag | Effect |
|---|---|
| `--no-log` | Leave out the certified log pages (just the summary + target pages) |
| `--as-of 2026-11-03` | Report as of that date; later flights are left out (default: today) |
| `--output DIR` | Write somewhere other than `exports/` |
| `--pilot FILE` | Use a different identity file than `pilot.toml` |

**Reading the output**

- A `WARNING: flight … has no Aircraft link` line means that flight counts in Total
  Time but in no category, class or type. Set its Aircraft in Grist and re-run.
- Night, instrument, cross-country and landings appear only in the summary and 8710
  totals, never per flight: on pre-2026 flights they exist as verified totals only.
- `—` means "not tracked" (solo time).
- On United's form, helicopters show their engine type (`Turboshaft`) under
  Powerplant; pick whatever the real form offers.
- No military conversion is applied anywhere except the Southwest block, where it
  is shown as its own rows.

### One-click exports (the button)

On mintbox the export is a button, not a command. `logbook-export.service`
serves a small page with one button per target; a click renders the export and
copies it into **`~/Logbook-Outbox`**, which Syncthing carries to
`/Users/crush/Documents/Logbook-Outbox` on the Mac. It takes about a second.

The page lives at **http://100.78.232.7:8486/** and is meant to be opened from
either of two places:

| Where | How it gets there |
|---|---|
| **Grist** (recommended) | A *custom widget* on a page of the logbook doc — the buttons sit next to the data they describe |
| Homepage (`:3001`) | A link in `services.yaml`, which opens the same page |

**Why a custom widget and not a Grist webhook.** Grist can fire an outgoing
webhook when a row is added, which would mean a "press me" table. Two things
rule it out: this Grist has no `ALLOWED_WEBHOOK_DOMAINS` in
`/srv/homelab/stacks/grist/compose.yaml`, and with that unset Grist rejects
*every* webhook target — so the route needs a compose edit and a container
restart before it can work at all. And it would turn pressing a button into a
row written to the canonical doc. A custom widget needs no Grist
configuration whatsoever: paste a URL. The page is served by the service
itself, so its own `fetch` is same-origin — no CORS, no API key, nothing to
keep in sync.

**What the service can and cannot do**

- It runs **nothing but `export-profile`**, which has no `--commit` and never
  writes to Grist. There is no importer behind it and no path the caller names.
- It binds **the Tailscale address only** (`100.78.232.7:8486`, like Grist) and
  refuses any request whose `Host` header is not that address, the same way
  Grist refuses an unexpected hostname.
- The target name is looked up in `profiles.TARGETS` and the export runs
  **in-process** — nothing from the caller ever reaches a shell.
- Only this page, Grist (`:8484`) and the homepage (`:3001`) may drive it; a
  request carrying any other `Origin` is refused before anything runs.
- The export lands in the outbox under a `*.part` name and is renamed into
  place, so Syncthing never carries a half-written file. The outbox's
  `.stignore` keeps the temporary name off the Mac.

#### 1. Install the service (sudo, once)

The live checkout (`/home/crushbox/Developer/logbook`) must be on a `main` that
has `serve-exports` — its `.venv` is an editable install, so a `git pull` is
enough; there is nothing to reinstall.

```sh
sudo cp deploy/systemd/logbook-export.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now logbook-export.service
```

Check it: `curl http://100.78.232.7:8486/healthz` →
`{"ok": true, "targets": ["generic", "faa", ...]}`. Logs:
`journalctl -u logbook-export.service -f` (every click logs the target, the
delivered file, the one-line total, and any `WARN:` the export raised).

The unit runs as `crushbox` from `/home/crushbox/Developer/logbook`, so it
picks up `logbook-tools/.env` (Grist credentials) and `pilot.toml` (your name)
exactly as a manual run does. `Restart=always` plus
`After=tailscaled.service` means it survives a reboot and waits for the
tailnet address to exist before binding.

#### 2. Add the button to Grist

1. Open the logbook doc → **Add New** (bottom left) → **Add Page**.
2. Pick widget type **Custom**, select any table as the data source (the page
   ignores it), and add the page.
3. In the right-hand creator panel, open the widget dropdown and choose
   **Custom URL**, then paste into **Enter Custom URL**:
   `http://100.78.232.7:8486/`
4. Leave access at **No document access** — the page needs none.
5. Rename the page to *Export* and drag it where you want it.

#### 3. Or add it to the homepage

In the homelab repo, `stacks/homepage/config/services.yaml`, under
*Grist - Data Management*:

```yaml
    - Export logbook:
        href: http://100.78.232.7:8486/
        description: One-click printable export to the Mac
        icon: grist.png
        siteMonitor: http://100.78.232.7:8486/healthz
```

No `server`/`container` here: the service is systemd, not Docker, so there is
no container for the usual status dot — `siteMonitor` checks the port instead,
the way the Home Assistant entry does.

#### 4. Pair the outbox with the Mac (Syncthing)

The mintbox side (`/home/crushbox/Logbook-Outbox`) already exists — the
service creates it. The Mac side, `/Users/crush/Documents/Logbook-Outbox`,
you have already made. To connect them, in the Syncthing web UI:

**On mintbox** (http://localhost:8384, or over SSH port-forward):

1. **Add Folder**.
2. *Folder Label*: `Logbook Outbox` — *Folder ID*: `logbook-outbox`.
3. *Folder Path*: `/home/crushbox/Logbook-Outbox`.
4. **Sharing** tab → tick **Justins-MacBook-Pro**.
5. **Advanced** tab → *Folder Type*: **Send Only** (the Mac never sends
   exports back; this keeps a deletion on the Mac from deleting the original).
6. **Save**.

**On the Mac** (http://localhost:8384): a notification appears offering the
new folder from `crushbox`.

7. **Add** on that notification.
8. *Folder Path*: `/Users/crush/Documents/Logbook-Outbox`.
9. **Advanced** tab → *Folder Type*: **Receive Only**.
10. **Save**.

Within a few seconds the existing exports appear in
`~/Documents/Logbook-Outbox` on the Mac. After that, every click of the button
lands there by itself.

> Syncthing config is yours to change — nothing here touches it, and the REST
> API is not used (it would need an API key).

#### Flags

`serve-exports` takes `--host` / `--port` (defaults: the tailnet address and
8486), `--outbox DIR`, `--output DIR`, `--pilot FILE`, `--no-log`, and
`--allow-host` / `--allow-origin` for an extra name to answer to (a MagicDNS
hostname, say). Never bind it to `0.0.0.0`.

### Command reference

Everything else the CLI can do. You will rarely touch these.

| Command | Purpose |
|---|---|
| `import-actual` | Import flown legs as Flight rows *(what the auto-importer runs)* |
| `import-planned` | Import the schedule as planned Trips/Duty Periods |
| `export-map` | Regenerate `docs/map_data.geojson` (add `--update` to push) |
| `serve-exports` | Serve the one-click export page (Tailscale-only, read-only) — *what `logbook-export.service` runs* |
| `export-profile --target {generic,faa,ual,swa,allegiant,jetblue,aal}` | Printable logbook export (summary, target sections, application-reference tables, certified log pages) into gitignored `exports/`; read-only. Needs `pilot.toml` (copy `pilot.toml.example`) |
| `backfill-sic-to-pic --workbook FILE` | One-off: fill `Flights.SIC_to_PIC` from the legacy workbook's PF column (14 CFR 61.51). Dry-run unless `--commit`; refuses to write unless the per-aircraft reconciliation gate matches exactly |
| `backfill-training-codes` | One-off: rewrite the historical `Flights.Notes` remarks to their 4-digit military event codes, dropping the import preamble. Dry-run unless `--commit` |
| `export-apps` | *(legacy, Airtable-only)* regenerate `docs/apps/*.html` |
| `enrich-night` | *(legacy, Airtable-only)* backfill night data — Grist imports enrich inline |
| `backfill-passengers` | *(legacy, Airtable-only)* re-derive Passengers from archived exports |

Run any command with `--help` for its flags.

---

## The flight map

- Live map: **https://justin-lenhart.github.io/logbook/**
- It's a static Leaflet page served from `docs/`. `docs/map_data.geojson` is
  **generated — never hand-edit it.** The auto-importer refreshes it on every
  actual import; manual refresh is `--update-map` (during an import) or
  `export-map --update`.
- **Deadhead legs never appear on the map — by design.** Only flown legs
  (PIC or SIC time > 0, not deadhead) qualify; a route you've only deadheaded
  is correctly absent.
- The map is embedded in the Grist doc as its **Flight Map** page (a Custom-URL
  widget pointing at the page above). Day-to-day map updates happen here via the
  CLI — the embed just re-renders whatever is published.

---

## Reference & background

Day-to-day you don't need any of this. It's here so the context isn't lost.

### Grist doc pages (the live logbook UI)

The Grist `Logbook` doc (`http://100.78.232.7:8484`, Tailscale-only) carries these
pages:

| Page | What it shows |
|------|---------------|
| Airports … Bugs_Features | Raw table views (one per table) |
| **Hours Dashboard** | Native Grist pivots: Category/Class × Position/Engine + career totals (kept for side-by-side comparison with Metabase; user may retire) |
| **Analytics** | Native Grist charts: block/credit by month, planned-v-actual, TAFB, trip pie, TCI (same retire-candidate status) |
| **Flights Logbook / Trips Log** | Curated grids, newest first |
| **Flight Map** | Custom-URL widget embedding the public Leaflet map |
| **Analytics (Metabase)** | Embedded Metabase **Daily Ops** dashboard (career + monthly tiles, trends, pivots) via its public link |
| **Application Reference** | Embedded Metabase **Application Reference** dashboard (per-aircraft totals, FAA 8710 matrix, class hours, currency recency) |
| **Trip Efficiency & Duty Legality** | Embedded Metabase **Trip Efficiency & Duty Legality** dashboard (Part 117 utilization awareness, TAFB efficiency, variance — personal analytics, NOT a compliance system) |
| **Trip Details** | Master-detail: pick a trip (newest-first grid) → trip card + its flights + its duty periods, linked by cursor |

The three Metabase embeds render the live dashboards from the `logbook-visualize`
stack (read-only 15-min sync of this doc); appearance edits made in Metabase
auto-reflect here. Embed URLs: `logbook-visualize/embed-urls.md`.

### How credit & times are handled

- **Times are converted to UTC on import.** SkedPlus reports local time at each
  airport; the importer looks up each airport's location and converts every
  out/in/report/release time to UTC before writing. Duty **report** uses the zone of
  the day's first schedule line origin; **release** uses the zone of the last line's
  destination (SkedPlus prints each in its own airport's local time). The importer
  warns when the resulting duty length differs from the sheet's `Duty:` by > 0.1 h.
  This is why the Airports table must contain every airport you fly (with lat/lon).
- **Placeholder schedule lines** (`CXL`, `FDP`, `REF`, `RDY`, `NMD`, … and any
  non-numeric code with 0:00 block and origin == destination) never become Flight
  rows and do not count in `Planned_Legs`. Numeric flights always become Flight
  rows, even same-station air returns.
- **Pairing suffix**: `E3436D`, `E3436A` and `E3436` are the same pairing. The suffix
  is removed from every key and from `Trips.Trip_Number_Pairing_ID`.
- **Header line** (`ORD CRJ FO`) is not trip data. `Trips.Base` = origin of the first
  schedule line, written only when the trip row is created. `Trips.Equipment_Family`
  is not written.
- **Aircraft code**: the Flight's Aircraft link comes only from the CSV `A/C Type`.
  No aircraft on a line → blank link and a warning (deadheads: no warning). SkyWest's `CRJ` (CRJ-200) is
  stored as `CR2`.
- **Flight hours** come only from the Flights table; Duty_Periods is for Part 117
  analysis.
- **Flown credit** (actual import): `Duty_Periods.Actual_Credit` = the Day Total
  credit; `Trips.Actual_Credit` = the sum of the trip's Day Totals (not the header
  `Credit:`, which is stale on reassigned trips). No 4:12 day minimum is applied.
  `Actual_Block` stays a formula (sum of Flights).
- **Cancelled days**: on an actual import, a flown duty day with no flight lines gets
  Status `Cancelled`, and so do the trip's `Planned` duty days that the actual export
  no longer contains (trip cut short) and that are dated today or earlier.
- **Duty airports**: `Duty_Periods.Report_Airport` / `Release_Airport` = first line
  origin / last line destination (the same airports used for the time zones).
- **Trip credit check**: an actual import warns when the header `Credit:` differs from
  the sum of the Day Totals (usually a reassigned trip).
- **Import warnings** are saved to `Import_Batch.Notes` (`WARN:` / `ERROR:` lines,
  replaced on re-import).
- **Deadhead passengers** are stored as 0; passenger totals count only operated
  flights.
- **Night time & landings** follow FAA currency rules (1 hr after sunset → 1 hr before
  sunrise) and are assigned by **pairing**, not by calendar day. Grist imports
  compute this inline on every flight; the standalone `enrich-night` backfill is
  Airtable-legacy.

### Efficiency metrics (viewed in Grist/Metabase, not here)

There are no efficiency *commands* — the metrics live in the Metabase
**Efficiency** dashboard (logbook-visualize), which compares flown trips
with the SkyWest RSR system averages that `import-rsr` loads into `RSR_Metrics`:
credit and block per duty period and per day, TAFB and duty per block and per
credit. Inputs this repo writes:

- `Trips.Actual_Credit` = sum of the export's Day Totals (no 4:12 floor). Checked
  against the crew pay reports' Processed Credit: exact on most trips, a little
  low on reassigned or pay-protected ones. The header credit is not used — it goes
  stale when a trip is reassigned.
- `Trips.TAFB` from the SkedPlus header (both import modes; the latest import wins).
- Duty periods with `Status = Actual`, report → release, drive the per-duty metrics.

### Part 117 awareness (Metabase dashboard; no CLI command)

The rolling-limit and FDP analytics now ship as the Metabase **Trip Efficiency &
Duty Legality** dashboard in the `logbook-visualize` stack — **personal analytics,
NOT a compliance system** (the company's system is the sole legality authority).
There is **no `compliance-check` CLI command.** The regulatory reference and
implementation notes — rolling 100h/672h block, §117.23 cumulative windows, rest
checks, etc. — are in [`docs/part117-compliance-plan.md`](docs/part117-compliance-plan.md).
The one piece still blocked is the *exact* Table A/B per-duty limits, which need a
derived local report time (`Airports.UTC_Offset` is all zeros — see that doc); the
dashboard shows floor–ceiling utilization ranges instead.

---

## Repo layout

```
logbook/
├── inbox/                  # drop SkedPlus exports here (git-ignored)
│   ├── planned/            #   watched — auto-imports planned trips
│   ├── actual/             #   watched — auto-imports flown trips
│   └── failed/             #   quarantine for failed auto-imports
├── recorded/               # processed exports land here (git-ignored)
│   ├── planned/
│   └── actual/
├── exports/                # printable logbook exports (git-ignored, owner-only)
├── deploy/systemd/         # units: the auto-importer + the export button
├── scripts/                # process-inbox.sh (watcher), update-map.sh
├── docs/                   # GitHub Pages site (the map + app pages)
│   ├── index.html          # Leaflet map
│   ├── map_data.geojson    # generated — do not edit
│   ├── apps/               # generated airline/FAA reference pages
│   └── *.md                # planning docs (Part 117, efficiency metrics)
└── logbook-tools/          # the CLI
    ├── src/logbook_import/ # source
    ├── scripts/            # one-off / maintenance scripts
    └── .env                # backend credentials (git-ignored):
                            #   LOGBOOK_BACKEND=grist|airtable + GRIST_*/AIRTABLE_*
```

Operational data (`inbox/`, `recorded/`, `exports/`, `backups/`, `misc/`, `.env`,
`pilot.toml`) is git-ignored — it contains crew names, tail numbers, certificate
details and credentials, and never leaves your machine. `~/Logbook-Outbox`, which
the export button writes to, is outside the repo for the same reason.

---

## Roadmap

- **Config file / `--std` flag** — collapse `--role sic --operator skw` into a stored
  default so the daily command becomes just `logbook-import import-actual --std`.
- **`compliance-check` command** — Part 117 rolling limits (see plan doc).
- **Flask web app** — eventually wrap this whole flow in a GUI so a non-coding pilot
  never touches a terminal. The import/publish logic here is the backend for that.
