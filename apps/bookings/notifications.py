import logging
from functools import partial

from django.db import transaction

logger = logging.getLogger("booking_management.booking")


def _publish_task(task, *args) -> None:
    try:
        task.delay(*args)
    except Exception:
        logger.exception("celery_task_dispatch_failed", extra={"task_name": task.name})


def schedule_booking_confirmation(*, booking_id: int) -> None:
    from .tasks import send_booking_confirmation_email

    transaction.on_commit(
        partial(_publish_task, send_booking_confirmation_email, booking_id), robust=True
    )


def schedule_booking_cancellation(*, booking_id: int) -> None:
    from .tasks import send_booking_cancellation_email

    transaction.on_commit(
        partial(_publish_task, send_booking_cancellation_email, booking_id), robust=True
    )
