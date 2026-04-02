from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core import mail
from django.utils import timezone

from apps.bookings.models import Booking
from apps.bookings.tasks import (
    send_booking_reminder_email,
    send_upcoming_booking_reminders,
)


@pytest.mark.django_db
def test_booking_reminder_email_is_sent_once(user, resource, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

    now = timezone.now()

    booking = Booking.objects.create(
        user=user,
        resource=resource,
        start_at=now + timedelta(minutes=30),
        end_at=now + timedelta(minutes=90),
        title="Team meeting",
    )

    mail.outbox.clear()

    result = send_booking_reminder_email.run(booking.id)

    booking.refresh_from_db()

    assert result["status"] == "sent"

    assert booking.reminder_sent_at is not None

    assert len(mail.outbox) == 1

    email = mail.outbox[0]

    assert email.to == [user.email]

    assert email.subject == "Booking reminder: Team meeting"


@pytest.mark.django_db
def test_booking_reminder_is_idempotent(user, resource, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

    now = timezone.now()

    booking = Booking.objects.create(
        user=user,
        resource=resource,
        start_at=now + timedelta(minutes=30),
        end_at=now + timedelta(minutes=90),
        title="Team meeting",
    )

    mail.outbox.clear()

    first_result = send_booking_reminder_email.run(booking.id)

    second_result = send_booking_reminder_email.run(booking.id)

    assert first_result["status"] == "sent"

    assert second_result["status"] == "skipped"

    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_cancelled_booking_reminder_is_skipped(user, resource, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

    now = timezone.now()

    booking = Booking.objects.create(
        user=user,
        resource=resource,
        start_at=now + timedelta(minutes=30),
        end_at=now + timedelta(minutes=90),
        title="Cancelled",
        status="CANCELLED",
        cancelled_at=now,
    )

    mail.outbox.clear()

    result = send_booking_reminder_email.run(booking.id)

    assert result["status"] == "skipped"

    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_started_booking_reminder_is_skipped(user, resource, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

    now = timezone.now()

    booking = Booking.objects.create(
        user=user,
        resource=resource,
        start_at=now - timedelta(minutes=5),
        end_at=now + timedelta(minutes=55),
        title="Already started",
    )

    mail.outbox.clear()

    result = send_booking_reminder_email.run(booking.id)

    assert result["status"] == "skipped"

    assert len(mail.outbox) == 0


@pytest.mark.django_db
def test_reminder_scanner_queues_upcoming_booking(user, resource):
    now = timezone.now()

    booking = Booking.objects.create(
        user=user,
        resource=resource,
        start_at=now + timedelta(minutes=30),
        end_at=now + timedelta(minutes=90),
        title="Meeting",
    )

    with patch("apps.bookings.tasks.send_booking_reminder_email.delay") as mocked_delay:
        result = send_upcoming_booking_reminders.run(
            minutes_before=60,
        )

    mocked_delay.assert_called_once_with(booking.id)

    assert result["processed"] == 1
    assert result["queued"] == 1
    assert result["failed"] == 0
