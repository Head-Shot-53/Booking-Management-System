from datetime import time, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.utils import timezone

from apps.bookings.models import Booking, BookingStatus
from apps.bookings.tasks import (
    send_booking_cancellation_email,
    send_booking_confirmation_email,
)
from apps.resources.models import Resource, ResourceCategory

User = get_user_model()


@pytest.fixture
def user():
    return User.objects.create_user(
        email="user@example.com", password="StrongPassword123!", first_name="John"
    )


@pytest.fixture
def resource():
    category = ResourceCategory.objects.create(name="Meeting Room", slug="meeting-room")

    return Resource.objects.create(
        name="Conference Room A",
        slug="conference-room-a",
        category=category,
        location="Building A",
        booking_min_duration=timedelta(minutes=30),
        booking_max_duration=timedelta(hours=4),
        available_from=time(8),
        available_to=time(20),
    )


@pytest.fixture
def booking(user, resource):
    start_at = timezone.now() + timedelta(days=1)

    return Booking.objects.create(
        user=user,
        resource=resource,
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
        title="Architecture meeting",
    )


@pytest.mark.django_db
def test_confirmation_email_is_sent(booking, user, resource, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

    mail.outbox.clear()

    result = send_booking_confirmation_email.run(booking.id)

    assert result["status"] == "sent"
    assert result["sent"] == 1

    assert len(mail.outbox) == 1

    email = mail.outbox[0]

    assert email.to == [user.email]

    assert email.subject == "Booking confirmed: Architecture meeting"

    assert "Architecture meeting" in email.body

    assert resource.name in email.body


@pytest.mark.django_db
def test_cancellation_email_is_sent(booking, user, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = timezone.now()

    booking.save(update_fields=["status", "cancelled_at", "updated_at"])

    mail.outbox.clear()

    result = send_booking_cancellation_email.run(booking.id)

    assert result["status"] == "sent"
    assert result["sent"] == 1

    assert len(mail.outbox) == 1

    email = mail.outbox[0]

    assert email.to == [user.email]

    assert email.subject == "Booking cancelled: Architecture meeting"

    assert "CANCELLED" in email.body


@pytest.mark.django_db
def test_confirmation_email_skips_missing_booking(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

    mail.outbox.clear()

    result = send_booking_confirmation_email.run(999999)

    assert result == {
        "status": "skipped",
        "reason": "booking_not_found",
        "booking_id": 999999,
    }

    assert len(mail.outbox) == 0
