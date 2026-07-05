from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.parse
import urllib.request

from .models import JobScore
from .utils import ensure_dir, write_jsonl


@dataclass(slots=True)
class TelegramOutbox:
    path: Path

    def send(self, payload: dict[str, Any]) -> None:
        write_jsonl(self.path, payload)


class TelegramClient:
    def __init__(
        self,
        token: str,
        chat_id: str,
        dry_run: bool = True,
        outbox_path: str | Path | None = None,
    ):
        self.token = token
        self.chat_id = chat_id
        self.dry_run = dry_run or not token or not chat_id
        self.outbox = TelegramOutbox(Path(outbox_path)) if outbox_path else None
        if self.outbox:
            ensure_dir(self.outbox.path.parent)

    def send_message(self, text: str, reply_markup: dict[str, Any] | None = None, parse_mode: str = "") -> dict[str, Any]:
        payload: dict[str, Any] = {"chat_id": self.chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if self.dry_run:
            if self.outbox:
                self.outbox.send({"kind": "telegram_message", "payload": payload})
            return {"ok": True, "dry_run": True, "payload": payload}
        return self._post("sendMessage", payload)

    def send_daily_digest(self, shortlisted: list[JobScore], discovered: int, filtered: int) -> dict[str, Any]:
        """Send a single consolidated digest message listing all shortlisted jobs."""
        now = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
        header = (
            f"📋 <b>JobFlow Daily Digest</b> — {now}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔍 Discovered: <b>{discovered}</b> jobs\n"
            f"❌ Filtered out: <b>{filtered}</b> jobs\n"
            f"✅ Shortlisted for review: <b>{len(shortlisted)}</b> jobs\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        lines = []
        for i, score in enumerate(shortlisted, 1):
            remote_tag = "🌐 Remote" if score.job.remote else "🏢 Office"
            line = (
                f"<b>{i}. {html.escape(score.job.title[:100])}</b>\n"
                f"   🏷 {html.escape(score.job.company[:50])} · {html.escape(score.job.location[:50])}\n"
                f"   📊 Match: {score.match_percent}%  {remote_tag}\n"
                f"   🔗 {html.escape(score.job.url[:60])}{'…' if len(score.job.url) > 60 else ''}"
            )
            if len("\n\n".join(lines)) + len(line) > 3500:
                lines.append(f"<i>...and {len(shortlisted) - i + 1} more jobs.</i>")
                break
            lines.append(line)
        body = "\n\n".join(lines) if lines else "<i>No shortlisted jobs this run.</i>"
        footer = "\n\n━━━━━━━━━━━━━━━━━━━━\n👇 Approve or skip each job below ↓"
        full_text = header + body + footer
        return self.send_message(full_text, parse_mode="HTML")

    def send_review_card(self, score: JobScore) -> dict[str, Any]:
        """Send an individual interactive Approve / Skip card for a job."""
        callback_id = score.job.raw_payload.get("fingerprint")
        if not callback_id:
            import hashlib
            val = score.job.url or score.job.title or ""
            callback_id = hashlib.sha256(val.encode("utf-8")).hexdigest()[:32]
        else:
            callback_id = str(callback_id)[:32]
            
        buttons = [
            {"text": "✅ Approve", "callback_data": f"approve:{callback_id}"},
            {"text": "⏭ Skip", "callback_data": f"skip:{callback_id}"},
        ]
        if getattr(score.job, "is_direct_apply", False):
            buttons.append({"text": "⚡ Auto-Apply", "callback_data": f"auto_apply:{callback_id}"})

        keyboard = {
            "inline_keyboard": [buttons]
        }
        remote_tag = "🌐 Remote" if score.job.remote else "🏢 On-site"
        direct_tag = "  |  ⚡ Easy Apply" if getattr(score.job, "is_direct_apply", False) else ""
        salary_text = ""
        if score.job.salary_min and score.job.salary_max:
            salary_text = f"\n💰 {score.job.salary_currency} {score.job.salary_min:,.0f}–{score.job.salary_max:,.0f}"
        elif score.job.salary_min:
            salary_text = f"\n💰 {score.job.salary_currency} {score.job.salary_min:,.0f}+"
        message = (
            f"<b>{html.escape(score.job.title[:150])}</b>\n"
            f"🏷 {html.escape(score.job.company[:50])} · {html.escape(score.job.location[:50])}\n"
            f"{remote_tag}{direct_tag}{html.escape(salary_text)}\n"
            f"📊 Match: {score.match_percent}%  |  Score: {score.score:.2f}\n"
            f"🔗 {html.escape(score.job.url[:800])}\n\n"
            f"💡 {html.escape(score.explanation()[:1000])}"
        )
        return self.send_message(message, keyboard, parse_mode="HTML")

    def send_summary(self, discovered: int, shortlisted: int, approved: int, skipped: int) -> dict[str, Any]:
        """Send a plain-text run summary (used at end of pipeline)."""
        text = (
            f"JobFlow run complete\n"
            f"Discovered: {discovered}\n"
            f"Shortlisted: {shortlisted}\n"
            f"Approved: {approved}\n"
            f"Skipped: {skipped}"
        )
        return self.send_message(text)

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{self.token}/{method}",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_updates(self, offset: int | None = None) -> list[dict[str, Any]]:
        if self.dry_run:
            return []
        params = {"timeout": 0}
        if offset is not None:
            params["offset"] = offset
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{self.token}/getUpdates?{query}",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("result", [])

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> dict[str, Any]:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        if self.dry_run:
            if self.outbox:
                self.outbox.send({"kind": "telegram_callback", "payload": payload})
            return {"ok": True, "dry_run": True, "payload": payload}
        return self._post("answerCallbackQuery", payload)


class ReviewQueue:
    def __init__(self, telegram: TelegramClient):
        self.telegram = telegram

    def dispatch(self, scores: list[JobScore]) -> list[dict[str, Any]]:
        responses = []
        for score in scores:
            try:
                responses.append(self.telegram.send_review_card(score))
            except Exception as exc:
                responses.append({"ok": False, "error": str(exc), "job": score.job.title})
        return responses
