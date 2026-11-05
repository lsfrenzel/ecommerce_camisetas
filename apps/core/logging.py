"""Logs estruturados em JSON, com remoção de dados sensíveis."""

import json
import logging
import re
from datetime import datetime, timezone

SENSITIVE_PATTERNS = [
    (re.compile(r"(?i)(password|senha|token|secret|authorization|access_token)(['\"]?\s*[:=]\s*['\"]?)([^'\"\s,&]+)"), r"\1\2[REDACTED]"),
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "[CPF]"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[CARD]"),
]


def redact(text: str) -> str:
    for pattern, repl in SENSITIVE_PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactSensitiveFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover
            return True
        record.msg = redact(message)
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("order", "payment_id", "event", "status_code", "path"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)
