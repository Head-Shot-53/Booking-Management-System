from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.bookings.models import Booking, BookingStatus
from apps.bookings.selectors import get_upcoming_booking_reminder_ids

User = get_user_model()


@pytest.mark.django_db
def test_selector_returns_upcoming_booking(user, resource):
    now = timezone.now()

    booking = Booking.objects.create(
        user=user,
        resource=resource,
        start_at=now + timedelta(minutes=30),
        end_at=now + timedelta(minutes=90),
        title="Upcoming meeting",
    )

    ids = get_upcoming_booking_reminder_ids(current_time=now)

    assert ids == [booking.id]


@pytest.mark.django_db
def test_selector_ignores_booking_outside_window(user, resource):
    now = timezone.now()

    Booking.objects.create(
        user=user,
        resource=resource,
        start_at=now + timedelta(hours=2),
        end_at=now + timedelta(hours=3),
        title="Later meeting",
    )

    ids = get_upcoming_booking_reminder_ids(current_time=now)

    assert ids == []


@pytest.mark.django_db
def test_selector_ignores_cancelled_booking(user, resource):
    now = timezone.now()

    Booking.objects.create(
        user=user,
        resource=resource,
        start_at=now + timedelta(minutes=30),
        end_at=now + timedelta(minutes=90),
        title="Cancelled meeting",
        status=BookingStatus.CANCELLED,
        cancelled_at=now,
    )

    ids = get_upcoming_booking_reminder_ids(current_time=now)

    assert ids == []


@pytest.mark.django_db
def test_selector_ignores_already_reminded_booking(user, resource):
    now = timezone.now()

    Booking.objects.create(
        user=user,
        resource=resource,
        start_at=now + timedelta(minutes=30),
        end_at=now + timedelta(minutes=90),
        title="Meeting",
        reminder_sent_at=now - timedelta(minutes=5),
    )

    ids = get_upcoming_booking_reminder_ids(current_time=now)

    assert ids == []
