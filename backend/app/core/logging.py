"""Structured JSON logging with automatic credential and secret redaction."""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

SENSITIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)(api[_-]?key|secret|password|token|authorization)\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.]{8,})['\"]?"),
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]


def redact_secrets(text: str) -> str:
    """Redact potential credentials, API keys, and tokens from log strings."""
    if not text:
        return text
    redacted = text
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub(
            lambda m: f"{m.group(1)}=***REDACTED***" if m.lastindex and m.lastindex >= 1 else "***REDACTED***",
            redacted,
        )
    return redacted


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as single-line structured JSON with UTC timestamps."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_secrets(record.getMessage()),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            payload["context"] = {
                k: redact_secrets(str(v)) if isinstance(v, str) else v
                for k, v in record.extra_data.items()
            }
        if record.exc_info:
            payload["exception"] = redact_secrets(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    root_logger = logging.getLogger("qc_platform")
    root_logger.setLevel(level)
    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredJsonFormatter())
        root_logger.addHandler(handler)
    return root_logger


logger = configure_logging()
