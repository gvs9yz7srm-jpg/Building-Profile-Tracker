import streamlit as st
import sqlite3
from datetime import datetime, date, time, timedelta
from statistics import median

# ============================================================
# BUILDING DIFFICULTY PROFILE — V2
# Field Intelligence + Scheduling Intelligence
# ============================================================

st.set_page_config(
    page_title="Building Difficulty Profile",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="collapsed"
)

DB_NAME = "building_difficulty.db"

# ============================================================
# DATABASE
# ============================================================

def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)


conn = get_connection()
conn.row_factory = sqlite3.Row


def execute(query, params=()):
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()
    return cur


# ------------------------------------------------------------
# V2 TABLES
# ------------------------------------------------------------

execute("""
CREATE TABLE IF NOT EXISTS visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    visit_date TEXT NOT NULL,
    address TEXT NOT NULL,
    street TEXT,
    suburb TEXT,
    profile_level TEXT NOT NULL DEFAULT 'Building',
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
# HELPERS
# ============================================================

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

    if level == "Minor":
        return "🟢"

    if level == "Moderate":
        return "🟡"

    if level == "Significant":
        return "🟠"

    return "🔴"


def pattern_status(report_count, confirmed):

    if confirmed:
        return "Confirmed"

    if report_count >= 3:
        return "Recognised"

    if report_count == 2:
        return "Emerging"

    return "Observation"


def pattern_icon(status):

    icons = {
        "Observation": "⚪",
        "Emerging": "🟡",
        "Recognised": "🟠",
        "Confirmed": "🔴"
    }

    return icons.get(status, "⚪")


def confidence_label(report_count):

    if report_count >= 5:
        return "High"

    if report_count >= 3:
        return "Moderate"

    return "Low"


def format_time(value):

    if not value:
        return ""

    try:
        return datetime.strptime(
            value,
            "%H:%M"
        ).strftime("%I:%M %p").lstrip("0")

    except:
        return value


def week_start():

    today = date.today()

    return today - timedelta(
        days=today.weekday()
    )


# ============================================================
# DATABASE FUNCTIONS
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
        item["delay_minutes"]
        for item in conditions
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

    for item in conditions:

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
            item["category"],
            item["condition_type"],
            item["delay_minutes"],
            item["applicability"],
            ",".join(item["days"]),
            item["start_time"],
            item["end_time"],
            item["source_status"],
            int(item["confirmed"]),
            item["solution"],
            item["solution_notes"],
            int(item["concierge"])
        ))

    return visit_id


def get_visits():

    return execute("""
        SELECT *
        FROM visits
        ORDER BY visit_date DESC, created_at DESC
    """).fetchall()


def get_conditions():

    return execute("""
        SELECT
            conditions.*,
            visits.address,
            visits.street,
            visits.suburb,
            visits.profile_level,
            visits.visit_date
        FROM conditions
        JOIN visits
            ON conditions.visit_id = visits.id
        ORDER BY conditions.created_at DESC
    """).fetchall()


def delete_visit(visit_id):

    execute(
        "DELETE FROM conditions WHERE visit_id = ?",
        (visit_id,)
    )

    execute(
        "DELETE FROM visits WHERE id = ?",
        (visit_id,)
    )


# ============================================================
# INTELLIGENCE ENGINE
# ============================================================

def build_patterns():

    rows = get_conditions()

    groups = {}

    for row in rows:

        if row["profile_level"] == "Street":

            location = (
                row["street"]
                or row["address"]
            )

        else:

            location = row["address"]

        key = (
            location.strip().lower(),
            row["condition_type"]
        )

        if key not in groups:

            groups[key] = {
                "location": location,
                "suburb": row["suburb"],
                "profile_level": row["profile_level"],
                "condition_type": row["condition_type"],
                "category": row["category"],
                "reports": [],
                "delays": [],
                "confirmed": False,
                "solutions": set(),
                "concierge": False,
                "applicability": set(),
                "days": set(),
                "time_windows": set(),
                "first_seen": row["visit_date"],
                "last_seen": row["visit_date"]
            }

        group = groups[key]

        group["reports"].append(row)

        if row["delay_minutes"] > 0:
            group["delays"].append(
                row["delay_minutes"]
            )

        if row["manually_confirmed"]:
            group["confirmed"] = True

        if row["solution"] and row["solution"] != "None":
            group["solutions"].add(
                row["solution"]
            )

        if row["concierge"]:
            group["concierge"] = True

        group["applicability"].add(
            row["applicability"]
        )

        if row["days"]:

            for day in row["days"].split(","):

                if day:
                    group["days"].add(day)

        if row["start_time"] and row["end_time"]:

            group["time_windows"].add(
                (
                    row["start_time"],
                    row["end_time"]
                )
            )

        if row["visit_date"] < group["first_seen"]:
            group["first_seen"] = row["visit_date"]

        if row["visit_date"] > group["last_seen"]:
            group["last_seen"] = row["visit_date"]


    patterns = []

    for group in groups.values():

        count = len(group["reports"])

        status = pattern_status(
            count,
            group["confirmed"]
        )

        if group["delays"]:

            median_delay = median(
                group["delays"]
            )

        else:

            median_delay = 0

        group["count"] = count
        group["status"] = status
        group["confidence"] = confidence_label(count)
        group["median_delay"] = median_delay

        patterns.append(group)

    return patterns


def applicable_visits_for_pattern(pattern):

    visits = get_visits()

    count = 0

    for visit in visits:

        if pattern["profile_level"] == "Building":

            if (
                visit["address"].strip().lower()
                ==
                pattern["location"].strip().lower()
            ):
                count += 1

        else:

            street = (
                visit["street"] or ""
            ).strip().lower()

            if (
                street
                ==
                pattern["location"].strip().lower()
            ):
                count += 1

    return count


def pattern_percentage(pattern):

    visits = applicable_visits_for_pattern(
        pattern
    )

    if visits == 0:
        return 0

    return round(
        pattern["count"] / visits * 100
    )


def recommendation(pattern):

    condition = pattern["condition_type"]

    windows = list(
        pattern["time_windows"]
    )

    if condition == "Clearway / timed parking restriction":

        if windows:

            start, end = windows[0]

            return (
                f"Avoid arrival between "
                f"{format_time(start)} and "
                f"{format_time(end)}. "
                f"Prefer scheduling after "
                f"{format_time(end)} where practical."
            )

        return (
            "Check clearway times before scheduling."
        )

    if condition == "Peak-hour traffic":

        if windows:

            start, end = windows[0]

            return (
                f"Avoid scheduling travel through this area "
                f"between {format_time(start)} and "
                f"{format_time(end)} where practical."
            )

    if condition == "School-zone traffic":

        if windows:

            start, end = windows[0]

            return (
                f"School-zone congestion recorded between "
                f"{format_time(start)} and "
                f"{format_time(end)}. "
                f"Prefer scheduling outside this window."
            )

    if pattern["median_delay"] > 0:

        return (
            f"Allow approximately "
            f"+{round(pattern['median_delay'])} minutes "
            f"additional operational time."
        )

    return None


# ============================================================
# DASHBOARD INTELLIGENCE
# ============================================================

def dashboard_stats():

    patterns = build_patterns()
    visits = get_visits()

    start = week_start().isoformat()

    new_delays = [
        p for p in patterns
        if p["first_seen"] >= start
    ]

    new_patterns = [
        p for p in patterns
        if p["first_seen"] >= start
        and p["status"] in [
            "Recognised",
            "Confirmed"
        ]
    ]

    scheduling_patterns = [
        p for p in patterns
        if p["category"] == "Scheduling"
        and p["first_seen"] >= start
    ]

    confirmed = [
        p for p in patterns
        if p["status"] == "Confirmed"
    ]

    solutions = [
        p for p in patterns
        if p["solutions"]
        and p["first_seen"] >= start
    ]

    delays = [
        p["median_delay"]
        for p in patterns
        if p["median_delay"] > 0
        and p["status"] in [
            "Recognised",
            "Confirmed"
        ]
    ]

    overall_delay = (
        median(delays)
        if delays
        else 0
    )

    total_minutes = sum(
        visit["total_delay"]
        for visit in visits
    )

    return {
        "new_delays": len(new_delays),
        "new_patterns": len(new_patterns),
        "scheduling_patterns": len(scheduling_patterns),
        "confirmed": len(confirmed),
        "solutions": len(solutions),
        "expected_delay": overall_delay,
        "total_minutes": total_minutes
    }


# ============================================================
# SESSION STATE
# ============================================================

if "condition_builder" not in st.session_state:
    st.session_state.condition_builder = []


# ============================================================
# HEADER
# ============================================================

st.title("🏢 Building Difficulty Profile")

st.caption(
    "Field intelligence for access, parking, delays "
    "and smarter scheduling."
)


# ============================================================
# NAVIGATION
# ============================================================

page = st.radio(
    "Navigation",
    [
        "📊 Dashboard",
        "➕ Report",
        "🏢 Profiles",
        "📋 Reports"
    ],
    horizontal=True,
    label_visibility="collapsed"
)

st.divider()


# ============================================================
# DASHBOARD
# ============================================================

if page == "📊 Dashboard":

    st.header("📊 Operations Dashboard")

    stats = dashboard_stats()

    # --------------------------------------------------------
    # HEADLINE INTELLIGENCE
    # --------------------------------------------------------

    col1, col2, col3 = st.columns(3)

    with col1:

        st.metric(
            "🆕 New Delays This Week",
            stats["new_delays"]
        )

    with col2:

        st.metric(
            "🔁 New Recurring Patterns",
            stats["new_patterns"]
        )

    with col3:

        st.metric(
            "🕐 New Scheduling Patterns",
            stats["scheduling_patterns"]
        )


    col1, col2, col3 = st.columns(3)

    with col1:

        st.metric(
            "🔴 Confirmed Conditions",
            stats["confirmed"]
        )

    with col2:

        st.metric(
            "⏱ Typical Expected Delay",
            f"{round(stats['expected_delay'])} min"
        )

    with col3:

        hours = (
            stats["total_minutes"] / 60
        )

        st.metric(
            "⌛ Total Field Time Lost",
            f"{hours:.1f} hrs"
        )


    # --------------------------------------------------------
    # WHAT CHANGED THIS WEEK
    # --------------------------------------------------------

    st.subheader("What Changed This Week")

    patterns = build_patterns()

    start = week_start().isoformat()

    weekly = [
        p for p in patterns
        if p["first_seen"] >= start
    ]

    weekly.sort(
        key=lambda x: (
            x["status"] == "Confirmed",
            x["status"] == "Recognised",
            x["median_delay"]
        ),
        reverse=True
    )

    if not weekly:

        st.info(
            "No new operational intelligence "
            "has been discovered this week."
        )

    else:

        for pattern in weekly[:10]:

            status = pattern["status"]

            icon = pattern_icon(status)

            if (
                pattern["category"]
                == "Scheduling"
            ):
                event_icon = "🕐"

            elif pattern["solutions"]:
                event_icon = "💡"

            else:
                event_icon = icon

            st.markdown(
                f"### {event_icon} "
                f"{pattern['condition_type']}"
            )

            st.write(
                f"**{pattern['location']}**"
            )

            st.caption(
                f"{pattern['count']} report(s) • "
                f"{status} • "
                f"{pattern['confidence']} confidence"
            )

            if pattern["median_delay"]:

                st.write(
                    f"Typical delay: "
                    f"**+{round(pattern['median_delay'])} min**"
                )

            rec = recommendation(pattern)

            if rec:
                st.info(rec)


    # --------------------------------------------------------
    # HIGHEST IMPACT
    # --------------------------------------------------------

    st.subheader("🔥 Highest Impact Locations")

    recognised = [
        p for p in patterns
        if p["status"] in [
            "Recognised",
            "Confirmed"
        ]
    ]

    recognised.sort(
        key=lambda x: x["median_delay"],
        reverse=True
    )

    if not recognised:

        st.caption(
            "Recognised patterns will appear here "
            "as more field reports are collected."
        )

    else:

        for pattern in recognised[:5]:

            st.write(
                f"**{severity_icon(pattern['median_delay'])} "
                f"{pattern['location']}**"
            )

            st.write(
                f"{pattern['condition_type']} — "
                f"+{round(pattern['median_delay'])} min"
            )

            st.caption(
                f"{pattern['status']} • "
                f"{pattern['count']} reports"
            )


# ============================================================
# REPORT PAGE
# ============================================================

elif page == "➕ Report":

    st.header("➕ Report Field Difficulty")

    st.caption(
        "Record what was observed and how much "
        "time it actually cost."
    )


    # --------------------------------------------------------
    # LOCATION
    # --------------------------------------------------------

    visit_date = st.date_input(
        "Visit date",
        value=date.today()
    )

    address = st.text_input(
        "Building / Job Address",
        placeholder="100 George Street"
    )

    street = st.text_input(
        "Street",
        placeholder="George Street"
    )

    suburb = st.text_input(
        "Suburb",
        placeholder="Sydney"
    )

    profile_level = st.radio(
        "This report primarily applies to",
        [
            "Building",
            "Street"
        ],
        horizontal=True
    )


    # --------------------------------------------------------
    # POSITIVE REPORT
    # --------------------------------------------------------

    no_difficulty = st.checkbox(
        "✅ No difficulty encountered on this visit"
    )

    st.caption(
        "Positive reports help determine how often "
        "a difficulty actually occurs."
    )


    # --------------------------------------------------------
    # CONDITION BUILDER
    # --------------------------------------------------------

    if not no_difficulty:

        st.divider()

        st.subheader(
            "Add Difficulty"
        )

        category = st.radio(
            "Category",
            [
                "Site / Access",
                "Scheduling"
            ],
            horizontal=True
        )

        if category == "Site / Access":

            condition_type = st.selectbox(
                "Difficulty",
                SITE_CONDITIONS
            )

            internal_category = "Site"

        else:

            condition_type = st.selectbox(
                "Scheduling difficulty",
                SCHEDULING_CONDITIONS
            )

            internal_category = "Scheduling"


        delay_minutes = st.number_input(
            "Actual time lost from this condition",
            min_value=0,
            max_value=240,
            value=0,
            step=1
        )

        if delay_minutes > 0:

            st.caption(
                f"{severity_icon(delay_minutes)} "
                f"{severity(delay_minutes)} delay"
            )


        # ----------------------------------------------------
        # APPLICABILITY
        # ----------------------------------------------------

        applicability = st.selectbox(
            "When does this condition apply?",
            [
                "Always",
                "Certain times",
                "Certain days and times"
            ]
        )

        selected_days = []
        start_time_value = None
        end_time_value = None


        if applicability == "Certain times":

            col1, col2 = st.columns(2)

            with col1:

                start_value = st.time_input(
                    "Starts",
                    value=time(8, 0)
                )

            with col2:

                end_value = st.time_input(
                    "Ends",
                    value=time(13, 0)
                )

            start_time_value = (
                start_value.strftime("%H:%M")
            )

            end_time_value = (
                end_value.strftime("%H:%M")
            )


        elif applicability == "Certain days and times":

            selected_days = st.multiselect(
                "Applicable days",
                DAYS,
                default=[
                    "Monday",
                    "Tuesday",
                    "Wednesday",
                    "Thursday",
                    "Friday"
                ]
            )

            col1, col2 = st.columns(2)

            with col1:

                start_value = st.time_input(
                    "Starts",
                    value=time(8, 0),
                    key="days_start"
                )

            with col2:

                end_value = st.time_input(
                    "Ends",
                    value=time(13, 0),
                    key="days_end"
                )

            start_time_value = (
                start_value.strftime("%H:%M")
            )

            end_time_value = (
                end_value.strftime("%H:%M")
            )


        # ----------------------------------------------------
        # EVIDENCE
        # ----------------------------------------------------

        source_status = st.radio(
            "Evidence type",
            [
                "Field observation",
                "Verified condition"
            ],
            horizontal=True
        )

        confirmed = st.checkbox(
            "Confirm as recurring/permanent immediately"
        )

        if confirmed:

            st.caption(
                "Use for objectively repeatable conditions "
                "such as a signed clearway or permanent "
                "building access requirement."
            )


        # ----------------------------------------------------
        # SOLUTION
        # ----------------------------------------------------

        solution = st.selectbox(
            "Known solution",
            SOLUTIONS
        )

        solution_notes = ""

        if solution != "None":

            solution_notes = st.text_input(
                "Solution details",
                placeholder=(
                    "Example: Concierge can reserve "
                    "contractor bay before arrival."
                )
            )


        concierge = solution in [
            "Concierge parking booking",
            "Contact concierge before arrival"
        ]

        if concierge:

            st.success(
                "🛎️ Concierge solution will appear "
                "on the profile."
            )


        # ----------------------------------------------------
        # ADD CONDITION
        # ----------------------------------------------------

        if st.button(
            "➕ Add Difficulty to Report",
            use_container_width=True
        ):

            condition = {
                "category": internal_category,
                "condition_type": condition_type,
                "delay_minutes": delay_minutes,
                "applicability": applicability,
                "days": selected_days,
                "start_time": start_time_value,
                "end_time": end_time_value,
                "source_status": source_status,
                "confirmed": confirmed,
                "solution": solution,
                "solution_notes": solution_notes,
                "concierge": concierge
            }

            st.session_state.condition_builder.append(
                condition
            )

            st.rerun()


    # --------------------------------------------------------
    # CURRENT REPORT
    # --------------------------------------------------------

    if st.session_state.condition_builder:

        st.divider()

        st.subheader(
            "Current Report"
        )

        total = sum(
            item["delay_minutes"]
            for item
            in st.session_state.condition_builder
        )

        st.metric(
            "Total Time Lost",
            f"{total} min"
        )

        for index, item in enumerate(
            st.session_state.condition_builder
        ):

            with st.expander(
                f"{index + 1}. "
                f"{item['condition_type']} — "
                f"{item['delay_minutes']} min"
            ):

                st.write(
                    f"**Category:** "
                    f"{item['category']}"
                )

                st.write(
                    f"**Applicability:** "
                    f"{item['applicability']}"
                )

                if item["days"]:

                    st.write(
                        "**Days:** "
                        + ", ".join(item["days"])
                    )

                if (
                    item["start_time"]
                    and item["end_time"]
                ):

                    st.write(
                        f"**Time:** "
                        f"{format_time(item['start_time'])}"
                        f" – "
                        f"{format_time(item['end_time'])}"
                    )

                st.write(
                    f"**Evidence:** "
                    f"{item['source_status']}"
                )

                if item["confirmed"]:

                    st.write(
                        "🔴 Immediately confirmed"
                    )

                if item["solution"] != "None":

                    st.write(
                        f"💡 {item['solution']}"
                    )

                if st.button(
                    "Remove",
                    key=f"remove_condition_{index}"
                ):

                    st.session_state.condition_builder.pop(
                        index
                    )

                    st.rerun()


    # --------------------------------------------------------
    # NOTES
    # --------------------------------------------------------

    notes = st.text_area(
        "Visit notes",
        placeholder=(
            "Anything else that may help the "
            "next technician or scheduler."
        )
    )


    # --------------------------------------------------------
    # SAVE REPORT
    # --------------------------------------------------------

    if st.button(
        "💾 Save Field Report",
        type="primary",
        use_container_width=True
    ):

        if not address.strip():

            st.error(
                "Enter the job/building address."
            )

        elif (
            not no_difficulty
            and
            not st.session_state.condition_builder
        ):

            st.error(
                "Add at least one difficulty or select "
                "'No difficulty encountered'."
            )

        else:

            save_visit(
                visit_date,
                address,
                street,
                suburb,
                profile_level,
                no_difficulty,
                st.session_state.condition_builder,
                notes
            )

            st.session_state.condition_builder = []

            st.success(
                "Field report saved successfully."
            )


# ============================================================
# PROFILES
# ============================================================

elif page == "🏢 Profiles":

    st.header(
        "🏢 Difficulty Profiles"
    )

    patterns = build_patterns()

    if not patterns:

        st.info(
            "No difficulty intelligence has "
            "been collected yet."
        )

    else:

        search = st.text_input(
            "🔎 Search address, street or suburb",
            placeholder="Start typing..."
        )

        filtered = patterns

        if search:

            term = search.lower()

            filtered = [
                p for p in patterns
                if (
                    term in p["location"].lower()
                    or
                    term in (
                        p["suburb"] or ""
                    ).lower()
                )
            ]


        locations = sorted(
            set(
                p["location"]
                for p in filtered
            )
        )


        if not locations:

            st.warning(
                "No matching profiles."
            )

        else:

            selected = st.selectbox(
                "Location",
                locations
            )

            location_patterns = [
                p for p in filtered
                if p["location"] == selected
            ]


            # ------------------------------------------------
            # PROFILE SUMMARY
            # ------------------------------------------------

            has_concierge = any(
                p["concierge"]
                for p in location_patterns
            )

            if has_concierge:

                st.header(
                    f"⚠️ {selected} 🛎️"
                )

            else:

                st.header(
                    f"⚠️ {selected}"
                )


            recognised = [
                p for p in location_patterns
                if p["status"] in [
                    "Recognised",
                    "Confirmed"
                ]
            ]

            expected_delays = [
                p["median_delay"]
                for p in recognised
                if p["median_delay"] > 0
            ]

            if expected_delays:

                expected = median(
                    expected_delays
                )

                st.warning(
                    f"⏱ Expected additional time: "
                    f"approximately "
                    f"+{round(expected)} minutes"
                )


            # ------------------------------------------------
            # ACTIONABLE WARNINGS
            # ------------------------------------------------

            st.subheader(
                "Actionable Intelligence"
            )

            for pattern in location_patterns:

                icon = pattern_icon(
                    pattern["status"]
                )

                st.markdown(
                    f"### {icon} "
                    f"{pattern['condition_type']}"
                )

                col1, col2, col3 = st.columns(3)

                with col1:

                    st.metric(
                        "Reports",
                        pattern["count"]
                    )

                with col2:

                    st.metric(
                        "Encounter Rate",
                        f"{pattern_percentage(pattern)}%"
                    )

                with col3:

                    st.metric(
                        "Median Delay",
                        f"{round(pattern['median_delay'])} min"
                    )


                st.caption(
                    f"{pattern['status']} pattern • "
                    f"{pattern['confidence']} confidence"
                )


                if pattern["time_windows"]:

                    for start, end in pattern["time_windows"]:

                        st.write(
                            f"🕐 **Applies:** "
                            f"{format_time(start)} – "
                            f"{format_time(end)}"
                        )


                if pattern["days"]:

                    st.write(
                        "📅 **Days:** "
                        + ", ".join(
                            sorted(pattern["days"])
                        )
                    )


                rec = recommendation(
                    pattern
                )

                if rec:

                    st.info(
                        f"💡 {rec}"
                    )


                if pattern["solutions"]:

                    for solution in sorted(
                        pattern["solutions"]
                    ):

                        if "Concierge" in solution:

                            st.success(
                                f"🛎️ {solution}"
                            )

                        else:

                            st.success(
                                f"💡 {solution}"
                            )

                st.divider()


# ============================================================
# REPORT HISTORY
# ============================================================

elif page == "📋 Reports":

    st.header(
        "📋 Field Report History"
    )

    visits = get_visits()

    if not visits:

        st.info(
            "No reports have been recorded."
        )

    else:

        for visit in visits:

            title = (
                f"{visit['visit_date']} — "
                f"{visit['address']}"
            )

            if visit["total_delay"]:

                title += (
                    f" — {visit['total_delay']} min"
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
                        f"**Suburb:** "
                        f"{visit['suburb']}"
                    )

                st.write(
                    f"**Profile level:** "
                    f"{visit['profile_level']}"
                )

                if visit["no_difficulty"]:

                    st.success(
                        "✅ No difficulty encountered"
                    )

                else:

                    condition_rows = execute("""
                        SELECT *
                        FROM conditions
                        WHERE visit_id = ?
                        ORDER BY id
                    """, (
                        visit["id"],
                    )).fetchall()

                    for row in condition_rows:

                        st.markdown(
                            f"**{row['condition_type']}**"
                        )

                        st.write(
                            f"Time lost: "
                            f"{row['delay_minutes']} min"
                        )

                        if (
                            row["start_time"]
                            and row["end_time"]
                        ):

                            st.write(
                                f"Applies: "
                                f"{format_time(row['start_time'])}"
                                f" – "
                                f"{format_time(row['end_time'])}"
                            )

                        if row["solution"] != "None":

                            st.write(
                                f"💡 {row['solution']}"
                            )

                        st.write("---")


                if visit["notes"]:

                    st.write(
                        f"**Notes:** "
                        f"{visit['notes']}"
                    )


                st.metric(
                    "Total Recorded Delay",
                    f"{visit['total_delay']} min"
                )


                if st.button(
                    "🗑 Delete Report",
                    key=f"delete_visit_{visit['id']}"
                ):

                    delete_visit(
                        visit["id"]
                    )

                    st.rerun()
