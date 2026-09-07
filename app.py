import streamlit as st
import sqlite3
from datetime import datetime, date, time, timedelta
from statistics import median

# ============================================================
# BUILDING DIFFICULTY PROFILE — V3
# Operational Intelligence Prototype
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
    conn = sqlite3.connect(
        DB_NAME,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    return conn


conn = get_connection()


def execute(query, params=()):
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()
    return cur


# ============================================================
# TABLES
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

if "schedule_jobs" not in st.session_state:
    st.session_state.schedule_jobs = []


# ============================================================
# GENERAL HELPERS
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

    if minutes <= 15:
        return "Moderate"

    if minutes <= 30:
        return "Significant"

    return "Severe"


def severity_icon(minutes):

    level = severity(minutes)

    return {
        "Minor": "🟢",
        "Moderate": "🟡",
        "Significant": "🟠",
        "Severe": "🔴"
    }.get(level, "⚪")


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

    if not planned or not start or not end:
        return False

    try:

        p = datetime.strptime(
            planned,
            "%H:%M"
        ).time()

        s = datetime.strptime(
            start,
            "%H:%M"
        ).time()

        e = datetime.strptime(
            end,
            "%H:%M"
        ).time()

        return s <= p <= e

    except:

        return False


# ============================================================
# SAVE FIELD REPORT
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
        c["delay_minutes"]
        for c in conditions
    )

    cur = execute("""
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

    visit_id = cur.lastrowid

    for c in conditions:

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
            c["category"],
            c["condition_type"],
            c["delay_minutes"],
            c["applicability"],
            ",".join(c["days"]),
            c["start_time"],
            c["end_time"],
            c["source_status"],
            int(c["confirmed"]),
            c["solution"],
            c["solution_notes"],
            int(c["concierge"])
        ))


# ============================================================
# GET DATA
# ============================================================

def get_visits():

    return execute("""
        SELECT *
        FROM visits
        ORDER BY visit_date DESC,
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
# INTELLIGENCE ENGINE
# ============================================================

def build_patterns():

    rows = get_conditions()

    groups = {}

    for row in rows:

        level = row["profile_level"]

        if level == "Street":

            location = (
                row["street"]
                or row["address"]
            )

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

                "condition_type":
                    row["condition_type"],

                "category":
                    row["category"],

                "rows": [],

                "delays": [],

                "confirmed": False,

                "solutions": set(),

                "solution_notes": set(),

                "concierge": False,

                "time_windows": set(),

                "days": set(),

                "first_seen":
                    row["visit_date"],

                "last_seen":
                    row["visit_date"]
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
            and
            row["solution"] != "None"
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
            and
            row["end_time"]
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
# MATCH PATTERNS TO JOB
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


# ============================================================
# CHECK WHETHER CONDITION APPLIES
# ============================================================

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
        and
        day_name not in pattern["days"]
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


# ============================================================
# JOB PREDICTION ENGINE
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

        "predicted_delay":
            predicted_delay,

        "risk": risk,

        "icon": icon
    }


# ============================================================
# RECOMMENDATION ENGINE
# ============================================================

def recommendation(pattern):

    windows = list(
        pattern["time_windows"]
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
                f"Avoid {format_time(start)} – "
                f"{format_time(end)}. "
                f"Prefer arrival after "
                f"{format_time(end)}."
            )

        if condition == "School-zone traffic":

            return (
                f"School-zone congestion recorded "
                f"{format_time(start)} – "
                f"{format_time(end)}. "
                f"Schedule outside this window "
                f"where practical."
            )

        if condition == "Peak-hour traffic":

            return (
                f"Peak-hour delay recorded "
                f"{format_time(start)} – "
                f"{format_time(end)}."
            )


    if pattern["median_delay"]:

        return (
            f"Allow approximately "
            f"+{round(pattern['median_delay'])} "
            f"minutes."
        )

    return None


# ============================================================
# TREND ENGINE
# ============================================================

def calculate_trend(pattern):

    rows = sorted(
        pattern["rows"],
        key=lambda r: r["visit_date"]
    )

    delays = [
        r["delay_minutes"]
        for r in rows
        if r["delay_minutes"] > 0
    ]

    if len(delays) < 4:

        return None

    midpoint = len(delays) // 2

    older = delays[:midpoint]

    recent = delays[midpoint:]

    old_median = median(older)

    new_median = median(recent)

    difference = (
        new_median - old_median
    )


    if difference >= 5:

        return {
            "direction": "Worsening",
            "icon": "📈",
            "old": old_median,
            "new": new_median
        }


    if difference <= -5:

        return {
            "direction": "Improving",
            "icon": "📉",
            "old": old_median,
            "new": new_median
        }

    return None


# ============================================================
# SOLUTION EFFECTIVENESS
# ============================================================

def solution_effectiveness(pattern):

    rows = sorted(
        pattern["rows"],
        key=lambda r: r["visit_date"]
    )

    solution_index = None

    solution_name = None


    for index, row in enumerate(rows):

        if (
            row["solution"]
            and
            row["solution"] != "None"
        ):

            solution_index = index
            solution_name = row["solution"]
            break


    if solution_index is None:
        return None


    before = [
        r["delay_minutes"]
        for r in rows[:solution_index]
        if r["delay_minutes"] > 0
    ]


    after = [
        r["delay_minutes"]
        for r in rows[solution_index:]
        if r["delay_minutes"] >= 0
    ]


    if not before or len(after) < 2:

        return None


    before_median = median(before)

    after_median = median(after)

    saving = (
        before_median - after_median
    )


    if saving <= 0:

        return None


    return {

        "solution": solution_name,

        "before": before_median,

        "after": after_median,

        "saving": saving,

        "visits_after": len(after),

        "total_saved":
            saving * len(after)
    }


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
        p for p in patterns
        if p["first_seen"] >= start
    ]


    recurring = [
        p for p in patterns
        if (
            p["first_seen"] >= start
            and
            p["status"] in [
                "Recognised",
                "Confirmed"
            ]
        )
    ]


    scheduling = [
        p for p in recurring
        if p["category"] == "Scheduling"
    ]


    confirmed = [
        p for p in patterns
        if p["status"] == "Confirmed"
    ]


    total_minutes = sum(
        v["total_delay"]
        for v in visits
    )


    # HEADLINE

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "🆕 New Delays This Week",
        len(new_delays)
    )

    col2.metric(
        "🔁 New Recurring Patterns",
        len(recurring)
    )

    col3.metric(
        "🕐 Scheduling Patterns",
        len(scheduling)
    )


    col1, col2, col3 = st.columns(3)

    col1.metric(
        "🔴 Confirmed Conditions",
        len(confirmed)
    )

    col2.metric(
        "⌛ Recorded Time Lost",
        f"{total_minutes / 60:.1f} hrs"
    )


    recognised_delays = [
        p["median_delay"]
        for p in patterns
        if (
            p["status"] in [
                "Recognised",
                "Confirmed"
            ]
            and
            p["median_delay"] > 0
        )
    ]


    typical = (
        median(recognised_delays)
        if recognised_delays
        else 0
    )


    col3.metric(
        "⏱ Typical Delay",
        f"{round(typical)} min"
    )


    # -------------------------------------------
    # NEW INTELLIGENCE
    # -------------------------------------------

    st.subheader(
        "🧠 New Intelligence"
    )

    if not new_delays:

        st.info(
            "No new conditions discovered "
            "this week."
        )

    else:

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


    # -------------------------------------------
    # TRENDS
    # -------------------------------------------

    st.subheader(
        "📈 Changing Conditions"
    )

    trends_found = False

    for pattern in patterns:

        trend = calculate_trend(
            pattern
        )

        if trend:

            trends_found = True

            st.write(
                f"{trend['icon']} "
                f"**{pattern['location']} — "
                f"{pattern['condition_type']}**"
            )

            st.write(
                f"{trend['direction']}: "
                f"{round(trend['old'])} → "
                f"{round(trend['new'])} min"
            )


    if not trends_found:

        st.caption(
            "More reports are needed before "
            "trend detection becomes meaningful."
        )


    # -------------------------------------------
    # SOLUTION EFFECTIVENESS
    # -------------------------------------------

    st.subheader(
        "💡 Solutions Saving Time"
    )

    solutions_found = False

    for pattern in patterns:

        result = solution_effectiveness(
            pattern
        )

        if result:

            solutions_found = True

            st.success(
                f"**{pattern['location']}**\n\n"
                f"{result['solution']}\n\n"
                f"Median delay "
                f"{round(result['before'])} → "
                f"{round(result['after'])} min\n\n"
                f"Estimated saving: "
                f"**{round(result['saving'])} min/visit**"
            )


    if not solutions_found:

        st.caption(
            "Solution effectiveness will appear "
            "once enough before/after visits exist."
        )


    # -------------------------------------------
    # TOP OPPORTUNITIES
    # -------------------------------------------

    st.subheader(
        "🎯 Highest Impact Opportunities"
    )

    opportunities = sorted(
        patterns,
        key=lambda p:
            p["median_delay"] * p["count"],
        reverse=True
    )


    for pattern in opportunities[:5]:

        impact = (
            pattern["median_delay"]
            *
            pattern["count"]
        )

        st.write(
            f"**{severity_icon(pattern['median_delay'])} "
            f"{pattern['location']}**"
        )

        st.write(
            pattern["condition_type"]
        )

        st.caption(
            f"{pattern['count']} reports • "
            f"{round(pattern['median_delay'])} min typical • "
            f"~{round(impact)} recorded impact minutes"
        )


# ============================================================
# REPORT DIFFICULTY PAGE
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

            condition_type = st.selectbox(
                "Scheduling condition",
                SCHEDULING_CONDITIONS
            )

            category = "Scheduling"

        else:

            condition_type = st.selectbox(
                "Site condition",
                SITE_CONDITIONS
            )

            category = "Site"


        delay = st.number_input(
            "Actual time lost (minutes)",
            0,
            240,
            0
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

                s = st.time_input(
                    "Start",
                    time(8, 0)
                )

            with col2:

                e = st.time_input(
                    "End",
                    time(13, 0)
                )

            start_value = s.strftime(
                "%H:%M"
            )

            end_value = e.strftime(
                "%H:%M"
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
            "Confirm immediately as recurring/permanent"
        )


        solution = st.selectbox(
            "Known solution",
            SOLUTIONS
        )


        solution_notes = ""

        if solution != "None":

            solution_notes = st.text_input(
                "Solution details"
            )


        concierge = solution in [
            "Concierge parking booking",
            "Contact concierge before arrival"
        ]


        if st.button(
            "➕ Add Condition",
            use_container_width=True
        ):

            st.session_state.conditions.append({

                "category": category,

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


    # -------------------------------------------
    # CURRENT CONDITIONS
    # -------------------------------------------

    if st.session_state.conditions:

        st.subheader(
            "Current Report"
        )

        total = sum(
            c["delay_minutes"]
            for c in st.session_state.conditions
        )

        st.metric(
            "Total delay",
            f"{total} min"
        )


        for index, c in enumerate(
            st.session_state.conditions
        ):

            with st.expander(
                f"{c['condition_type']} — "
                f"{c['delay_minutes']} min"
            ):

                st.write(
                    c["category"]
                )

                st.write(
                    c["applicability"]
                )

                if c["start_time"]:

                    st.write(
                        f"{format_time(c['start_time'])}"
                        f" – "
                        f"{format_time(c['end_time'])}"
                    )

                if c["solution"] != "None":

                    st.write(
                        f"💡 {c['solution']}"
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
                "Add a condition or select "
                "No difficulty encountered."
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
                "Report saved."
            )


# ============================================================
# PREDICT JOB PAGE
# ============================================================

def show_predictor():

    st.header(
        "🧠 Job Difficulty Predictor"
    )

    st.caption(
        "Test a proposed job time against "
        "known operational intelligence."
    )


    address = st.text_input(
        "Address",
        key="predict_address"
    )

    street = st.text_input(
        "Street",
        key="predict_street"
    )

    suburb = st.text_input(
        "Suburb / area",
        key="predict_suburb"
    )


    planned_date = st.date_input(
        "Proposed date",
        date.today()
    )


    planned = st.time_input(
        "Proposed arrival",
        time(9, 0)
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
            planned.strftime("%H:%M"),
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


        if not result["patterns"]:

            st.success(
                "No recognised difficulty patterns "
                "currently apply to this job."
            )


        for pattern in result["patterns"]:

            st.subheader(
                pattern["condition_type"]
            )

            st.write(
                f"**Source:** "
                f"{pattern['level']} profile"
            )

            st.write(
                f"**Evidence:** "
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


            for solution in pattern["solutions"]:

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
        "📸 Import Daily Schedule"
    )

    st.write(
        "Upload screenshots of your Field schedule."
    )

    st.info(
        "V3 prototype: screenshots are staged here "
        "for schedule extraction. Automatic image-to-job "
        "extraction is the next connector step."
    )


    schedule_date = st.date_input(
        "Schedule date",
        date.today(),
        key="schedule_date"
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
            f"{len(screenshots)} screenshot(s) uploaded."
        )

        for index, image in enumerate(
            screenshots
        ):

            with st.expander(
                f"Screenshot {index + 1}"
            ):

                st.image(
                    image,
                    use_container_width=True
                )


        st.divider()

        st.subheader(
            "Extraction Pipeline"
        )

        st.write(
            "The extraction engine will identify:"
        )

        st.write(
            "• Planned arrival time"
        )

        st.write(
            "• Address"
        )

        st.write(
            "• Street"
        )

        st.write(
            "• Suburb"
        )

        st.write(
            "• Job ID"
        )

        st.write(
            "• Job vs agency pickup/drop-off"
        )


        st.warning(
            "Automatic screenshot reading is not "
            "connected in this prototype build yet. "
            "The rest of the scheduling intelligence "
            "engine is ready for extracted jobs."
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
            "No intelligence profiles yet."
        )

        return


    search = st.text_input(
        "🔎 Search address, street or suburb"
    )


    filtered = patterns


    if search:

        term = clean(search)

        filtered = [

            p for p in patterns

            if (
                term in clean(p["location"])
                or
                term in clean(p["suburb"])
            )
        ]


    locations = sorted(
        set(
            p["location"]
            for p in filtered
            if p["location"]
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

        p for p in filtered

        if p["location"] == selected
    ]


    concierge = any(
        p["concierge"]
        for p in location_patterns
    )


    title = f"⚠️ {selected}"

    if concierge:

        title += " 🛎️"


    st.header(title)


    for pattern in location_patterns:

        st.subheader(
            pattern["condition_type"]
        )


        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Reports",
            pattern["count"]
        )

        col2.metric(
            "Median Delay",
            f"{round(pattern['median_delay'])} min"
        )

        col3.metric(
            "Confidence",
            pattern["confidence"]
        )


        st.write(
            f"**Status:** "
            f"{pattern['status']}"
        )


        if pattern["time_windows"]:

            for start, end in (
                pattern["time_windows"]
            ):

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
                rec
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


        effectiveness = (
            solution_effectiveness(
                pattern
            )
        )


        if effectiveness:

            st.success(
                f"💡 {effectiveness['solution']} "
                f"is associated with approximately "
                f"{round(effectiveness['saving'])} "
                f"minutes saved per visit."
            )


        for solution in (
            pattern["solutions"]
        ):

            st.write(
                f"💡 **Known solution:** "
                f"{solution}"
            )


        for note in (
            pattern["solution_notes"]
        ):

            st.caption(note)


        st.divider()


# ============================================================
# REPORT HISTORY
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


        if visit["total_delay"]:

            title += (
                f" — "
                f"{visit['total_delay']} min"
            )


        with st.expander(title):

            st.write(
                f"**Address:** "
                f"{visit['address']}"
            )


            if visit["street"]:

                st.write(
                    f"**Street:** "
                    f"{visit['street']}"
                )


            if visit["suburb"]:

                st.write(
                    f"**Area:** "
                    f"{visit['suburb']}"
                )


            if visit["no_difficulty"]:

                st.success(
                    "✅ No difficulty encountered"
                )


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


# ============================================================
# APP HEADER
# ============================================================

st.title(
    "🏢 Building Difficulty Intelligence"
)

st.caption(
    "Field observations → recurring patterns → "
    "predicted delays → better scheduling"
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


# ============================================================
# ROUTING
# ============================================================

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
