from datetime import datetime, time, timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import cancel_booking, create_booking
from apps.resources.models import Resource, ResourceCategory

User = get_user_model()


def future_datetime(hour: int, minute: int = 0):
    target_date = timezone.localdate() + timedelta(days=1)

    naive_datetime = datetime.combine(target_date, time(hour, minute))

    return timezone.make_aware(naive_datetime, timezone.get_current_timezone())


@pytest.fixture
def user():
    return User.objects.create_user(
        email="user@example.com", password="StrongPassword123!"
    )


@pytest.fixture
def resource():
    category = ResourceCategory.objects.create(name="Meeting Room", slug="meeting-room")

    return Resource.objects.create(
        name="Room A",
        slug="room-a",
        category=category,
        location="Building A",
        booking_min_duration=timedelta(minutes=30),
        booking_max_duration=timedelta(hours=4),
        available_from=time(8),
        available_to=time(20),
    )


@pytest.mark.django_db(transaction=True)
def test_confirmation_is_dispatched_after_commit(user, resource):
    with patch(
        "apps.bookings.tasks.send_booking_confirmation_email.delay"
    ) as mocked_delay:
        booking = create_booking(
            user=user,
            resource=resource,
            start_at=future_datetime(10),
            end_at=future_datetime(11),
            title="Meeting",
            changed_by=user,
        )

    mocked_delay.assert_called_once_with(booking.id)


@pytest.mark.django_db(transaction=True)
def test_confirmation_is_not_dispatched_on_rollback(user, resource):
    with patch(
        "apps.bookings.tasks.send_booking_confirmation_email.delay"
    ) as mocked_delay:
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                create_booking(
                    user=user,
                    resource=resource,
                    start_at=future_datetime(10),
                    end_at=future_datetime(11),
                    title="Rolled back",
                    changed_by=user,
                )

                assert mocked_delay.call_count == 0

                raise RuntimeError("Force rollback")

    mocked_delay.assert_not_called()

    assert Booking.objects.filter(title="Rolled back").exists() is False


@pytest.mark.django_db(transaction=True)
def test_cancellation_is_dispatched_after_commit(user, resource):
    booking = Booking.objects.create(
        user=user,
        resource=resource,
        start_at=future_datetime(10),
        end_at=future_datetime(11),
        title="Meeting",
        status=BookingStatus.CONFIRMED,
    )

    with patch(
        "apps.bookings.tasks.send_booking_cancellation_email.delay"
    ) as mocked_delay:
        cancel_booking(booking=booking, changed_by=user)

    mocked_delay.assert_called_once_with(booking.id)


@pytest.mark.django_db(transaction=True)
def test_cancellation_email_is_not_dispatched_on_rollback(user, resource):
    booking = Booking.objects.create(
        user=user,
        resource=resource,
        start_at=future_datetime(10),
        end_at=future_datetime(11),
        title="Meeting",
        status=BookingStatus.CONFIRMED,
    )

    with patch(
        "apps.bookings.tasks.send_booking_cancellation_email.delay"
    ) as mocked_delay:
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                cancel_booking(booking=booking, changed_by=user)

                raise RuntimeError("Force rollback")

    mocked_delay.assert_not_called()

    booking.refresh_from_db()

    assert booking.status == BookingStatus.CONFIRMED
