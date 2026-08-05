"""Structured, secret-aware logging configuration."""

import json
import logging
import logging.config
import re
from datetime import UTC, datetime
from typing import Any

_KEY_VALUE_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|application[_-]?key|authorization|password|secret|token)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_CONNECTION_STRING = re.compile(
    r"(?i)\b(postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s]+"
)
_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_QUERY_SECRET = re.compile(
    r"(?i)([?&](?:key|api_key|token|access_token)=)[^&\s]+"
)


def redact_sensitive_text(value: object) -> str:
    """Remove common credential shapes from a log-safe string."""
    text = str(value)
    text = _KEY_VALUE_SECRET.sub(r"\1\2[REDACTED]", text)
    text = _CONNECTION_STRING.sub(r"\1://[REDACTED]", text)
    text = _QUERY_SECRET.sub(r"\1[REDACTED]", text)
    return _BEARER_TOKEN.sub("Bearer [REDACTED]", text)


class SensitiveDataFilter(logging.Filter):
    """Redact secrets after interpolation and before a record is emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_sensitive_text(record.getMessage())
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    """Serialize log records as one-line JSON for local and hosted runtimes."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = redact_sensitive_text(
                self.formatException(record.exc_info)
            )
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    """Apply a consistent configuration to the app and Uvicorn loggers."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "redact": {"()": SensitiveDataFilter},
            },
            "formatters": {
                "json": {"()": JsonFormatter},
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "filters": ["redact"],
                    "formatter": "json",
                    "stream": "ext://sys.stdout",
                },
            },
            "loggers": {
                "uvicorn": {
                    "handlers": ["default"],
                    "level": level,
                    "propagate": False,
                },
                "uvicorn.error": {
                    "handlers": ["default"],
                    "level": level,
                    "propagate": False,
                },
                "uvicorn.access": {
                    "handlers": ["default"],
                    "level": level,
                    "propagate": False,
                },
            },
            "root": {
                "handlers": ["default"],
                "level": level,
            },
        }
    )
