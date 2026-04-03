from datetime import datetime, time, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db.models import ProtectedError
from django.utils import timezone

from apps.audit.models import BookingHistory, BookingHistoryAction
from apps.bookings.exceptions import BookingConflictError
from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import (
    cancel_booking,
    complete_booking,
    create_booking,
    update_booking,
)
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
def manager():
    return User.objects.create_user(
        email="manager@example.com", password="StrongPassword123!"
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


@pytest.mark.django_db
def test_create_booking_creates_history_entry(user, resource):
    booking = create_booking(
        user=user,
        resource=resource,
        start_at=future_datetime(10),
        end_at=future_datetime(11),
        title="Team meeting",
        changed_by=user,
    )

    history = BookingHistory.objects.get()

    assert history.booking == booking
    assert history.changed_by == user

    assert history.action == BookingHistoryAction.CREATED

    assert history.old_data == {}

    assert history.new_data["user_id"] == user.id

    assert history.new_data["resource_id"] == resource.id

    assert history.new_data["status"] == BookingStatus.CONFIRMED

    assert history.new_data["title"] == "Team meeting"


@pytest.mark.django_db
def test_update_booking_creates_history_entry(user, manager, resource):
    booking = create_booking(
        user=user,
        resource=resource,
        start_at=future_datetime(10),
        end_at=future_datetime(11),
        title="Old title",
        changed_by=user,
    )

    update_booking(booking=booking, title="New title", changed_by=manager)

    histories = BookingHistory.objects.filter(booking=booking)

    assert histories.count() == 2

    update_history = histories.get(action=BookingHistoryAction.UPDATED)

    assert update_history.changed_by == manager

    assert update_history.old_data["title"] == "Old title"

    assert update_history.new_data["title"] == "New title"


@pytest.mark.django_db
def test_cancel_booking_creates_history_entry(user, resource):
    booking = create_booking(
        user=user,
        resource=resource,
        start_at=future_datetime(10),
        end_at=future_datetime(11),
        title="Meeting",
        changed_by=user,
    )

    cancel_booking(booking=booking, changed_by=user)

    history = BookingHistory.objects.get(
        booking=booking, action=BookingHistoryAction.CANCELLED
    )

    assert history.old_data["status"] == BookingStatus.CONFIRMED

    assert history.new_data["status"] == BookingStatus.CANCELLED

    assert history.old_data["cancelled_at"] is None

    assert history.new_data["cancelled_at"] is not None


@pytest.mark.django_db
def test_complete_booking_creates_history_entry(user, resource):
    end_at = timezone.now() - timedelta(minutes=30)

    booking = Booking.objects.create(
        user=user,
        resource=resource,
        start_at=end_at - timedelta(hours=1),
        end_at=end_at,
        title="Finished meeting",
    )

    complete_booking(booking=booking, changed_by=None)

    history = BookingHistory.objects.get(booking=booking)

    assert history.action == BookingHistoryAction.COMPLETED

    assert history.changed_by is None

    assert history.old_data["status"] == BookingStatus.CONFIRMED

    assert history.new_data["status"] == BookingStatus.COMPLETED


@pytest.mark.django_db
def test_failed_booking_creation_does_not_create_history(user, resource):
    create_booking(
        user=user,
        resource=resource,
        start_at=future_datetime(10),
        end_at=future_datetime(11),
        title="Existing",
        changed_by=user,
    )

    assert BookingHistory.objects.count() == 1

    with pytest.raises(BookingConflictError):
        create_booking(
            user=user,
            resource=resource,
            start_at=future_datetime(10, 30),
            end_at=future_datetime(11, 30),
            title="Conflict",
            changed_by=user,
        )

    assert Booking.objects.count() == 1
    assert BookingHistory.objects.count() == 1


@pytest.mark.django_db
def test_booking_with_history_cannot_be_deleted(user, resource):
    booking = create_booking(
        user=user,
        resource=resource,
        start_at=future_datetime(10),
        end_at=future_datetime(11),
        title="Protected booking",
        changed_by=user,
    )

    with pytest.raises(ProtectedError):
        booking.delete()

    assert Booking.objects.filter(pk=booking.pk).exists()

    assert BookingHistory.objects.filter(booking=booking).exists()


@pytest.mark.django_db
def test_history_survives_changed_by_deletion(user, manager, resource):
    booking = create_booking(
        user=user,
        resource=resource,
        start_at=future_datetime(10),
        end_at=future_datetime(11),
        title="Meeting",
        changed_by=manager,
    )

    history = BookingHistory.objects.get(booking=booking)

    manager.delete()

    history.refresh_from_db()

    assert history.changed_by is None


@pytest.mark.django_db
def test_booking_history_is_ordered_newest_first(user, resource):
    booking = create_booking(
        user=user,
        resource=resource,
        start_at=future_datetime(10),
        end_at=future_datetime(11),
        title="Old title",
        changed_by=user,
    )

    update_booking(booking=booking, title="New title", changed_by=user)

    history = list(booking.history.all())

    assert history[0].action == BookingHistoryAction.UPDATED
    assert history[1].action == BookingHistoryAction.CREATED


@pytest.mark.django_db
def test_title_update_does_not_reset_reminder(user, resource):
    reminder_sent_at = timezone.now()

    booking = Booking.objects.create(
        user=user,
        resource=resource,
        start_at=future_datetime(10),
        end_at=future_datetime(11),
        title="Old title",
        reminder_sent_at=reminder_sent_at,
    )

    updated = update_booking(
        booking=booking,
        title="New title",
        changed_by=user,
    )

    updated.refresh_from_db()

    assert updated.title == "New title"
    assert updated.reminder_sent_at == reminder_sent_at
