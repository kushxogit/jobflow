from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def ensure_dir(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def tokenize(value: str) -> list[str]:
    return _TOKEN_RE.findall(normalize_text(value))


def hash_payload(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def fingerprint_job(source: str, title: str, company: str, url: str, description: str) -> str:
    normalized = {
        "source": normalize_text(source),
        "title": normalize_text(title),
        "company": normalize_text(company),
        "url": normalize_text(url),
        "description": normalize_text(description)[:3000],
    }
    return hash_payload(normalized)


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def write_jsonl(path: str | Path, record: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str))
        handle.write("\n")


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_text(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()

