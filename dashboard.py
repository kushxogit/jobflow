"""
JobFlow Dashboard — Neue Haas Grotesk, top nav, interactive calendar filter.
"""
from __future__ import annotations

import json
import sqlite3
import calendar as cal_module
from datetime import datetime, timezone, date
from pathlib import Path

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parent
DB_PATH = ROOT_DIR / "data" / "jobflow.db"

MONTHS = ["","January","February","March","April","May","June",
          "July","August","September","October","November","December"]
WEEKDAYS = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]


# ─────────────────────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="JobFlow", page_icon="□", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown("""
<style>
/* ── Font ── */
* {
    font-family: "Neue Haas Grotesk Display Pro", "NeueHaasGroteskDisplayPro",
                 "Neue Haas Grotesk Text Pro", HelveticaNeue, "Helvetica Neue",
                 Helvetica, -apple-system, BlinkMacSystemFont, Arial, sans-serif !important;
}

/* ── Hide Streamlit chrome ── */
header[data-testid="stHeader"],
#MainMenu, footer,
.stDeployButton,
[data-testid="manage-app-button"],
section[data-testid="stSidebar"] { display: none !important; }

/* ── Base ── */
html, body, .stApp { background: #fafafa; color: #111; }
.main .block-container {
    padding-top: 88px !important;
    padding-left: 40px !important;
    padding-right: 40px !important;
    max-width: 100% !important;
}

/* ── Fixed top nav ── */
.jf-nav {
    position: fixed; top: 0; left: 0; right: 0; z-index: 9999;
    background: #111; height: 52px;
    display: flex; align-items: stretch;
    border-bottom: none;
}
.jf-nav-logo {
    font-size: 0.78rem; font-weight: 700; letter-spacing: 0.18em;
    text-transform: uppercase; color: #fff;
    padding: 0 28px; display: flex; align-items: center;
    border-right: 1px solid #2a2a2a; white-space: nowrap;
}
.jf-nav a {
    color: #666; text-decoration: none;
    font-size: 0.73rem; font-weight: 500; letter-spacing: 0.06em;
    text-transform: uppercase; padding: 0 22px;
    display: flex; align-items: center;
    transition: color 0.12s, background 0.12s;
    border-bottom: 2px solid transparent;
}
.jf-nav a:hover { color: #fff; background: #1c1c1c; text-decoration: none; }
.jf-nav a.active { color: #fff; border-bottom-color: #fff; }
.jf-nav-right {
    margin-left: auto; display: flex; align-items: center;
    padding: 0 24px; font-size: 0.7rem; color: #555;
    white-space: nowrap;
}

/* ── Stat strip ── */
.jf-stats {
    display: flex; gap: 0; margin-bottom: 20px;
    border: 1px solid #e4e4e4; background: #fff;
}
.jf-stat {
    flex: 1; padding: 14px 18px; border-right: 1px solid #e4e4e4;
    text-align: center;
}
.jf-stat:last-child { border-right: none; }
.jf-stat-n { font-size: 1.6rem; font-weight: 600; color: #111; line-height: 1; }
.jf-stat-l {
    font-size: 0.62rem; font-weight: 600; letter-spacing: 0.14em;
    text-transform: uppercase; color: #bbb; margin-top: 3px;
}

/* ── Calendar ── */
.jf-cal {
    border: 1px solid #e4e4e4; background: #fff;
    padding: 18px 22px; margin-bottom: 20px;
}
.jf-cal-head {
    display: flex; align-items: center; gap: 12px; margin-bottom: 14px;
}
.jf-cal-month {
    font-size: 0.78rem; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; color: #111;
}
.jf-cal-arrow {
    color: #111; text-decoration: none;
    font-size: 0.85rem; font-weight: 700;
    padding: 3px 9px; border: 1px solid #e4e4e4;
    line-height: 1.4; transition: background 0.12s;
}
.jf-cal-arrow:hover { background: #f0f0f0; text-decoration: none; color: #111; }
.jf-cal-clear {
    margin-left: auto; font-size: 0.68rem; color: #bbb;
    text-decoration: none; letter-spacing: 0.06em; text-transform: uppercase;
}
.jf-cal-clear:hover { color: #111; text-decoration: none; }
.jf-cal-grid {
    display: grid; grid-template-columns: repeat(7, 1fr); gap: 3px;
}
.jf-cal-dow {
    font-size: 0.6rem; font-weight: 700; letter-spacing: 0.14em;
    text-transform: uppercase; color: #ccc; text-align: center;
    padding: 4px 0 8px;
}
.jf-cal-d {
    display: block; text-align: center; padding: 6px 3px;
    font-size: 0.76rem; font-weight: 500;
    text-decoration: none; color: #ccc;
    transition: background 0.1s;
    position: relative;
}
.jf-cal-d:hover { background: #f5f5f5; text-decoration: none; color: #111; }
.jf-cal-d.has  { color: #111; background: #dcfce7; font-weight: 600; }
.jf-cal-d.has:hover { background: #bbf7d0; text-decoration: none; }
.jf-cal-d.sel  { background: #111 !important; color: #fff !important; font-weight: 700; }
.jf-cal-d.sel:hover { background: #333 !important; text-decoration: none; color: #fff !important; }
.jf-cal-d.empty { visibility: hidden; }
.jf-cal-dot {
    display: block; width: 3px; height: 3px; background: #111;
    border-radius: 50%; margin: 2px auto 0; opacity: 0.5;
}

/* ── Job rows ── */
.jf-list { border-top: 2px solid #111; }
.jf-row {
    display: flex; justify-content: space-between; align-items: flex-start;
    gap: 20px; padding: 14px 0; border-bottom: 1px solid #e4e4e4;
}
.jf-row-l { flex: 1; min-width: 0; }
.jf-title {
    font-size: 0.9rem; font-weight: 600; color: #111;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    margin-bottom: 3px;
}
.jf-sub { font-size: 0.72rem; color: #888; margin-bottom: 6px; }
.jf-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.jf-tag {
    font-size: 0.6rem; font-weight: 700; letter-spacing: 0.1em;
    text-transform: uppercase; padding: 2px 7px;
    border: 1px solid currentColor;
}
.jf-g  { color: #16a34a; }
.jf-b  { color: #2563eb; }
.jf-r  { color: #dc2626; }
.jf-gr { color: #9ca3af; }
.jf-row-r {
    text-align: right; flex-shrink: 0;
    font-size: 0.7rem; color: #bbb; line-height: 1.9;
}
.jf-score { font-size: 1.05rem; font-weight: 700; color: #111; }
.jf-empty { font-size: 0.8rem; color: #bbb; padding: 28px 0; }

/* ── Streamlit buttons — robust overrides ── */
.stButton > button {
    background: #fff !important;
    color: #111 !important;
    border: 1px solid #111 !important;
    border-radius: 0 !important;
    font-size: 0.68rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
    padding: 5px 14px !important;
    line-height: 1.4 !important;
    min-height: 28px !important;
    box-shadow: none !important;
    transition: background 0.12s, color 0.12s !important;
}
.stButton > button:hover,
.stButton > button:active {
    background: #111 !important;
    color: #fff !important;
    border-color: #111 !important;
    box-shadow: none !important;
}
.stButton > button:focus:not(:active) {
    box-shadow: 0 0 0 2px #111 !important;
    outline: none !important;
}

/* ── Link button ── */
a[data-testid="stLinkButton-link"] {
    background: #fff !important;
    color: #111 !important;
    border: 1px solid #111 !important;
    border-radius: 0 !important;
    font-size: 0.68rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
    padding: 5px 14px !important;
    line-height: 1.4 !important;
    text-decoration: none !important;
    display: inline-flex !important;
    align-items: center !important;
    transition: background 0.12s, color 0.12s !important;
}
a[data-testid="stLinkButton-link"]:hover {
    background: #111 !important;
    color: #fff !important;
    text-decoration: none !important;
}

/* ── Inputs ── */
.stTextInput input {
    border: 1px solid #e4e4e4 !important;
    border-radius: 0 !important;
    background: #fff !important;
    font-size: 0.8rem !important;
    padding: 7px 12px !important;
    box-shadow: none !important;
}
.stTextInput input:focus {
    border-color: #111 !important;
    box-shadow: none !important;
}
.stSelectbox > div > div {
    border: 1px solid #e4e4e4 !important;
    border-radius: 0 !important;
    font-size: 0.8rem !important;
    box-shadow: none !important;
}

/* ── Expander ── */
details[data-testid="stExpander"] summary {
    border: 1px solid #e4e4e4 !important;
    border-radius: 0 !important;
    padding: 7px 12px !important;
    font-size: 0.65rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
    background: #fafafa !important;
    color: #888 !important;
}
details[data-testid="stExpander"] summary:hover { background: #f0f0f0 !important; }

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 1px solid #e4e4e4 !important;
    gap: 0 !important;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    border-radius: 0 !important;
    border: none !important;
    font-size: 0.68rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
    color: #aaa !important;
    padding: 8px 20px !important;
}
.stTabs [aria-selected="true"] {
    color: #111 !important;
    border-bottom: 2px solid #111 !important;
}

/* ── Section labels ── */
.jf-section {
    font-size: 0.62rem; font-weight: 700; letter-spacing: 0.18em;
    text-transform: uppercase; color: #bbb; margin-bottom: 14px;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: #fafafa; }
::-webkit-scrollbar-thumb { background: #ddd; }
::-webkit-scrollbar-thumb:hover { background: #bbb; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_data(ttl=30)
def load_stats() -> dict:
    if not DB_PATH.exists():
        return {k: 0 for k in ["total","shortlisted","filtered","approved","skipped","applied"]}
    conn = get_conn()
    try:
        def cnt(w=""): return conn.execute(f"SELECT COUNT(*) FROM seen_jobs {w}").fetchone()[0]
        return {
            "total":       cnt(),
            "shortlisted": cnt("WHERE status='shortlisted'"),
            "filtered":    cnt("WHERE status='filtered'"),
            "approved":    cnt("WHERE status='approved'"),
            "skipped":     cnt("WHERE status='skipped'"),
            "applied":     cnt("WHERE status='applied'"),
        }
    finally:
        conn.close()


@st.cache_data(ttl=30)
def get_job_days_in_month(year: int, month: int) -> set[int]:
    """Return set of day-of-month ints that have at least one job."""
    if not DB_PATH.exists():
        return set()
    conn = get_conn()
    try:
        prefix = f"{year}-{month:02d}"
        rows = conn.execute(
            "SELECT first_seen_at FROM seen_jobs WHERE first_seen_at LIKE ?",
            (f"{prefix}%",)
        ).fetchall()
        days: set[int] = set()
        for row in rows:
            try:
                dt = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                days.add(dt.day)
            except Exception:
                pass
        return days
    finally:
        conn.close()


def load_jobs(
    status: str | None = None,
    day_filter: date | None = None,
    search: str = "",
    source: str = "All",
    limit: int = 500,
) -> list[dict]:
    if not DB_PATH.exists():
        return []
    conn = get_conn()
    try:
        clauses: list[str] = []
        params: list = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if day_filter:
            clauses.append("first_seen_at LIKE ?")
            params.append(f"{day_filter.isoformat()}%")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM seen_jobs {where} ORDER BY first_seen_at DESC LIMIT ?",
            params
        ).fetchall()
        jobs = [dict(r) for r in rows]
    finally:
        conn.close()

    if search:
        q = search.lower()
        jobs = [j for j in jobs if q in j.get("title","").lower() or q in j.get("company","").lower()]
    if source != "All":
        jobs = [j for j in jobs if source.lower() in j.get("source","").lower()]
    return jobs


def set_status(fingerprint: str, new_status: str) -> None:
    conn = get_conn()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE seen_jobs SET status=?, last_seen_at=? WHERE fingerprint=?",
            (new_status, now, fingerprint)
        )
        conn.commit()
    finally:
        conn.close()
    st.cache_data.clear()


# ─────────────────────────────────────────────────────────────────────────────
# URL state  (tab, month, date all live in query params so links work)
# ─────────────────────────────────────────────────────────────────────────────

qp = st.query_params
active_tab    = qp.get("tab", "overview")
cal_month_str = qp.get("month", "")
sel_date_str  = qp.get("date", "")

_now = datetime.now()
if cal_month_str:
    try:
        cal_year, cal_month = map(int, cal_month_str.split("-"))
    except Exception:
        cal_year, cal_month = _now.year, _now.month
else:
    cal_year, cal_month = _now.year, _now.month

selected_date: date | None = None
if sel_date_str:
    try:
        selected_date = date.fromisoformat(sel_date_str)
    except Exception:
        selected_date = None

def _prev(y, m): return (y - 1, 12) if m == 1 else (y, m - 1)
def _next(y, m): return (y + 1, 1) if m == 12 else (y, m + 1)

pm_y, pm_m = _prev(cal_year, cal_month)
nm_y, nm_m = _next(cal_year, cal_month)
pm_str = f"{pm_y}-{pm_m:02d}"
nm_str = f"{nm_y}-{nm_m:02d}"
cm_str = f"{cal_year}-{cal_month:02d}"


def url(tab=None, month=None, day: date | None = None) -> str:
    t = tab or active_tab
    m = month or cm_str
    d = f"&date={day.isoformat()}" if day else ""
    return f"?tab={t}&month={m}{d}"


# ─────────────────────────────────────────────────────────────────────────────
# Top nav bar
# ─────────────────────────────────────────────────────────────────────────────

stats = load_stats()

tabs = [
    ("overview", "Overview"),
    ("review",   "Review"),
    ("approved", "Approved"),
    ("filtered", "Filtered"),
    ("all",      "All Jobs"),
]
nav_html = ""
for key, label in tabs:
    cls = "active" if active_tab == key else ""
    nav_html += f'<a href="{url(tab=key)}" class="{cls}">{label}</a>'

st.markdown(f"""
<div class="jf-nav">
  <div class="jf-nav-logo">JobFlow</div>
  {nav_html}
  <div class="jf-nav-right">
    {stats["shortlisted"]} pending &nbsp;·&nbsp; {stats["approved"]} approved
  </div>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Stat strip
# ─────────────────────────────────────────────────────────────────────────────

st.markdown(f"""
<div class="jf-stats">
  <div class="jf-stat"><div class="jf-stat-n">{stats["total"]}</div><div class="jf-stat-l">Total</div></div>
  <div class="jf-stat"><div class="jf-stat-n">{stats["shortlisted"]}</div><div class="jf-stat-l">Review</div></div>
  <div class="jf-stat"><div class="jf-stat-n">{stats["approved"]}</div><div class="jf-stat-l">Approved</div></div>
  <div class="jf-stat"><div class="jf-stat-n">{stats["applied"]}</div><div class="jf-stat-l">Applied</div></div>
  <div class="jf-stat"><div class="jf-stat-n">{stats["skipped"]}</div><div class="jf-stat-l">Skipped</div></div>
  <div class="jf-stat"><div class="jf-stat-n">{stats["filtered"]}</div><div class="jf-stat-l">Filtered</div></div>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Calendar
# ─────────────────────────────────────────────────────────────────────────────

job_days   = get_job_days_in_month(cal_year, cal_month)
cal_weeks  = cal_module.monthcalendar(cal_year, cal_month)
today      = date.today()

# Weekday header
dow_html = "".join(f'<div class="jf-cal-dow">{d}</div>' for d in WEEKDAYS)

# Day cells
cells_html = ""
for week in cal_weeks:
    for day in week:
        if day == 0:
            cells_html += '<div class="jf-cal-d empty"></div>'
        else:
            d = date(cal_year, cal_month, day)
            classes = "jf-cal-d"
            if day in job_days: classes += " has"
            if d == selected_date: classes += " sel"
            dot = '<span class="jf-cal-dot"></span>' if d == today and d != selected_date else ""
            day_url = url(day=d)
            cells_html += f'<a href="{day_url}" class="{classes}">{day}{dot}</a>'

# Clear link
clear_html = (
    f'<a href="{url()}" class="jf-cal-clear">Clear</a>'
    if selected_date else ""
)

cal_label = f"{MONTHS[cal_month]} {cal_year}"
if selected_date:
    cal_label += f" &nbsp;·&nbsp; {selected_date.strftime('%d %b')}"

st.markdown(f"""
<div class="jf-cal">
  <div class="jf-cal-head">
    <a href="{url(month=pm_str)}" class="jf-cal-arrow">&#8592;</a>
    <span class="jf-cal-month">{cal_label}</span>
    <a href="{url(month=nm_str)}" class="jf-cal-arrow">&#8594;</a>
    {clear_html}
  </div>
  <div class="jf-cal-grid">
    {dow_html}
    {cells_html}
  </div>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Filter bar
# ─────────────────────────────────────────────────────────────────────────────

f1, f2, f3 = st.columns([3, 2, 1])
with f1:
    search = st.text_input("", placeholder="Search by title or company...", label_visibility="collapsed")
with f2:
    source_sel = st.selectbox("", ["All", "LinkedIn Jobs", "Indeed Jobs"], label_visibility="collapsed")
with f3:
    if st.button("Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Job renderer
# ─────────────────────────────────────────────────────────────────────────────

STATUS_TAG = {
    "shortlisted": ("Review",   "jf-b"),
    "filtered":    ("Filtered", "jf-r"),
    "approved":    ("Approved", "jf-g"),
    "applied":     ("Applied",  "jf-b"),
    "skipped":     ("Skipped",  "jf-gr"),
    "discovered":  ("New",      "jf-gr"),
}


def fmt_date(iso: str) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y")
    except Exception:
        return iso[:10]


def render_jobs(jobs: list[dict], show_actions: bool = True, key_base: int = 0) -> None:
    if not jobs:
        st.markdown('<div class="jf-empty">No jobs found.</div>', unsafe_allow_html=True)
        return

    st.markdown('<div class="jf-list">', unsafe_allow_html=True)
    for i, job in enumerate(jobs):
        raw: dict = {}
        try:
            raw = json.loads(job.get("raw_json", "{}"))
        except Exception:
            pass

        title    = job.get("title", "Untitled")
        company  = job.get("company", "—")
        url_job  = job.get("url", "")
        status   = job.get("status", "discovered")
        score    = float(job.get("final_score") or job.get("score") or 0)
        pct      = int(round(score * 100))
        location = raw.get("location", "") or "—"
        seen     = fmt_date(job.get("first_seen_at", ""))
        is_easy  = bool(job.get("is_direct_apply", 0))
        fp       = job.get("fingerprint", "")
        wm       = job.get("work_mode", "")
        source   = job.get("source", "")

        stag, scls = STATUS_TAG.get(status, (status.upper(), "jf-gr"))
        tags = f'<span class="jf-tag {scls}">{stag}</span>'
        if wm == "remote":
            tags += ' <span class="jf-tag jf-g">Remote</span>'
        if is_easy:
            tags += ' <span class="jf-tag jf-b">Easy Apply</span>'

        st.markdown(f"""
<div class="jf-row">
  <div class="jf-row-l">
    <div class="jf-title">{title}</div>
    <div class="jf-sub">{company} &nbsp;&middot;&nbsp; {location} &nbsp;&middot;&nbsp; {source}</div>
    <div class="jf-tags">{tags}</div>
  </div>
  <div class="jf-row-r">
    <div class="jf-score">{pct}%</div>
    <div>{seen}</div>
  </div>
</div>
""", unsafe_allow_html=True)

        if show_actions:
            k = f"{key_base}_{i}_{fp[:8]}"
            c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 5])
            with c1:
                if status not in ("approved", "applied"):
                    if st.button("Approve", key=f"a_{k}"):
                        set_status(fp, "approved"); st.rerun()
            with c2:
                if status != "skipped":
                    if st.button("Skip", key=f"s_{k}"):
                        set_status(fp, "skipped"); st.rerun()
            with c3:
                if is_easy and status != "applied":
                    if st.button("Auto Apply", key=f"aa_{k}"):
                        set_status(fp, "applying"); st.rerun()
            with c4:
                if url_job:
                    st.link_button("Open", url_job)
            with c5:
                with st.expander("Description"):
                    desc = raw.get("description", "") or "No description."
                    st.caption(desc[:1500])

    st.markdown('</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Page views
# ─────────────────────────────────────────────────────────────────────────────

if active_tab == "overview":
    st.markdown('<div class="jf-section">Recent</div>', unsafe_allow_html=True)
    jobs = load_jobs(day_filter=selected_date, search=search, source=source_sel, limit=30)
    render_jobs(jobs, show_actions=True, key_base=0)

elif active_tab == "review":
    st.markdown('<div class="jf-section">Pending Review</div>', unsafe_allow_html=True)
    jobs = load_jobs(status="shortlisted", day_filter=selected_date, search=search, source=source_sel)
    if jobs:
        b1, b2, _ = st.columns([1, 1, 6])
        with b1:
            if st.button("Approve All"):
                for j in jobs: set_status(j["fingerprint"], "approved")
                st.rerun()
        with b2:
            if st.button("Skip All"):
                for j in jobs: set_status(j["fingerprint"], "skipped")
                st.rerun()
    render_jobs(jobs, show_actions=True, key_base=1000)

elif active_tab == "approved":
    st.markdown('<div class="jf-section">Approved</div>', unsafe_allow_html=True)
    jobs = load_jobs(status="approved", day_filter=selected_date, search=search, source=source_sel)
    render_jobs(jobs, show_actions=True, key_base=2000)

elif active_tab == "filtered":
    st.markdown('<div class="jf-section">Filtered Out</div>', unsafe_allow_html=True)
    jobs = load_jobs(status="filtered", day_filter=selected_date, search=search, source=source_sel, limit=200)
    render_jobs(jobs, show_actions=False, key_base=3000)

elif active_tab == "all":
    status_tabs = st.tabs(["All","New","Review","Approved","Applied","Skipped","Filtered"])
    sf_list     = [None,"discovered","shortlisted","approved","applied","skipped","filtered"]
    for t, sf in zip(status_tabs, sf_list):
        with t:
            jobs = load_jobs(status=sf, day_filter=selected_date,
                             search=search, source=source_sel, limit=200)
            render_jobs(jobs, show_actions=(sf != "filtered"),
                        key_base=4000 + (sf_list.index(sf)) * 500)
