Building difficulty profiler V1

import streamlit as st
import sqlite3
from datetime import datetime, time

# ============================================================
# BUILDING DIFFICULTY PROFILE — V1
# Python + Streamlit + SQLite
# ============================================================

st.set_page_config(
    page_title="Building Difficulty Profile",
    page_icon="🏢",
    layout="centered"
)

DB_NAME = "building_difficulty.db"


# ============================================================
# DATABASE
# ============================================================

def get_connection():
    return sqlite3.connect(DB_NAME, check_same_thread=False)


conn = get_connection()
cursor = conn.cursor()


cursor.execute("""
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    created_at TEXT NOT NULL,

    address TEXT NOT NULL,
    suburb TEXT,

    profile_level TEXT DEFAULT 'Building',

    difficulty_type TEXT NOT NULL,

    time_lost INTEGER DEFAULT 0,

    notes TEXT,

    clearway INTEGER DEFAULT 0,

    clearway_start TEXT,
    clearway_end TEXT,

    confirmed INTEGER DEFAULT 0,

    solution TEXT,

    concierge INTEGER DEFAULT 0
)
""")

conn.commit()


# ============================================================
# CONSTANTS
# ============================================================

DIFFICULTY_TYPES = [
    "Parking difficult",
    "No parking available",
    "Clearway / timed parking restriction",
    "Loading zone only",
    "Long walk from parking",
    "Building access difficult",
    "Intercom delay",
    "Tenant access delay",
    "Concierge / reception delay",
    "Lift delay",
    "Multiple buildings / confusing complex",
    "Restricted access",
    "Other"
]


PROFILE_LEVELS = [
    "Building",
    "Street"
]


SOLUTIONS = [
    "None",
    "Concierge parking booking",
    "Contact concierge before arrival",
    "Call tenant before arrival",
    "Use alternative parking location",
    "Allow additional arrival time",
    "Use loading area",
    "Alternative building entrance",
    "Other"
]


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def normalize_address(address):
    return address.strip().lower()


def save_report(
    address,
    suburb,
    profile_level,
    difficulty_type,
    time_lost,
    notes,
    clearway,
    clearway_start,
    clearway_end,
    confirmed,
    solution,
    concierge
):

    cursor.execute("""
        INSERT INTO reports (
            created_at,
            address,
            suburb,
            profile_level,
            difficulty_type,
            time_lost,
            notes,
            clearway,
            clearway_start,
            clearway_end,
            confirmed,
            solution,
            concierge
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(),
        address.strip(),
        suburb.strip(),
        profile_level,
        difficulty_type,
        time_lost,
        notes.strip(),
        int(clearway),
        clearway_start.strftime("%H:%M") if clearway else None,
        clearway_end.strftime("%H:%M") if clearway else None,
        int(confirmed),
        solution,
        int(concierge)
    ))

    conn.commit()


def get_reports():

    cursor.execute("""
        SELECT *
        FROM reports
        ORDER BY created_at DESC
    """)

    return cursor.fetchall()


def get_address_reports(address):

    cursor.execute("""
        SELECT *
        FROM reports
        WHERE LOWER(address) = ?
        ORDER BY created_at DESC
    """, (normalize_address(address),))

    return cursor.fetchall()


def delete_report(report_id):

    cursor.execute(
        "DELETE FROM reports WHERE id = ?",
        (report_id,)
    )

    conn.commit()


def calculate_profile(address):

    reports = get_address_reports(address)

    if not reports:
        return None

    report_count = len(reports)

    total_delay = sum(row[6] for row in reports)

    average_delay = (
        total_delay / report_count
        if report_count > 0
        else 0
    )

    confirmed = any(row[11] == 1 for row in reports)

    concierge = any(row[13] == 1 for row in reports)

    clearway = any(row[8] == 1 for row in reports)

    difficulty_counts = {}

    for row in reports:

        difficulty = row[5]

        difficulty_counts[difficulty] = (
            difficulty_counts.get(difficulty, 0) + 1
        )

    most_common = max(
        difficulty_counts,
        key=difficulty_counts.get
    )

    # --------------------------------------------------------
    # V1 PROFILE RULE
    #
    # 1 report:
    # Observation only
    #
    # 2 reports:
    # Emerging pattern
    #
    # 3+ reports:
    # Expected difficulty
    #
    # Manual confirmed flag bypasses repetition requirement
    # --------------------------------------------------------

    if confirmed:
        status = "CONFIRMED DIFFICULTY"

    elif report_count >= 3:
        status = "EXPECTED DIFFICULTY"

    elif report_count == 2:
        status = "EMERGING PATTERN"

    else:
        status = "OBSERVATION"

    return {
        "reports": reports,
        "count": report_count,
        "average_delay": average_delay,
        "most_common": most_common,
        "status": status,
        "concierge": concierge,
        "clearway": clearway
    }


def get_unique_addresses():

    cursor.execute("""
        SELECT DISTINCT address
        FROM reports
        ORDER BY address
    """)

    return [row[0] for row in cursor.fetchall()]


# ============================================================
# HEADER
# ============================================================

st.title("🏢 Building Difficulty Profile")

st.caption(
    "Record operational delays and build expected difficulty "
    "profiles from real field experience."
)


# ============================================================
# NAVIGATION
# ============================================================

page = st.radio(
    "Navigation",
    [
        "➕ Report Delay",
        "🏢 Building Profiles",
        "📋 Report History"
    ],
    horizontal=True
)


# ============================================================
# PAGE 1 — REPORT DELAY
# ============================================================

if page == "➕ Report Delay":

    st.header("Report Delay")

    st.write(
        "Record difficulty encountered while accessing or "
        "completing a job."
    )

    address = st.text_input(
        "Building / Job Address",
        placeholder="Example: 100 George Street"
    )

    suburb = st.text_input(
        "Suburb",
        placeholder="Example: Sydney"
    )

    profile_level = st.selectbox(
        "Difficulty applies to",
        PROFILE_LEVELS
    )

    difficulty_type = st.selectbox(
        "Difficulty Type",
        DIFFICULTY_TYPES
    )

    time_lost = st.number_input(
        "Time Lost (minutes)",
        min_value=0,
        max_value=240,
        value=0,
        step=1
    )

    # --------------------------------------------------------
    # CLEARWAY
    # --------------------------------------------------------

    clearway = False
    clearway_start = time(8, 0)
    clearway_end = time(13, 0)

    if difficulty_type == "Clearway / timed parking restriction":

        st.subheader("🚫 Clearway / Parking Restriction")

        clearway = st.checkbox(
            "This difficulty only applies during certain times",
            value=True
        )

        if clearway:

            col1, col2 = st.columns(2)

            with col1:

                clearway_start = st.time_input(
                    "Restriction starts",
                    value=time(8, 0)
                )

            with col2:

                clearway_end = st.time_input(
                    "Restriction ends",
                    value=time(13, 0)
                )

            st.info(
                f"Parking difficulty expected between "
                f"{clearway_start.strftime('%I:%M %p')} and "
                f"{clearway_end.strftime('%I:%M %p')}."
            )


    # --------------------------------------------------------
    # CONFIRMED DIFFICULTY
    # --------------------------------------------------------

    st.subheader("Difficulty Status")

    confirmed = st.checkbox(
        "Confirm this as a repeating difficulty immediately"
    )

    st.caption(
        "Use this when the nature of the problem clearly means "
        "it will affect future jobs, even if it has only been "
        "reported once."
    )


    # --------------------------------------------------------
    # SOLUTION
    # --------------------------------------------------------

    st.subheader("Possible Solution")

    solution = st.selectbox(
        "Solution",
        SOLUTIONS
    )

    concierge = False

    if solution in [
        "Concierge parking booking",
        "Contact concierge before arrival"
    ]:

        concierge = True

        st.success(
            "🛎️ Concierge solution will be shown on the "
            "building profile."
        )


    notes = st.text_area(
        "Notes",
        placeholder=(
            "Example: No street parking available. "
            "Building concierge can reserve contractor parking."
        )
    )


    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    if st.button(
        "Save Delay Report",
        type="primary",
        use_container_width=True
    ):

        if not address.strip():

            st.error(
                "Enter the building or street address."
            )

        else:

            save_report(
                address,
                suburb,
                profile_level,
                difficulty_type,
                time_lost,
                notes,
                clearway,
                clearway_start,
                clearway_end,
                confirmed,
                solution,
                concierge
            )

            st.success(
                "Delay report saved."
            )


# ============================================================
# PAGE 2 — BUILDING PROFILES
# ============================================================

elif page == "🏢 Building Profiles":

    st.header("Building Difficulty Profiles")

    addresses = get_unique_addresses()

    if not addresses:

        st.info(
            "No building profiles yet. "
            "Submit a delay report first."
        )

    else:

        selected_address = st.selectbox(
            "Select Building",
            addresses
        )

        profile = calculate_profile(
            selected_address
        )

        if profile:

            st.divider()

            # ------------------------------------------------
            # PROFILE HEADER
            # ------------------------------------------------

            if profile["concierge"]:

                st.subheader(
                    f"🏢 🛎️ {selected_address}"
                )

            else:

                st.subheader(
                    f"🏢 {selected_address}"
                )


            status = profile["status"]

            if status == "CONFIRMED DIFFICULTY":

                st.error(
                    "🔴 CONFIRMED DIFFICULTY"
                )

            elif status == "EXPECTED DIFFICULTY":

                st.warning(
                    "🟠 EXPECTED DIFFICULTY"
                )

            elif status == "EMERGING PATTERN":

                st.info(
                    "🟡 EMERGING PATTERN"
                )

            else:

                st.write(
                    "⚪ OBSERVATION"
                )


            # ------------------------------------------------
            # METRICS
            # ------------------------------------------------

            col1, col2 = st.columns(2)

            with col1:

                st.metric(
                    "Reports",
                    profile["count"]
                )

            with col2:

                st.metric(
                    "Average Time Lost",
                    f"{profile['average_delay']:.0f} min"
                )


            st.write(
                "**Most common difficulty:**",
                profile["most_common"]
            )


            # ------------------------------------------------
            # EXPECTED DELAY
            # ------------------------------------------------

            if status in [
                "CONFIRMED DIFFICULTY",
                "EXPECTED DIFFICULTY"
            ]:

                st.warning(
                    f"⏱️ Expected operational delay: "
                    f"approximately "
                    f"{profile['average_delay']:.0f} minutes."
                )


            # ------------------------------------------------
            # CLEARWAY INFORMATION
            # ------------------------------------------------

            clearway_reports = [
                row
                for row in profile["reports"]
                if row[8] == 1
            ]

            if clearway_reports:

                st.subheader(
                    "🚫 Timed Parking Restrictions"
                )

                seen = set()

                for row in clearway_reports:

                    restriction = (
                        row[9],
                        row[10]
                    )

                    if restriction not in seen:

                        seen.add(restriction)

                        st.write(
                            f"Parking difficulty expected "
                            f"between **{row[9]} – {row[10]}**"
                        )

                        st.caption(
                            "Outside this period the parking "
                            "restriction is not treated as an "
                            "expected difficulty."
                        )


            # ------------------------------------------------
            # SOLUTIONS
            # ------------------------------------------------

            solutions = []

            for row in profile["reports"]:

                solution = row[12]

                if (
                    solution
                    and solution != "None"
                    and solution not in solutions
                ):

                    solutions.append(solution)


            if solutions:

                st.subheader(
                    "💡 Known Solutions"
                )

                for solution in solutions:

                    if "Concierge" in solution:

                        st.success(
                            f"🛎️ {solution}"
                        )

                    else:

                        st.write(
                            f"• {solution}"
                        )


            # ------------------------------------------------
            # REPORT HISTORY
            # ------------------------------------------------

            st.subheader(
                "Previous Reports"
            )

            for row in profile["reports"]:

                report_date = datetime.fromisoformat(
                    row[1]
                ).strftime(
                    "%d %b %Y %I:%M %p"
                )

                with st.expander(
                    f"{report_date} — {row[5]}"
                ):

                    st.write(
                        f"**Time lost:** {row[6]} minutes"
                    )

                    st.write(
                        f"**Applies to:** {row[4]}"
                    )

                    if row[7]:

                        st.write(
                            f"**Notes:** {row[7]}"
                        )

                    if row[8]:

                        st.write(
                            f"🚫 **Restriction:** "
                            f"{row[9]} – {row[10]}"
                        )

                    if row[11]:

                        st.write(
                            "🔴 **Manually confirmed "
                            "difficulty**"
                        )

                    if row[12] != "None":

                        st.write(
                            f"💡 **Solution:** {row[12]}"
                        )

                    if row[13]:

                        st.write(
                            "🛎️ **Concierge option available**"
                        )


# ============================================================
# PAGE 3 — REPORT HISTORY
# ============================================================

elif page == "📋 Report History":

    st.header(
        "Delay Report History"
    )

    reports = get_reports()

    if not reports:

        st.info(
            "No delay reports have been recorded."
        )

    else:

        for row in reports:

            report_id = row[0]

            report_date = datetime.fromisoformat(
                row[1]
            ).strftime(
                "%d %b %Y %I:%M %p"
            )

            title = (
                f"{row[2]} — "
                f"{row[5]} — "
                f"{row[6]} min"
            )

            with st.expander(title):

                st.write(
                    f"**Reported:** {report_date}"
                )

                if row[3]:

                    st.write(
                        f"**Suburb:** {row[3]}"
                    )

                st.write(
                    f"**Profile level:** {row[4]}"
                )

                st.write(
                    f"**Difficulty:** {row[5]}"
                )

                st.write(
                    f"**Time lost:** {row[6]} minutes"
                )

                if row[7]:

                    st.write(
                        f"**Notes:** {row[7]}"
                    )

                if row[8]:

                    st.write(
                        f"🚫 **Timed restriction:** "
                        f"{row[9]} – {row[10]}"
                    )

                if row[11]:

                    st.write(
                        "🔴 **Confirmed recurring difficulty**"
                    )

                if row[12] != "None":

                    st.write(
                        f"💡 **Solution:** {row[12]}"
                    )

                if row[13]:

                    st.write(
                        "🛎️ **Concierge option available**"
                    )

                st.divider()

                if st.button(
                    "Delete Report",
                    key=f"delete_{report_id}"
                ):

                    delete_report(report_id)

                    st.success(
                        "Report deleted."
                    )

                    st.rerun()
