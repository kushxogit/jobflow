from __future__ import annotations

import argparse
import json
from pathlib import Path
from dataclasses import asdict

from .config import load_app_config
from .pipeline import JobFlowPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobflow", description="Local job discovery and review pipeline")
    parser.add_argument("--root", default=".", help="Project root directory")
    subparsers = parser.add_subparsers(dest="command", required=False)

    run_parser = subparsers.add_parser("run", help="Run the pipeline once")
    run_parser.add_argument("--dry-run", action="store_true", help="Force dry-run integrations")
    run_parser.add_argument(
        "--all",
        action="store_true",
        help="Skip site selection prompt and run all enabled sources (useful for scheduling)",
    )

    subparsers.add_parser("doctor", help="Validate config and print a short report")
    subparsers.add_parser("poll", help="Poll Telegram for review callbacks once")

    login_parser = subparsers.add_parser(
        "login",
        help="Interactive login — opens each job site and waits for you to log in before crawling",
    )
    login_parser.add_argument(
        "--sites",
        nargs="*",
        help="Specific site kinds to log into (e.g. linkedin_playwright naukri_playwright). Defaults to all enabled playwright sources.",
    )

    packet_parser = subparsers.add_parser("build-packet", help="Build one tailored packet from a stored fingerprint")
    packet_parser.add_argument("fingerprint", help="Job fingerprint from the SQLite store")

    # Daemon — background scheduler
    daemon_parser = subparsers.add_parser(
        "daemon",
        help="Run the pipeline on a recurring schedule in the background",
    )
    daemon_parser.add_argument(
        "--hours", type=float, default=6.0,
        help="Interval between pipeline runs in hours (default: 6)",
    )
    daemon_parser.add_argument(
        "--poll-seconds", type=int, default=30,
        help="Interval between Telegram polls in seconds (default: 30)",
    )
    daemon_parser.add_argument("--dry-run", action="store_true", help="Force dry-run integrations")

    # Dashboard — web UI
    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help="Launch the Streamlit web dashboard",
    )
    dashboard_parser.add_argument(
        "--port", type=int, default=8501,
        help="Port for the Streamlit server (default: 8501)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_app_config(args.root)
    if getattr(args, "dry_run", False):
        config.telegram_dry_run = True
        config.notion_dry_run = True

    command = args.command or "run"

    if command == "login":
        return _run_login_flow(config, getattr(args, "sites", None))

    if command == "daemon":
        from .daemon import run_daemon
        run_daemon(
            root_dir=args.root,
            interval_hours=args.hours,
            dry_run=getattr(args, "dry_run", False),
            poll_interval_seconds=args.poll_seconds,
        )
        return 0

    if command == "dashboard":
        return _run_dashboard(config, getattr(args, "port", 8501))

    pipeline = JobFlowPipeline(config)

    if command == "doctor":
        print(json.dumps(_doctor_report(config), indent=2))
        return 0
    if command == "poll":
        result = _poll_once(pipeline)
        print(json.dumps(result, indent=2, default=str))
        return 0
    if command == "build-packet":
        job = pipeline.store.load_job(args.fingerprint)
        if job is None:
            print(json.dumps({"ok": False, "reason": "job_not_found"}, indent=2))
            return 1
        score = pipeline.scorer.score(job)
        packet = pipeline._build_packet(score)
        pipeline._write_packet(packet)
        print(json.dumps({"ok": True, "job": job.title, "packet_generated_at": packet.generated_at}, indent=2))
        return 0

    result = pipeline.run(site_filter=_pick_sites(pipeline, args))
    print(
        json.dumps(
            {
                "summary": asdict(result.summary),
                "approved_packets": len(result.approved_packets),
            },
            indent=2,
            default=str,
        )
    )
    return 0


def _run_dashboard(config, port: int = 8501) -> int:
    """Launch the Streamlit dashboard."""
    import subprocess
    import sys

    dashboard_path = config.root_dir / "dashboard.py"
    if not dashboard_path.exists():
        print(f"Dashboard file not found at {dashboard_path}")
        return 1

    print(f"\n{'='*55}")
    print(f"  JobFlow Dashboard")
    print(f"{'='*55}")
    print(f"  Starting on http://localhost:{port}")
    print(f"  Press Ctrl+C to stop")
    print(f"{'='*55}\n")

    try:
        subprocess.run(
            [
                sys.executable, "-m", "streamlit", "run",
                str(dashboard_path),
                "--server.port", str(port),
                "--server.headless", "true",
                "--browser.gatherUsageStats", "false",
            ],
            cwd=str(config.root_dir),
        )
    except KeyboardInterrupt:
        print("\n[Dashboard] Shutting down.")
    return 0


def _run_login_flow(config, requested_sites: list[str] | None) -> int:
    from .config import load_source_specs
    from .browser_sources import LoginManager

    all_specs = load_source_specs(config.sources_path)

    # Only playwright sources that actually need a login
    playwright_kinds = {
        "linkedin_playwright",
        "naukri_playwright",
        "indeed_playwright",
        "wellfound_playwright",
    }

    # Gather enabled playwright sources from config
    candidates = [
        spec for spec in all_specs
        if spec.kind.lower() in playwright_kinds
    ]

    if not candidates:
        print("No Playwright sources are configured in sources.yaml.")
        return 0

    # If user specified --sites, filter to those
    if requested_sites:
        candidates = [s for s in candidates if s.kind.lower() in {r.lower() for r in requested_sites}]

    if not candidates:
        print("None of the requested sites matched any enabled source.")
        return 1

    # ── Interactive site selection ──────────────────────────────────────────
    print("\n" + "═" * 55)
    print("  JobFlow — Manual Login Setup")
    print("═" * 55)
    print("  The browser will open for each site.")
    print("  Log in normally, then come back here and press ENTER.")
    print("  Your session will be saved — you only do this once.\n")

    print("  Sites available to log into:\n")
    for i, spec in enumerate(candidates, 1):
        print(f"    [{i}] {spec.name}  ({spec.kind})")

    print(f"\n  Enter numbers to log into (e.g. 1,2,3)  or press ENTER for all: ", end="", flush=True)
    raw = input().strip()

    if raw == "":
        selected = candidates
    else:
        try:
            indices = [int(x.strip()) - 1 for x in raw.split(",")]
            selected = [candidates[i] for i in indices if 0 <= i < len(candidates)]
        except (ValueError, IndexError):
            print("  Invalid selection. Please run 'python -m jobflow login' again.")
            return 1

    if not selected:
        print("  No sites selected. Exiting.")
        return 0

    # ── Run the login flow ──────────────────────────────────────────────────
    manager = LoginManager(config)
    manager.login_all(selected)

    print("\n" + "═" * 55)
    print("  All sessions saved! You can now run:")
    print("  python -m jobflow run")
    print("═" * 55 + "\n")
    return 0


def _doctor_report(config) -> dict[str, object]:
    return {
        "root": str(config.root_dir),
        "profile_exists": config.profile_path.exists(),
        "sources_exists": config.sources_path.exists(),
        "db_path": str(config.db_path),
        "output_dir": str(config.output_dir),
        "telegram_dry_run": config.telegram_dry_run,
        "notion_dry_run": config.notion_dry_run,
        "llm_dry_run": config.llm_dry_run,
    }


def _poll_once(pipeline: JobFlowPipeline) -> dict[str, object]:
    updates = pipeline.telegram.get_updates()
    processed = []
    for update in updates:
        callback = update.get("callback_query") or {}
        callback_id = str(callback.get("id", ""))
        data = str(callback.get("data", ""))
        if ":" not in data:
            continue
        action, fingerprint = data.split(":", 1)
        processed.append(pipeline.process_review_callback(action, fingerprint))
        if callback_id:
            pipeline.telegram.answer_callback_query(callback_id, text=f"{action.title()} saved")
    return {"polled": len(updates), "processed": processed}


def _pick_sites(pipeline: JobFlowPipeline, args) -> set[str] | None:
    """
    Show an interactive site selection menu before `run`.
    Returns a set of source names to crawl, or None (= all enabled sources).
    Pass --all to skip the prompt entirely.
    """
    if getattr(args, "all", False):
        return None  # Run everything

    from .config import load_source_specs
    all_specs = load_source_specs(pipeline.config.sources_path)
    enabled = [s for s in all_specs if s.enabled]

    if not enabled:
        print("No enabled sources found in sources.yaml.")
        return None

    print("\n" + "=" * 55)
    print("  JobFlow — Which sites to crawl?")
    print("=" * 55)
    for i, spec in enumerate(enabled, 1):
        print(f"    [{i}] {spec.name}")
    print("\n  Enter numbers (e.g. 1,3) or press ENTER to run all: ", end="", flush=True)

    raw = input().strip()

    if raw == "":
        return None  # All

    try:
        indices = [int(x.strip()) - 1 for x in raw.split(",")]
        selected = {enabled[i].name for i in indices if 0 <= i < len(enabled)}
        if not selected:
            print("  No valid selection — running all sources.")
            return None
        print(f"  Running: {', '.join(sorted(selected))}\n")
        return selected
    except (ValueError, IndexError):
        print("  Invalid input — running all sources.")
        return None
