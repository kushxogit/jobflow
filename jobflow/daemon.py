"""
JobFlow Daemon — Background scheduler that runs the pipeline on a
configurable interval and continuously polls Telegram for review callbacks.

Usage:
    python -m jobflow daemon --interval-hours 6
    python -m jobflow daemon --interval-hours 4 --dry-run
"""
from __future__ import annotations

import json
import signal
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import schedule

from .config import load_app_config
from .pipeline import JobFlowPipeline


_SHUTDOWN = False


def _handle_signal(signum, frame):
    global _SHUTDOWN
    print(f"\n[Daemon] Received signal {signum}. Shutting down gracefully...")
    _SHUTDOWN = True


def _run_pipeline(pipeline: JobFlowPipeline) -> None:
    """Execute one full pipeline run and log results."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n{'='*60}")
    print(f"  [Daemon] Starting pipeline run at {timestamp}")
    print(f"{'='*60}\n")
    try:
        result = pipeline.run(site_filter=None)
        summary = asdict(result.summary)
        print(f"\n[Daemon] Pipeline run complete:")
        print(f"  Discovered:  {summary['discovered']}")
        print(f"  Deduped:     {summary['deduped']}")
        print(f"  Scored:      {summary['scored']}")
        print(f"  Shortlisted: {summary['shortlisted']}")
        print(f"  Approved:    {summary['approved']}")

        # Log to file
        log_path = pipeline.config.output_dir / "daemon_runs.jsonl"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": timestamp, **summary}, default=str) + "\n")

    except Exception as exc:
        print(f"[Daemon] Pipeline run failed: {exc}")
        import traceback
        traceback.print_exc()


def _poll_telegram(pipeline: JobFlowPipeline) -> None:
    """Poll Telegram for pending review callbacks and process them."""
    try:
        updates = pipeline.telegram.get_updates()
        if not updates:
            return
        for update in updates:
            callback = update.get("callback_query") or {}
            callback_id = str(callback.get("id", ""))
            data = str(callback.get("data", ""))
            if ":" not in data:
                continue
            action, fingerprint = data.split(":", 1)
            result = pipeline.process_review_callback(action, fingerprint)
            print(f"[Daemon] Processed callback: {action} -> {result.get('ok')}")
            if callback_id:
                pipeline.telegram.answer_callback_query(
                    callback_id, text=f"{action.title()} saved"
                )
    except Exception as exc:
        # Don't crash the daemon on transient Telegram errors
        pass


def run_daemon(
    root_dir: str = ".",
    interval_hours: float = 6.0,
    dry_run: bool = False,
    poll_interval_seconds: int = 30,
) -> None:
    """
    Main daemon entry point.

    - Runs the pipeline immediately on startup.
    - Schedules subsequent runs every `interval_hours` hours.
    - Polls Telegram for review callbacks every `poll_interval_seconds` seconds.
    """
    global _SHUTDOWN

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    config = load_app_config(root_dir)
    if dry_run:
        config.telegram_dry_run = True
        config.notion_dry_run = True

    pipeline = JobFlowPipeline(config)

    print(f"\n{'='*60}")
    print(f"  JobFlow Daemon")
    print(f"{'='*60}")
    print(f"  Pipeline interval:  every {interval_hours} hours")
    print(f"  Telegram polling:   every {poll_interval_seconds} seconds")
    print(f"  Dry run:            {dry_run}")
    print(f"  Press Ctrl+C to stop")
    print(f"{'='*60}\n")

    # Run immediately on startup
    _run_pipeline(pipeline)

    # Schedule recurring runs
    if interval_hours >= 1:
        schedule.every(interval_hours).hours.do(_run_pipeline, pipeline)
    else:
        # For sub-hour intervals (e.g. 0.5 = 30 minutes)
        minutes = int(interval_hours * 60)
        schedule.every(max(minutes, 1)).minutes.do(_run_pipeline, pipeline)

    # Main loop: alternate between running scheduled jobs and polling Telegram
    last_poll = 0.0
    while not _SHUTDOWN:
        schedule.run_pending()

        now = time.time()
        if now - last_poll >= poll_interval_seconds:
            _poll_telegram(pipeline)
            last_poll = now

        time.sleep(1)  # Low CPU idle loop

    print("[Daemon] Shutdown complete.")
