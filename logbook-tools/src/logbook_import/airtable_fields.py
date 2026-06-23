"""Airtable table and field names (live logbook base schema)."""

from __future__ import annotations

# Tables
TABLE_TRIPS = "Trips"
TABLE_DUTY_PERIODS = "Duty Periods"
TABLE_FLIGHTS = "Flights"
TABLE_AIRCRAFT = "Aircraft"
TABLE_IMPORT_BATCH = "Import Batch"

# Trips
F_TRIP_KEY = "Trip Key"
F_TRIP_PAIRING_ID = "Trip Number / Pairing ID"
F_TRIP_STATUS = "Status"
F_TRIP_START_DATE = "Start Date"
F_TRIP_END_DATE = "End Date"
F_TRIP_BASE = "Base"
F_TRIP_PLANNED_BLOCK = "Planned Block"
F_TRIP_PLANNED_CREDIT = "Planned Credit"
F_TRIP_PLANNED_LEGS = "Planned Legs"
F_TRIP_PLANNED_DUTY_PERIODS = "Planned Duty Periods"
F_TRIP_TAFB = "TAFB"                       # decimal hours, from TXT header on planned import
F_TRIP_ACTUAL_BLOCK = "Actual Block"       # rollup from linked Flights
F_TRIP_ACTUAL_CREDIT = "Actual Credit"     # rollup from linked Flights
F_TRIP_ACTUAL_LEGS = "Actual Legs"         # rollup from linked Flights
F_TRIP_BLOCK_VARIANCE = "Block Variance"   # formula: Actual Block - Planned Block
F_TRIP_CREDIT_VARIANCE = "Credit Variance" # formula: Actual Credit - Planned Credit
F_TRIP_EQUIPMENT_FAMILY = "Equipment Family"
F_TRIP_IMPORT_BATCH = "Import Batch"

# Duty Periods
F_DUTY_PERIOD_KEY = "Duty Period Key"
F_DUTY_TRIPS = "Trips"
F_DUTY_STATUS = "Status"
F_DUTY_DATE = "Duty Date"
F_DUTY_REPORT_TIME = "Report Time"
F_DUTY_RELEASE_TIME = "Release Time"
F_DUTY_PLANNED_BLOCK = "Planned Block"
F_DUTY_PLANNED_CREDIT = "Planned Credit"
F_DUTY_PLANNED_LEGS = "Planned Legs"
F_DUTY_ACTUAL_BLOCK = "Actual Block"       # rollup from linked Flights
F_DUTY_ACTUAL_CREDIT = "Actual Credit"     # rollup from linked Flights
F_DUTY_ACTUAL_LEGS = "Actual Legs"         # rollup from linked Flights
F_DUTY_BLOCK_VARIANCE = "Block Variance"   # formula: Actual Block - Planned Block
F_DUTY_CREDIT_VARIANCE = "Credit Variance" # formula: Actual Credit - Planned Credit
F_DUTY_IMPORT_BATCH = "Import Batch"

# Flights
F_IMPORT_FLIGHT_KEY = "Import Flight Key"
F_FLIGHT_TRIPS = "Trips"
F_FLIGHT_DUTY_PERIOD = "Duty Period"
F_FLIGHT_DATE = "Flight Date"
F_FLIGHT_AIRLINE = "Airline"
F_FLIGHT_NUMBER = "Flight Number"
F_FLIGHT_DEPARTURE = "Departure Airport"
F_FLIGHT_ARRIVAL = "Arrival Airport"
F_FLIGHT_OUT_TIME = "Out Time"
F_FLIGHT_IN_TIME = "In Time"
F_FLIGHT_BLOCK_TIME = "Block Time"
F_FLIGHT_CREDIT_TIME = "Credit Time"
F_FLIGHT_PIC_TIME = "PIC Time"
F_FLIGHT_SIC_TIME = "SIC Time"
F_FLIGHT_DEADHEAD = "Deadhead"
F_FLIGHT_AIRCRAFT = "Aircraft"
F_FLIGHT_TAIL = "Tail Number"
F_FLIGHT_OPERATION = "Operation"
F_FLIGHT_IMPORT_BATCH = "Import Batch"
F_FLIGHT_NIGHT_TIME = "Night Time"
F_FLIGHT_DAY_LANDING = "Day Landing"
F_FLIGHT_NIGHT_LANDING = "Night Landing"
F_FLIGHT_XC_TIME = "Cross Country Time"
F_FLIGHT_SPECIAL_CATEGORY = "Special Category"
F_FLIGHT_PASSENGERS = "Passengers"

# Aircraft
F_AIRCRAFT_CODE = "Aircraft"

# Import Batch
F_BATCH_NAME = "Batch Name"
F_BATCH_IMPORT_TYPE = "Import Type"
F_BATCH_IMPORT_DATETIME = "Import Date/Time"
F_BATCH_SOURCE_FOLDER = "Source Folder"
F_BATCH_SOURCE_FILENAME = "Source Filename"
F_BATCH_IMPORT_STATUS = "Import Status"
F_BATCH_IMPORTED_TRIPS = "Imported Trips"
F_BATCH_DUTY_PERIODS = "Duty Periods"
F_BATCH_IMPORTED_FLIGHTS = "Imported Flights"

# Airports
TABLE_AIRPORTS = "Airports"
F_AIRPORT_TYPE = "Type"
F_AIRPORT_IATA = "IATA"
F_AIRPORT_ICAO = "ICAO"
F_AIRPORT_NAME = "Airport Name"
F_AIRPORT_CITY = "Municipality"
F_AIRPORT_COUNTRY = "Country"
F_AIRPORT_LAT = "Latitude"
F_AIRPORT_LON = "Longitude"
F_AIRPORT_ELEVATION = "Elevation"
F_AIRPORT_UTC_OFFSET = "UTC Offset"

