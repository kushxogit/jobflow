from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request

from .models import ApplicationPacket, JobListing, JobScore
from .utils import ensure_dir, utc_now_iso, write_jsonl


@dataclass(slots=True)
class NotionOutbox:
    path: Path

    def send(self, payload: dict[str, Any]) -> None:
        write_jsonl(self.path, payload)


class NotionClient:
    def __init__(
        self,
        api_key: str,
        database_id: str,
        dry_run: bool = True,
        outbox_path: str | Path | None = None,
    ):
        self.api_key = api_key
        self.database_id = database_id
        self.dry_run = dry_run or not api_key or not database_id
        self.outbox = NotionOutbox(Path(outbox_path)) if outbox_path else None
        if self.outbox:
            ensure_dir(self.outbox.path.parent)

    def log_job(self, job: JobListing, score: float, status: str = "Discovered") -> str:
        """Log any job (discovered, filtered, shortlisted) to Notion. Returns Notion page_id or '' in dry-run."""
        payload = self._build_job_payload(job, score, status)
        if self.dry_run:
            if self.outbox:
                self.outbox.send({"kind": "notion_page", "status": status, "payload": payload})
            return f"dry_run_{job.source}_{job.title[:20]}"
        try:
            result = self._post("pages", payload)
            return str(result.get("id", ""))
        except Exception as exc:
            print(f"[Notion] log_job error: {exc}")
            return ""

    def create_job_page(self, packet: ApplicationPacket) -> dict[str, Any]:
        """Create a full application packet page in Notion for an approved job."""
        payload = self._build_packet_payload(packet)
        if self.dry_run:
            if self.outbox:
                self.outbox.send({"kind": "notion_page", "payload": payload})
            return {"ok": True, "dry_run": True, "id": f"dry_run_{packet.job.title[:20]}", "payload": payload}
        try:
            result = self._post("pages", payload)
            return result
        except Exception as exc:
            print(f"[Notion] create_job_page error: {exc}")
            return {"ok": False, "error": str(exc)}

    def update_status(self, page_id: str, status: str) -> dict[str, Any]:
        """Update the Status property of an existing Notion page."""
        if not page_id or page_id.startswith("dry_run_"):
            if self.outbox:
                self.outbox.send({"kind": "notion_update", "page_id": page_id, "status": status})
            return {"ok": True, "dry_run": True}
        payload = {"properties": {"Status": {"select": {"name": status}}}}
        if self.dry_run:
            if self.outbox:
                self.outbox.send({"kind": "notion_update", "page_id": page_id, "payload": payload})
            return {"ok": True, "dry_run": True, "payload": payload}
        try:
            return self._patch(f"pages/{page_id}", payload)
        except Exception as exc:
            print(f"[Notion] update_status error: {exc}")
            return {"ok": False, "error": str(exc)}

    def _build_job_payload(self, job: JobListing, score: float, status: str) -> dict[str, Any]:
        """Build a minimal Notion page payload for any job (no full packet needed)."""
        title = f"{job.title} — {job.company}"
        return {
            "parent": {"database_id": self.database_id},
            "properties": {
                "Name": {"title": [{"text": {"content": title}}]},
                "Source": {"rich_text": [{"text": {"content": job.source}}]},
                "Status": {"select": {"name": status}},
                "Score": {"number": round(score, 4)},
                "URL": {"url": job.url or "https://example.com"},
            },
            "children": [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": (
                                        f"Company: {job.company}\n"
                                        f"Location: {job.location}\n"
                                        f"Remote: {'Yes' if job.remote else 'No'}\n"
                                        f"Posted: {job.posted_at or 'Unknown'}\n"
                                        f"Score: {score:.2f}\n\n"
                                        + job.description[:1500]
                                    )
                                },
                            }
                        ]
                    },
                }
            ],
        }

    def _build_packet_payload(self, packet: ApplicationPacket) -> dict[str, Any]:
        """Build a full Notion page payload including tailored resume, cover letter, etc."""
        title = f"{packet.job.title} — {packet.job.company}"
        return {
            "parent": {"database_id": self.database_id},
            "properties": {
                "Name": {"title": [{"text": {"content": title}}]},
                "Source": {"rich_text": [{"text": {"content": packet.job.source}}]},
                "Status": {"select": {"name": "Approved"}},
                "Score": {"number": packet.score.score},
                "URL": {"url": packet.job.url or "https://example.com"},
            },
            "children": self._build_children(packet),
        }

    def _build_children(self, packet: ApplicationPacket) -> list[dict[str, Any]]:
        return [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": packet.to_markdown()[:1900]}}],
                },
            }
        ]

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", path, payload)

    def _patch(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PATCH", path, payload)

    def _request(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"https://api.notion.com/v1/{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
