import logging
from smtplib import SMTPException

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from .exceptions import BookingStateError
from .models import Booking
from .selectors import get_expired_confirmed_booking_ids

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
        booking = Booking.objects.select_related("user", "resource").get(pk=booking_id)
    except Booking.DoesNotExist:
        logger.warning(
            "booking_confirmation_email_skipped",
            extra={
                "task_id": self.request.id,
                "booking_id": booking_id,
                "notification_type": ("booking_confirmation"),
            },
        )

        return {
            "status": "skipped",
            "reason": "booking_not_found",
            "booking_id": booking_id,
        }

    start_at = timezone.localtime(booking.start_at)

    end_at = timezone.localtime(booking.end_at)

    message = render_to_string(
        "emails/bookings/confirmation.txt",
        {"booking": booking, "start_at": start_at, "end_at": end_at},
    )

    sent_count = send_mail(
        subject=(f"Booking confirmed: {booking.title}"),
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
            "notification_type": ("booking_confirmation"),
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
        booking = Booking.objects.select_related("user", "resource").get(pk=booking_id)
    except Booking.DoesNotExist:
        logger.warning(
            "booking_cancellation_email_skipped",
            extra={
                "task_id": self.request.id,
                "booking_id": booking_id,
                "notification_type": ("booking_cancellation"),
            },
        )

        return {
            "status": "skipped",
            "reason": "booking_not_found",
            "booking_id": booking_id,
        }

    start_at = timezone.localtime(booking.start_at)

    end_at = timezone.localtime(booking.end_at)

    message = render_to_string(
        "emails/bookings/cancellation.txt",
        {"booking": booking, "start_at": start_at, "end_at": end_at},
    )

    sent_count = send_mail(
        subject=(f"Booking cancelled: {booking.title}"),
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
            "notification_type": ("booking_cancellation"),
            "sent_count": sent_count,
        },
    )

    return {"status": "sent", "booking_id": booking.id, "sent": sent_count}
