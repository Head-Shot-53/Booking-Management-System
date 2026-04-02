import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_context.get()

        return True


class JsonFormatter(logging.Formatter):
    EXTRA_FIELDS = (
        "status_code",
        "method",
        "path",
        "user_id",
        "actor_id",
        "owner_id",
        "booking_id",
        "resource_id",
        "error_code",
        "task_id",
        "processed_count",
        "queued_count",
        "completed_count",
        "skipped_count",
        "failed_count",
        "task_name",
        "notification_type",
        "sent_count",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }

        for field in self.EXTRA_FIELDS:
            value = getattr(record, field, None)

            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)
