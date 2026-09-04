"""Real camera registry — 30 live Sentinel Grid cameras + 20 departmental cameras.

Sentinel Grid cameras:
  HLS  : https://cctv.corp8.cloud/{id}/index.m3u8   (CDN, password-protected)
  RTSP : rtsp://103.250.160.189:8554/stream/{id}     (direct TCP)
  WHEP : http://103.250.160.189:8889/stream/{id}/whep (WebRTC low-latency)

Camera IDs and names sourced directly from the live catalogue at:
  https://cctv.corp8.cloud/cameras.json
"""

# (sentinel_id, display_name, city, district, lat, lng, camera_type, tier, road)
# Coordinates are real Gujarat locations matching each camera's actual area
#
# Tiers for cam01-cam15 reflect a real capability audit (operator watched each
# live feed at night and recorded exactly what is/isn't legible — see
# CAMERA_CAPABILITY_NOTES below), not a guess. Several were previously
# mislabeled Tier A ("Full ANPR + Face") when the plate/face are provably not
# legible on that feed (headlight glare, distance, resolution), and several
# were mislabeled Tier C when they actually support solid vehicle
# classification/tracking (Tier B) even without plate/face. cam16-30 are
# unaudited — left as originally assigned.
SENTINEL_CAMERAS = [
    ("cam01", "Chiman bhai Bridge",          "Ahmedabad",  "Ahmedabad",  23.0265, 72.5714, "anpr",   "B", "Chimanbhai Bridge Rd"),
    ("cam02", "Janpath",                     "Ahmedabad",  "Ahmedabad",  23.0330, 72.5600, "anpr",   "B", "Janpath Rd"),
    ("cam03", "O.N.G.C. Office",             "Ahmedabad",  "Ahmedabad",  23.0401, 72.5611, "bullet", "B", "ONGC Colony Rd"),
    ("cam04", "Paldi Circle",                "Ahmedabad",  "Ahmedabad",  23.0040, 72.5680, "anpr",   "A", "Paldi Circle"),
    ("cam05", "Visat teen Rasta",            "Ahmedabad",  "Ahmedabad",  23.1100, 72.5870, "anpr",   "B", "Visat Petrol Pump Rd"),
    ("cam06", "Timbavadi Gate - Junagadh",   "Junagadh",   "Junagadh",   21.5310, 70.4710, "anpr",   "A", "Timbavadi Gate"),
    ("cam07", "Hero Showroom - Gir Somnath", "Gir Somnath","Gir Somnath",20.9080, 70.3720, "bullet", "A", "Veraval Rd"),
    ("cam08", "Majewadi Gate - Junagadh",    "Junagadh",   "Junagadh",   21.5220, 70.4600, "anpr",   "B", "Majevadi Gate"),
    ("cam09", "New Bypass Circle - Junagadh","Junagadh",   "Junagadh",   21.5480, 70.4830, "bullet", "C", "Junagadh Bypass"),
    ("cam10", "Char Chowk Road - Junagadh",  "Junagadh",   "Junagadh",   21.5200, 70.4550, "dome",   "B", "Char Chowk"),
    ("cam11", "Dolatpara - Junagadh",        "Junagadh",   "Junagadh",   21.5180, 70.4630, "dome",   "B", "Dolatpara"),
    ("cam12", "Tri Mandir Adalaj Tollnaka",  "Gandhinagar","Gandhinagar", 23.1660, 72.5800, "anpr",   "A", "SG Hwy Tollnaka"),
    ("cam13", "C.N. Vidhyalaya",             "Ahmedabad",  "Ahmedabad",  23.0390, 72.5560, "dome",   "B", "Ambawadi"),
    ("cam14", "Delight - RLVD",              "Ahmedabad",  "Ahmedabad",  23.0750, 72.5000, "bullet", "B", "RLVD Rd"),
    ("cam15", "Suvidha Park",                "Ahmedabad",  "Ahmedabad",  23.0620, 72.5450, "dome",   "B", "Suvidha Park"),
    ("cam16", "Visat P2",                    "Ahmedabad",  "Ahmedabad",  23.1080, 72.5880, "anpr",   "A", "Visat"),
    ("cam17", "Rajkot Bus Port CCTV",        "Rajkot",     "Rajkot",     22.3010, 70.8010, "anpr",   "A", "Rajkot Bus Port"),
    ("cam18", "Rajkot CCTV",                 "Rajkot",     "Rajkot",     22.3030, 70.8020, "bullet", "B", "Rajkot City Centre"),
    ("cam19", "Khaparia Gram Panchayat - Navsari","Navsari","Navsari",   20.9570, 72.9250, "dome",   "C", "Gandevi Rd"),
    ("cam20", "Mohanpura",                   "Rajkot",     "Rajkot",     22.2960, 70.8040, "dome",   "C", "Mohanpura"),
    ("cam21", "Patan Dethali Char Rasta",    "Patan",      "Patan",      23.8420, 72.1140, "anpr",   "A", "Dethali Char Rasta"),
    ("cam22", "BK Mervada tran Rasta",       "Patan",      "Patan",      23.8500, 72.1270, "bullet", "B", "BK Mervada"),
    ("cam23", "Kheram",                      "Gandhinagar","Gandhinagar", 23.1720, 72.6540, "dome",   "C", "Kheram"),
    ("cam24", "Dehgam",                      "Gandhinagar","Gandhinagar", 23.1750, 73.0000, "bullet", "B", "Dehgam Rd"),
    ("cam25", "Dhanori",                     "Gandhinagar","Gandhinagar", 23.2000, 72.7500, "dome",   "C", "Dhanori"),
    ("cam26", "TANKAL",                      "Navsari",    "Navsari",    20.9260, 72.9560, "bullet", "B", "Tankal"),
    ("cam27", "Bilimora Junction 1",         "Navsari",    "Navsari",    20.7680, 72.9600, "anpr",   "A", "Bilimora Station Rd"),
    ("cam28", "Bilimora Junction 2",         "Navsari",    "Navsari",    20.7700, 72.9610, "bullet", "B", "Bilimora Town"),
    ("cam29", "Bilimora Junction 3",         "Navsari",    "Navsari",    20.7720, 72.9620, "dome",   "C", "Bilimora Market"),
    ("cam30", "Gandhidham Rambaugh P2",      "Kutch",      "Kutch",      23.0830, 70.1320, "anpr",   "A", "Rambaugh P2"),
]

# Real per-camera capability audit (operator review of each live feed at
# night) for cam01-cam15 — what a human can actually read off the feed, not
# an assumption from the tier letter. Consumed by both seed.py (folded into
# each Camera's analytics_config) and analytics/worker.py, which skips the
# plate/face passes entirely for a camera marked False here instead of
# running (and potentially hallucinating on) a crop that's already known to
# be illegible — see the ANPR hallucination note in CLAUDE.md. Cameras not
# listed here (cam16-30, and any camera added later) default to "attempt it"
# based on tier, preserving prior behaviour.
CAMERA_CAPABILITY_NOTES: dict[str, dict] = {
    "cam01": {"plate_readable": False, "face_readable": False,
              "notes": "Headlight glare blinds plates; no face recognition. Reliable vehicle type/count/parking/streetlight status."},
    "cam02": {"plate_readable": False, "face_readable": False,
              "notes": "No plate, no face. Reliable vehicle type+brand, wet-road detection, zebra-crossing compliance."},
    "cam03": {"plate_readable": False, "face_readable": False,
              "notes": "B&W feed — no plate, no color. Vehicle type distinguishable (not brand); 2-wheeler rider count visible."},
    "cam04": {"plate_readable": True, "face_readable": True,
              "notes": "Plate readable depending on lighting; face recognition and rider/occupant counts work."},
    "cam05": {"plate_readable": False, "face_readable": False,
              "notes": "Night headlight glare blinds plates entirely; no face recognition. Reliable type/brand/count."},
    "cam06": {"plate_readable": True, "face_readable": True,
              "notes": "High quality — exact plate reads and face ID, including driver/passenger visibility."},
    "cam07": {"plate_readable": True, "face_readable": True,
              "notes": "IR night vision reads plates perfectly; B&W so no color; rider face somewhat recognisable."},
    "cam08": {"plate_readable": False, "face_readable": False,
              "notes": "No plate, no face (distance/low light). Good vehicle count/classification/direction; can guess model."},
    "cam09": {"plate_readable": False, "face_readable": False,
              "notes": "Headlight-blinded — can only guess vehicle size class (bike/car/big vehicle). No plate, type, color, or occupants."},
    "cam10": {"plate_readable": False, "face_readable": False,
              "notes": "Plate visible but too blurry to read accurately; no face. Solid multi-type classification, pedestrian and multi-direction tracking."},
    "cam11": {"plate_readable": False, "face_readable": False,
              "notes": "No reliable plate; face/dress only guessable, not recognisable. Good classify/count and loitering detection."},
    "cam12": {"plate_readable": True, "face_readable": True,
              "notes": "Toll-plaza quality — exact plate and model reads, driver directly identifiable."},
    "cam13": {"plate_readable": False, "face_readable": False,
              "notes": "No plate, no face; overexposed signboards. Good classification and multi-signal traffic-light monitoring. KNOWN HEALTH ISSUE: a thick black cable crosses the lens, occluding part of the frame — needs a maintenance visit, not a software fix."},
    "cam14": {"plate_readable": False, "face_readable": False,
              "notes": "No plate (lens flare at intersection center), no face. Good classification, red-light compliance, helmet-usage detection."},
    "cam15": {"plate_readable": False, "face_readable": False,
              "notes": "Plates too blurry/washed out; faces obscured by helmets/angle/blur. Good classification, traffic-light and violation (stopped-on-crossing) detection, helmet-usage counts."},
}

# Departmental cameras (no Sentinel Grid stream — departmental VMS / future onboarding)
# (name, city, district, lat, lng, camera_type, tier, road)
DEPARTMENTAL_CAMERAS = [
    ("Ring Road Junction",          "Surat",      "Surat",      21.1702, 72.8311, "anpr",   "A", "Ring Rd"),
    ("Athwa Gate - Ghod Dod Road",  "Surat",      "Surat",      21.1890, 72.8150, "anpr",   "A", "Ghod Dod Rd"),
    ("Hazira Industrial Area Gate", "Surat",      "Surat",      21.0950, 72.6480, "anpr",   "A", "Hazira Rd"),
    ("Race Course Circle",          "Vadodara",   "Vadodara",   22.3110, 73.1810, "anpr",   "A", "Race Course Rd"),
    ("Alkapuri - RC Dutt Road",     "Vadodara",   "Vadodara",   22.3080, 73.1760, "anpr",   "A", "RC Dutt Rd"),
    ("Fatehgunj Circle",            "Vadodara",   "Vadodara",   22.3320, 73.1830, "anpr",   "A", "Fatehgunj"),
    ("Kalawad Road Circle",         "Rajkot",     "Rajkot",     22.2950, 70.7940, "anpr",   "A", "Kalawad Rd"),
    ("Gandhinagar Sector 21 Chowk", "Gandhinagar","Gandhinagar",23.2240, 72.6490, "anpr",   "A", "Sector Rd"),
    ("Gandhinagar Sector 16/17",    "Gandhinagar","Gandhinagar",23.2330, 72.6500, "anpr",   "A", "CH Rd"),
    ("Sarkhej-Gandhinagar Hwy Toll","Gandhinagar","Gandhinagar",23.1300, 72.5800, "anpr",   "A", "SG Hwy"),
    ("Bharuch Narmada Bridge South","Bharuch",    "Bharuch",    21.7000, 72.9950, "anpr",   "A", "NH-48"),
    ("Anand Amul Dairy Circle",     "Anand",      "Anand",      22.5650, 72.9290, "anpr",   "A", "NH-48"),
    ("Jamnagar Refinery Gate",      "Jamnagar",   "Jamnagar",   22.3250, 69.7900, "anpr",   "A", "Refinery Rd"),
    ("Kutch Mundra Port Gate",      "Kutch",      "Kutch",      22.7500, 69.5250, "anpr",   "A", "Port Rd"),
    ("Palsana Highway Checkpost",   "Surat",      "Surat",      21.2500, 72.9300, "anpr",   "A", "NH-48"),
    ("Maninagar Station Road",      "Ahmedabad",  "Ahmedabad",  22.9960, 72.6020, "dome",   "B", "Maninagar"),
    ("Adajan Patiya Circle",        "Surat",      "Surat",      21.2050, 72.8000, "bullet", "B", "Adajan"),
    ("Waghodia Road Junction",      "Vadodara",   "Vadodara",   22.3210, 73.2100, "bullet", "B", "Waghodia Rd"),
    ("Bhavnagar Takhteshwar Jn",    "Bhavnagar",  "Bhavnagar",  21.7650, 72.1520, "bullet", "B", "Takhteshwar"),
    ("Nadiad Railway Crossing",     "Kheda",      "Kheda",      22.6930, 72.8620, "bullet", "B", "Station Rd"),
]

VEHICLE_TYPES = [
    ("car",   ["Maruti Swift", "Hyundai i20", "Tata Nexon", "Honda City", "Maruti Baleno"]),
    ("bike",  ["Hero Splendor", "Bajaj Pulsar", "Honda Activa", "TVS Jupiter"]),
    ("truck", ["Tata 407", "Ashok Leyland Dost", "Eicher Pro"]),
    ("auto",  ["Bajaj RE", "Piaggio Ape"]),
    ("bus",   ["Ashok Leyland Viking", "GSRTC Express"]),
]

COLORS = ["WHITE", "BLACK", "SILVER", "GREY", "RED", "BLUE", "GOLD", "GREEN"]
