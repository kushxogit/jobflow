from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Iterable
from contextlib import contextmanager

from .models import JobListing, JobScore
from .utils import ensure_dir, fingerprint_job, utc_now_iso


class JobStore:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        ensure_dir(self.path.parent)
        self._ensure_schema()

    @contextmanager
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_jobs (
                    fingerprint TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_job_id TEXT,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    url TEXT NOT NULL,
                    score REAL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'discovered',
                    notion_page_id TEXT DEFAULT '',
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    raw_json TEXT NOT NULL
                )
                """
            )
            # Migrate existing databases that don't have notion_page_id
            try:
                connection.execute("ALTER TABLE seen_jobs ADD COLUMN notion_page_id TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass  # Column already exists
            try:
                connection.execute("ALTER TABLE seen_jobs ADD COLUMN is_direct_apply INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # Column already exists
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS review_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT NOT NULL,
                    action TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            # Telemetry columns (idempotent migrations)
            _tele_cols = [
                "title_score REAL", "skill_score REAL", "freshness_score REAL",
                "work_mode_score REAL", "salary_score REAL", "experience_score REAL",
                "semantic_score REAL", "source_quality_score REAL",
                "company_velocity_score REAL", "final_score REAL",
                "work_mode TEXT", "review_bucket TEXT",
                "approved_by_user INTEGER DEFAULT 0", "skipped_by_user INTEGER DEFAULT 0",
            ]
            for col_def in _tele_cols:
                col_name = col_def.split()[0]
                try:
                    connection.execute(f"ALTER TABLE seen_jobs ADD COLUMN {col_def}")
                except sqlite3.OperationalError:
                    pass  # Already exists

    def fingerprint_for(self, job: JobListing) -> str:
        return fingerprint_job(job.source, job.title, job.company, job.url, job.description)

    def has_seen(self, job: JobListing) -> bool:
        fingerprint = self.fingerprint_for(job)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM seen_jobs WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            return row is not None

    def record_job(self, job: JobListing, score: float = 0.0, status: str = "discovered") -> str:
        fingerprint = self.fingerprint_for(job)
        now = utc_now_iso()
        payload = json.dumps(asdict(job), ensure_ascii=False, default=str)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO seen_jobs (
                    fingerprint, source, source_job_id, title, company, url, score,
                    status, notion_page_id, first_seen_at, last_seen_at, raw_json, is_direct_apply
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    score = excluded.score,
                    status = excluded.status,
                    last_seen_at = excluded.last_seen_at,
                    raw_json = excluded.raw_json,
                    is_direct_apply = excluded.is_direct_apply
                """,
                (
                    fingerprint,
                    job.source,
                    job.source_job_id,
                    job.title,
                    job.company,
                    job.url,
                    score,
                    status,
                    "",
                    now,
                    now,
                    payload,
                    1 if job.is_direct_apply else 0,
                ),
            )
        return fingerprint

    def update_status(self, job: JobListing, status: str, note: str = "") -> None:
        fingerprint = self.fingerprint_for(job)
        now = utc_now_iso()
        # Update approved_by_user / skipped_by_user counters too
        if status == "approved":
            with self._connect() as connection:
                connection.execute(
                    "UPDATE seen_jobs SET status=?, last_seen_at=?, approved_by_user=1 WHERE fingerprint=?",
                    (status, now, fingerprint),
                )
        elif status == "skipped":
            with self._connect() as connection:
                connection.execute(
                    "UPDATE seen_jobs SET status=?, last_seen_at=?, skipped_by_user=1 WHERE fingerprint=?",
                    (status, now, fingerprint),
                )
        else:
            with self._connect() as connection:
                connection.execute(
                    "UPDATE seen_jobs SET status=?, last_seen_at=? WHERE fingerprint=?",
                    (status, now, fingerprint),
                )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO review_actions (fingerprint, action, created_at, payload_json) VALUES (?, ?, ?, ?)",
                (
                    fingerprint, status, now,
                    json.dumps({"note": note}, ensure_ascii=False),
                ),
            )

    def record_telemetry(self, job: JobListing, score_obj: "JobScore") -> None:
        """Persist per-signal scores into seen_jobs row for future calibration."""
        from .scoring import detect_work_mode
        fingerprint = self.fingerprint_for(job)
        wm = detect_work_mode(job)
        signals = {s.name: s.value for s in score_obj.signals}
        # Map age to review bucket
        posted_at = job.posted_at or ""
        from datetime import date as _date
        try:
            from .scoring import _parse_date as _pd
            posted = _pd(posted_at)
            age = ((_date.today() - posted).days) if posted else None
        except Exception:
            age = None
        if age is None:
            bucket = "unknown"
        elif age <= 3:
            bucket = "0-3d"
        elif age <= 7:
            bucket = "4-7d"
        elif age <= 14:
            bucket = "8-14d"
        else:
            bucket = "15-21d"
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE seen_jobs SET
                    title_score=?, skill_score=?, freshness_score=?,
                    work_mode_score=?, salary_score=?, experience_score=?,
                    semantic_score=?, source_quality_score=?, company_velocity_score=?,
                    final_score=?, work_mode=?, review_bucket=?
                WHERE fingerprint=?
                """,
                (
                    signals.get("title", 0), signals.get("skills", 0), signals.get("freshness", 0),
                    signals.get("work_mode", 0), signals.get("salary", 0), signals.get("experience", 0),
                    signals.get("semantic", 0), signals.get("source", 0), signals.get("velocity", 0),
                    score_obj.score, wm.value, bucket,
                    fingerprint,
                ),
            )

    def update_notion_page_id(self, job: JobListing, page_id: str) -> None:
        """Store the Notion page ID so we can update it later on approve/skip."""
        fingerprint = self.fingerprint_for(job)
        with self._connect() as connection:
            connection.execute(
                "UPDATE seen_jobs SET notion_page_id = ? WHERE fingerprint = ?",
                (page_id, fingerprint),
            )

    def get_notion_page_id(self, job: JobListing) -> str:
        """Retrieve the previously stored Notion page ID for a job, or '' if not set."""
        fingerprint = self.fingerprint_for(job)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT notion_page_id FROM seen_jobs WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
        if row is None:
            return ""
        return str(row["notion_page_id"] or "")

    def get_notion_page_id_by_fingerprint(self, fingerprint: str) -> str:
        """Retrieve the Notion page ID directly by fingerprint."""
        with self._connect() as connection:
            if len(fingerprint) < 64:
                row = connection.execute(
                    "SELECT notion_page_id FROM seen_jobs WHERE fingerprint LIKE ?",
                    (f"{fingerprint}%",),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT notion_page_id FROM seen_jobs WHERE fingerprint = ?",
                    (fingerprint,),
                ).fetchone()
        if row is None:
            return ""
        return str(row["notion_page_id"] or "")

    def mark_review_action(self, job: JobListing, action: str, payload: dict[str, object] | None = None) -> None:
        fingerprint = self.fingerprint_for(job)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO review_actions (fingerprint, action, created_at, payload_json) VALUES (?, ?, ?, ?)",
                (
                    fingerprint,
                    action,
                    utc_now_iso(),
                    json.dumps(payload or {}, ensure_ascii=False, default=str),
                ),
            )

    def recent_jobs(self, limit: int = 20) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM seen_jobs ORDER BY last_seen_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def load_job(self, fingerprint: str) -> JobListing | None:
        with self._connect() as connection:
            if len(fingerprint) < 64:
                row = connection.execute(
                    "SELECT raw_json FROM seen_jobs WHERE fingerprint LIKE ?",
                    (f"{fingerprint}%",),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT raw_json FROM seen_jobs WHERE fingerprint = ?",
                    (fingerprint,),
                ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["raw_json"])
        return JobListing(
            source=str(payload.get("source", "")),
            title=str(payload.get("title", "")),
            company=str(payload.get("company", "")),
            location=str(payload.get("location", "")),
            url=str(payload.get("url", "")),
            description=str(payload.get("description", "")),
            apply_url=str(payload.get("apply_url", "")),
            source_job_id=str(payload.get("source_job_id", "")),
            posted_at=str(payload.get("posted_at", "")),
            remote=bool(payload.get("remote", False)),
            seniority=str(payload.get("seniority", "")),
            tags=[str(item) for item in payload.get("tags", [])],
            raw_payload=dict(payload.get("raw_payload", {})),
            is_direct_apply=bool(payload.get("is_direct_apply", False)),
        )

    def review_history(self, fingerprint: str) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM review_actions WHERE fingerprint = ? ORDER BY created_at DESC",
                (fingerprint,),
            ).fetchall()
        return [dict(row) for row in rows]
