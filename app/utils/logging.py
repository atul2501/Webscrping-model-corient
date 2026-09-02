import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("crawl_id", "source", "url", "status_code", "elapsed_ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", log_file: str | None = None) -> None:
    """Wires up structured JSON logging for the whole app.

    log_file (LOG_FILE env var, see .env.example) sends every log line to
    that file - rotated at 5MB, keeping 3 backups - instead of the
    terminal, which is what local dev wants (a `/api/search` run logs one
    line per HTTP fetch across 3 adapters; that's noisy mid-conversation in
    a terminal, easy to search through in a file). Deployed environments
    (Docker/Render - see render.yaml) deliberately leave LOG_FILE unset:
    Render captures container stdout for its own log viewer, and a file
    written inside an ephemeral container would just vanish on redeploy.
    """

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    if log_file:
        handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3)
    else:
        handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
