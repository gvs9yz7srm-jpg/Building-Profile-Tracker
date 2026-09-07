import streamlit as st
import sqlite3
import re

from datetime import datetime, date, time, timedelta
from statistics import median
from PIL import Image
import pytesseract


# ============================================================
# BUILDING DIFFICULTY INTELLIGENCE — V3.1
# Screenshot Schedule Extraction Prototype
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

    cursor.execute(
        query,
        params
    )

    conn.commit()

    return cursor


# ============================================================
# DATABASE TABLES
# ============================================================

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

    FOREIGN KEY (visit_id)
        REFERENCES visits(id)
)
""")


execute("""
CREATE TABLE IF NOT EXISTS schedules (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    created_at TEXT NOT NULL,

    schedule_date TEXT NOT NULL,

    name TEXT
)
""")


execute("""
CREATE TABLE IF NOT EXISTS schedule_jobs (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    schedule_id INTEGER NOT NULL,

    position INTEGER,

    stop_type TEXT DEFAULT 'Job',

    job_id TEXT,

    address TEXT,

    street TEXT,

    suburb TEXT,

    planned_time TEXT,

    FOREIGN KEY (schedule_id)
        REFERENCES schedules(id)
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


DAYS = [

    "Monday",

    "Tuesday",

    "Wednesday",

    "Thursday",

    "Friday",

    "Saturday",

    "Sunday"
]


# ============================================================
# SESSION STATE
# ============================================================

if "conditions" not in st.session_state:

    st.session_state.conditions = []


if "extracted_jobs" not in st.session_state:

    st.session_state.extracted_jobs = []


if "ocr_text" not in st.session_state:

    st.session_state.ocr_text = ""


# ============================================================
# HELPERS
# ============================================================

def clean(value):

    if value is None:

        return ""

    return str(value).strip().lower()


def format_time(value):

    if not value:

        return ""

    try:

        return datetime.strptime(
            value,
            "%H:%M"
        ).strftime(
            "%I:%M %p"
        ).lstrip("0")

    except:

        return value


def severity(minutes):

    if minutes <= 5:

        return "Minor"

    elif minutes <= 15:

        return "Moderate"

    elif minutes <= 30:

        return "Significant"

    return "Severe"


def severity_icon(minutes):

    level = severity(minutes)

    icons = {

        "Minor": "🟢",

        "Moderate": "🟡",

        "Significant": "🟠",

        "Severe": "🔴"
    }

    return icons.get(
        level,
        "⚪"
    )


def pattern_status(
    count,
    confirmed
):

    if confirmed:

        return "Confirmed"

    elif count >= 3:

        return "Recognised"

    elif count == 2:

        return "Emerging"

    return "Observation"


def confidence(count):

    if count >= 5:

        return "High"

    elif count >= 3:

        return "Moderate"

    return "Low"


def week_start():

    today = date.today()

    return today - timedelta(
        days=today.weekday()
    )


def time_inside_window(
    planned,
    start,
    end
):

    if not planned:

        return False

    if not start:

        return False

    if not end:

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

        return (
            start_time
            <=
            planned_time
            <=
            end_time
        )

    except:

        return False


# ============================================================
# FIELD REPORT DATABASE
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

        address.strip(),

        street.strip(),

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

            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )

        """, (

            visit_id,

            datetime.now().isoformat(),

            condition["category"],

            condition["condition_type"],

            condition["delay_minutes"],

            condition["applicability"],

            ",".join(
                condition["days"]
            ),

            condition["start_time"],

            condition["end_time"],

            condition["source_status"],

            int(
                condition["confirmed"]
            ),

            condition["solution"],

            condition["solution_notes"],

            int(
                condition["concierge"]
            )
        ))


def get_visits():

    return execute("""
        SELECT *

        FROM visits

        ORDER BY
            visit_date DESC,
            created_at DESC
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

        level = row[
            "profile_level"
        ]


        if level == "Street":

            location = (
                row["street"]
                or
                row["address"]
            )


        elif level == "Area":

            location = (
                row["suburb"]
            )


        else:

            location = (
                row["address"]
            )


        key = (

            clean(location),

            row["condition_type"],

            level
        )


        if key not in groups:

            groups[key] = {

                "location":
                    location,

                "street":
                    row["street"],

                "suburb":
                    row["suburb"],

                "level":
                    level,

                "condition_type":
                    row["condition_type"],

                "category":
                    row["category"],

                "rows":
                    [],

                "delays":
                    [],

                "confirmed":
                    False,

                "solutions":
                    set(),

                "solution_notes":
                    set(),

                "concierge":
                    False,

                "time_windows":
                    set(),

                "days":
                    set(),

                "first_seen":
                    row["visit_date"],

                "last_seen":
                    row["visit_date"]
            }


        group = groups[key]

        group[
            "rows"
        ].append(
            row
        )


        if row[
            "delay_minutes"
        ] > 0:

            group[
                "delays"
            ].append(
                row[
                    "delay_minutes"
                ]
            )


        if row[
            "manually_confirmed"
        ]:

            group[
                "confirmed"
            ] = True


        if (
            row["solution"]
            and
            row["solution"] != "None"
        ):

            group[
                "solutions"
            ].add(
                row["solution"]
            )


        if row[
            "solution_notes"
        ]:

            group[
                "solution_notes"
            ].add(
                row[
                    "solution_notes"
                ]
            )


        if row[
            "concierge"
        ]:

            group[
                "concierge"
            ] = True


        if row["days"]:

            for day in row[
                "days"
            ].split(","):

                if day:

                    group[
                        "days"
                    ].add(day)


        if (
            row["start_time"]
            and
            row["end_time"]
        ):

            group[
                "time_windows"
            ].add(
                (
                    row["start_time"],
                    row["end_time"]
                )
            )


        group[
            "first_seen"
        ] = min(

            group["first_seen"],

            row["visit_date"]
        )


        group[
            "last_seen"
        ] = max(

            group["last_seen"],

            row["visit_date"]
        )


    patterns = []


    for group in groups.values():

        count = len(
            group["rows"]
        )


        group[
            "count"
        ] = count


        group[
            "status"
        ] = pattern_status(

            count,

            group["confirmed"]
        )


        group[
            "confidence"
        ] = confidence(
            count
        )


        group[
            "median_delay"
        ] = (

            median(
                group["delays"]
            )

            if group["delays"]

            else 0
        )


        patterns.append(
            group
        )


    return patterns


# ============================================================
# PATTERN MATCHING
# ============================================================

def pattern_matches_job(
    pattern,
    address,
    street,
    suburb
):

    if pattern[
        "level"
    ] == "Building":

        return (
            clean(
                pattern["location"]
            )
            ==
            clean(address)
        )


    elif pattern[
        "level"
    ] == "Street":

        return (
            clean(
                pattern["location"]
            )
            ==
            clean(street)
        )


    elif pattern[
        "level"
    ] == "Area":

        return (
            clean(
                pattern["location"]
            )
            ==
            clean(suburb)
        )


    return False


def condition_applies(
    pattern,
    planned_time,
    schedule_date
):

    day_name = (
        schedule_date.strftime(
            "%A"
        )
    )


    if (
        pattern["days"]
        and
        day_name
        not in pattern["days"]
    ):

        return False


    if pattern[
        "time_windows"
    ]:

        for start, end in pattern[
            "time_windows"
        ]:

            if time_inside_window(

                planned_time,

                start,

                end
            ):

                return True


        return False


    return True


# ============================================================
# JOB PREDICTION
# ============================================================

def analyse_job(
    address,
    street,
    suburb,
    planned_time,
    schedule_date
):

    patterns = build_patterns()

    matches = []

    predicted_delay = 0


    for pattern in patterns:

        if pattern[
            "status"
        ] not in [

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


        matches.append(
            pattern
        )


        predicted_delay += (
            pattern[
                "median_delay"
            ]
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

        "patterns":
            matches,

        "predicted_delay":
            predicted_delay,

        "risk":
            risk,

        "icon":
            icon
    }


# ============================================================
# RECOMMENDATIONS
# ============================================================

def recommendation(
    pattern
):

    windows = list(
        pattern[
            "time_windows"
        ]
    )


    condition = pattern[
        "condition_type"
    ]


    if windows:

        start, end = windows[0]


        if condition == (
            "Clearway / timed parking restriction"
        ):

            return (

                f"Avoid arrival between "
                f"{format_time(start)} and "
                f"{format_time(end)}. "
                f"Prefer after "
                f"{format_time(end)}."
            )


        elif condition == (
            "School-zone traffic"
        ):

            return (

                f"School-zone congestion "
                f"{format_time(start)} – "
                f"{format_time(end)}. "
                f"Prefer outside this window."
            )


        elif condition == (
            "Peak-hour traffic"
        ):

            return (

                f"Peak-hour congestion "
                f"{format_time(start)} – "
                f"{format_time(end)}."
            )


    if pattern[
        "median_delay"
    ]:

        return (

            f"Allow approximately "
            f"+{round(pattern['median_delay'])} "
            f"minutes."
        )


    return None


# ============================================================
# TREND ENGINE
# ============================================================

def calculate_trend(
    pattern
):

    rows = sorted(

        pattern["rows"],

        key=lambda row:
            row["visit_date"]
    )


    delays = [

        row["delay_minutes"]

        for row in rows

        if row[
            "delay_minutes"
        ] > 0
    ]


    if len(
        delays
    ) < 4:

        return None


    midpoint = (
        len(delays) // 2
    )


    older = (
        delays[:midpoint]
    )


    recent = (
        delays[midpoint:]
    )


    old_median = median(
        older
    )


    new_median = median(
        recent
    )


    difference = (
        new_median
        -
        old_median
    )


    if difference >= 5:

        return {

            "direction":
                "Worsening",

            "icon":
                "📈",

            "old":
                old_median,

            "new":
                new_median
        }


    elif difference <= -5:

        return {

            "direction":
                "Improving",

            "icon":
                "📉",

            "old":
                old_median,

            "new":
                new_median
        }


    return None


# ============================================================
# OCR IMAGE PROCESSING
# ============================================================

def preprocess_image(
    uploaded_file
):

    image = Image.open(
        uploaded_file
    )


    image = image.convert(
        "L"
    )


    width, height = image.size


    if width < 1600:

        scale = (
            1600 / width
        )

        image = image.resize(
            (
                int(
                    width * scale
                ),

                int(
                    height * scale
                )
            )
        )


    return image


def extract_text_from_image(
    uploaded_file
):

    image = preprocess_image(
        uploaded_file
    )


    text = pytesseract.image_to_string(
        image,
        config="--psm 6"
    )


    return text


# ============================================================
# OCR TEXT HELPERS
# ============================================================

def normalize_ocr_text(
    text
):

    text = text.replace(
        "\r",
        "\n"
    )


    text = re.sub(
        r"\n+",
        "\n",
        text
    )


    return text.strip()


def extract_time(
    text
):

    patterns = [

        r"\b([0-1]?\d:[0-5]\d)\s*([apAP][mM])\b",

        r"\b([0-2]?\d:[0-5]\d)\b"
    ]


    for pattern in patterns:

        match = re.search(
            pattern,
            text
        )


        if match:

            raw = (
                match.group(0)
                .strip()
            )


            for fmt in [

                "%I:%M %p",

                "%I:%M%p",

                "%H:%M"
            ]:

                try:

                    parsed = datetime.strptime(
                        raw.upper(),
                        fmt
                    )


                    return parsed.strftime(
                        "%H:%M"
                    )

                except:

                    pass


    return ""


def looks_like_address(
    line
):

    line = line.strip()


    address_words = [

        "street",

        "st ",

        "road",

        "rd ",

        "avenue",

        "ave ",

        "parade",

        "pde ",

        "drive",

        "dr ",

        "lane",

        "ln ",

        "way",

        "crescent",

        "circuit",

        "boulevard",

        "place",

        "pl ",

        "close",

        "court",

        "terrace",

        "highway"
    ]


    has_number = bool(

        re.search(
            r"\d",
            line
        )
    )


    has_street_word = any(

        word
        in
        line.lower()

        for word
        in
        address_words
    )


    return (
        has_number
        and
        has_street_word
    )


def extract_job_id(
    block
):

    patterns = [

        r"Job\s*ID[:\s#]*([A-Za-z0-9\-]+)",

        r"Job[:\s#]*([0-9]{4,})",

        r"\b([0-9]{6,})\b"
    ]


    for pattern in patterns:

        match = re.search(
            pattern,
            block,
            re.IGNORECASE
        )


        if match:

            return match.group(1)


    return ""


def detect_stop_type(
    block
):

    lower = block.lower()


    if (
        "agency pickup"
        in lower
        or
        "agency pick up"
        in lower
    ):

        return "Agency Pickup"


    if (
        "agency dropoff"
        in lower
        or
        "agency drop off"
        in lower
    ):

        return "Agency Drop-off"


    if (
        "pickup"
        in lower
        and
        "agency"
        in lower
    ):

        return "Agency Pickup"


    if (
        "drop"
        in lower
        and
        "agency"
        in lower
    ):

        return "Agency Drop-off"


    return "Job"


# ============================================================
# ADDRESS PARSING
# ============================================================

def parse_address_line(
    line
):

    line = (
        line.strip()
    )


    postcode_match = re.search(

        r"\b([A-Za-z][A-Za-z\s\-']+)\s+(\d{4})\b",

        line
    )


    suburb = ""


    if postcode_match:

        suburb = (
            postcode_match
            .group(1)
            .strip()
        )


    street_match = re.search(

        r"(?:(?:Unit|U)\s*)?"
        r"(?:\d+[A-Za-z]?"
        r"(?:/\d+[A-Za-z]?)?)"
        r"\s+"
        r"(.+?"
        r"(?:Street|St|Road|Rd|Avenue|Ave|"
        r"Parade|Pde|Drive|Dr|Lane|Ln|Way|"
        r"Crescent|Circuit|Boulevard|Place|"
        r"Pl|Close|Court|Terrace|Highway))",

        line,

        re.IGNORECASE
    )


    street = ""


    if street_match:

        full_address_part = (
            street_match.group(0)
        )


        street = re.sub(

            r"^(?:Unit|U)?\s*"
            r"\d+[A-Za-z]?"
            r"(?:/\d+[A-Za-z]?)?"
            r"\s+",

            "",

            full_address_part,

            flags=re.IGNORECASE
        )


    return {

        "address":
            line,

        "street":
            street,

        "suburb":
            suburb
    }


# ============================================================
# OCR JOB EXTRACTION
# ============================================================

def extract_jobs_from_text(
    text
):

    text = normalize_ocr_text(
        text
    )


    lines = [

        line.strip()

        for line in text.split(
            "\n"
        )

        if line.strip()
    ]


    jobs = []


    for index, line in enumerate(
        lines
    ):

        if not looks_like_address(
            line
        ):

            continue


        start = max(
            0,
            index - 5
        )


        end = min(
            len(lines),
            index + 6
        )


        block_lines = (
            lines[start:end]
        )


        block = "\n".join(
            block_lines
        )


        address_data = (
            parse_address_line(
                line
            )
        )


        planned_time = (
            extract_time(
                block
            )
        )


        job_id = (
            extract_job_id(
                block
            )
        )


        stop_type = (
            detect_stop_type(
                block
            )
        )


        job = {

            "position":
                len(jobs) + 1,

            "stop_type":
                stop_type,

            "job_id":
                job_id,

            "address":
                address_data[
                    "address"
                ],

            "street":
                address_data[
                    "street"
                ],

            "suburb":
                address_data[
                    "suburb"
                ],

            "planned_time":
                planned_time
        }


        duplicate = any(

            clean(
                existing[
                    "address"
                ]
            )
            ==
            clean(
                job["address"]
            )

            and

            existing[
                "planned_time"
            ]
            ==
            job[
                "planned_time"
            ]

            for existing
            in jobs
        )


        if not duplicate:

            jobs.append(
                job
            )


    return jobs


# ============================================================
# SAVE SCHEDULE
# ============================================================

def save_schedule(
    schedule_date,
    jobs
):

    cursor = execute("""
        INSERT INTO schedules (

            created_at,

            schedule_date,

            name
        )

        VALUES (?, ?, ?)

    """, (

        datetime.now().isoformat(),

        schedule_date.isoformat(),

        f"Field Schedule "
        f"{schedule_date.isoformat()}"
    ))


    schedule_id = (
        cursor.lastrowid
    )


    for position, job in enumerate(
        jobs,
        start=1
    ):

        execute("""
            INSERT INTO schedule_jobs (

                schedule_id,

                position,

                stop_type,

                job_id,

                address,

                street,

                suburb,

                planned_time
            )

            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?
            )

        """, (

            schedule_id,

            position,

            job[
                "stop_type"
            ],

            job[
                "job_id"
            ],

            job[
                "address"
            ],

            job[
                "street"
            ],

            job[
                "suburb"
            ],

            job[
                "planned_time"
            ]
        ))


    return schedule_id


# ============================================================
# DASHBOARD
# ============================================================

def show_dashboard():

    st.header(
        "📊 Operational Intelligence"
    )


    patterns = build_patterns()

    visits = get_visits()

    start = (
        week_start()
        .isoformat()
    )


    new_delays = [

        pattern

        for pattern
        in patterns

        if pattern[
            "first_seen"
        ] >= start
    ]


    recurring = [

        pattern

        for pattern
        in patterns

        if (
            pattern[
                "first_seen"
            ] >= start

            and

            pattern[
                "status"
            ] in [

                "Recognised",

                "Confirmed"
            ]
        )
    ]


    scheduling = [

        pattern

        for pattern
        in recurring

        if pattern[
            "category"
        ] == "Scheduling"
    ]


    confirmed = [

        pattern

        for pattern
        in patterns

        if pattern[
            "status"
        ] == "Confirmed"
    ]


    total_minutes = sum(

        visit[
            "total_delay"
        ]

        for visit
        in visits
    )


    col1, col2, col3 = (
        st.columns(3)
    )


    col1.metric(

        "🆕 New Delays This Week",

        len(
            new_delays
        )
    )


    col2.metric(

        "🔁 New Recurring Patterns",

        len(
            recurring
        )
    )


    col3.metric(

        "🕐 Scheduling Patterns",

        len(
            scheduling
        )
    )


    col1, col2, col3 = (
        st.columns(3)
    )


    col1.metric(

        "🔴 Confirmed Conditions",

        len(
            confirmed
        )
    )


    col2.metric(

        "⌛ Recorded Time Lost",

        f"{total_minutes / 60:.1f} hrs"
    )


    recognised_delays = [

        pattern[
            "median_delay"
        ]

        for pattern
        in patterns

        if (

            pattern[
                "status"
            ] in [

                "Recognised",

                "Confirmed"
            ]

            and

            pattern[
                "median_delay"
            ] > 0
        )
    ]


    typical = (

        median(
            recognised_delays
        )

        if recognised_delays

        else 0
    )


    col3.metric(

        "⏱ Typical Delay",

        f"{round(typical)} min"
    )


    # -----------------------------------------
    # WHAT CHANGED
    # -----------------------------------------

    st.subheader(
        "🧠 What Changed This Week"
    )


    if not new_delays:

        st.info(
            "No new difficulty intelligence "
            "this week."
        )


    for pattern in new_delays[:10]:

        if pattern[
            "category"
        ] == "Scheduling":

            icon = "🕐"

        elif pattern[
            "status"
        ] == "Confirmed":

            icon = "🔴"

        elif pattern[
            "status"
        ] == "Recognised":

            icon = "🔁"

        else:

            icon = "🆕"


        st.markdown(

            f"### {icon} "
            f"{pattern['condition_type']}"
        )


        st.write(
            f"**{pattern['location']}**"
        )


        st.caption(

            f"{pattern['count']} report(s) • "
            f"{pattern['status']} • "
            f"{pattern['confidence']} confidence"
        )


        if pattern[
            "median_delay"
        ]:

            st.write(

                f"Typical delay: "
                f"**+{round(pattern['median_delay'])} min**"
            )


    # -----------------------------------------
    # HIGHEST IMPACT
    # -----------------------------------------

    st.subheader(
        "🎯 Highest Impact Locations"
    )


    opportunities = sorted(

        patterns,

        key=lambda pattern:

            pattern[
                "median_delay"
            ]
            *
            pattern[
                "count"
            ],

        reverse=True
    )


    for pattern in opportunities[:5]:

        impact = (

            pattern[
                "median_delay"
            ]
            *
            pattern[
                "count"
            ]
        )


        st.write(

            f"**{severity_icon(pattern['median_delay'])} "
            f"{pattern['location']}**"
        )


        st.write(
            pattern[
                "condition_type"
            ]
        )


        st.caption(

            f"{pattern['count']} reports • "
            f"{round(pattern['median_delay'])} min typical • "
            f"~{round(impact)} impact minutes"
        )


# ============================================================
# REPORT PAGE
# ============================================================

def show_report_page():

    st.header(
        "➕ Report Difficulty"
    )


    visit_date = st.date_input(

        "Visit date",

        date.today()
    )


    address = st.text_input(
        "Building / job address"
    )


    street = st.text_input(
        "Street"
    )


    suburb = st.text_input(
        "Suburb / area"
    )


    profile_level = st.radio(

        "Condition applies to",

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

        st.subheader(
            "Add Condition"
        )


        category_choice = st.radio(

            "Category",

            [
                "Site / Access",

                "Scheduling"
            ],

            horizontal=True
        )


        if category_choice == "Scheduling":

            category = "Scheduling"

            condition_type = st.selectbox(

                "Scheduling condition",

                SCHEDULING_CONDITIONS
            )


        else:

            category = "Site"

            condition_type = st.selectbox(

                "Site condition",

                SITE_CONDITIONS
            )


        delay = st.number_input(

            "Actual time lost (minutes)",

            min_value=0,

            max_value=240,

            value=0
        )


        applicability = st.selectbox(

            "Applicability",

            [
                "Always",

                "Certain times",

                "Certain days and times"
            ]
        )


        selected_days = []

        start_value = None

        end_value = None


        if applicability == (
            "Certain days and times"
        ):

            selected_days = st.multiselect(

                "Days",

                DAYS,

                default=DAYS[:5]
            )


        if applicability != "Always":

            col1, col2 = st.columns(2)


            with col1:

                start = st.time_input(

                    "Start",

                    time(8, 0)
                )


            with col2:

                end = st.time_input(

                    "End",

                    time(13, 0)
                )


            start_value = (
                start.strftime(
                    "%H:%M"
                )
            )


            end_value = (
                end.strftime(
                    "%H:%M"
                )
            )


        source_status = st.radio(

            "Evidence",

            [
                "Field observation",

                "Verified condition"
            ],

            horizontal=True
        )


        confirmed = st.checkbox(

            "Confirm immediately as "
            "recurring/permanent"
        )


        solution = st.selectbox(

            "Known solution",

            SOLUTIONS
        )


        solution_notes = ""


        if solution != "None":

            solution_notes = (
                st.text_input(
                    "Solution details"
                )
            )


        concierge = solution in [

            "Concierge parking booking",

            "Contact concierge before arrival"
        ]


        if concierge:

            st.success(
                "🛎️ Concierge solution detected."
            )


        if st.button(

            "➕ Add Condition",

            use_container_width=True
        ):

            st.session_state.conditions.append({

                "category":
                    category,

                "condition_type":
                    condition_type,

                "delay_minutes":
                    delay,

                "applicability":
                    applicability,

                "days":
                    selected_days,

                "start_time":
                    start_value,

                "end_time":
                    end_value,

                "source_status":
                    source_status,

                "confirmed":
                    confirmed,

                "solution":
                    solution,

                "solution_notes":
                    solution_notes,

                "concierge":
                    concierge
            })


            st.rerun()


    if st.session_state.conditions:

        st.subheader(
            "Current Report"
        )


        total = sum(

            condition[
                "delay_minutes"
            ]

            for condition
            in st.session_state.conditions
        )


        st.metric(

            "Total delay",

            f"{total} min"
        )


        for index, condition in enumerate(

            st.session_state.conditions
        ):

            with st.expander(

                f"{condition['condition_type']} — "
                f"{condition['delay_minutes']} min"
            ):

                st.write(
                    condition[
                        "category"
                    ]
                )


                st.write(
                    condition[
                        "applicability"
                    ]
                )


                if condition[
                    "start_time"
                ]:

                    st.write(

                        f"{format_time(condition['start_time'])}"
                        f" – "
                        f"{format_time(condition['end_time'])}"
                    )


                if condition[
                    "solution"
                ] != "None":

                    st.write(

                        f"💡 "
                        f"{condition['solution']}"
                    )


                if st.button(

                    "Remove",

                    key=(
                        f"remove_condition_"
                        f"{index}"
                    )
                ):

                    st.session_state.conditions.pop(
                        index
                    )

                    st.rerun()


    notes = st.text_area(
        "Visit notes"
    )


    if st.button(

        "💾 Save Report",

        type="primary",

        use_container_width=True
    ):

        if not address.strip():

            st.error(
                "Enter the job address."
            )


        elif (
            not no_difficulty
            and
            not st.session_state.conditions
        ):

            st.error(

                "Add at least one condition "
                "or select No difficulty."
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
                "Field report saved."
            )


# ============================================================
# SINGLE JOB PREDICTOR
# ============================================================

def show_predictor():

    st.header(
        "🧠 Job Difficulty Predictor"
    )


    address = st.text_input(
        "Address",
        key="prediction_address"
    )


    street = st.text_input(
        "Street",
        key="prediction_street"
    )


    suburb = st.text_input(
        "Suburb",
        key="prediction_suburb"
    )


    planned_date = st.date_input(

        "Proposed date",

        date.today(),

        key="prediction_date"
    )


    planned_time = st.time_input(

        "Proposed arrival",

        time(9, 0),

        key="prediction_time"
    )


    if st.button(

        "Analyse Job",

        type="primary",

        use_container_width=True
    ):

        result = analyse_job(

            address,

            street,

            suburb,

            planned_time.strftime(
                "%H:%M"
            ),

            planned_date
        )


        st.header(

            f"{result['icon']} "
            f"{result['risk']} Difficulty"
        )


        st.metric(

            "Predicted Additional Time",

            f"+{round(result['predicted_delay'])} min"
        )


        if not result[
            "patterns"
        ]:

            st.success(

                "No recognised difficulty "
                "currently applies."
            )


        for pattern in result[
            "patterns"
        ]:

            st.subheader(
                pattern[
                    "condition_type"
                ]
            )


            st.caption(

                f"{pattern['level']} profile • "
                f"{pattern['count']} reports • "
                f"{pattern['confidence']} confidence"
            )


            rec = recommendation(
                pattern
            )


            if rec:

                st.info(
                    f"💡 {rec}"
                )


            for solution in pattern[
                "solutions"
            ]:

                if "Concierge" in solution:

                    st.success(
                        f"🛎️ {solution}"
                    )

                else:

                    st.success(
                        f"💡 {solution}"
                    )


# ============================================================
# SCREENSHOT SCHEDULE IMPORT
# ============================================================

def show_schedule_import():

    st.header(
        "📸 Import Field Schedule"
    )


    st.caption(

        "Upload screenshots of the day's "
        "Field schedule. V3.1 will attempt "
        "to extract the jobs automatically."
    )


    schedule_date = st.date_input(

        "Schedule date",

        date.today(),

        key="import_schedule_date"
    )


    screenshots = st.file_uploader(

        "Upload Field screenshots",

        type=[
            "png",
            "jpg",
            "jpeg"
        ],

        accept_multiple_files=True
    )


    if screenshots:

        st.success(

            f"{len(screenshots)} "
            f"screenshot(s) ready."
        )


        with st.expander(
            "Preview Screenshots"
        ):

            for image in screenshots:

                st.image(
                    image,
                    use_container_width=True
                )


        if st.button(

            "🔍 Extract Schedule",

            type="primary",

            use_container_width=True
        ):

            all_text = []

            all_jobs = []


            progress = st.progress(0)


            for index, screenshot in enumerate(
                screenshots
            ):

                with st.spinner(

                    f"Reading screenshot "
                    f"{index + 1}..."
                ):

                    text = (
                        extract_text_from_image(
                            screenshot
                        )
                    )


                    all_text.append(
                        text
                    )


                    detected = (
                        extract_jobs_from_text(
                            text
                        )
                    )


                    for job in detected:

                        duplicate = any(

                            clean(
                                existing[
                                    "address"
                                ]
                            )
                            ==
                            clean(
                                job[
                                    "address"
                                ]
                            )

                            and

                            existing[
                                "planned_time"
                            ]
                            ==
                            job[
                                "planned_time"
                            ]

                            for existing
                            in all_jobs
                        )


                        if not duplicate:

                            all_jobs.append(
                                job
                            )


                progress.progress(

                    (
                        index + 1
                    )
                    /
                    len(
                        screenshots
                    )
                )


            for position, job in enumerate(

                all_jobs,

                start=1
            ):

                job[
                    "position"
                ] = position


            st.session_state.ocr_text = (
                "\n\n".join(
                    all_text
                )
            )


            st.session_state.extracted_jobs = (
                all_jobs
            )


            st.rerun()


    # -----------------------------------------
    # REVIEW EXTRACTED SCHEDULE
    # -----------------------------------------

    if st.session_state.extracted_jobs:

        st.divider()


        st.subheader(
            "✅ Review Extracted Schedule"
        )


        st.info(

            f"{len(st.session_state.extracted_jobs)} "
            f"possible stops detected. "
            f"Review them before analysis."
        )


        reviewed_jobs = []


        for index, job in enumerate(

            st.session_state.extracted_jobs
        ):

            st.markdown(
                f"### Stop {index + 1}"
            )


            col1, col2 = st.columns(
                [1, 2]
            )


            with col1:

                stop_type = st.selectbox(

                    "Type",

                    [
                        "Job",

                        "Agency Pickup",

                        "Agency Drop-off"
                    ],

                    index=(

                        [
                            "Job",

                            "Agency Pickup",

                            "Agency Drop-off"
                        ].index(
                            job[
                                "stop_type"
                            ]
                        )

                        if job[
                            "stop_type"
                        ] in [

                            "Job",

                            "Agency Pickup",

                            "Agency Drop-off"
                        ]

                        else 0
                    ),

                    key=(
                        f"stop_type_{index}"
                    )
                )


                time_text = st.text_input(

                    "Arrival time",

                    value=job[
                        "planned_time"
                    ],

                    placeholder="08:30",

                    key=(
                        f"job_time_{index}"
                    )
                )


            with col2:

                address = st.text_input(

                    "Address",

                    value=job[
                        "address"
                    ],

                    key=(
                        f"job_address_{index}"
                    )
                )


                street = st.text_input(

                    "Street",

                    value=job[
                        "street"
                    ],

                    key=(
                        f"job_street_{index}"
                    )
                )


                suburb = st.text_input(

                    "Suburb",

                    value=job[
                        "suburb"
                    ],

                    key=(
                        f"job_suburb_{index}"
                    )
                )


                job_id = st.text_input(

                    "Job ID",

                    value=job[
                        "job_id"
                    ],

                    key=(
                        f"job_id_{index}"
                    )
                )


            include = st.checkbox(

                "Include this stop",

                value=True,

                key=(
                    f"include_job_{index}"
                )
            )


            if include:

                reviewed_jobs.append({

                    "position":
                        len(
                            reviewed_jobs
                        ) + 1,

                    "stop_type":
                        stop_type,

                    "job_id":
                        job_id,

                    "address":
                        address,

                    "street":
                        street,

                    "suburb":
                        suburb,

                    "planned_time":
                        time_text
                })


            st.divider()


        # -------------------------------------
        # ANALYSE ENTIRE DAY
        # -------------------------------------

        if st.button(

            "🧠 Analyse Entire Schedule",

            type="primary",

            use_container_width=True
        ):

            st.session_state[
                "reviewed_schedule"
            ] = reviewed_jobs

            st.session_state[
                "analysis_date"
            ] = schedule_date

            st.rerun()


    # -----------------------------------------
    # DAILY ANALYSIS
    # -----------------------------------------

    if (
        "reviewed_schedule"
        in st.session_state

        and

        st.session_state[
            "reviewed_schedule"
        ]
    ):

        st.divider()


        st.header(
            "📊 Daily Schedule Analysis"
        )


        reviewed_jobs = st.session_state[
            "reviewed_schedule"
        ]


        analysis_date = st.session_state[
            "analysis_date"
        ]


        analysed = []

        total_predicted = 0

        conflict_count = 0

        moderate_count = 0

        clear_count = 0


        for job in reviewed_jobs:

            if job[
                "stop_type"
            ] != "Job":

                analysed.append({

                    "job":
                        job,

                    "operational_stop":
                        True
                })

                continue


            result = analyse_job(

                job[
                    "address"
                ],

                job[
                    "street"
                ],

                job[
                    "suburb"
                ],

                job[
                    "planned_time"
                ],

                analysis_date
            )


            total_predicted += (
                result[
                    "predicted_delay"
                ]
            )


            if result[
                "risk"
            ] == "High":

                conflict_count += 1


            elif result[
                "risk"
            ] == "Moderate":

                moderate_count += 1


            else:

                clear_count += 1


            analysed.append({

                "job":
                    job,

                "result":
                    result,

                "operational_stop":
                    False
            })


        col1, col2, col3, col4 = (
            st.columns(4)
        )


        col1.metric(

            "Stops",

            len(
                reviewed_jobs
            )
        )


        col2.metric(

            "🔴 High Risk",

            conflict_count
        )


        col3.metric(

            "🟡 Moderate",

            moderate_count
        )


        col4.metric(

            "Predicted Delay",

            f"{round(total_predicted)} min"
        )


        if total_predicted > 0:

            st.warning(

                f"Known difficulty patterns predict "
                f"approximately "
                f"**{round(total_predicted)} minutes** "
                f"of additional operational time "
                f"across this schedule."
            )


        else:

            st.success(

                "No recognised difficulty patterns "
                "currently conflict with this schedule."
            )


        # -------------------------------------
        # INDIVIDUAL JOBS
        # -------------------------------------

        st.subheader(
            "Schedule"
        )


        for item in analysed:

            job = item[
                "job"
            ]


            if item[
                "operational_stop"
            ]:

                st.info(

                    f"📦 "
                    f"**{format_time(job['planned_time'])} — "
                    f"{job['stop_type']}**\n\n"
                    f"{job['address']}"
                )

                continue


            result = item[
                "result"
            ]


            st.markdown(

                f"### "
                f"{result['icon']} "
                f"{format_time(job['planned_time'])} — "
                f"{job['address']}"
            )


            st.write(

                f"**Risk:** "
                f"{result['risk']}"
            )


            st.write(

                f"**Predicted additional time:** "
                f"+{round(result['predicted_delay'])} min"
            )


            if not result[
                "patterns"
            ]:

                st.caption(

                    "No recognised conditions "
                    "currently apply."
                )


            for pattern in result[
                "patterns"
            ]:

                st.write(

                    f"• "
                    f"**{pattern['condition_type']}** "
                    f"({pattern['level']})"
                )


                rec = recommendation(
                    pattern
                )


                if rec:

                    st.info(
                        f"💡 {rec}"
                    )


                for solution in pattern[
                    "solutions"
                ]:

                    if "Concierge" in solution:

                        st.success(
                            f"🛎️ {solution}"
                        )

                    else:

                        st.success(
                            f"💡 {solution}"
                        )


            st.divider()


        # -------------------------------------
        # SAVE SCHEDULE
        # -------------------------------------

        if st.button(

            "💾 Save Analysed Schedule",

            use_container_width=True
        ):

            save_schedule(

                analysis_date,

                reviewed_jobs
            )


            st.success(
                "Schedule saved."
            )


    # -----------------------------------------
    # OCR DEBUG
    # -----------------------------------------

    if st.session_state.ocr_text:

        with st.expander(
            "Developer: OCR Text"
        ):

            st.text(
                st.session_state.ocr_text
            )


# ============================================================
# PROFILES
# ============================================================

def show_profiles():

    st.header(
        "🏢 Intelligence Profiles"
    )


    patterns = build_patterns()


    if not patterns:

        st.info(
            "No profiles yet."
        )

        return


    search = st.text_input(

        "🔎 Search address, street or suburb"
    )


    filtered = patterns


    if search:

        term = clean(
            search
        )


        filtered = [

            pattern

            for pattern
            in patterns

            if (

                term
                in
                clean(
                    pattern[
                        "location"
                    ]
                )

                or

                term
                in
                clean(
                    pattern[
                        "suburb"
                    ]
                )
            )
        ]


    locations = sorted(

        set(

            pattern[
                "location"
            ]

            for pattern
            in filtered

            if pattern[
                "location"
            ]
        )
    )


    if not locations:

        st.warning(
            "No matching profiles."
        )

        return


    selected = st.selectbox(

        "Location",

        locations
    )


    location_patterns = [

        pattern

        for pattern
        in filtered

        if pattern[
            "location"
        ] == selected
    ]


    has_concierge = any(

        pattern[
            "concierge"
        ]

        for pattern
        in location_patterns
    )


    if has_concierge:

        st.header(
            f"⚠️ {selected} 🛎️"
        )


    else:

        st.header(
            f"⚠️ {selected}"
        )


    for pattern in location_patterns:

        st.subheader(
            pattern[
                "condition_type"
            ]
        )


        col1, col2, col3 = (
            st.columns(3)
        )


        col1.metric(

            "Reports",

            pattern[
                "count"
            ]
        )


        col2.metric(

            "Median Delay",

            f"{round(pattern['median_delay'])} min"
        )


        col3.metric(

            "Confidence",

            pattern[
                "confidence"
            ]
        )


        st.write(

            f"**Status:** "
            f"{pattern['status']}"
        )


        if pattern[
            "time_windows"
        ]:

            for start, end in pattern[
                "time_windows"
            ]:

                st.write(

                    f"🕐 "
                    f"{format_time(start)} – "
                    f"{format_time(end)}"
                )


        rec = recommendation(
            pattern
        )


        if rec:

            st.info(
                f"💡 {rec}"
            )


        trend = calculate_trend(
            pattern
        )


        if trend:

            st.warning(

                f"{trend['icon']} "
                f"{trend['direction']}: "
                f"{round(trend['old'])} → "
                f"{round(trend['new'])} min"
            )


        for solution in pattern[
            "solutions"
        ]:

            if "Concierge" in solution:

                st.success(
                    f"🛎️ {solution}"
                )

            else:

                st.success(
                    f"💡 {solution}"
                )


        for note in pattern[
            "solution_notes"
        ]:

            st.caption(
                note
            )


        st.divider()


# ============================================================
# HISTORY
# ============================================================

def show_history():

    st.header(
        "📋 Field Reports"
    )


    visits = get_visits()


    if not visits:

        st.info(
            "No reports yet."
        )

        return


    for visit in visits:

        title = (

            f"{visit['visit_date']} — "
            f"{visit['address']}"
        )


        if visit[
            "total_delay"
        ]:

            title += (

                f" — "
                f"{visit['total_delay']} min"
            )


        with st.expander(
            title
        ):

            st.write(

                f"**Address:** "
                f"{visit['address']}"
            )


            if visit[
                "street"
            ]:

                st.write(

                    f"**Street:** "
                    f"{visit['street']}"
                )


            if visit[
                "suburb"
            ]:

                st.write(

                    f"**Area:** "
                    f"{visit['suburb']}"
                )


            if visit[
                "no_difficulty"
            ]:

                st.success(
                    "✅ No difficulty encountered"
                )


            rows = execute("""
                SELECT *

                FROM conditions

                WHERE visit_id = ?

                ORDER BY id
            """, (
                visit[
                    "id"
                ],
            )).fetchall()


            for row in rows:

                st.write(

                    f"**{row['condition_type']}** "
                    f"— "
                    f"{row['delay_minutes']} min"
                )


            if visit[
                "notes"
            ]:

                st.write(
                    visit[
                        "notes"
                    ]
                )


# ============================================================
# APP
# ============================================================

st.title(
    "🏢 Building Difficulty Intelligence"
)


st.caption(

    "Field observations → recurring patterns → "
    "schedule intelligence → predicted delays"
)


page = st.radio(

    "Navigation",

    [
        "📊 Dashboard",

        "➕ Report",

        "🧠 Predict",

        "📸 Schedule",

        "🏢 Profiles",

        "📋 History"
    ],

    horizontal=True,

    label_visibility="collapsed"
)


st.divider()


if page == "📊 Dashboard":

    show_dashboard()


elif page == "➕ Report":

    show_report_page()


elif page == "🧠 Predict":

    show_predictor()


elif page == "📸 Schedule":

    show_schedule_import()


elif page == "🏢 Profiles":

    show_profiles()


elif page == "📋 History":

    show_history()
