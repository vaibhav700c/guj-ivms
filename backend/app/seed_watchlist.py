"""Watchlist + VAHAN-like data mirroring plan.md §8.4 / §19.2.

Watchlist entries match actual Gujarat police FIR formats.
VAHAN records cover the Gujarat RTO code range (GJ01-GJ30+) with
real vehicle makes/models, owner names, and RTO offices.
"""

WATCHLIST = [
    # category, subject_type, identifier, severity, fir_number, police_station, description
    ("stolen_vehicle",    "vehicle", "GJ 01 AB 1234", "critical", "FIR-2024-AHD-001", "Navrangpura PS, Ahmedabad",
     "White Maruti Swift — carjacked on 2024-08-15 near Sabarmati"),
    ("stolen_vehicle",    "vehicle", "GJ 05 CD 5678", "critical", "FIR-2024-SUR-002", "Athwa PS, Surat",
     "Black Hero Splendor Plus — stolen from Adajan residential area"),
    ("stolen_vehicle",    "vehicle", "GJ 03 EF 9012", "high",     "FIR-2024-VAD-003", "Vadodara City PS",
     "Red Hyundai i20 Asta — used in armed robbery, Alkapuri 2024-09-03"),
    ("blacklisted_vehicle","vehicle","GJ 18 GH 3456", "medium",   None,               None,
     "Tata LPT 407 truck — tax defaulter ₹84,000 pending, fitness expired"),
    ("blacklisted_vehicle","vehicle","GJ 01 JK 7890", "medium",   None,               None,
     "Honda City ZX — insurance expired 2024-06-11, fitness certificate revoked"),
    ("wanted_person",     "person",  "Suspect A (Rakesh P.)", "critical", "FIR-2024-AHD-010", "Crime Branch Ahmedabad",
     "Wanted for armed robbery, 3 FIRs registered — DO NOT APPROACH ALONE"),
    ("missing_person",    "person",  "Suspect B (Mohan L.)", "high",     "MR-2024-AHD-015",  "Ellisbridge PS, Ahmedabad",
     "Missing minor male, 16 yrs — last seen near Kankaria Lake 2024-09-01"),
]


def _vr(reg, owner, cls, maker, model, color, fuel, reg_dt, ins_till, fit_till, rto, rto_name):
    return (reg, owner, cls, maker, model, color, fuel, reg_dt, ins_till, fit_till, rto, rto_name)


VAHAN_RECORDS = [
    # Watchlist plates (must match exactly for alert engine)
    _vr("GJ01AB1234", "Ramesh Kantilal Patel",    "Motor Car",             "MARUTI SUZUKI", "SWIFT VDI",        "WHITE",  "DIESEL",  "2020-03-15", "2025-03-14", "2025-03-14", "GJ01", "Ahmedabad (Central)"),
    _vr("GJ05CD5678", "Kiran Hemant Shah",         "Motor Cycle",           "HERO",          "SPLENDOR PLUS",    "BLACK",  "PETROL",  "2019-07-22", "2024-07-21", "2026-07-21", "GJ05", "Surat"),
    _vr("GJ03EF9012", "Devendra Suresh Joshi",     "Motor Car",             "HYUNDAI",       "I20 ASTA",         "RED",    "PETROL",  "2021-11-05", "2026-11-04", "2026-11-04", "GJ03", "Vadodara"),
    _vr("GJ18GH3456", "Haulage Transport Co.",     "Heavy Goods Vehicle",   "TATA",          "LPT 407",          "BLUE",   "DIESEL",  "2018-01-30", "2024-01-29", "2024-01-29", "GJ18", "Gandhinagar"),
    _vr("GJ01JK7890", "Priya Mahesh Mehta",        "Motor Car",             "HONDA",         "CITY ZX",          "SILVER", "PETROL",  "2017-06-12", "2024-06-11", "2027-06-11", "GJ01", "Ahmedabad (Central)"),
    # Additional Ahmedabad vehicles
    _vr("GJ01MN2345", "Alpesh Ramji Solanki",      "Motor Cycle",           "BAJAJ",         "PULSAR 150",       "BLUE",   "PETROL",  "2022-02-18", "2027-02-17", "2027-02-17", "GJ01", "Ahmedabad (Central)"),
    _vr("GJ01PQ6789", "Sunita Girish Desai",       "Motor Car",             "TATA",          "NEXON XM",         "GREY",   "DIESEL",  "2023-04-25", "2028-04-24", "2028-04-24", "GJ01", "Ahmedabad (Central)"),
    _vr("GJ01RS4567", "Vikram Singh Chauhan",      "Light Goods Vehicle",   "MAHINDRA",      "BOLERO PICKUP",    "WHITE",  "DIESEL",  "2020-09-14", "2025-09-13", "2025-09-13", "GJ01", "Ahmedabad (Central)"),
    _vr("GJ01TU8901", "Nikhil Vipul Trivedi",      "Motor Car",             "TOYOTA",        "FORTUNER 4X2",     "BLACK",  "DIESEL",  "2019-12-01", "2024-11-30", "2026-11-30", "GJ01", "Ahmedabad (Central)"),
    _vr("GJ01VW3210", "Bhavna Ajit Rathod",        "Motor Cycle",           "HONDA",         "ACTIVA 6G",        "GOLD",   "PETROL",  "2021-08-09", "2026-08-08", "2026-08-08", "GJ01", "Ahmedabad (Central)"),
    _vr("GJ01XY5432", "Jayesh Harishbhai Modi",    "Motor Car",             "MARUTI SUZUKI", "DZIRE VXI",        "WHITE",  "PETROL",  "2022-05-20", "2027-05-19", "2027-05-19", "GJ01", "Ahmedabad (Central)"),
    _vr("GJ01ZA7654", "Meena Suresh Jain",         "Motor Car",             "HYUNDAI",       "CRETA SX",         "SILVER", "DIESEL",  "2021-03-12", "2026-03-11", "2026-03-11", "GJ01", "Ahmedabad (Central)"),
    # Surat vehicles
    _vr("GJ05BC1122", "Suresh Arjunbhai Patel",    "Motor Car",             "MARUTI SUZUKI", "BALENO DELTA",     "WHITE",  "PETROL",  "2022-07-01", "2027-06-30", "2027-06-30", "GJ05", "Surat"),
    _vr("GJ05DE3344", "Fatima Abdul Shaikh",        "Motor Cycle",           "TVS",           "JUPITER",          "RED",    "PETROL",  "2021-11-15", "2026-11-14", "2026-11-14", "GJ05", "Surat"),
    _vr("GJ05FG5566", "Harshad Bhupesh Mehta",     "Motor Car",             "KIA",           "SELTOS HTK",       "GREY",   "DIESEL",  "2023-01-08", "2028-01-07", "2028-01-07", "GJ05", "Surat"),
    _vr("GJ05HI7788", "Rohit Pravinbhai Shah",     "Motor Car",             "HONDA",         "AMAZE VX",         "SILVER", "DIESEL",  "2020-08-25", "2025-08-24", "2025-08-24", "GJ05", "Surat"),
    _vr("GJ05JK9900", "Nikita Chirag Desai",       "Motor Car",             "TATA",          "TIAGO XZ",         "BLUE",   "PETROL",  "2022-12-10", "2027-12-09", "2027-12-09", "GJ05", "Surat"),
    # Vadodara vehicles
    _vr("GJ06BC1234", "Dinesh Ramanlal Rao",       "Motor Car",             "HONDA",         "CITY 4TH GEN",     "PEARL WHITE","PETROL","2021-02-20","2026-02-19","2026-02-19", "GJ06", "Vadodara"),
    _vr("GJ06DE5678", "Priyanka Santosh Gupta",    "Motor Car",             "MARUTI SUZUKI", "ERTIGA ZXI",       "BROWN",  "PETROL",  "2022-06-14", "2027-06-13", "2027-06-13", "GJ06", "Vadodara"),
    _vr("GJ06FG9012", "Mahesh Laxmibhai Patel",    "Motor Cycle",           "BAJAJ",         "DOMINAR 400",      "BLACK",  "PETROL",  "2020-04-05", "2025-04-04", "2025-04-04", "GJ06", "Vadodara"),
    # Rajkot vehicles
    _vr("GJ03HI3456", "Bhavesh Gopalbhai Makwana", "Motor Car",             "MARUTI SUZUKI", "SWIFT ZXI",        "RED",    "PETROL",  "2023-03-18", "2028-03-17", "2028-03-17", "GJ03", "Rajkot"),
    _vr("GJ03JK7890", "Komal Jayantibhai Dodiya",  "Motor Car",             "TATA",          "PUNCH CREATIVE",   "DAYTONA GREY","PETROL","2023-08-22","2028-08-21","2028-08-21","GJ03", "Rajkot"),
    _vr("GJ03LM2345", "Rajesh Kanubhai Joshi",     "Motor Cycle",           "ROYAL ENFIELD", "BULLET 350",       "BLACK",  "PETROL",  "2019-11-03", "2024-11-02", "2025-11-02", "GJ03", "Rajkot"),
    # Gandhinagar / highway vehicles
    _vr("GJ18NO6789", "Laxmi Transport Pvt Ltd",   "Heavy Goods Vehicle",   "ASHOK LEYLAND", "DOST 1.7T",        "WHITE",  "DIESEL",  "2021-07-20", "2026-07-19", "2026-07-19", "GJ18", "Gandhinagar"),
    _vr("GJ18PQ1111", "Bharatbhai Nathabhai Patel","Motor Car",             "TOYOTA",        "INNOVA CRYSTA GX", "SILVER", "DIESEL",  "2020-02-14", "2025-02-13", "2026-02-13", "GJ18", "Gandhinagar"),
    # Junagadh / Gir Somnath vehicles
    _vr("GJ08RS2222", "Kantibhai Manubhai Mer",    "Motor Car",             "MARUTI SUZUKI", "GYPSY MG413W",     "GREEN",  "PETROL",  "2016-05-01", "2024-05-31", "2026-05-01", "GJ08", "Junagadh"),
    _vr("GJ08TU3333", "Savitaben Arjunbhai Gohil", "Motor Cycle",           "HERO",          "HF DELUXE",        "RED",    "PETROL",  "2020-09-10", "2025-09-09", "2025-09-09", "GJ08", "Junagadh"),
    _vr("GJ08VW4444", "Mukesh Haribhai Baraiya",   "Motor Car",             "MAHINDRA",      "SCORPIO S5",       "BLACK",  "DIESEL",  "2018-12-22", "2023-12-21", "2025-12-21", "GJ08", "Junagadh"),
    # Navsari / Bilimora vehicles
    _vr("GJ24XY5555", "Dilip Ravjibhai Patel",     "Motor Car",             "SUZUKI",        "ACCESS 125",       "BLUE",   "PETROL",  "2022-04-07", "2027-04-06", "2027-04-06", "GJ24", "Navsari"),
    _vr("GJ24ZA6666", "Hansa Dhirajlal Desai",     "Motor Car",             "MARUTI SUZUKI", "ALTO 800 LXI",     "WHITE",  "PETROL",  "2019-06-18", "2024-06-17", "2024-06-17", "GJ24", "Navsari"),
    # Kutch / Gandhidham vehicles
    _vr("GJ30BC7777", "Rajendra Shivlal Patel",    "Motor Car",             "MAHINDRA",      "THAR LX 4WD",      "NAPOLI BLACK","DIESEL","2022-11-30","2027-11-29","2027-11-29","GJ30", "Kutch (Bhuj)"),
    _vr("GJ30DE8888", "Harjibhai Pethabhai Jadeja", "Heavy Goods Vehicle",  "TATA",          "PRIMA 4825",       "WHITE",  "DIESEL",  "2017-04-25", "2022-04-24", "2023-04-24", "GJ30", "Kutch (Bhuj)"),
    # Anand / Kheda vehicles
    _vr("GJ17FG9999", "Prakashbhai Ambalal Shah",  "Motor Car",             "HONDA",         "JAZZ VX CVT",      "LUNAR SILVER","PETROL","2021-10-01","2026-09-30","2026-09-30","GJ17", "Anand"),
    _vr("GJ17HI0001", "Nandini Premji Patel",      "Motor Car",             "RENAULT",       "KWID 1.0 RXL",     "FIRE RED","PETROL", "2022-03-25", "2027-03-24", "2027-03-24", "GJ17", "Anand"),
    _vr("GJ17JK0002", "Rameshbhai Bhagubhai Patel","Motor Cycle",           "TVS",           "APACHE RTR 160",   "RED",    "PETROL",  "2020-07-11", "2025-07-10", "2025-07-10", "GJ17", "Anand"),
    # Patan vehicles
    _vr("GJ02LM0003", "Prafulbhai Shanabhai Patel","Motor Car",             "MARUTI SUZUKI", "ERTIGA LDI",       "GREY",   "DIESEL",  "2023-02-14", "2028-02-13", "2028-02-13", "GJ02", "Patan"),
    _vr("GJ02NO0004", "Daksha Ashokbhai Pathak",   "Motor Car",             "TATA",          "SAFARI ADVENTURE", "WHITE",  "DIESEL",  "2022-09-05", "2027-09-04", "2027-09-04", "GJ02", "Patan"),
    # Commercial / freight vehicles
    _vr("GJ01PQ0005", "Rajkot Cargo Express",      "Heavy Goods Vehicle",   "EICHER",        "PRO 3015",         "YELLOW", "DIESEL",  "2019-03-20", "2024-03-19", "2024-03-19", "GJ01", "Ahmedabad (Central)"),
    _vr("GJ05RS0006", "Surat Freight Lines",       "Medium Goods Vehicle",  "MAHINDRA",      "BLAZO 31",         "ORANGE", "DIESEL",  "2020-11-08", "2025-11-07", "2025-11-07", "GJ05", "Surat"),
    _vr("GJ06TU0007", "Vadodara Logistics",        "Light Commercial",      "PIAGGIO",       "APE TRUK",         "YELLOW", "DIESEL",  "2021-05-30", "2026-05-29", "2026-05-29", "GJ06", "Vadodara"),
    # Buses
    _vr("GJ01VW0008", "GSRTC",                     "Bus",                   "ASHOK LEYLAND", "VIKING B",         "RED",    "DIESEL",  "2018-08-14", "2023-08-13", "2024-08-13", "GJ01", "Ahmedabad (Central)"),
    _vr("GJ05XY0009", "Surat BRTS",                "Bus",                   "TATA",          "STARBUS ULTRA",    "ORANGE", "CNG",     "2022-07-20", "2027-07-19", "2027-07-19", "GJ05", "Surat"),
    # Electric vehicles
    _vr("GJ01ZA0010", "Ankit Bipinchandra Shah",   "Motor Car",             "TATA",          "NEXON EV MAX",     "INTENSI TEAL","ELECTRIC","2023-06-10","2028-06-09","2028-06-09","GJ01", "Ahmedabad (Central)"),
    _vr("GJ06BC0011", "Mittal Dilipkumar Patel",   "Motor Car",             "MG",            "ZS EV EXCITE+",    "AURORA SILVER","ELECTRIC","2022-12-25","2027-12-24","2027-12-24","GJ06", "Vadodara"),
    _vr("GJ05DE0012", "Kavita Sureshbhai Rathod",  "Motor Cycle",           "ATHER",         "450X GEN 3",       "COSMIC BLACK","ELECTRIC","2023-04-15","2028-04-14","2028-04-14","GJ05", "Surat"),
    # Auto-rickshaws
    _vr("GJ01FG0013", "Mahmudbhai Yunusbhai Shaikh","Three Wheeler (Auto)", "BAJAJ",         "RE COMPACT 4S",    "YELLOW", "CNG",     "2021-01-15", "2026-01-14", "2026-01-14", "GJ01", "Ahmedabad (Central)"),
    _vr("GJ05HI0014", "Suleman Ismail Shaikh",     "Three Wheeler (Auto)",  "PIAGGIO",       "APE AUTO",         "YELLOW", "CNG",     "2020-06-22", "2025-06-21", "2025-06-21", "GJ05", "Surat"),
    # More Ahmedabad private vehicles
    _vr("GJ01JK0015", "Yogesh Champaklal Dave",    "Motor Car",             "VOLKSWAGEN",    "POLO HIGHLINE",    "CARBON STEEL","PETROL","2018-09-01","2023-08-31","2025-08-31","GJ01", "Ahmedabad (Central)"),
    _vr("GJ01LM0016", "Reena Sureshbhai Modi",     "Motor Car",             "SKODA",         "RAPID STYLE",      "CANDY WHITE","PETROL","2019-10-20","2024-10-19","2025-10-19","GJ01", "Ahmedabad (Central)"),
    _vr("GJ01NO0017", "Jitendra Kantilal Parikh",  "Motor Car",             "FORD",          "ECOSPORT TITANIUM","OXFORD WHITE","DIESEL","2020-07-03","2025-07-02","2025-07-02","GJ01", "Ahmedabad (Central)"),
    _vr("GJ01PQ0018", "Shailesh Hasmukhlal Shah",  "Motor Car",             "HYUNDAI",       "VENUE SX+",        "TYPHOON SILVER","PETROL","2022-11-11","2027-11-10","2027-11-10","GJ01", "Ahmedabad (Central)"),
    _vr("GJ01RS0019", "Geeta Dineshbhai Trivedi",  "Motor Car",             "MARUTI SUZUKI", "BREZZA ZXI",       "EARTH GOLD","PETROL","2023-02-28","2028-02-27","2028-02-27","GJ01", "Ahmedabad (Central)"),
    _vr("GJ01TU0020", "Harshil Nileshbhai Patel",  "Motor Car",             "KIA",           "SONET HTX",        "IMPERIAL BLUE","DIESEL","2022-08-15","2027-08-14","2027-08-14","GJ01", "Ahmedabad (Central)"),
]
