# Logbook

A personal aviation logbook that automatically imports your SkyWest schedule from SkedPlus into Airtable, with an interactive flight map.

---

## What This Is

This tool takes your SkedPlus export files and imports them into an Airtable logbook — automatically calculating block time, credit time, night time, and landings. It runs locally on your computer and opens in a web browser. Your data lives in your own Airtable account.

---

## Before You Start

You'll need three things:

1. **A Mac computer** (macOS 12 or later recommended)
2. **An Airtable account** (free tier works) — [sign up here](https://airtable.com/signup)
3. **Your own Airtable logbook base** — see [Airtable Setup](#airtable-setup) below
4. **An internet connection** (to sync with Airtable)

---

## Install & Run

> **First time only — takes about 2 minutes.** After that, step 4 starts in seconds.

**Step 1 — Download this project**

Click the green **Code** button at the top of this page, then **Download ZIP**. Unzip it somewhere easy to find, like your Desktop or Documents folder.

**Step 2 — Open Terminal**

Press **Cmd + Space**, type `Terminal`, and press Enter.

**Step 3 — Navigate to the project folder**

In the Terminal window, type `cd ` (with a space after it), then drag the unzipped folder from Finder into the Terminal window. Press Enter.

It should look something like:
```
cd /Users/yourname/Desktop/logbook-distribute
```

**Step 4 — Start Logbook**

Type this and press Enter:
```
./start.sh
```

The first time, it will install a small package manager (takes ~30 seconds). After that, it installs all dependencies automatically.

Your browser will open to **http://localhost:5000** — this is your Logbook.

**Step 5 — Enter your Airtable credentials**

The first time you open Logbook, you'll be taken to the Settings page. Enter your Airtable API token and Base ID (see [Airtable Setup](#airtable-setup) below), then click Save.

---

## Daily Use

### Importing a Trip

1. In SkedPlus, export your pairing — you'll get a `.txt` file and a `.csv` file.
2. Copy both files into the `inbox/` folder inside the Logbook project folder.
3. Open Logbook (run `./start.sh` if it's not already running).
4. Click **Import** in the top menu.
5. You'll see your files listed. Click **Dry Run** to preview exactly what will be imported.
6. Review the output. If it looks correct, click **Commit to Airtable**.
7. Your flights are now in your Airtable logbook, and the files are moved to `recorded/`.

### Importing a Planned Trip

Select **Planned (schedule only)** in the Import options before running. Planned imports create trip and duty period records without creating flight rows — useful for tracking upcoming trips before you fly them.

---

## The Flight Map

Click **Map** in the top menu to see all your logged routes on an interactive map. Routes are drawn from your live Airtable data — no setup required.

Line thickness shows how many times you've flown each route. Click any route or airport for details.

### Optional: Public Map via GitHub Pages

If you want a public, shareable version of your map, you can host it on GitHub Pages. This requires a free GitHub account and a few extra steps — see the developer README on the `main` branch for details. Once set up, enter your GitHub Pages URL in **Settings → Flight Map URL**.

---

## Airtable Setup

Each pilot needs their own Airtable base. There are two ways to set one up:

### Option A — Use the Template (Recommended)

[**Click here to copy the Logbook template into your Airtable account.**](https://airtable.com/universe)
*(Template link — ask the person who shared this with you for the direct URL)*

Click **Use Template** and it creates an empty, pre-configured logbook base in your account. Then follow the steps below to get your credentials.

### Option B — Set Up From Scratch

Create a new base in Airtable and add the following tables with these fields:

<details>
<summary><strong>Click to expand: full table and field reference</strong></summary>

**Flights table**
| Field | Type |
|---|---|
| Flight Key | Auto number |
| Import Flight Key | Single line text |
| Departure Airport | Single line text |
| Arrival Airport | Single line text |
| Out Time | Date/time (UTC) |
| In Time | Date/time (UTC) |
| Block Time | Number (decimal) |
| Credit Time | Number (decimal) |
| Cross Country Time | Number (decimal) |
| PIC Time | Number (decimal) |
| SIC Time | Number (decimal) |
| Night Time | Number (decimal) |
| Day Landing | Number (integer) |
| Night Landing | Number (integer) |
| Deadhead | Checkbox |
| Aircraft Code | Single line text |
| Tail Number | Single line text |
| Operation | Single line text |
| Special Category | Multiple select |
| Legacy Summary | Checkbox |
| Duty Period | Link to Duty Periods |
| Trip | Link to Trips |

**Trips table**
| Field | Type |
|---|---|
| Trip Key | Single line text |
| Pairing ID | Single line text |
| Start Date | Date |
| End Date | Date |
| Status | Single select (planned/actual) |
| Planned Block | Number (decimal) |
| Planned Credit | Number (decimal) |
| Planned Duty Periods | Number (integer) |
| Planned Legs | Number (integer) |
| Import Batch | Link to Import Batch |

**Duty Periods table**
| Field | Type |
|---|---|
| Duty Period Key | Single line text |
| Trip | Link to Trips |
| Duty Date | Date |
| Status | Single select |
| Planned Block | Number (decimal) |
| Planned Credit | Number (decimal) |
| Planned Legs | Number (integer) |

**Aircraft table**
| Field | Type |
|---|---|
| Aircraft Code | Single line text (primary) |
| FAA Type | Single line text |
| Equipment Family | Single line text |

**Import Batch table**
| Field | Type |
|---|---|
| Batch Name | Single line text |
| Import Type | Single select (planned/actual) |
| Import Date | Date |
| Pairing ID | Single line text |
| Source File | Single line text |

**Airports table**
*(populated by the seed script — see developer README)*
| Field | Type |
|---|---|
| IATA | Single line text (primary) |
| Airport Name | Single line text |
| Municipality | Single line text |
| Country | Single line text |
| Latitude | Number |
| Longitude | Number |

</details>

### Getting Your API Token and Base ID

**API Token:**
1. Go to [airtable.com/create/tokens](https://airtable.com/create/tokens)
2. Click **Create new token**
3. Give it a name (e.g. "Logbook")
4. Under **Scopes**, add: `data.records:read`, `data.records:write`, `schema.bases:read`
5. Under **Access**, select your logbook base
6. Click **Create token** and copy the value (starts with `pat…`)

**Base ID:**
1. Open your Airtable base in a browser
2. Look at the URL: `https://airtable.com/appXXXXXXXXXXXXXX/...`
3. The Base ID is the `appXXXXXXXXXXXXXX` part

Enter both values in Logbook → **Settings**.

---

## Supported Import Formats

| Format | Airlines | Files Needed |
|---|---|---|
| SkyWest / SkedPlus | SkyWest Airlines (SKW) | `.txt` + `.csv` from SkedPlus |

Support for additional airline formats (UPS, FedEx, Delta, etc.) is planned. If you fly for a different carrier, open an issue or reach out.

---

## Updating Logbook

When a new version is available:

**If you used Download ZIP:**
1. Download the new ZIP
2. Unzip it
3. Copy your `logbook.json` file from the old folder to the new folder
4. Run `./start.sh` from the new folder

**If you used `git clone`:**
```
git pull
./start.sh
```

---

## Troubleshooting

**"Permission denied" when running `./start.sh`**
Run this once to fix it:
```
chmod +x start.sh
```
Then try `./start.sh` again.

---

**Browser doesn't open automatically**
Open Safari or Chrome manually and go to: **http://localhost:5000**

---

**"No files found in inbox"**
Make sure you copied your SkedPlus files directly into the `inbox/` folder (not into a subfolder inside it). File names should look like `1_20260509_E3058E.txt` and `1_20260509_E3058E.csv`.

---

**"Cannot reach Airtable"**
- Check your internet connection
- In Settings, verify your API token and Base ID are entered correctly
- Make sure your token has not expired (Airtable tokens can be set to expire)

---

**Dry run shows warnings about airport codes**
If you see warnings like `Airport not found: XYZ`, that airport is missing from your Airports table. Contact the person who shared this tool — the Airports table needs to be seeded with the full airport database.

---

**Committed a trip by mistake**
You cannot undo an Airtable commit from within Logbook. Open Airtable directly and delete the records from the Flights, Trips, Duty Periods, and Import Batch tables that were created by that import. You can identify them by the Import Batch name shown in the commit output.

---

## Notes on Data & Privacy

- Your Airtable API token and Base ID are stored **only on your computer** in a file called `logbook.json`. This file is never synced to GitHub.
- The web interface runs locally only — it is not accessible from other computers on your network.
- Your flight data lives in **your** Airtable account. No one else has access to it.

---

*Questions? Open an issue on GitHub or reach out to the pilot who shared this with you.*
