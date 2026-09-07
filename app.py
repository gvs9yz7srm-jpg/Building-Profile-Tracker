import streamlit as st
import sqlite3
import re
from io import BytesIO
from datetime import datetime, date, time, timedelta
from statistics import median

from PIL import Image, ImageEnhance
import pytesseract

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)
from reportlab.lib import colors


# ============================================================
# BUILDING DIFFICULTY INTELLIGENCE — V3.3
# ============================================================

st.set_page_config(
    page_title="Building Difficulty Intelligence",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="collapsed"
)

DB_NAME = "building_difficulty.db"


# ============================================================
# DATABASE
# ============================================================

@st.cache_resource
def get_connection():
    connection = sqlite3.connect(
        DB_NAME,
        check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    return connection


conn = get_connection()


def execute(query, params=()):
    cursor = conn.cursor()
    cursor.execute(query, params)
    conn.commit()
    return cursor


execute("""
CREATE TABLE IF NOT EXISTS visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    visit_date TEXT NOT NULL,
    address TEXT NOT NULL,
    street TEXT,
    suburb TEXT,
    profile_level TEXT DEFAULT 'Building',
    no_difficulty INTEGER DEFAULT 0,
    total_delay INTEGER DEFAULT 0,
    notes TEXT
)
""")


execute("""
CREATE TABLE IF NOT EXISTS conditions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    category TEXT NOT NULL,
    condition_type TEXT NOT NULL,
    delay_minutes INTEGER DEFAULT 0,
    applicability TEXT DEFAULT 'Always',
    days TEXT,
    start_time TEXT,
    end_time TEXT,
    source_status TEXT DEFAULT 'Field observation',
    manually_confirmed INTEGER DEFAULT 0,
    solution TEXT,
    solution_notes TEXT,
    concierge INTEGER DEFAULT 0,
    FOREIGN KEY (visit_id) REFERENCES visits(id)
)
""")


execute("""
CREATE TABLE IF NOT EXISTS agencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    agency_name TEXT NOT NULL,
    address TEXT,
    suburb TEXT,
    notes TEXT,
    recommended_action TEXT
)
""")


execute("""
CREATE TABLE IF NOT EXISTS agency_delays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    delay_date TEXT NOT NULL,
    agency_name TEXT NOT NULL,
    address TEXT,
    suburb TEXT,
    delay_reason TEXT,
    delay_minutes INTEGER DEFAULT 0,
    notes TEXT,
    recurring INTEGER DEFAULT 0
)
""")


execute("""
CREATE TABLE IF NOT EXISTS prediction_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    schedule_date TEXT NOT NULL,
    total_stops INTEGER DEFAULT 0,
    total_jobs INTEGER DEFAULT 0,
    flagged_stops INTEGER DEFAULT 0,
    predicted_delay INTEGER DEFAULT 0
)
""")


execute("""
CREATE TABLE IF NOT EXISTS prediction_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL,
    position INTEGER,
    stop_type TEXT,
    job_id TEXT,
    agency_name TEXT,
    address TEXT,
    suburb TEXT,
    postcode TEXT,
    planned_time TEXT,
    risk TEXT,
    predicted_delay INTEGER DEFAULT 0,
    reasons TEXT,
    FOREIGN KEY (report_id) REFERENCES prediction_reports(id)
)
""")


# New V3.3 settings table
execute("""
CREATE TABLE IF NOT EXISTS settings (
    setting_key TEXT PRIMARY KEY,
    setting_value TEXT
)
""")


# ============================================================
# CONSTANTS
# ============================================================

SITE_CONDITIONS = [
    "Parking difficult",
    "No parking available",
    "Loading zone only",
    "Long walk from parking",
    "Building access difficult",
    "Intercom delay",
    "Tenant access delay",
    "Concierge / reception delay",
    "Lift delay",
    "Multiple buildings / confusing complex",
    "Restricted access",
    "Other site difficulty"
]


SCHEDULING_CONDITIONS = [
    "Clearway / timed parking restriction",
    "Peak-hour traffic",
    "School-zone traffic",
    "Timed loading restriction",
    "Other recurring scheduling restriction"
]


AGENCY_DELAY_REASONS = [
    "Keys not ready",
    "Waiting for staff",
    "Agency closed",
    "Parking difficulty",
    "Key collection / admin delay",
    "Incorrect or missing keys",
    "Other agency delay"
]


SOLUTIONS = [
    "None",
    "Concierge parking booking",
    "Contact concierge before arrival",
    "Call tenant before arrival",
    "Alternative parking location",
    "Allow additional arrival time",
    "Use loading area",
    "Alternative building entrance",
    "Avoid restricted time window",
    "Other"
]


AGENCY_ACTIONS = [
    "None",
    "Call in advance",
    "Confirm keys are ready",
    "Allow additional time",
    "Use alternative parking",
    "Other"
]


DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday"
]


STREET_TYPES = (
    r"Street|St|Road|Rd|Avenue|Ave|Parade|Pde|"
    r"Drive|Dr|Lane|Ln|Way|Crescent|Cres|Circuit|"
    r"Boulevard|Blvd|Place|Pl|Close|Court|Ct|"
    r"Terrace|Tce|Highway|Hwy"
)


# ============================================================
# SESSION STATE
# ============================================================

defaults = {
    "conditions": [],
    "schedule_stage": "upload",
    "extracted_jobs": [],
    "analysed_jobs": [],
    "analysis_summary": {},
    "analysis_date": date.today(),
    "generated_pdf": None,
    "schedule_uploader_key": 0,
}


for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# SETTINGS
# ============================================================

def get_setting(key, default=""):
    row = execute("""
        SELECT setting_value
        FROM settings
        WHERE setting_key = ?
    """, (key,)).fetchone()

    if row:
        return row["setting_value"]

    return default


def save_setting(key, value):
    execute("""
        INSERT INTO settings (
            setting_key,
            setting_value
        )
        VALUES (?, ?)
        ON CONFLICT(setting_key)
        DO UPDATE SET
            setting_value = excluded.setting_value
    """, (
        key,
        value.strip()
    ))


# ============================================================
# GENERAL HELPERS
# ============================================================

def clean(value):
    if value is None:
        return ""

    value = str(value).lower().strip()

    value = re.sub(
        r"[^\w\s]",
        " ",
        value
    )

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


def format_time(value):
    if not value:
        return "—"

    try:
        return datetime.strptime(
            value,
            "%H:%M"
        ).strftime(
            "%I:%M %p"
        ).lstrip("0")

    except:
        return value


def normalise_time(value):
    if not value:
        return ""

    value = value.strip().upper()
    value = value.replace(".", ":")

    formats = [
        "%H:%M",
        "%H:%M:%S",
        "%I:%M %p",
        "%I:%M:%S %p",
        "%I:%M%p",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(
                value,
                fmt
            ).strftime("%H:%M")
        except:
            pass

    return ""


def week_start():
    today = date.today()

    return today - timedelta(
        days=today.weekday()
    )


def pattern_status(count, confirmed):
    if confirmed:
        return "Confirmed"

    if count >= 3:
        return "Recognised"

    if count == 2:
        return "Emerging"

    return "Observation"


def confidence(count):
    if count >= 5:
        return "High"

    if count >= 3:
        return "Moderate"

    return "Low"


def time_inside_window(planned, start, end):
    if not planned or not start or not end:
        return False

    try:
        planned_time = datetime.strptime(
            planned,
            "%H:%M"
        ).time()

        start_time = datetime.strptime(
            start,
            "%H:%M"
        ).time()

        end_time = datetime.strptime(
            end,
            "%H:%M"
        ).time()

        if start_time <= end_time:
            return start_time <= planned_time <= end_time

        return (
            planned_time >= start_time
            or planned_time <= end_time
        )

    except:
        return False


# ============================================================
# V3.3 ADDRESS CLEANER
# ============================================================

def clean_address_line(line):
    """
    Important V3.3 change.

    OCR sometimes reads:
        44B Sydney Street eee peers
        28/143-147 Parramatta Road eee arms

    We deliberately stop the address at the recognised
    street type.
    """

    if not line:
        return ""

    line = re.sub(
        r"\s+",
        " ",
        line
    ).strip()

    pattern = (
        rf"^(.+?\b(?:{STREET_TYPES})\b)"
    )

    match = re.search(
        pattern,
        line,
        re.IGNORECASE
    )

    if match:
        return match.group(1).strip()

    return line


def looks_like_address(line):
    if not line:
        return False

    cleaned = clean_address_line(line)

    return bool(
        re.search(r"\d", cleaned)
        and
        re.search(
            rf"\b(?:{STREET_TYPES})\b",
            cleaned,
            re.IGNORECASE
        )
    )


def looks_like_suburb(line):
    return bool(
        re.search(
            r"\bNSW\s+\d{4}\b",
            line,
            re.IGNORECASE
        )
    )


def parse_suburb(line):
    match = re.search(
        r"([A-Za-z][A-Za-z\s'\-]+?)"
        r"\s+NSW\s+(\d{4})",
        line,
        re.IGNORECASE
    )

    if not match:
        return "", ""

    suburb = match.group(1).strip()
    postcode = match.group(2).strip()

    # Remove OCR junk before the suburb.
    suburb = re.sub(
        r"[^A-Za-z\s'\-]",
        "",
        suburb
    ).strip()

    return suburb, postcode


def derive_street(address):
    address = clean_address_line(
        address
    )

    if not address:
        return ""

    street = re.sub(
        r"^\s*(?:Unit\s*)?"
        r"\d+[A-Za-z]?"
        r"(?:\s*/\s*\d+[A-Za-z\-]*)?"
        r"\s+",
        "",
        address,
        flags=re.IGNORECASE
    )

    return street.strip()


# ============================================================
# RESET SCHEDULE
# ============================================================

def reset_schedule():
    st.session_state.schedule_stage = "upload"
    st.session_state.extracted_jobs = []
    st.session_state.analysed_jobs = []
    st.session_state.analysis_summary = {}
    st.session_state.generated_pdf = None
    st.session_state.analysis_date = date.today()
    st.session_state.schedule_uploader_key += 1


# ============================================================
# PROPERTY DATA
# ============================================================

def save_visit(
    visit_date,
    address,
    street,
    suburb,
    profile_level,
    no_difficulty,
    conditions,
    notes
):
    total_delay = sum(
        condition["delay_minutes"]
        for condition in conditions
    )

    cursor = execute("""
        INSERT INTO visits (
            created_at,
            visit_date,
            address,
            street,
            suburb,
            profile_level,
            no_difficulty,
            total_delay,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(),
        visit_date.isoformat(),
        clean_address_line(address),
        street,
        suburb.strip(),
        profile_level,
        int(no_difficulty),
        total_delay,
        notes.strip()
    ))

    visit_id = cursor.lastrowid

    for condition in conditions:
        execute("""
            INSERT INTO conditions (
                visit_id,
                created_at,
                category,
                condition_type,
                delay_minutes,
                applicability,
                days,
                start_time,
                end_time,
                source_status,
                manually_confirmed,
                solution,
                solution_notes,
                concierge
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            visit_id,
            datetime.now().isoformat(),
            condition["category"],
            condition["condition_type"],
            condition["delay_minutes"],
            condition["applicability"],
            ",".join(condition["days"]),
            condition["start_time"],
            condition["end_time"],
            condition["source_status"],
            int(condition["confirmed"]),
            condition["solution"],
            condition["solution_notes"],
            int(condition["concierge"])
        ))


def get_visits():
    return execute("""
        SELECT *
        FROM visits
        ORDER BY visit_date DESC, created_at DESC
    """).fetchall()


def get_conditions():
    return execute("""
        SELECT
            c.*,
            v.address,
            v.street,
            v.suburb,
            v.profile_level,
            v.visit_date
        FROM conditions c
        JOIN visits v
        ON c.visit_id = v.id
        ORDER BY c.created_at DESC
    """).fetchall()


# ============================================================
# PATTERN ENGINE
# ============================================================

def build_patterns():
    rows = get_conditions()

    groups = {}

    for row in rows:
        level = row["profile_level"]

        if level == "Street":
            location = row["street"] or row["address"]

        elif level == "Area":
            location = row["suburb"]

        else:
            location = row["address"]

        key = (
            clean(location),
            row["condition_type"],
            level
        )

        if key not in groups:
            groups[key] = {
                "location": location,
                "street": row["street"],
                "suburb": row["suburb"],
                "level": level,
                "condition_type": row["condition_type"],
                "category": row["category"],
                "rows": [],
                "delays": [],
                "confirmed": False,
                "solutions": set(),
                "solution_notes": set(),
                "concierge": False,
                "time_windows": set(),
                "days": set(),
                "first_seen": row["visit_date"],
                "last_seen": row["visit_date"]
            }

        group = groups[key]

        group["rows"].append(row)

        if row["delay_minutes"] > 0:
            group["delays"].append(
                row["delay_minutes"]
            )

        if row["manually_confirmed"]:
            group["confirmed"] = True

        if (
            row["solution"]
            and row["solution"] != "None"
        ):
            group["solutions"].add(
                row["solution"]
            )

        if row["solution_notes"]:
            group["solution_notes"].add(
                row["solution_notes"]
            )

        if row["concierge"]:
            group["concierge"] = True

        if row["days"]:
            for day in row["days"].split(","):
                if day:
                    group["days"].add(day)

        if (
            row["start_time"]
            and row["end_time"]
        ):
            group["time_windows"].add(
                (
                    row["start_time"],
                    row["end_time"]
                )
            )

        group["first_seen"] = min(
            group["first_seen"],
            row["visit_date"]
        )

        group["last_seen"] = max(
            group["last_seen"],
            row["visit_date"]
        )

    patterns = []

    for group in groups.values():
        count = len(group["rows"])

        group["count"] = count

        group["status"] = pattern_status(
            count,
            group["confirmed"]
        )

        group["confidence"] = confidence(
            count
        )

        group["median_delay"] = (
            median(group["delays"])
            if group["delays"]
            else 0
        )

        patterns.append(group)

    return patterns


# ============================================================
# PROPERTY PREDICTION
# ============================================================

def pattern_matches_job(
    pattern,
    address,
    street,
    suburb
):
    if pattern["level"] == "Building":
        return (
            clean(pattern["location"])
            ==
            clean(address)
        )

    if pattern["level"] == "Street":
        return (
            clean(pattern["location"])
            ==
            clean(street)
        )

    if pattern["level"] == "Area":
        return (
            clean(pattern["location"])
            ==
            clean(suburb)
        )

    return False


def condition_applies(
    pattern,
    planned_time,
    schedule_date
):
    day_name = schedule_date.strftime(
        "%A"
    )

    if (
        pattern["days"]
        and day_name not in pattern["days"]
    ):
        return False

    if pattern["time_windows"]:
        for start, end in pattern["time_windows"]:
            if time_inside_window(
                planned_time,
                start,
                end
            ):
                return True

        return False

    return True


def analyse_property_job(
    address,
    suburb,
    planned_time,
    schedule_date
):
    address = clean_address_line(
        address
    )

    street = derive_street(
        address
    )

    matches = []
    predicted_delay = 0

    for pattern in build_patterns():
        if pattern["status"] not in [
            "Recognised",
            "Confirmed"
        ]:
            continue

        if not pattern_matches_job(
            pattern,
            address,
            street,
            suburb
        ):
            continue

        if not condition_applies(
            pattern,
            planned_time,
            schedule_date
        ):
            continue

        matches.append(pattern)

        predicted_delay += (
            pattern["median_delay"]
        )

    if predicted_delay >= 20:
        risk = "High"
        icon = "🔴"

    elif predicted_delay >= 10:
        risk = "Moderate"
        icon = "🟡"

    elif matches:
        risk = "Low"
        icon = "🟢"

    else:
        risk = "No known difficulty"
        icon = "⚪"

    return {
        "patterns": matches,
        "predicted_delay": predicted_delay,
        "risk": risk,
        "icon": icon
    }


# ============================================================
# AGENCY INTELLIGENCE
# ============================================================

def save_agency_profile(
    agency_name,
    address,
    suburb,
    notes,
    recommended_action
):
    existing = execute("""
        SELECT id
        FROM agencies
        WHERE lower(agency_name) = lower(?)
        LIMIT 1
    """, (
        agency_name.strip(),
    )).fetchone()

    if existing:
        execute("""
            UPDATE agencies
            SET
                address = ?,
                suburb = ?,
                notes = ?,
                recommended_action = ?
            WHERE id = ?
        """, (
            clean_address_line(address),
            suburb.strip(),
            notes.strip(),
            recommended_action,
            existing["id"]
        ))

    else:
        execute("""
            INSERT INTO agencies (
                created_at,
                agency_name,
                address,
                suburb,
                notes,
                recommended_action
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            agency_name.strip(),
            clean_address_line(address),
            suburb.strip(),
            notes.strip(),
            recommended_action
        ))


def save_agency_delay(
    delay_date,
    agency_name,
    address,
    suburb,
    reason,
    delay_minutes,
    notes,
    recurring
):
    execute("""
        INSERT INTO agency_delays (
            created_at,
            delay_date,
            agency_name,
            address,
            suburb,
            delay_reason,
            delay_minutes,
            notes,
            recurring
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(),
        delay_date.isoformat(),
        agency_name.strip(),
        clean_address_line(address),
        suburb.strip(),
        reason,
        delay_minutes,
        notes.strip(),
        int(recurring)
    ))


def get_agency_intelligence(
    agency_name,
    address=""
):
    profile = None

    if agency_name:
        profile = execute("""
            SELECT *
            FROM agencies
            WHERE lower(agency_name) = lower(?)
            LIMIT 1
        """, (
            agency_name.strip(),
        )).fetchone()

    delays = []

    if agency_name:
        delays = execute("""
            SELECT *
            FROM agency_delays
            WHERE lower(agency_name) = lower(?)
            ORDER BY delay_date DESC
        """, (
            agency_name.strip(),
        )).fetchall()

    if not delays and address:
        delays = execute("""
            SELECT *
            FROM agency_delays
            WHERE lower(address) = lower(?)
            ORDER BY delay_date DESC
        """, (
            clean_address_line(address),
        )).fetchall()

    delay_values = [
        row["delay_minutes"]
        for row in delays
        if row["delay_minutes"] > 0
    ]

    confirmed_recurring = any(
        row["recurring"]
        for row in delays
    )

    count = len(delays)

    recognised = (
        confirmed_recurring
        or count >= 3
    )

    typical_delay = (
        median(delay_values)
        if delay_values
        else 0
    )

    reasons = []

    for row in delays:
        reason = row["delay_reason"]

        if reason and reason not in reasons:
            reasons.append(reason)

    return {
        "profile": profile,
        "delays": delays,
        "count": count,
        "recognised": recognised,
        "typical_delay": typical_delay,
        "reasons": reasons,
        "confidence": confidence(count)
    }


def analyse_agency_stop(job):
    intelligence = get_agency_intelligence(
        job["agency_name"],
        job["address"]
    )

    predicted_delay = 0

    if intelligence["recognised"]:
        predicted_delay = (
            intelligence["typical_delay"]
        )

    if predicted_delay >= 15:
        risk = "High"
        icon = "🔴"

    elif predicted_delay > 0:
        risk = "Moderate"
        icon = "🟡"

    else:
        risk = "No recognised delay"
        icon = "📦"

    return {
        "risk": risk,
        "icon": icon,
        "predicted_delay": predicted_delay,
        "intelligence": intelligence
    }


# ============================================================
# OCR
# ============================================================

def preprocess_image(uploaded_file):
    image = Image.open(
        uploaded_file
    )

    image = image.convert("L")

    width, height = image.size

    if width < 1800:
        scale = 1800 / width

        image = image.resize(
            (
                int(width * scale),
                int(height * scale)
            )
        )

    image = ImageEnhance.Contrast(
        image
    ).enhance(1.6)

    return image


def extract_text(uploaded_file):
    image = preprocess_image(
        uploaded_file
    )

    return pytesseract.image_to_string(
        image,
        config="--psm 6"
    )


# ============================================================
# V3.3 OCR PARSER
# ============================================================

def find_job_id(lines):
    text = "\n".join(lines)

    match = re.search(
        r"Job\s*(?:ID|Id|#)?\s*:?\s*(\d{5,})",
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(1)

    return ""


def detect_stop_type(lines):
    text = " ".join(lines).lower()

    if (
        "agency pickup" in text
        or "agency pick up" in text
        or "key pickup" in text
        or "key pick up" in text
    ):
        return "Agency Pickup"

    if (
        "agency dropoff" in text
        or "agency drop off" in text
        or "key dropoff" in text
        or "key drop off" in text
    ):
        return "Agency Drop-off"

    return "Job"


def find_anticipated_time(lines):
    """
    Only uses Anticipated Appointment time / Anticipated time.

    This prevents:
        Start of Day Travel 07:15

    from becoming the first property's appointment time.
    """

    for index, line in enumerate(lines):
        lower = line.lower()

        if "anticipated" not in lower:
            continue

        search_lines = [
            line
        ]

        if index + 1 < len(lines):
            search_lines.append(
                lines[index + 1]
            )

        if index + 2 < len(lines):
            search_lines.append(
                lines[index + 2]
            )

        search_text = " ".join(
            search_lines
        )

        # Supports:
        # 08:00
        # 08:00:00
        # 08:00 AM
        match = re.search(
            r"\b("
            r"\d{1,2}:\d{2}(?::\d{2})?"
            r")\s*([APap][Mm])?",
            search_text
        )

        if match:
            raw = match.group(1)

            if match.group(2):
                raw += " " + match.group(2)

            result = normalise_time(
                raw
            )

            if result:
                return result

    return ""


def find_agency_name(lines):
    for index, line in enumerate(lines):
        lower = line.lower()

        if (
            "agency pickup" in lower
            or "agency pick up" in lower
            or "agency dropoff" in lower
            or "agency drop off" in lower
            or "key pickup" in lower
            or "key pick up" in lower
        ):
            for candidate in lines[
                index + 1:index + 4
            ]:
                if (
                    candidate
                    and not looks_like_address(candidate)
                    and not looks_like_suburb(candidate)
                    and "anticipated" not in candidate.lower()
                ):
                    return candidate.strip()

    return ""


def extract_schedule_from_text(text):
    raw_lines = [
        re.sub(
            r"\s+",
            " ",
            line
        ).strip()
        for line in text.splitlines()
        if line.strip()
    ]

    stops = []

    # --------------------------------------------------------
    # PROPERTY JOBS
    # --------------------------------------------------------

    for index, line in enumerate(raw_lines):
        if not looks_like_address(line):
            continue

        address = clean_address_line(
            line
        )

        # Don't use the same address twice.
        if any(
            clean(stop["address"])
            ==
            clean(address)
            for stop in stops
        ):
            continue

        start = max(
            0,
            index - 3
        )

        end = min(
            len(raw_lines),
            index + 12
        )

        block = raw_lines[
            start:end
        ]

        stop_type = detect_stop_type(
            block
        )

        suburb = ""
        postcode = ""

        for candidate in raw_lines[
            index + 1:index + 4
        ]:
            if looks_like_suburb(candidate):
                suburb, postcode = parse_suburb(
                    candidate
                )
                break

        planned_time = find_anticipated_time(
            block
        )

        if stop_type == "Job":
            job_id = find_job_id(
                block
            )

            agency_name = ""

        else:
            job_id = ""

            agency_name = find_agency_name(
                block
            )

        stops.append({
            "position": 0,
            "stop_type": stop_type,
            "job_id": job_id,
            "agency_name": agency_name,
            "address": address,
            "suburb": suburb,
            "postcode": postcode,
            "planned_time": planned_time
        })

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    def sort_key(stop):
        if stop["planned_time"]:
            try:
                return datetime.strptime(
                    stop["planned_time"],
                    "%H:%M"
                ).time()
            except:
                pass

        return time(23, 59)

    stops.sort(
        key=sort_key
    )

    for position, stop in enumerate(
        stops,
        start=1
    ):
        stop["position"] = position

    return stops


# ============================================================
# PDF GENERATOR
# ============================================================

def generate_predictive_pdf(
    schedule_date,
    analysed_jobs,
    summary
):
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Predictive Daily Operational Report"
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontSize=19,
        leading=23,
        alignment=TA_CENTER,
        spaceAfter=8
    )

    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontSize=10,
        alignment=TA_CENTER,
        textColor=colors.grey,
        spaceAfter=18
    )

    heading_style = ParagraphStyle(
        "Heading",
        parent=styles["Heading2"],
        fontSize=14,
        leading=18,
        spaceBefore=10,
        spaceAfter=8
    )

    body_style = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontSize=10,
        leading=14
    )

    small_style = ParagraphStyle(
        "Small",
        parent=styles["BodyText"],
        fontSize=8,
        leading=11,
        textColor=colors.grey
    )

    story = []

    story.append(
        Paragraph(
            "Building Difficulty Intelligence",
            title_style
        )
    )

    story.append(
        Paragraph(
            "Predictive Daily Operational Report",
            subtitle_style
        )
    )

    story.append(
        Paragraph(
            schedule_date.strftime(
                "%A %d %B %Y"
            ),
            styles["Heading1"]
        )
    )

    story.append(
        Paragraph(
            "Generated before day progression: "
            + datetime.now().strftime(
                "%d %B %Y at %I:%M %p"
            ),
            body_style
        )
    )

    story.append(
        Spacer(
            1,
            10
        )
    )

    summary_data = [
        [
            "Scheduled Stops",
            "Service Jobs",
            "Flagged Stops",
            "Predicted Delay"
        ],
        [
            str(summary["total_stops"]),
            str(summary["total_jobs"]),
            str(summary["flagged_stops"]),
            f"+{round(summary['predicted_delay'])} min"
        ]
    ]

    summary_table = Table(
        summary_data,
        colWidths=[
            42 * mm,
            42 * mm,
            42 * mm,
            42 * mm
        ]
    )

    summary_table.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.lightgrey
            ),
            (
                "FONTNAME",
                (0, 0),
                (-1, 0),
                "Helvetica-Bold"
            ),
            (
                "ALIGN",
                (0, 0),
                (-1, -1),
                "CENTER"
            ),
            (
                "GRID",
                (0, 0),
                (-1, -1),
                0.5,
                colors.grey
            ),
            (
                "TOPPADDING",
                (0, 0),
                (-1, -1),
                7
            ),
            (
                "BOTTOMPADDING",
                (0, 0),
                (-1, -1),
                7
            )
        ])
    )

    story.append(
        summary_table
    )

    story.append(
        Spacer(
            1,
            18
        )
    )

    story.append(
        Paragraph(
            "Predicted Difficulties",
            heading_style
        )
    )

    flagged_items = [
        item
        for item in analysed_jobs
        if item["result"]["predicted_delay"] > 0
    ]

    if not flagged_items:
        story.append(
            Paragraph(
                "No recognised predictive delays were "
                "identified for this schedule at the "
                "time of analysis.",
                body_style
            )
        )

    for item in flagged_items:
        job = item["job"]
        result = item["result"]

        if job["stop_type"] == "Job":
            name = job["address"]

        else:
            name = (
                job["agency_name"]
                or job["address"]
            )

        story.append(
            Paragraph(
                f"<b>Stop {job['position']} — "
                f"{format_time(job['planned_time'])}</b>",
                styles["Heading3"]
            )
        )

        story.append(
            Paragraph(
                f"{job['stop_type']}<br/>"
                f"{name}<br/>"
                f"{job['suburb']} {job['postcode']}",
                body_style
            )
        )

        story.append(
            Paragraph(
                f"<b>Predicted additional time: "
                f"+{round(result['predicted_delay'])} minutes</b>",
                body_style
            )
        )

        if job["stop_type"] == "Job":
            for pattern in result["patterns"]:
                text = (
                    f"{pattern['condition_type']} — "
                    f"{pattern['count']} previous report(s), "
                    f"{pattern['confidence']} confidence"
                )

                if pattern["median_delay"]:
                    text += (
                        f", historical median "
                        f"+{round(pattern['median_delay'])} min"
                    )

                story.append(
                    Paragraph(
                        "• " + text,
                        body_style
                    )
                )

                for solution in pattern["solutions"]:
                    story.append(
                        Paragraph(
                            f"Recommended action: {solution}",
                            body_style
                        )
                    )

                for note in pattern["solution_notes"]:
                    story.append(
                        Paragraph(
                            f"Field note: {note}",
                            body_style
                        )
                    )

        else:
            intelligence = result[
                "intelligence"
            ]

            for reason in intelligence["reasons"]:
                story.append(
                    Paragraph(
                        "• " + reason,
                        body_style
                    )
                )

            profile = intelligence["profile"]

            if profile:
                if profile["notes"]:
                    story.append(
                        Paragraph(
                            "Field note: "
                            + profile["notes"],
                            body_style
                        )
                    )

                if (
                    profile["recommended_action"]
                    and profile["recommended_action"]
                    != "None"
                ):
                    story.append(
                        Paragraph(
                            "Recommended action: "
                            + profile[
                                "recommended_action"
                            ],
                            body_style
                        )
                    )

        story.append(
            Spacer(
                1,
                12
            )
        )

    story.append(
        Spacer(
            1,
            20
        )
    )

    story.append(
        Paragraph(
            "Evidence statement",
            heading_style
        )
    )

    story.append(
        Paragraph(
            "This report records recognised operational "
            "difficulty patterns identified before the "
            "scheduled day's progression. Later cancellations, "
            "schedule changes or actual outcomes do not alter "
            "the original prediction.",
            body_style
        )
    )

    story.append(
        Spacer(
            1,
            12
        )
    )

    story.append(
        Paragraph(
            "Building Difficulty Intelligence — "
            "prototype operational evidence report.",
            small_style
        )
    )

    doc.build(
        story
    )

    pdf_bytes = buffer.getvalue()

    buffer.close()

    return pdf_bytes


# ============================================================
# SAVE PREDICTION
# ============================================================

def save_prediction_snapshot(
    schedule_date,
    analysed_jobs,
    summary
):
    cursor = execute("""
        INSERT INTO prediction_reports (
            created_at,
            schedule_date,
            total_stops,
            total_jobs,
            flagged_stops,
            predicted_delay
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(),
        schedule_date.isoformat(),
        summary["total_stops"],
        summary["total_jobs"],
        summary["flagged_stops"],
        round(summary["predicted_delay"])
    ))

    report_id = cursor.lastrowid

    for item in analysed_jobs:
        job = item["job"]
        result = item["result"]

        reasons = []

        if job["stop_type"] == "Job":
            reasons = [
                pattern["condition_type"]
                for pattern in result["patterns"]
            ]

        else:
            reasons = result[
                "intelligence"
            ]["reasons"]

        execute("""
            INSERT INTO prediction_jobs (
                report_id,
                position,
                stop_type,
                job_id,
                agency_name,
                address,
                suburb,
                postcode,
                planned_time,
                risk,
                predicted_delay,
                reasons
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            report_id,
            job["position"],
            job["stop_type"],
            job["job_id"],
            job["agency_name"],
            job["address"],
            job["suburb"],
            job["postcode"],
            job["planned_time"],
            result["risk"],
            round(result["predicted_delay"]),
            " | ".join(reasons)
        ))

    return report_id


# ============================================================
# DASHBOARD
# ============================================================

def show_dashboard():
    st.header(
        "📊 Operational Intelligence"
    )

    patterns = build_patterns()

    visits = get_visits()

    start = week_start().isoformat()

    new_delays = [
        pattern
        for pattern in patterns
        if pattern["first_seen"] >= start
    ]

    recurring = [
        pattern
        for pattern in patterns
        if (
            pattern["first_seen"] >= start
            and pattern["status"]
            in ["Recognised", "Confirmed"]
        )
    ]

    scheduling = [
        pattern
        for pattern in recurring
        if pattern["category"] == "Scheduling"
    ]

    total_minutes = sum(
        visit["total_delay"]
        for visit in visits
    )

    agency_rows = execute("""
        SELECT *
        FROM agency_delays
    """).fetchall()

    agency_minutes = sum(
        row["delay_minutes"]
        for row in agency_rows
    )

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "🆕 New Delays",
        len(new_delays)
    )

    col2.metric(
        "🔁 New Patterns",
        len(recurring)
    )

    col3.metric(
        "🕐 Scheduling",
        len(scheduling)
    )

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "🏢 Property Delay",
        f"{total_minutes / 60:.1f} hrs"
    )

    col2.metric(
        "🔑 Agency Delay",
        f"{agency_minutes / 60:.1f} hrs"
    )

    reports = execute("""
        SELECT COUNT(*) AS count
        FROM prediction_reports
    """).fetchone()

    col3.metric(
        "📄 Predictions",
        reports["count"]
    )

    st.subheader(
        "🧠 Recent Intelligence"
    )

    if not new_delays:
        st.info(
            "No new property difficulty intelligence this week."
        )

    for pattern in new_delays[:8]:
        st.write(
            f"**{pattern['location']}**"
        )

        st.write(
            f"{pattern['condition_type']} — "
            f"{pattern['status']}"
        )

        if pattern["median_delay"]:
            st.caption(
                f"Typical delay "
                f"+{round(pattern['median_delay'])} min"
            )

        st.divider()


# ============================================================
# REPORT PAGE
# ============================================================

def show_report_page():
    st.header(
        "➕ Report Delay"
    )

    report_type = st.radio(
        "What caused the delay?",
        [
            "🏢 Property / Building",
            "🔑 Agency"
        ],
        horizontal=True
    )

    st.divider()

    if report_type == "🏢 Property / Building":
        visit_date = st.date_input(
            "Visit date",
            date.today()
        )

        address = st.text_input(
            "Job address"
        )

        suburb = st.text_input(
            "Suburb / area"
        )

        street = derive_street(
            address
        )

        profile_level = st.radio(
            "Applies to",
            [
                "Building",
                "Street",
                "Area"
            ],
            horizontal=True
        )

        no_difficulty = st.checkbox(
            "✅ No difficulty encountered"
        )

        if not no_difficulty:
            category_choice = st.radio(
                "Delay type",
                [
                    "Site / Access",
                    "Scheduling"
                ],
                horizontal=True
            )

            if category_choice == "Scheduling":
                category = "Scheduling"

                condition_type = st.selectbox(
                    "Condition",
                    SCHEDULING_CONDITIONS
                )

            else:
                category = "Site"

                condition_type = st.selectbox(
                    "Condition",
                    SITE_CONDITIONS
                )

            delay = st.number_input(
                "Minutes lost",
                min_value=0,
                max_value=240,
                value=0
            )

            applicability = st.selectbox(
                "When does it apply?",
                [
                    "Always",
                    "Certain times",
                    "Certain days and times"
                ]
            )

            selected_days = []

            start_value = None
            end_value = None

            if applicability == "Certain days and times":
                selected_days = st.multiselect(
                    "Days",
                    DAYS,
                    default=DAYS[:5]
                )

            if applicability != "Always":
                col1, col2 = st.columns(2)

                with col1:
                    start_time = st.time_input(
                        "From",
                        time(8, 0)
                    )

                with col2:
                    end_time = st.time_input(
                        "Until",
                        time(13, 0)
                    )

                start_value = start_time.strftime(
                    "%H:%M"
                )

                end_value = end_time.strftime(
                    "%H:%M"
                )

            confirmed = st.checkbox(
                "Known recurring condition"
            )

            solution = st.selectbox(
                "Known solution",
                SOLUTIONS
            )

            solution_notes = ""

            if solution != "None":
                solution_notes = st.text_input(
                    "Solution / field note"
                )

            concierge = solution in [
                "Concierge parking booking",
                "Contact concierge before arrival"
            ]

            if st.button(
                "➕ Add Delay",
                use_container_width=True
            ):
                st.session_state.conditions.append({
                    "category": category,
                    "condition_type": condition_type,
                    "delay_minutes": delay,
                    "applicability": applicability,
                    "days": selected_days,
                    "start_time": start_value,
                    "end_time": end_value,
                    "source_status": "Field observation",
                    "confirmed": confirmed,
                    "solution": solution,
                    "solution_notes": solution_notes,
                    "concierge": concierge
                })

                st.rerun()

        if st.session_state.conditions:
            st.subheader(
                "Current report"
            )

            for index, condition in enumerate(
                st.session_state.conditions
            ):
                st.write(
                    f"**{condition['condition_type']}** "
                    f"— {condition['delay_minutes']} min"
                )

                if st.button(
                    "Remove",
                    key=f"remove_{index}"
                ):
                    st.session_state.conditions.pop(
                        index
                    )

                    st.rerun()

        notes = st.text_area(
            "Notes"
        )

        if st.button(
            "💾 Save Property Report",
            type="primary",
            use_container_width=True
        ):
            if not address.strip():
                st.error(
                    "Enter the job address."
                )

            elif (
                not no_difficulty
                and not st.session_state.conditions
            ):
                st.error(
                    "Add a delay first."
                )

            else:
                save_visit(
                    visit_date,
                    address,
                    street,
                    suburb,
                    profile_level,
                    no_difficulty,
                    st.session_state.conditions,
                    notes
                )

                st.session_state.conditions = []

                st.success(
                    "Property report saved."
                )

    else:
        delay_date = st.date_input(
            "Date",
            date.today(),
            key="agency_date"
        )

        agency_name = st.text_input(
            "Agency name"
        )

        address = st.text_input(
            "Agency address"
        )

        suburb = st.text_input(
            "Suburb",
            key="agency_suburb"
        )

        reason = st.selectbox(
            "Agency delay",
            AGENCY_DELAY_REASONS
        )

        delay_minutes = st.number_input(
            "Minutes lost",
            min_value=0,
            max_value=240,
            value=0,
            key="agency_minutes"
        )

        recurring = st.checkbox(
            "Known recurring agency delay"
        )

        general_note = st.text_area(
            "Field note",
            placeholder=(
                "Example: This agency usually takes a while."
            )
        )

        recommended_action = st.selectbox(
            "Recommended action",
            AGENCY_ACTIONS
        )

        if recommended_action == "Other":
            recommended_action = st.text_input(
                "Recommended action details"
            )

        delay_note = st.text_area(
            "This visit notes"
        )

        if st.button(
            "💾 Save Agency Delay",
            type="primary",
            use_container_width=True
        ):
            if not agency_name.strip():
                st.error(
                    "Enter the agency name."
                )

            else:
                save_agency_profile(
                    agency_name,
                    address,
                    suburb,
                    general_note,
                    recommended_action
                )

                save_agency_delay(
                    delay_date,
                    agency_name,
                    address,
                    suburb,
                    reason,
                    delay_minutes,
                    delay_note,
                    recurring
                )

                st.success(
                    "Agency intelligence saved."
                )


# ============================================================
# SCHEDULE PAGE
# ============================================================

def show_schedule_page():
    st.header(
        "📸 Daily Schedule Prediction"
    )

    # --------------------------------------------------------
    # UPLOAD
    # --------------------------------------------------------

    if st.session_state.schedule_stage == "upload":
        st.caption(
            "Upload today's Field screenshots."
        )

        schedule_date = st.date_input(
            "Schedule date",
            date.today(),
            key="schedule_date_input"
        )

        uploader_key = (
            f"schedule_upload_"
            f"{st.session_state.schedule_uploader_key}"
        )

        screenshots = st.file_uploader(
            "Field screenshots",
            type=[
                "png",
                "jpg",
                "jpeg"
            ],
            accept_multiple_files=True,
            key=uploader_key
        )

        if screenshots:
            st.success(
                f"{len(screenshots)} screenshot(s) ready."
            )

            if st.button(
                "🔍 Extract Schedule",
                type="primary",
                use_container_width=True
            ):
                combined_jobs = []

                progress = st.progress(0)

                for index, screenshot in enumerate(
                    screenshots
                ):
                    with st.spinner(
                        f"Reading screenshot {index + 1}..."
                    ):
                        text = extract_text(
                            screenshot
                        )

                        jobs = extract_schedule_from_text(
                            text
                        )

                        for job in jobs:
                            duplicate = any(
                                clean(existing["address"])
                                ==
                                clean(job["address"])
                                for existing in combined_jobs
                            )

                            if not duplicate:
                                combined_jobs.append(
                                    job
                                )

                    progress.progress(
                        (index + 1)
                        /
                        len(screenshots)
                    )

                def job_sort(job):
                    try:
                        return datetime.strptime(
                            job["planned_time"],
                            "%H:%M"
                        ).time()

                    except:
                        return time(23, 59)

                combined_jobs.sort(
                    key=job_sort
                )

                for position, job in enumerate(
                    combined_jobs,
                    start=1
                ):
                    job["position"] = position

                st.session_state.extracted_jobs = (
                    combined_jobs
                )

                st.session_state.analysis_date = (
                    schedule_date
                )

                st.session_state.schedule_stage = (
                    "review"
                )

                st.rerun()

    # --------------------------------------------------------
    # REVIEW
    # --------------------------------------------------------

    elif st.session_state.schedule_stage == "review":
        jobs = st.session_state.extracted_jobs

        st.subheader(
            "Review Extracted Schedule"
        )

        st.caption(
            "Only correct anything the reader got wrong."
        )

        if not jobs:
            st.error(
                "No schedule stops were detected."
            )

            if st.button(
                "🔄 Try Again",
                use_container_width=True
            ):
                reset_schedule()
                st.rerun()

            return

        st.success(
            f"{len(jobs)} stops detected."
        )

        reviewed = []

        for index, job in enumerate(jobs):
            icon = (
                "🔑"
                if job["stop_type"] != "Job"
                else "🏠"
            )

            title_name = (
                job["agency_name"]
                if (
                    job["stop_type"] != "Job"
                    and job["agency_name"]
                )
                else job["address"]
            )

            with st.expander(
                f"{icon} {index + 1}. "
                f"{format_time(job['planned_time'])} — "
                f"{title_name}"
            ):
                stop_options = [
                    "Job",
                    "Agency Pickup",
                    "Agency Drop-off"
                ]

                stop_type = st.selectbox(
                    "Type",
                    stop_options,
                    index=(
                        stop_options.index(
                            job["stop_type"]
                        )
                        if job["stop_type"]
                        in stop_options
                        else 0
                    ),
                    key=f"type_{index}"
                )

                planned_time = st.text_input(
                    "Anticipated time",
                    value=job["planned_time"],
                    key=f"time_{index}"
                )

                address = st.text_input(
                    "Address",
                    value=job["address"],
                    key=f"address_{index}"
                )

                suburb = st.text_input(
                    "Suburb",
                    value=job["suburb"],
                    key=f"suburb_{index}"
                )

                postcode = st.text_input(
                    "Postcode",
                    value=job["postcode"],
                    key=f"postcode_{index}"
                )

                agency_name = job["agency_name"]
                job_id = job["job_id"]

                if stop_type == "Job":
                    job_id = st.text_input(
                        "Job ID",
                        value=job_id,
                        key=f"jobid_{index}"
                    )

                    agency_name = ""

                else:
                    agency_name = st.text_input(
                        "Agency",
                        value=agency_name,
                        key=f"agency_{index}"
                    )

                    job_id = ""

                include = st.checkbox(
                    "Include this stop",
                    value=True,
                    key=f"include_{index}"
                )

                if include:
                    reviewed.append({
                        "position": len(reviewed) + 1,
                        "stop_type": stop_type,
                        "job_id": job_id,
                        "agency_name": agency_name,
                        "address": clean_address_line(
                            address
                        ),
                        "suburb": suburb,
                        "postcode": postcode,
                        "planned_time": (
                            normalise_time(
                                planned_time
                            )
                            or planned_time
                        )
                    })

        col1, col2 = st.columns(2)

        with col1:
            if st.button(
                "🔄 Reset",
                use_container_width=True
            ):
                reset_schedule()
                st.rerun()

        with col2:
            if st.button(
                "🧠 Analyse Day",
                type="primary",
                use_container_width=True
            ):
                analysed = []

                total_delay = 0
                flagged = 0
                total_jobs = 0

                for job in reviewed:
                    if job["stop_type"] == "Job":
                        total_jobs += 1

                        result = analyse_property_job(
                            job["address"],
                            job["suburb"],
                            job["planned_time"],
                            st.session_state.analysis_date
                        )

                    else:
                        result = analyse_agency_stop(
                            job
                        )

                    if result["predicted_delay"] > 0:
                        flagged += 1

                    total_delay += (
                        result["predicted_delay"]
                    )

                    analysed.append({
                        "job": job,
                        "result": result
                    })

                summary = {
                    "total_stops": len(reviewed),
                    "total_jobs": total_jobs,
                    "flagged_stops": flagged,
                    "predicted_delay": total_delay
                }

                save_prediction_snapshot(
                    st.session_state.analysis_date,
                    analysed,
                    summary
                )

                pdf = generate_predictive_pdf(
                    st.session_state.analysis_date,
                    analysed,
                    summary
                )

                st.session_state.analysed_jobs = (
                    analysed
                )

                st.session_state.analysis_summary = (
                    summary
                )

                st.session_state.generated_pdf = (
                    pdf
                )

                st.session_state.schedule_stage = (
                    "analysis"
                )

                st.rerun()

    # --------------------------------------------------------
    # ANALYSIS
    # --------------------------------------------------------

    elif st.session_state.schedule_stage == "analysis":
        summary = st.session_state.analysis_summary

        analysed = st.session_state.analysed_jobs

        st.subheader(
            "📊 Pre-Day Prediction"
        )

        st.caption(
            st.session_state.analysis_date.strftime(
                "%A %d %B %Y"
            )
        )

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Stops",
            summary["total_stops"]
        )

        col2.metric(
            "⚠️ Flagged",
            summary["flagged_stops"]
        )

        col3.metric(
            "Predicted Delay",
            f"+{round(summary['predicted_delay'])} min"
        )

        if summary["flagged_stops"]:
            st.warning(
                "Recognised operational difficulties "
                "exist in this schedule."
            )

        else:
            st.success(
                "No recognised predictive delays "
                "were identified."
            )

        st.subheader(
            "Schedule"
        )

        for item in analysed:
            job = item["job"]
            result = item["result"]

            if job["stop_type"] == "Job":
                name = job["address"]

            else:
                name = (
                    job["agency_name"]
                    or job["address"]
                )

            st.markdown(
                f"### {result['icon']} "
                f"{format_time(job['planned_time'])} — "
                f"{name}"
            )

            st.caption(
                job["stop_type"]
            )

            if job["suburb"]:
                st.caption(
                    f"{job['suburb']} "
                    f"{job['postcode']}"
                )

            if result["predicted_delay"]:
                st.write(
                    f"Predicted additional time: "
                    f"**+{round(result['predicted_delay'])} min**"
                )

            if job["stop_type"] == "Job":
                for pattern in result["patterns"]:
                    st.write(
                        f"• {pattern['condition_type']} "
                        f"— {pattern['status']}"
                    )

                    for solution in pattern["solutions"]:
                        if "Concierge" in solution:
                            st.success(
                                f"🛎️ {solution}"
                            )

                        else:
                            st.info(
                                f"💡 {solution}"
                            )

                    for note in pattern["solution_notes"]:
                        st.caption(
                            f"Field note: {note}"
                        )

            else:
                intelligence = result[
                    "intelligence"
                ]

                profile = intelligence[
                    "profile"
                ]

                if profile:
                    if profile["notes"]:
                        st.info(
                            f"📝 {profile['notes']}"
                        )

                    if (
                        profile["recommended_action"]
                        and profile["recommended_action"]
                        != "None"
                    ):
                        st.success(
                            f"💡 "
                            f"{profile['recommended_action']}"
                        )

            st.divider()

        # ----------------------------------------------------
        # PDF
        # ----------------------------------------------------

        st.subheader(
            "📄 Evidence Report"
        )

        filename = (
            "predictive_report_"
            + st.session_state.analysis_date.isoformat()
            + ".pdf"
        )

        st.download_button(
            "📄 Open / Save Predictive PDF",
            data=st.session_state.generated_pdf,
            file_name=filename,
            mime="application/pdf",
            use_container_width=True
        )

        st.caption(
            "On iPhone, open the PDF and use Share to "
            "Mail it or Save to Files."
        )

        default_email = get_setting(
            "report_email"
        )

        if default_email:
            st.info(
                f"📧 Intended recipient: {default_email}"
            )

        st.caption(
            "The prediction was recorded before the day's "
            "progression. Later cancellations do not alter "
            "the evidence snapshot."
        )

        if st.button(
            "🔄 Finish & Analyse New Schedule",
            type="primary",
            use_container_width=True
        ):
            reset_schedule()
            st.rerun()


# ============================================================
# PROFILES
# ============================================================

def show_profiles():
    st.header(
        "🏢 Intelligence Profiles"
    )

    profile_type = st.radio(
        "Profiles",
        [
            "Properties",
            "Agencies"
        ],
        horizontal=True
    )

    if profile_type == "Properties":
        patterns = build_patterns()

        if not patterns:
            st.info(
                "No property profiles yet."
            )

            return

        locations = sorted(
            set(
                pattern["location"]
                for pattern in patterns
                if pattern["location"]
            )
        )

        selected = st.selectbox(
            "Location",
            locations
        )

        location_patterns = [
            pattern
            for pattern in patterns
            if pattern["location"] == selected
        ]

        concierge = any(
            pattern["concierge"]
            for pattern in location_patterns
        )

        title = selected

        if concierge:
            title += " 🛎️"

        st.subheader(
            title
        )

        for pattern in location_patterns:
            st.write(
                f"**{pattern['condition_type']}**"
            )

            st.caption(
                f"{pattern['count']} reports • "
                f"{pattern['status']} • "
                f"{pattern['confidence']} confidence • "
                f"+{round(pattern['median_delay'])} min typical"
            )

            for solution in pattern["solutions"]:
                st.success(
                    f"💡 {solution}"
                )

            for note in pattern["solution_notes"]:
                st.write(
                    f"📝 {note}"
                )

            st.divider()

    else:
        agencies = execute("""
            SELECT *
            FROM agencies
            ORDER BY agency_name
        """).fetchall()

        delay_names = execute("""
            SELECT DISTINCT agency_name
            FROM agency_delays
            ORDER BY agency_name
        """).fetchall()

        names = set()

        for agency in agencies:
            names.add(
                agency["agency_name"]
            )

        for row in delay_names:
            names.add(
                row["agency_name"]
            )

        if not names:
            st.info(
                "No agency profiles yet."
            )

            return

        selected = st.selectbox(
            "Agency",
            sorted(names)
        )

        intelligence = get_agency_intelligence(
            selected
        )

        st.subheader(
            f"🔑 {selected}"
        )

        col1, col2 = st.columns(2)

        col1.metric(
            "Delay Reports",
            intelligence["count"]
        )

        col2.metric(
            "Typical Delay",
            f"+{round(intelligence['typical_delay'])} min"
        )

        profile = intelligence[
            "profile"
        ]

        if profile:
            if profile["notes"]:
                st.info(
                    f"📝 {profile['notes']}"
                )

            if (
                profile["recommended_action"]
                and profile["recommended_action"]
                != "None"
            ):
                st.success(
                    f"💡 {profile['recommended_action']}"
                )

        if intelligence["recognised"]:
            st.warning(
                "🔁 Recognised recurring agency delay"
            )


# ============================================================
# HISTORY
# ============================================================

def show_history():
    st.header(
        "📋 History"
    )

    history_type = st.radio(
        "History",
        [
            "Property Reports",
            "Agency Delays",
            "Predictive Reports"
        ],
        horizontal=True
    )

    if history_type == "Property Reports":
        visits = get_visits()

        if not visits:
            st.info(
                "No property reports yet."
            )

            return

        for visit in visits:
            with st.expander(
                f"{visit['visit_date']} — "
                f"{visit['address']} — "
                f"{visit['total_delay']} min"
            ):
                rows = execute("""
                    SELECT *
                    FROM conditions
                    WHERE visit_id = ?
                    ORDER BY id
                """, (
                    visit["id"],
                )).fetchall()

                for row in rows:
                    st.write(
                        f"**{row['condition_type']}** "
                        f"— {row['delay_minutes']} min"
                    )

                if visit["notes"]:
                    st.write(
                        visit["notes"]
                    )

    elif history_type == "Agency Delays":
        rows = execute("""
            SELECT *
            FROM agency_delays
            ORDER BY delay_date DESC, created_at DESC
        """).fetchall()

        if not rows:
            st.info(
                "No agency delays yet."
            )

            return

        for row in rows:
            with st.expander(
                f"{row['delay_date']} — "
                f"{row['agency_name']} — "
                f"{row['delay_minutes']} min"
            ):
                st.write(
                    f"**Reason:** "
                    f"{row['delay_reason']}"
                )

                if row["notes"]:
                    st.write(
                        row["notes"]
                    )

    else:
        reports = execute("""
            SELECT *
            FROM prediction_reports
            ORDER BY created_at DESC
        """).fetchall()

        if not reports:
            st.info(
                "No predictive reports yet."
            )

            return

        for report in reports:
            generated = datetime.fromisoformat(
                report["created_at"]
            )

            with st.expander(
                f"{report['schedule_date']} — "
                f"{report['flagged_stops']} flagged — "
                f"+{report['predicted_delay']} min"
            ):
                st.write(
                    f"Generated "
                    f"{generated.strftime('%d %b %Y %I:%M %p')}"
                )

                st.write(
                    f"**Scheduled stops:** "
                    f"{report['total_stops']}"
                )

                st.write(
                    f"**Predicted delay:** "
                    f"+{report['predicted_delay']} min"
                )


# ============================================================
# SETTINGS PAGE
# ============================================================

def show_settings():
    st.header(
        "⚙️ Report Settings"
    )

    st.write(
        "Set the email address you normally send "
        "predictive reports to."
    )

    current_email = get_setting(
        "report_email"
    )

    email = st.text_input(
        "Default report email",
        value=current_email,
        placeholder="name@example.com"
    )

    if st.button(
        "💾 Save Email Address",
        type="primary",
        use_container_width=True
    ):
        if email and "@" not in email:
            st.error(
                "Enter a valid email address."
            )

        else:
            save_setting(
                "report_email",
                email
            )

            st.success(
                "Default report email saved."
            )

    st.divider()

    st.caption(
        "The Streamlit proof-of-concept generates the PDF "
        "locally for download/share. Direct automatic emailing "
        "can be added when the application moves to its "
        "production architecture."
    )


# ============================================================
# APP
# ============================================================

st.title(
    "🏢 Building Difficulty Intelligence"
)

st.caption(
    "Field evidence → recurring patterns → "
    "pre-day prediction → operational evidence"
)

page = st.radio(
    "Navigation",
    [
        "📊 Dashboard",
        "➕ Report",
        "📸 Schedule",
        "🏢 Profiles",
        "📋 History",
        "⚙️ Settings"
    ],
    horizontal=True,
    label_visibility="collapsed"
)

st.divider()


if page == "📊 Dashboard":
    show_dashboard()

elif page == "➕ Report":
    show_report_page()

elif page == "📸 Schedule":
    show_schedule_page()

elif page == "🏢 Profiles":
    show_profiles()

elif page == "📋 History":
    show_history()

elif page == "⚙️ Settings":
    show_settings()
