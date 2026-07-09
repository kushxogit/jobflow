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
/* ── Font Import ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

* {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
}

/* ── Hide Streamlit chrome ── */
header[data-testid="stHeader"],
#MainMenu, footer,
.stDeployButton,
[data-testid="manage-app-button"],
section[data-testid="stSidebar"] { display: none !important; }

/* ── Base ── */
html, body, .stApp { 
    background: #0B0F19; /* Rich dark slate */
    color: #F3F4F6; 
}
.main .block-container {
    padding-top: 100px !important;
    padding-left: 5% !important;
    padding-right: 5% !important;
    max-width: 1400px !important;
}

/* ── Fixed top nav (Glassmorphism) ── */
.jf-nav {
    position: fixed; top: 0; left: 0; right: 0; z-index: 9999;
    background: rgba(11, 15, 25, 0.75); 
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    height: 64px;
    display: flex; align-items: stretch;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1);
}
.jf-nav-logo {
    font-size: 0.9rem; font-weight: 700; letter-spacing: 0.15em;
    text-transform: uppercase; 
    background: linear-gradient(135deg, #60A5FA, #A78BFA);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    padding: 0 32px; display: flex; align-items: center;
    border-right: 1px solid rgba(255,255,255,0.08); white-space: nowrap;
}
.jf-nav a {
    color: #9CA3AF; text-decoration: none;
    font-size: 0.75rem; font-weight: 600; letter-spacing: 0.08em;
    text-transform: uppercase; padding: 0 24px;
    display: flex; align-items: center;
    transition: color 0.2s, background 0.2s, border-color 0.2s;
    border-bottom: 2px solid transparent;
}
.jf-nav a:hover { color: #F3F4F6; background: rgba(255,255,255,0.03); text-decoration: none; }
.jf-nav a.active { color: #60A5FA; border-bottom-color: #60A5FA; }
.jf-nav-right {
    margin-left: auto; display: flex; align-items: center;
    padding: 0 32px; font-size: 0.75rem; color: #9CA3AF;
    white-space: nowrap; font-weight: 500;
}

/* ── Stat strip ── */
.jf-stats {
    display: flex; gap: 16px; margin-bottom: 32px;
}
.jf-stat {
    flex: 1; padding: 20px; 
    background: rgba(30, 41, 59, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 16px;
    text-align: center;
    backdrop-filter: blur(12px);
    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    transition: transform 0.2s ease, background 0.2s ease, border-color 0.2s ease;
}
.jf-stat:hover { 
    transform: translateY(-4px); 
    background: rgba(30, 41, 59, 0.8);
    border-color: rgba(96, 165, 250, 0.4);
}
.jf-stat-n { font-size: 1.8rem; font-weight: 700; color: #F3F4F6; line-height: 1; }
.jf-stat-l {
    font-size: 0.65rem; font-weight: 600; letter-spacing: 0.15em;
    text-transform: uppercase; color: #9CA3AF; margin-top: 6px;
}

/* ── Calendar ── */
.jf-cal {
    background: rgba(30, 41, 59, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 16px;
    padding: 24px 32px; margin-bottom: 32px;
    backdrop-filter: blur(12px);
    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
}
.jf-cal-head {
    display: flex; align-items: center; gap: 16px; margin-bottom: 20px;
}
.jf-cal-month {
    font-size: 0.85rem; font-weight: 700; letter-spacing: 0.12em;
    text-transform: uppercase; color: #F3F4F6;
}
.jf-cal-arrow {
    color: #9CA3AF; text-decoration: none;
    font-size: 0.9rem; font-weight: 700;
    padding: 4px 12px; 
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    background: rgba(255,255,255,0.03);
    line-height: 1.4; transition: all 0.2s;
}
.jf-cal-arrow:hover { background: rgba(255,255,255,0.1); color: #F3F4F6; text-decoration: none; }
.jf-cal-clear {
    margin-left: auto; font-size: 0.7rem; color: #EF4444;
    text-decoration: none; letter-spacing: 0.08em; text-transform: uppercase;
    font-weight: 600; padding: 4px 12px; border-radius: 8px;
    background: rgba(239, 68, 68, 0.1); transition: all 0.2s;
}
.jf-cal-clear:hover { background: rgba(239, 68, 68, 0.2); color: #FCA5A5; text-decoration: none; }
.jf-cal-grid {
    display: grid; grid-template-columns: repeat(7, 1fr); gap: 6px;
}
.jf-cal-dow {
    font-size: 0.65rem; font-weight: 700; letter-spacing: 0.15em;
    text-transform: uppercase; color: #6B7280; text-align: center;
    padding: 4px 0 12px;
}
.jf-cal-d {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    padding: 10px 0; font-size: 0.85rem; font-weight: 500;
    text-decoration: none; color: #6B7280;
    border-radius: 10px; transition: all 0.2s;
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid transparent;
}
.jf-cal-d:hover { background: rgba(255, 255, 255, 0.05); text-decoration: none; color: #F3F4F6; }
.jf-cal-d.has  { color: #F3F4F6; background: rgba(59, 130, 246, 0.15); font-weight: 600; border: 1px solid rgba(59, 130, 246, 0.3); }
.jf-cal-d.has:hover { background: rgba(59, 130, 246, 0.25); text-decoration: none; }
.jf-cal-d.sel  { background: linear-gradient(135deg, #3B82F6, #8B5CF6) !important; color: #FFF !important; font-weight: 700; border: none; box-shadow: 0 4px 10px rgba(59, 130, 246, 0.4); }
.jf-cal-d.sel:hover { opacity: 0.9; text-decoration: none; }
.jf-cal-d.empty { visibility: hidden; }
.jf-cal-dot {
    display: block; width: 4px; height: 4px; background: #60A5FA;
    border-radius: 50%; margin-top: 4px; 
}

/* ── Job rows ── */
.jf-list { display: flex; flex-direction: column; gap: 16px; margin-top: 8px; }
.jf-row {
    display: flex; justify-content: space-between; align-items: flex-start;
    gap: 24px; padding: 20px 24px; 
    background: rgba(30, 41, 59, 0.4);
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 16px;
    backdrop-filter: blur(12px);
    transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}
.jf-row:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.2);
    border-color: rgba(255,255,255,0.15);
}
.jf-row-l { flex: 1; min-width: 0; }
.jf-title {
    font-size: 1.05rem; font-weight: 600; color: #F3F4F6;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    margin-bottom: 6px;
}
.jf-sub { font-size: 0.8rem; color: #9CA3AF; margin-bottom: 12px; font-weight: 500; }
.jf-tags { display: flex; gap: 8px; flex-wrap: wrap; }
.jf-tag {
    font-size: 0.65rem; font-weight: 700; letter-spacing: 0.12em;
    text-transform: uppercase; padding: 4px 10px;
    border-radius: 6px;
}
.jf-g  { background: rgba(16, 185, 129, 0.15); color: #34D399; border: 1px solid rgba(16, 185, 129, 0.3); }
.jf-b  { background: rgba(59, 130, 246, 0.15); color: #60A5FA; border: 1px solid rgba(59, 130, 246, 0.3); }
.jf-r  { background: rgba(239, 68, 68, 0.15); color: #F87171; border: 1px solid rgba(239, 68, 68, 0.3); }
.jf-gr { background: rgba(156, 163, 175, 0.15); color: #9CA3AF; border: 1px solid rgba(156, 163, 175, 0.3); }
.jf-row-r {
    text-align: right; flex-shrink: 0;
    font-size: 0.75rem; color: #9CA3AF; line-height: 1.8;
}
.jf-score { font-size: 1.3rem; font-weight: 700; color: #60A5FA; }
.jf-empty { font-size: 0.9rem; color: #6B7280; padding: 40px 0; text-align: center; font-weight: 500; }

/* ── Streamlit buttons — robust overrides ── */
.stButton > button {
    background: rgba(255, 255, 255, 0.05) !important;
    color: #F3F4F6 !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    border-radius: 8px !important;
    font-size: 0.75rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
    padding: 6px 16px !important;
    line-height: 1.5 !important;
    min-height: 34px !important;
    box-shadow: none !important;
    transition: all 0.2s !important;
}
.stButton > button:hover,
.stButton > button:active {
    background: rgba(255, 255, 255, 0.15) !important;
    color: #FFF !important;
    border-color: rgba(255, 255, 255, 0.3) !important;
    transform: translateY(-1px) !important;
}
.stButton > button:focus:not(:active) {
    box-shadow: 0 0 0 2px rgba(96, 165, 250, 0.5) !important;
    outline: none !important;
}

/* ── Link button ── */
a[data-testid="stLinkButton-link"] {
    background: linear-gradient(135deg, #3B82F6, #8B5CF6) !important;
    color: #FFF !important;
    border: none !important;
    border-radius: 8px !important;
    font-size: 0.75rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
    padding: 6px 16px !important;
    line-height: 1.5 !important;
    text-decoration: none !important;
    display: inline-flex !important;
    align-items: center !important;
    transition: all 0.2s !important;
    box-shadow: 0 4px 10px rgba(59, 130, 246, 0.3) !important;
}
a[data-testid="stLinkButton-link"]:hover {
    opacity: 0.9 !important;
    transform: translateY(-1px) !important;
    text-decoration: none !important;
    box-shadow: 0 6px 15px rgba(59, 130, 246, 0.4) !important;
}

/* ── Inputs ── */
.stTextInput input, .stSelectbox > div > div {
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    border-radius: 8px !important;
    background: rgba(15, 23, 42, 0.6) !important;
    color: #F3F4F6 !important;
    font-size: 0.85rem !important;
    padding: 10px 16px !important;
    box-shadow: inset 0 2px 4px rgba(0,0,0,0.1) !important;
    transition: border-color 0.2s, box-shadow 0.2s !important;
}
.stTextInput input:focus, .stSelectbox > div > div:focus-within {
    border-color: #60A5FA !important;
    box-shadow: 0 0 0 2px rgba(96, 165, 250, 0.3), inset 0 2px 4px rgba(0,0,0,0.1) !important;
}
.stSelectbox * {
    color: #F3F4F6 !important;
    background: #0B0F19 !important;
}

/* ── Expander ── */
details[data-testid="stExpander"] {
    background: rgba(30, 41, 59, 0.4) !important;
    border: 1px solid rgba(255, 255, 255, 0.06) !important;
    border-radius: 12px !important;
    overflow: hidden;
}
details[data-testid="stExpander"] summary {
    padding: 12px 16px !important;
    font-size: 0.75rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.1em !important;
    text-transform: uppercase !important;
    background: rgba(255, 255, 255, 0.02) !important;
    color: #9CA3AF !important;
    transition: background 0.2s, color 0.2s !important;
}
details[data-testid="stExpander"] summary:hover { 
    background: rgba(255, 255, 255, 0.05) !important; 
    color: #F3F4F6 !important;
}
details[data-testid="stExpander"] .streamlit-expanderContent {
    color: #D1D5DB !important;
    font-size: 0.85rem !important;
    line-height: 1.6 !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1) !important;
    gap: 0 !important;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    border-radius: 0 !important;
    border: none !important;
    font-size: 0.75rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
    color: #6B7280 !important;
    padding: 12px 24px !important;
    transition: color 0.2s !important;
}
.stTabs [data-baseweb="tab"]:hover {
    color: #9CA3AF !important;
}
.stTabs [aria-selected="true"] {
    color: #60A5FA !important;
    border-bottom: 2px solid #60A5FA !important;
}

/* ── Section labels ── */
.jf-section {
    font-size: 0.75rem; font-weight: 700; letter-spacing: 0.15em;
    text-transform: uppercase; color: #9CA3AF; margin-bottom: 20px; margin-top: 10px;
    display: flex; align-items: center;
}
.jf-section::after {
    content: ''; flex: 1; height: 1px; background: rgba(255,255,255,0.08); margin-left: 16px;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: #0B0F19; }
::-webkit-scrollbar-thumb { background: #374151; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #4B5563; }
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
