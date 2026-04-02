from datetime import datetime, time, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.bookings.exceptions import (
    BookingConflictError,
    BookingStateError,
    BookingValidationError,
)
from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import cancel_booking, complete_booking, update_booking
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
def category():
    return ResourceCategory.objects.create(name="Meeting Room", slug="meeting-room")


@pytest.fixture
def resource(category):
    return Resource.objects.create(
        name="Conference Room A",
        slug="conference-room-a",
        category=category,
        location="Building A",
        capacity=12,
        booking_min_duration=timedelta(minutes=30),
        booking_max_duration=timedelta(hours=4),
        available_from=time(8, 0),
        available_to=time(20, 0),
    )


@pytest.fixture
def booking(user, resource):
    return Booking.objects.create(
        user=user,
        resource=resource,
        start_at=future_datetime(10),
        end_at=future_datetime(11),
        title="Team meeting",
    )


@pytest.mark.django_db
def test_update_booking_title(booking):
    updated_booking = update_booking(booking=booking, title="Updated meeting")

    assert updated_booking.title == "Updated meeting"

    booking.refresh_from_db()

    assert booking.title == "Updated meeting"


@pytest.mark.django_db
def test_update_booking_time(booking):
    updated_booking = update_booking(
        booking=booking, start_at=future_datetime(12), end_at=future_datetime(13)
    )

    assert updated_booking.start_at == future_datetime(12)
    assert updated_booking.end_at == future_datetime(13)


@pytest.mark.django_db
def test_update_booking_does_not_conflict_with_itself(booking):
    updated_booking = update_booking(booking=booking, title="Updated title")

    assert updated_booking.pk == booking.pk


@pytest.mark.django_db
def test_update_booking_rejects_overlap(user, resource, booking):
    Booking.objects.create(
        user=user,
        resource=resource,
        start_at=future_datetime(12),
        end_at=future_datetime(13),
        title="Second booking",
    )

    with pytest.raises(BookingConflictError):
        update_booking(
            booking=booking,
            start_at=future_datetime(12, 30),
            end_at=future_datetime(13, 30),
        )

    booking.refresh_from_db()

    assert booking.start_at == future_datetime(10)
    assert booking.end_at == future_datetime(11)


@pytest.mark.django_db
def test_update_booking_can_change_resource(category, booking):
    second_resource = Resource.objects.create(
        name="Conference Room B",
        slug="conference-room-b",
        category=category,
        location="Building B",
        capacity=8,
        booking_min_duration=timedelta(minutes=30),
        booking_max_duration=timedelta(hours=4),
        available_from=time(8, 0),
        available_to=time(20, 0),
    )

    updated_booking = update_booking(booking=booking, resource=second_resource)

    assert updated_booking.resource == second_resource

    booking.refresh_from_db()

    assert booking.resource == second_resource


@pytest.mark.django_db
def test_update_booking_checks_conflict_on_new_resource(user, category, booking):
    second_resource = Resource.objects.create(
        name="Conference Room B",
        slug="conference-room-b",
        category=category,
        location="Building B",
        capacity=8,
        booking_min_duration=timedelta(minutes=30),
        booking_max_duration=timedelta(hours=4),
        available_from=time(8, 0),
        available_to=time(20, 0),
    )

    Booking.objects.create(
        user=user,
        resource=second_resource,
        start_at=future_datetime(10),
        end_at=future_datetime(11),
        title="Existing B booking",
    )

    with pytest.raises(BookingConflictError):
        update_booking(booking=booking, resource=second_resource)

    booking.refresh_from_db()

    assert booking.resource_id != second_resource.id


@pytest.mark.django_db
def test_cancelled_booking_cannot_be_updated(booking):
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = timezone.now()

    booking.save(update_fields=["status", "cancelled_at", "updated_at"])

    with pytest.raises(BookingStateError) as exc_info:
        update_booking(booking=booking, title="Should not work")

    assert exc_info.value.code == "booking_not_editable"


@pytest.mark.django_db
def test_completed_booking_cannot_be_updated(booking):
    booking.status = BookingStatus.COMPLETED

    booking.save(update_fields=["status", "updated_at"])

    with pytest.raises(BookingStateError):
        update_booking(booking=booking, title="Should not work")


@pytest.mark.django_db
def test_cancel_booking(booking):
    cancelled_booking = cancel_booking(
        booking=booking,
    )

    assert cancelled_booking.status == BookingStatus.CANCELLED
    assert cancelled_booking.cancelled_at is not None

    booking.refresh_from_db()

    assert booking.status == BookingStatus.CANCELLED
    assert booking.cancelled_at is not None


@pytest.mark.django_db
def test_cancel_booking_does_not_delete_booking(booking):
    booking_id = booking.id

    cancel_booking(booking=booking)

    assert Booking.objects.filter(pk=booking_id).exists()


@pytest.mark.django_db
def test_cancelled_booking_cannot_be_cancelled_again(booking):
    cancel_booking(booking=booking)

    with pytest.raises(BookingStateError) as exc_info:
        cancel_booking(booking=booking)

    assert exc_info.value.code == "booking_cannot_be_cancelled"


@pytest.mark.django_db
def test_completed_booking_cannot_be_cancelled(booking):
    booking.status = BookingStatus.COMPLETED

    booking.save(update_fields=["status", "updated_at"])

    with pytest.raises(BookingStateError):
        cancel_booking(booking=booking)


@pytest.mark.django_db
def test_complete_booking(user, resource):
    end_at = timezone.now() - timedelta(minutes=30)
    start_at = end_at - timedelta(hours=1)

    booking = Booking.objects.create(
        user=user,
        resource=resource,
        start_at=start_at,
        end_at=end_at,
        title="Finished meeting",
    )

    completed_booking = complete_booking(
        booking=booking,
    )

    assert completed_booking.status == BookingStatus.COMPLETED

    booking.refresh_from_db()

    assert booking.status == BookingStatus.COMPLETED
    assert booking.cancelled_at is None


@pytest.mark.django_db
def test_future_booking_cannot_be_completed(booking):
    with pytest.raises(BookingStateError) as exc_info:
        complete_booking(booking=booking)

    assert exc_info.value.code == "booking_not_finished"

    booking.refresh_from_db()

    assert booking.status == BookingStatus.CONFIRMED


@pytest.mark.django_db
def test_cancelled_booking_cannot_be_completed(booking):
    cancel_booking(booking=booking)

    with pytest.raises(BookingStateError) as exc_info:
        complete_booking(booking=booking)

    assert exc_info.value.code == "booking_cannot_be_completed"


@pytest.mark.django_db
def test_completed_booking_cannot_be_completed_again(user, resource):
    end_at = timezone.now() - timedelta(minutes=30)

    booking = Booking.objects.create(
        user=user,
        resource=resource,
        start_at=end_at - timedelta(hours=1),
        end_at=end_at,
        title="Finished meeting",
    )

    complete_booking(booking=booking)

    with pytest.raises(BookingStateError):
        complete_booking(booking=booking)


@pytest.mark.django_db
def test_pending_booking_can_be_cancelled(booking):
    booking.status = BookingStatus.PENDING

    booking.save(update_fields=["status", "updated_at"])

    cancelled_booking = cancel_booking(booking=booking)

    assert cancelled_booking.status == BookingStatus.CANCELLED


@pytest.mark.django_db
def test_pending_booking_cannot_be_completed(user, resource):
    end_at = timezone.now() - timedelta(minutes=30)

    booking = Booking.objects.create(
        user=user,
        resource=resource,
        start_at=end_at - timedelta(hours=1),
        end_at=end_at,
        title="Pending booking",
        status=BookingStatus.PENDING,
    )

    with pytest.raises(BookingStateError):
        complete_booking(booking=booking)


@pytest.mark.django_db
def test_booking_cannot_be_moved_to_inactive_resource(category, booking):
    inactive_resource = Resource.objects.create(
        name="Inactive Room",
        slug="inactive-room",
        category=category,
        location="Building B",
        capacity=8,
        is_active=False,
        booking_min_duration=timedelta(minutes=30),
        booking_max_duration=timedelta(hours=4),
        available_from=time(8, 0),
        available_to=time(20, 0),
    )

    with pytest.raises(BookingValidationError) as exc_info:
        update_booking(booking=booking, resource=inactive_resource)

    assert exc_info.value.code == "resource_inactive"


@pytest.mark.django_db
def test_reschedule_resets_reminder_sent_at(user, resource):
    now = timezone.now()

    booking = Booking.objects.create(
        user=user,
        resource=resource,
        start_at=now + timedelta(hours=2),
        end_at=now + timedelta(hours=3),
        title="Meeting",
        reminder_sent_at=now,
    )

    new_start = now + timedelta(hours=4)

    new_end = now + timedelta(hours=5)

    updated = update_booking(
        booking=booking, start_at=new_start, end_at=new_end, changed_by=user
    )

    assert updated.reminder_sent_at is None


@pytest.mark.django_db
def test_title_update_does_not_reset_reminder(user, resource):
    now = timezone.now()

    booking = Booking.objects.create(
        user=user,
        resource=resource,
        start_at=now + timedelta(hours=2),
        end_at=now + timedelta(hours=3),
        title="Old title",
        reminder_sent_at=now,
    )

    updated = update_booking(booking=booking, title="New title", changed_by=user)

    assert updated.reminder_sent_at == booking.reminder_sent_at
