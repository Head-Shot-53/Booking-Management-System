import logging
from datetime import timedelta
from smtplib import SMTPException

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from .exceptions import BookingStateError
from .models import Booking, BookingStatus
from .selectors import (
    get_expired_confirmed_booking_ids,
    get_upcoming_booking_reminder_ids,
)

logger = logging.getLogger("booking_management.booking")


@shared_task(name="bookings.celery_health_check")
def celery_health_check() -> dict[str, str]:
    return {"status": "ok"}


@shared_task(bind=True, name="bookings.complete_expired_bookings")
def complete_expired_bookings(self, batch_size: int = 100) -> dict[str, int]:
    from .services import complete_booking

    current_time = timezone.now()

    booking_ids = get_expired_confirmed_booking_ids(
        current_time=current_time, limit=batch_size
    )

    completed_count = 0
    skipped_count = 0
    failed_count = 0

    for booking_id in booking_ids:
        try:
            booking = Booking.objects.get(pk=booking_id)

            complete_booking(booking=booking, changed_by=None)

            completed_count += 1

        except Booking.DoesNotExist:
            skipped_count += 1

        except BookingStateError as exc:
            skipped_count += 1

            logger.info(
                "automatic_booking_completion_skipped",
                extra={
                    "task_id": self.request.id,
                    "booking_id": booking_id,
                    "error_code": exc.code,
                },
            )

        except Exception:
            failed_count += 1

            logger.exception(
                "automatic_booking_completion_failed",
                extra={"task_id": self.request.id, "booking_id": booking_id},
            )

    logger.info(
        "expired_bookings_processed",
        extra={
            "task_id": self.request.id,
            "processed_count": len(booking_ids),
            "completed_count": completed_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
        },
    )

    return {
        "processed": len(booking_ids),
        "completed": completed_count,
        "skipped": skipped_count,
        "failed": failed_count,
    }


@shared_task(
    bind=True,
    name="bookings.send_booking_confirmation_email",
    autoretry_for=(SMTPException, OSError),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def send_booking_confirmation_email(self, booking_id: int) -> dict:
    try:
        booking = Booking.objects.select_related(
            "user",
            "resource",
        ).get(pk=booking_id)

    except Booking.DoesNotExist:
        logger.warning(
            "booking_confirmation_email_skipped",
            extra={
                "task_id": self.request.id,
                "booking_id": booking_id,
                "notification_type": "booking_confirmation",
            },
        )

        return {
            "status": "skipped",
            "reason": "booking_not_found",
            "booking_id": booking_id,
        }

    if booking.status != BookingStatus.CONFIRMED:
        logger.info(
            "booking_confirmation_email_skipped",
            extra={
                "task_id": self.request.id,
                "booking_id": booking.id,
                "notification_type": "booking_confirmation",
            },
        )

        return {
            "status": "skipped",
            "reason": "booking_not_confirmed",
            "booking_id": booking.id,
        }

    start_at = timezone.localtime(booking.start_at)
    end_at = timezone.localtime(booking.end_at)

    message = render_to_string(
        "emails/bookings/confirmation.txt",
        {
            "booking": booking,
            "start_at": start_at,
            "end_at": end_at,
        },
    )

    sent_count = send_mail(
        subject=f"Booking confirmed: {booking.title}",
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[booking.user.email],
        fail_silently=False,
    )

    logger.info(
        "booking_confirmation_email_sent",
        extra={
            "task_id": self.request.id,
            "booking_id": booking.id,
            "owner_id": booking.user_id,
            "notification_type": "booking_confirmation",
            "sent_count": sent_count,
        },
    )

    return {"status": "sent", "booking_id": booking.id, "sent": sent_count}


@shared_task(
    bind=True,
    name="bookings.send_booking_cancellation_email",
    autoretry_for=(SMTPException, OSError),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def send_booking_cancellation_email(self, booking_id: int) -> dict:
    try:
        booking = Booking.objects.select_related(
            "user",
            "resource",
        ).get(pk=booking_id)

    except Booking.DoesNotExist:
        logger.warning(
            "booking_cancellation_email_skipped",
            extra={
                "task_id": self.request.id,
                "booking_id": booking_id,
                "notification_type": "booking_cancellation",
            },
        )

        return {
            "status": "skipped",
            "reason": "booking_not_found",
            "booking_id": booking_id,
        }

    if booking.status != BookingStatus.CANCELLED:
        logger.info(
            "booking_cancellation_email_skipped",
            extra={
                "task_id": self.request.id,
                "booking_id": booking.id,
                "owner_id": booking.user_id,
                "notification_type": "booking_cancellation",
                "reason": "booking_not_cancelled",
            },
        )

        return {
            "status": "skipped",
            "reason": "booking_not_cancelled",
            "booking_id": booking.id,
        }

    start_at = timezone.localtime(booking.start_at)
    end_at = timezone.localtime(booking.end_at)

    message = render_to_string(
        "emails/bookings/cancellation.txt",
        {
            "booking": booking,
            "start_at": start_at,
            "end_at": end_at,
        },
    )

    sent_count = send_mail(
        subject=f"Booking cancelled: {booking.title}",
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[booking.user.email],
        fail_silently=False,
    )

    logger.info(
        "booking_cancellation_email_sent",
        extra={
            "task_id": self.request.id,
            "booking_id": booking.id,
            "owner_id": booking.user_id,
            "notification_type": "booking_cancellation",
            "sent_count": sent_count,
        },
    )

    return {"status": "sent", "booking_id": booking.id, "sent": sent_count}


def _claim_booking_reminder(*, booking_id: int, claimed_at) -> bool:
    updated_rows = Booking.objects.filter(
        pk=booking_id,
        status=BookingStatus.CONFIRMED,
        reminder_sent_at__isnull=True,
        start_at__gt=claimed_at,
    ).update(reminder_sent_at=claimed_at)

    return updated_rows == 1


def _release_booking_reminder_claim(*, booking_id: int, claimed_at) -> None:
    Booking.objects.filter(
        pk=booking_id,
        reminder_sent_at=claimed_at,
    ).update(reminder_sent_at=None)


@shared_task(bind=True, name="bookings.send_booking_reminder_email", max_retries=3)
def send_booking_reminder_email(self, booking_id: int) -> dict:
    claimed_at = timezone.now()

    claimed = _claim_booking_reminder(booking_id=booking_id, claimed_at=claimed_at)

    if not claimed:
        logger.info(
            "booking_reminder_email_skipped",
            extra={
                "task_id": self.request.id,
                "booking_id": booking_id,
                "notification_type": ("booking_reminder"),
            },
        )

        return {"status": "skipped", "booking_id": booking_id}

    try:
        booking = Booking.objects.select_related("user", "resource").get(pk=booking_id)

        start_at = timezone.localtime(booking.start_at)

        end_at = timezone.localtime(booking.end_at)

        message = render_to_string(
            "emails/bookings/reminder.txt",
            {"booking": booking, "start_at": start_at, "end_at": end_at},
        )

        sent_count = send_mail(
            subject=(f"Booking reminder: {booking.title}"),
            message=message,
            from_email=(settings.DEFAULT_FROM_EMAIL),
            recipient_list=[
                booking.user.email,
            ],
            fail_silently=False,
        )

        if sent_count != 1:
            raise RuntimeError("Booking reminder email was not sent.")

    except (SMTPException, OSError) as exc:
        _release_booking_reminder_claim(booking_id=booking_id, claimed_at=claimed_at)

        logger.warning(
            "booking_reminder_email_retry",
            extra={
                "task_id": self.request.id,
                "booking_id": booking_id,
                "notification_type": ("booking_reminder"),
            },
        )

        countdown = min(60 * (2**self.request.retries), 600)

        raise self.retry(exc=exc, countdown=countdown) from exc

    except Exception:
        _release_booking_reminder_claim(booking_id=booking_id, claimed_at=claimed_at)

        logger.exception(
            "booking_reminder_email_failed",
            extra={
                "task_id": self.request.id,
                "booking_id": booking_id,
                "notification_type": ("booking_reminder"),
            },
        )

        raise

    logger.info(
        "booking_reminder_email_sent",
        extra={
            "task_id": self.request.id,
            "booking_id": booking.id,
            "owner_id": booking.user_id,
            "notification_type": "booking_reminder",
            "sent_count": sent_count,
        },
    )

    return {"status": "sent", "booking_id": booking.id, "sent": sent_count}


@shared_task(bind=True, name="bookings.send_upcoming_booking_reminders")
def send_upcoming_booking_reminders(
    self, minutes_before: int = 60, batch_size: int = 100
) -> dict[str, int]:
    current_time = timezone.now()

    reminder_window = timedelta(minutes=minutes_before)

    booking_ids = get_upcoming_booking_reminder_ids(
        current_time=current_time, reminder_window=reminder_window, limit=batch_size
    )

    queued_count = 0
    failed_count = 0

    for booking_id in booking_ids:
        try:
            send_booking_reminder_email.delay(booking_id)

            queued_count += 1

        except Exception:
            failed_count += 1

            logger.exception(
                "booking_reminder_dispatch_failed",
                extra={
                    "task_id": self.request.id,
                    "booking_id": booking_id,
                    "notification_type": ("booking_reminder"),
                },
            )

    logger.info(
        "upcoming_booking_reminders_processed",
        extra={
            "task_id": self.request.id,
            "processed_count": len(booking_ids),
            "queued_count": queued_count,
            "failed_count": failed_count,
        },
    )

    return {
        "processed": len(booking_ids),
        "queued": queued_count,
        "failed": failed_count,
    }
