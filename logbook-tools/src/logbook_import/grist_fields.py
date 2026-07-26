"""Grist table and column ids (mintbox Logbook doc schema).

Mirrors ``airtable_fields.py`` for the Grist backend. Column ids come from the
migrated schema (Grist normalizes names: spaces become underscores, and the
Import Batch reverse-link lists are FORMULA columns here — they compute from the
child tables' Import_Batch references and must never be written).
"""

from __future__ import annotations

# Tables
TABLE_TRIPS = "Trips"
TABLE_DUTY_PERIODS = "Duty_Periods"
TABLE_FLIGHTS = "Flights"
TABLE_AIRCRAFT = "Aircraft"
TABLE_IMPORT_BATCH = "Import_Batch"
TABLE_AIRPORTS = "Airports"

# Trips
F_TRIP_KEY = "Trip_Key"
F_TRIP_PAIRING_ID = "Trip_Number_Pairing_ID"
F_TRIP_STATUS = "Status"
F_TRIP_START_DATE = "Start_Date"
F_TRIP_END_DATE = "End_Date"
F_TRIP_BASE = "Base"
F_TRIP_PLANNED_BLOCK = "Planned_Block"
F_TRIP_PLANNED_CREDIT = "Planned_Credit"
F_TRIP_PLANNED_LEGS = "Planned_Legs"
F_TRIP_PLANNED_DUTY_PERIODS = "Planned_Duty_Periods"
F_TRIP_TAFB = "TAFB"
F_TRIP_EQUIPMENT_FAMILY = "Equipment_Family"
F_TRIP_IMPORT_BATCH = "Import_Batch"        # Ref:Import_Batch (row id)

# Duty Periods
F_DUTY_PERIOD_KEY = "Duty_Period_Key"
F_DUTY_TRIPS = "Trips"                      # Ref:Trips (row id)
F_DUTY_STATUS = "Status"
F_DUTY_DATE = "Duty_Date"
F_DUTY_REPORT_TIME = "Report_Time"
F_DUTY_RELEASE_TIME = "Release_Time"
F_DUTY_PLANNED_BLOCK = "Planned_Block"
F_DUTY_PLANNED_CREDIT = "Planned_Credit"
F_DUTY_PLANNED_LEGS = "Planned_Legs"
F_DUTY_IMPORT_BATCH = "Import_Batch"        # Ref:Import_Batch (row id)

# Flights
F_IMPORT_FLIGHT_KEY = "Import_Flight_Key"
F_FLIGHT_TRIPS = "Trips"                    # Ref:Trips (row id)
F_FLIGHT_DUTY_PERIOD = "Duty_Period"        # Ref:Duty_Periods (row id)
F_FLIGHT_DATE = "Flight_Date"
F_FLIGHT_AIRLINE = "Airline"
F_FLIGHT_NUMBER = "Flight_Number"
F_FLIGHT_DEPARTURE = "Departure_Airport"    # Ref:Airports (row id)
F_FLIGHT_ARRIVAL = "Arrival_Airport"        # Ref:Airports (row id)
F_FLIGHT_OUT_TIME = "Out_Time"
F_FLIGHT_IN_TIME = "In_Time"
F_FLIGHT_BLOCK_TIME = "Block_Time"
F_FLIGHT_CREDIT_TIME = "Credit_Time"
F_FLIGHT_PIC_TIME = "PIC_Time"
F_FLIGHT_SIC_TIME = "SIC_Time"
F_FLIGHT_POSITION = "Flight_Position"
F_FLIGHT_DEADHEAD = "Deadhead"
F_FLIGHT_AIRCRAFT = "Aircraft"              # Ref:Aircraft (row id)
F_FLIGHT_TAIL = "Tail_Number"
F_FLIGHT_OPERATION = "Operation"
F_FLIGHT_IMPORT_BATCH = "Import_Batch"      # Ref:Import_Batch (row id)
F_FLIGHT_NIGHT_TIME = "Night_Time"
F_FLIGHT_DAY_LANDING = "Day_Landing"
F_FLIGHT_NIGHT_LANDING = "Night_Landing"
F_FLIGHT_XC_TIME = "Cross_Country_Time"
F_FLIGHT_SPECIAL_CATEGORY = "Special_Category"  # ChoiceList -> ["L", ...]
F_FLIGHT_PASSENGERS = "Passengers"

# Aircraft
F_AIRCRAFT_CODE = "Aircraft"

# Import Batch (reverse-link lists are formulas in Grist -- not writable, not listed)
F_BATCH_NAME = "Batch_Name"
F_BATCH_IMPORT_TYPE = "Import_Type"
F_BATCH_IMPORT_DATETIME = "Import_Date_Time"
F_BATCH_SOURCE_FOLDER = "Source_Folder"
F_BATCH_SOURCE_FILENAME = "Source_Filename"
F_BATCH_IMPORT_STATUS = "Import_Status"

# Airports
F_AIRPORT_TYPE = "Type"
F_AIRPORT_IATA = "IATA"
F_AIRPORT_ICAO = "ICAO"
F_AIRPORT_NAME = "Airport_Name"
F_AIRPORT_CITY = "Municipality"
F_AIRPORT_COUNTRY = "Country"
F_AIRPORT_LAT = "Latitude"
F_AIRPORT_LON = "Longitude"
