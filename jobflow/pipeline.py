from __future__ import annotations

from dataclasses import dataclass
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import AppConfig, load_profile, load_source_specs
from .models import ApplicationPacket, JobListing, JobScore, PipelineSummary, Profile
from .notion import NotionClient
from .scoring import LaneReranker, RelevanceScorer
from .sources import create_source
from .store import JobStore
from .tailor import TailorEngine, compile_docx_resume, compile_pdf_resume
from .telegram import ReviewQueue, TelegramClient
from .utils import utc_now_iso, write_jsonl


@dataclass(slots=True)
class PipelineRunResult:
    summary: PipelineSummary
    jobs: list[JobScore]
    approved_packets: list[ApplicationPacket]


class JobFlowPipeline:
    def __init__(self, config: AppConfig):
        self.config = config
        self.store = JobStore(config.db_path)
        self.profile = load_profile(config.profile_path)
        self.source_specs = load_source_specs(config.sources_path)
        self.telegram = TelegramClient(
            config.telegram_bot_token,
            config.telegram_chat_id,
            dry_run=config.telegram_dry_run,
            outbox_path=config.output_dir / "telegram_outbox.jsonl",
        )
        self.notion = NotionClient(
            config.notion_api_key,
            config.notion_database_id,
            dry_run=config.notion_dry_run,
            outbox_path=config.output_dir / "notion_outbox.jsonl",
        )
        self.review_queue = ReviewQueue(self.telegram)
        self.scorer = RelevanceScorer(self.profile, threshold=config.scoring_threshold)
        self.tailor = TailorEngine(config, self.profile)

    def discover_jobs(self, site_filter: set[str] | None = None) -> list[JobListing]:
        jobs: list[JobListing] = []
        for spec in self.source_specs:
            if not spec.enabled:
                continue
            if site_filter is not None and spec.name not in site_filter:
                continue
            source = create_source(spec, self.config.root_dir, self.config)
            try:
                jobs.extend(source.fetch_jobs())
            except Exception as exc:
                self._log_event("source_error", {"source": spec.name, "error": str(exc)})
        return jobs

    def run(self, site_filter: set[str] | None = None) -> PipelineRunResult:
        discovered = self.discover_jobs(site_filter=site_filter)
        new_jobs = [job for job in discovered if not self.store.has_seen(job)]

        # Record all new jobs in SQLite first
        for job in new_jobs:
            self.store.record_job(job, status="discovered")

        # Score all new jobs
        scoring_result = self.scorer.score_many(new_jobs)

        # Persist telemetry for every scored job
        for score in scoring_result.scores:
            try:
                self.store.record_telemetry(score.job, score)
            except Exception:
                pass

        # --- Feature 3: Log EVERY new job to Notion immediately with its status ---
        for score in scoring_result.scores:
            status = "Filtered" if score.rejected else "Shortlisted"
            try:
                notion_page_id = self.notion.log_job(score.job, score.score, status=status)
                if notion_page_id:
                    self.store.update_notion_page_id(score.job, notion_page_id)
            except Exception as notion_exc:
                self._log_event("notion_log_error", {"job": score.job.title, "error": str(notion_exc)})

        # Determine shortlist using lane-based reranker
        reranker = LaneReranker(
            remote_quota=self.config.remote_review_quota,
            hybrid_quota=self.config.hybrid_review_quota,
        )
        shortlisted = reranker.rerank(scoring_result.scores)
        shortlisted = shortlisted[: self.config.review_limit]
        approved_packets: list[ApplicationPacket] = []
        approved_count = 0
        skipped_count = 0

        # Stamp fingerprints into raw_payload so Telegram callbacks resolve correctly
        if shortlisted:
            for score in shortlisted:
                fingerprint = self.store.fingerprint_for(score.job)
                score.job.raw_payload = {**score.job.raw_payload, "fingerprint": fingerprint}

        # Update filtered jobs status in SQLite
        for score in scoring_result.scores:
            if score.rejected:
                reason = ", ".join(score.rejection_reasons) if score.rejection_reasons else "below score threshold"
                self.store.update_status(score.job, "filtered", reason)

        # --- Feature 5: Send consolidated daily digest BEFORE individual cards ---
        filtered_count = len(scoring_result.scores) - len(shortlisted)
        self.telegram.send_daily_digest(
            shortlisted=shortlisted,
            discovered=len(discovered),
            filtered=filtered_count,
        )

        # Send individual Approve/Skip review cards
        if shortlisted:
            self.review_queue.dispatch(shortlisted)

        summary = PipelineSummary(
            discovered=len(discovered),
            deduped=len(new_jobs),
            scored=len(scoring_result.scores),
            shortlisted=len(shortlisted),
            approved=approved_count,
            skipped=skipped_count,
            sent_to_telegram=len(shortlisted) + 1,
            logged_to_notion=len(scoring_result.scores),
        )
        self._log_event(
            "run_complete",
            {
                "timestamp": utc_now_iso(),
                "summary": asdict(summary),
            },
        )
        return PipelineRunResult(summary=summary, jobs=scoring_result.scores, approved_packets=approved_packets)

    def process_review_callback(self, action: str, fingerprint: str) -> dict[str, object]:
        job = self.store.load_job(fingerprint)
        if job is None:
            return {"ok": False, "reason": "job_not_found"}

        # Retrieve the Notion page ID stored at discovery time
        notion_page_id = self.store.get_notion_page_id_by_fingerprint(fingerprint)

        if action == "skip":
            self.store.update_status(job, "skipped", "skipped from Telegram")
            self.store.mark_review_action(job, action)
            # --- Feature 3: Update Notion status on skip ---
            if notion_page_id:
                try:
                    self.notion.update_status(notion_page_id, "Skipped")
                except Exception:
                    pass
            return {"ok": True, "action": action}

        if action == "approve":
            score = self.scorer.score(job)
            packet = self._build_packet(score)

            # --- Feature 1: Write Markdown + DOCX + PDF on approval ---
            self._write_packet(packet)

            # --- Feature 3: Update Notion page to Approved with full packet ---
            try:
                notion_result = self.notion.create_job_page(packet)
                new_page_id = str(notion_result.get("id", notion_page_id))
                # Update the original "Shortlisted" page if we have its ID
                if notion_page_id:
                    self.notion.update_status(notion_page_id, "Approved")
            except Exception as notion_exc:
                notion_result = {"ok": False, "error": str(notion_exc)}

            self.store.update_status(job, "approved", "approved from Telegram")
            self.store.mark_review_action(job, action)
            return {"ok": True, "action": action, "notion": notion_result}

        return {"ok": False, "reason": "unknown_action"}

    def _build_packet(self, score: JobScore) -> ApplicationPacket:
        packet = self.tailor.build_packet(score)
        packet.generated_at = utc_now_iso()
        return packet

    def _write_packet(self, packet: ApplicationPacket) -> None:
        """Write the full application packet: Markdown + DOCX + PDF."""
        safe_company = "".join(ch for ch in packet.job.company if ch.isalnum() or ch in {"-", "_", " "}).strip() or "company"
        safe_title = "".join(ch for ch in packet.job.title if ch.isalnum() or ch in {"-", "_", " "}).strip() or "role"
        base_name = f"{safe_company} - {safe_title}"
        packets_dir = self.config.output_dir / "packets"
        packets_dir.mkdir(parents=True, exist_ok=True)

        # Markdown (always written)
        md_path = packets_dir / f"{base_name}.md"
        md_path.write_text(packet.to_markdown(), encoding="utf-8")

        # --- Feature 1: DOCX resume ---
        base_docx = None
        resume_path = self.profile.resume_base_path or self.profile.resume_path
        if resume_path:
            candidate = Path(resume_path)
            if not candidate.is_absolute():
                candidate = self.config.root_dir / candidate
            if candidate.exists() and candidate.suffix.lower() == ".docx":
                base_docx = candidate
        try:
            compile_docx_resume(packet, packets_dir / f"{base_name}.docx", base_docx_path=base_docx)
        except Exception as docx_exc:
            self._log_event("docx_error", {"job": packet.job.title, "error": str(docx_exc)})

        # --- Feature 1: PDF resume ---
        try:
            compile_pdf_resume(packet, packets_dir / f"{base_name}.pdf")
        except Exception as pdf_exc:
            self._log_event("pdf_error", {"job": packet.job.title, "error": str(pdf_exc)})

    def _log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        write_jsonl(self.config.output_dir / "pipeline_events.jsonl", {"type": event_type, "payload": payload})
