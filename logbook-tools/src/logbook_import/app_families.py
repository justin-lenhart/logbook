"""
Application-family mapping for airline / FAA hour-reporting pages.

The live Aircraft table splits types finer than airline applications do
(e.g. TH-57B + TH-57C, or CR5/CR7/CR9/CRJ). Applications group by *family*.
This module is the single source of truth that:

  * maps each Airtable Aircraft name -> an application family code, and
  * carries the per-family display attributes each application needs
    (SWA category, FAA category bucket, UAL make/model, etc.), plus the
    fixed historical military **sortie counts** used for the "x 0.3 per
    sortie" conversion that SWA (and the legacy Summary) applies.

Sortie counts are a one-time historical quantity (legacy military flying is
complete). They are seeded here, verbatim, from the SWA worksheet of
LEN2J-AnytimeLogbook2025.12.01.xlsx so the generated pages reconcile exactly
with the trusted logbook. For any *future* live military leg, count it as one
sortie in the relevant role.

Nothing here is written to Airtable; the generator reads Airtable hours and
joins to this config in memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# SWA military-sortie conversion factor (hours added per sortie).
SORTIE_FACTOR = 0.3


@dataclass(frozen=True)
class Sorties:
    """Historical military sortie counts for the x0.3 conversion."""

    pic: int = 0
    sic: int = 0
    ip: int = 0  # instructor / evaluator

    @property
    def picsic(self) -> int:
        return self.pic + self.sic


@dataclass(frozen=True)
class Family:
    code: str            # application family code (e.g. "AH1Z", "CRJ")
    label: str           # human label (e.g. "AH-1Z", "CRJ-200/700/900")
    faa_bucket: str      # "Airplane" | "Rotorcraft" | "Powered Lift" | "Glider"
    swa_category: str    # SWA "Aircraft Category Totals" bucket
    ual_mfr: str
    ual_model: str
    ual_class: str       # UAL aircraft-class label
    ual_powerplant: str  # "Propeller" | "Jet"
    ual_type_rated: bool
    sorties: Sorties = field(default_factory=Sorties)


# SWA "Aircraft Category Totals" buckets (order as on the worksheet).
SWA_CATEGORIES = [
    "Jet/Turbine",
    "Large/Heavy Military",
    "Fighters",
    "Military Trainers",
    "Turbo Prop Multi Engine",
    "Turbo Prop Single Engine",
    "Light Piston",
    "Helicopter/Power Lift",
]

HELO = "Helicopter/Power Lift"

# Per-family definitions. Sorties seeded from the SWA worksheet.
FAMILIES: dict[str, Family] = {
    "AH1Z":  Family("AH1Z",  "AH-1Z",  "Rotorcraft",   HELO,
                    "Bell", "AH-1Z", "Rotorcraft", "Propeller", True,
                    Sorties(pic=82, sic=191, ip=12)),
    "UC12W": Family("UC12W", "UC-12W", "Airplane",     "Turbo Prop Multi Engine",
                    "Beechcraft", "UC-12W (King Air)", "Multi Engine Land", "Propeller", True,
                    Sorties(pic=13, sic=103)),
    "H57":   Family("H57",   "TH-57B/C", "Rotorcraft", HELO,
                    "Bell", "TH-57", "Rotorcraft", "Propeller", True,
                    Sorties(sic=77)),
    "T6":    Family("T6",    "T-6B",   "Airplane",     "Military Trainers",
                    "Beechcraft", "T-6B Texan II", "Single Engine Land", "Propeller", True,
                    Sorties(pic=3, sic=40)),
    "C172":  Family("C172",  "C172",   "Airplane",     "Light Piston",
                    "Cessna", "172", "Single Engine Land", "Propeller", False),
    "PA44":  Family("PA44",  "PA-44",  "Airplane",     "Light Piston",
                    "Piper", "PA-44 Seminole", "Multi Engine Land", "Propeller", False),
    "AH1W":  Family("AH1W",  "AH-1W",  "Rotorcraft",   HELO,
                    "Bell", "AH-1W", "Rotorcraft", "Propeller", True,
                    Sorties(sic=3)),
    "UH1Y":  Family("UH1Y",  "UH-1Y",  "Rotorcraft",   HELO,
                    "Bell", "UH-1Y", "Rotorcraft", "Propeller", True,
                    Sorties(sic=3)),
    "V22":   Family("V22",   "V-22",   "Powered Lift", HELO,
                    "Bell-Boeing", "V-22 Osprey", "Multi Engine Land", "Propeller", True,
                    Sorties(sic=1)),
    "CRJ":   Family("CRJ",   "CRJ-200/700/900", "Airplane", "Jet/Turbine",
                    "Bombardier", "CRJ", "Multi Engine Land", "Jet", False),
    "E175":  Family("E175",  "E175",   "Airplane",     "Jet/Turbine",
                    "Embraer", "E175", "Multi Engine Land", "Jet", False),
}

# Airtable Aircraft name -> family code.
AIRCRAFT_TO_FAMILY: dict[str, str] = {
    "AH-1Z":  "AH1Z",
    "AH1-W":  "AH1W",
    "TH-57B": "H57",
    "TH-57C": "H57",
    "T-6B":   "T6",
    "C172":   "C172",
    "PA-44":  "PA44",
    "UC-12W": "UC12W",
    "UH-1Y":  "UH1Y",
    "MV-22":  "V22",
    "CR5":    "CRJ",
    "CR7":    "CRJ",
    "CR9":    "CRJ",
    "CRJ":    "CRJ",
    "E175":   "E175",
}

# Order families are presented in (matches the SWA worksheet ordering, with
# any not-yet-classified families appended).
FAMILY_ORDER = [
    "AH1Z", "UC12W", "H57", "T6", "C172", "PA44", "AH1W", "UH1Y", "V22",
    "CRJ", "E175",
]


def family_for_aircraft(name: str | None) -> str | None:
    """Return the family code for an Airtable Aircraft name, or None."""
    if not name:
        return None
    return AIRCRAFT_TO_FAMILY.get(name)
