"""Watchlist + VAHAN-like demo data (from plan.md §8.4 / §19.2)."""

WATCHLIST = [
    # category, subject_type, identifier, severity, fir, police_station, description
    ("stolen_vehicle", "vehicle", "GJ 01 AB 1234", "critical", "FIR-2024-001", "Navrangpura PS",
     "White Maruti Swift — carjacked on 2024-08-15"),
    ("stolen_vehicle", "vehicle", "GJ 05 CD 5678", "critical", "FIR-2024-002", "Athwa PS",
     "Black Hero Splendor — stolen from Adajan"),
    ("stolen_vehicle", "vehicle", "GJ 03 EF 9012", "high", "FIR-2024-003", "Vadodara City PS",
     "Red Hyundai i20 — used in robbery case"),
    ("blacklisted_vehicle", "vehicle", "GJ 18 GH 3456", "medium", None, None,
     "Truck — tax defaulter, pending dues ₹84,000"),
    ("blacklisted_vehicle", "vehicle", "GJ 01 JK 7890", "medium", None, None,
     "Car — insurance expired, fitness revoked"),
    ("wanted_person", "person", "Suspect A (Rakesh P.)", "critical", "FIR-2024-010", "Crime Branch AHD",
     "Wanted for armed robbery — DO NOT APPROACH ALONE"),
    ("missing_person", "person", "Suspect B (Mohan L.)", "high", "MR-2024-015", "Ellisbridge PS",
     "Missing minor — last seen near Kankaria"),
]

VAHAN_RECORDS = [
    ("GJ01AB1234", "Ramesh Patel", "Motor Car", "MARUTI SUZUKI", "SWIFT VDI", "WHITE", "DIESEL", "2020-03-15", "2025-03-14", "2025-03-14", "GJ01", "Ahmedabad (Central)"),
    ("GJ05CD5678", "Kiran Shah", "Motor Cycle", "HERO", "SPLENDOR PLUS", "BLACK", "PETROL", "2019-07-22", "2024-07-21", "2026-07-21", "GJ05", "Surat"),
    ("GJ03EF9012", "Devendra Joshi", "Motor Car", "HYUNDAI", "I20 ASTA", "RED", "PETROL", "2021-11-05", "2026-11-04", "2026-11-04", "GJ03", "Vadodara"),
    ("GJ18GH3456", "Haulage Transport Co", "Heavy Goods Vehicle", "TATA", "LPT 407", "BLUE", "DIESEL", "2018-01-30", "2024-01-29", "2024-01-29", "GJ18", "Gandhinagar"),
    ("GJ01JK7890", "Priya Mehta", "Motor Car", "HONDA", "CITY ZX", "SILVER", "PETROL", "2017-06-12", "2024-06-11", "2027-06-11", "GJ01", "Ahmedabad (Central)"),
    ("GJ06MN2345", "Alpesh Solanki", "Motor Cycle", "BAJAJ", "PULSAR 150", "BLUE", "PETROL", "2022-02-18", "2027-02-17", "2027-02-17", "GJ06", "Rajkot"),
    ("GJ10PQ6789", "Sunita Desai", "Motor Car", "TATA", "NEXON XM", "GREY", "DIESEL", "2023-04-25", "2028-04-24", "2028-04-24", "GJ10", "Bhavnagar"),
    ("GJ02RS4567", "Vikram Chauhan", "Light Goods Vehicle", "MAHINDRA", "BOLERO PICKUP", "WHITE", "DIESEL", "2020-09-14", "2025-09-13", "2025-09-13", "GJ02", "Mehsana"),
    ("GJ27TU8901", "Nikhil Trivedi", "Motor Car", "TOYOTA", "FORTUNER 4x2", "BLACK", "DIESEL", "2019-12-01", "2024-11-30", "2026-11-30", "GJ27", "Jamnagar"),
    ("GJ09VW3210", "Bhavna Rathod", "Motor Cycle", "HONDA", "ACTIVA 6G", "GOLD", "PETROL", "2021-08-09", "2026-08-08", "2026-08-08", "GJ09", "Anand"),
]
