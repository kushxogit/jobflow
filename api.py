from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sqlite3
from datetime import datetime, timezone, date
import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
DB_PATH = ROOT_DIR / "data" / "jobflow.db"

app = FastAPI(title="JobFlow API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow local Vite frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_conn():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/api/stats")
def get_stats():
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

@app.get("/api/calendar")
def get_calendar(year: int, month: int):
    if not DB_PATH.exists():
        return {"days": []}
    conn = get_conn()
    try:
        prefix = f"{year}-{month:02d}"
        rows = conn.execute(
            "SELECT first_seen_at FROM seen_jobs WHERE first_seen_at LIKE ?",
            (f"{prefix}%",)
        ).fetchall()
        days = set()
        for row in rows:
            try:
                dt = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                days.add(dt.day)
            except Exception:
                pass
        return {"days": list(days)}
    finally:
        conn.close()

@app.get("/api/jobs")
def get_jobs(
    status: Optional[str] = None,
    day: Optional[str] = None,
    search: Optional[str] = None,
    source: Optional[str] = "All",
    limit: int = 500
):
    if not DB_PATH.exists():
        return {"jobs": []}
    conn = get_conn()
    try:
        clauses = []
        params = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if day:
            clauses.append("first_seen_at LIKE ?")
            params.append(f"{day}%")
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
    if source and source != "All":
        jobs = [j for j in jobs if source.lower() in j.get("source","").lower()]
        
    return {"jobs": jobs}

class StatusUpdate(BaseModel):
    status: str

@app.post("/api/jobs/{fingerprint}/status")
def update_status(fingerprint: str, payload: StatusUpdate):
    if not DB_PATH.exists():
        raise HTTPException(status_code=404, detail="DB not found")
    conn = get_conn()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE seen_jobs SET status=?, last_seen_at=? WHERE fingerprint=?",
            (payload.status, now, fingerprint)
        )
        conn.commit()
        return {"success": True, "status": payload.status}
    finally:
        conn.close()
