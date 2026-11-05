import hashlib
import re
from typing import List, Tuple

SECRET_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}"), "LLM_API_KEY"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"), "GITHUB_TOKEN"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS_ACCESS_KEY"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "GOOGLE_API_KEY"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"), "SLACK_TOKEN"),
    (re.compile(r"eyJ[\w\-]+\.eyJ[\w\-]+\.[\w\-]+"), "JWT"),
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"
        ),
        "PRIVATE_KEY",
    ),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|secret|token|password)\b(\s*[:=]\s*)(['\"]?)[^\s'\"]{8,}\3"
        ),
        "GENERIC",
    ),
]


def redact(text: str) -> Tuple[str, List[str]]:
    """Redacts known secret patterns from text and returns (redacted_text, labels_found)."""
    found: List[str] = []
    current = text
    for pattern, label in SECRET_PATTERNS:
        if label == "GENERIC":
            current, count = pattern.subn(
                lambda m: f"{m.group(1)}{m.group(2)}[REDACTED:GENERIC]", current
            )
        else:
            current, count = pattern.subn(f"[REDACTED:{label}]", current)
        if count > 0 and label not in found:
            found.append(label)
    return current, found


def compute_content_hash(content: str, project_name: str | None = None) -> str:
    """Computes a normalized SHA-256 hash for idempotent memory deduplication."""
    norm_content = " ".join(content.strip().lower().split())
    norm_proj = (project_name or "").strip().lower()
    payload = f"{norm_proj}::{norm_content}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
