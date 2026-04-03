import logging
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.audit.models import BookingHistoryAction
from apps.audit.services import get_booking_snapshot, record_booking_history
from apps.resources.models import Resource

from .exceptions import BookingConflictError, BookingStateError, BookingValidationError
from .models import Booking, BookingStatus
from .notifications import schedule_booking_cancellation, schedule_booking_confirmation

logger = logging.getLogger("booking_management.booking")


def validate_booking_creation(
    *, resource: Resource, start_at: datetime, end_at: datetime
) -> None:
    _validate_timezone_awareness(start_at=start_at, end_at=end_at)

    _validate_time_range(start_at=start_at, end_at=end_at)

    _validate_not_in_past(start_at=start_at)

    _validate_resource_is_active(resource=resource)

    _validate_duration(resource=resource, start_at=start_at, end_at=end_at)

    _validate_working_hours(resource=resource, start_at=start_at, end_at=end_at)


def _validate_timezone_awareness(*, start_at: datetime, end_at: datetime) -> None:
    if timezone.is_naive(start_at) or timezone.is_naive(end_at):
        raise BookingValidationError(
            "Booking datetimes must be timezone-aware.", code="timezone_aware_required"
        )


def _validate_time_range(*, start_at: datetime, end_at: datetime) -> None:
    if start_at >= end_at:
        raise BookingValidationError(
            "Booking end time must be after start time.", code="invalid_time_range"
        )


def _validate_not_in_past(*, start_at: datetime) -> None:
    if start_at < timezone.now():
        raise BookingValidationError(
            "Booking cannot be created in the past.", code="booking_in_past"
        )


def _validate_resource_is_active(*, resource: Resource) -> None:
    if not resource.is_active:
        raise BookingValidationError(
            "Inactive resources cannot be booked.", code="resource_inactive"
        )


def _validate_duration(
    *, resource: Resource, start_at: datetime, end_at: datetime
) -> None:
    duration = end_at - start_at

    if duration < resource.booking_min_duration:
        raise BookingValidationError(
            "Booking duration is shorter than the minimum allowed duration.",
            code="duration_too_short",
        )

    if duration > resource.booking_max_duration:
        raise BookingValidationError(
            "Booking duration exceeds the maximum allowed duration.",
            code="duration_too_long",
        )


def _validate_working_hours(
    *, resource: Resource, start_at: datetime, end_at: datetime
) -> None:
    start_local = timezone.localtime(start_at)
    end_local = timezone.localtime(end_at)

    if start_local.date() != end_local.date():
        raise BookingValidationError(
            "Booking must start and end on the same day.", code="cross_day_booking"
        )

    if (
        start_local.time() < resource.available_from
        or end_local.time() > resource.available_to
    ):
        raise BookingValidationError(
            "Booking must be within resource working hours.",
            code="outside_working_hours",
        )


def _lock_resource(*, resource: Resource) -> Resource:
    return Resource.objects.select_for_update().get(pk=resource.pk)


@transaction.atomic
def create_booking(
    *,
    user,
    resource: Resource,
    start_at: datetime,
    end_at: datetime,
    title: str,
    notes: str = "",
    changed_by=None,
) -> Booking:
    locked_resource = _lock_resource(resource=resource)

    validate_booking_creation(
        resource=locked_resource, start_at=start_at, end_at=end_at
    )

    _validate_no_booking_conflict(
        resource=locked_resource, start_at=start_at, end_at=end_at
    )

    booking = Booking.objects.create(
        user=user,
        resource=locked_resource,
        start_at=start_at,
        end_at=end_at,
        title=title,
        notes=notes,
    )

    record_booking_history(
        booking=booking,
        action=BookingHistoryAction.CREATED,
        changed_by=changed_by,
        old_data={},
        new_data=get_booking_snapshot(booking),
    )

    schedule_booking_confirmation(booking_id=booking.id)

    logger.info(
        "booking_created",
        extra={
            "booking_id": booking.id,
            "resource_id": booking.resource_id,
            "owner_id": booking.user_id,
            "actor_id": getattr(
                changed_by,
                "id",
                None,
            ),
        },
    )

    return booking


def check_booking_conflict(
    *,
    resource: Resource,
    start_at: datetime,
    end_at: datetime,
    exclude_booking_id: int | None = None,
) -> bool:
    queryset = Booking.objects.filter(
        resource=resource, start_at__lt=end_at, end_at__gt=start_at
    ).exclude(
        status=BookingStatus.CANCELLED,
    )

    if exclude_booking_id is not None:
        queryset = queryset.exclude(pk=exclude_booking_id)

    return queryset.exists()


def _validate_no_booking_conflict(
    *,
    resource: Resource,
    start_at: datetime,
    end_at: datetime,
    exclude_booking_id: int | None = None,
) -> None:

    if check_booking_conflict(
        resource=resource,
        start_at=start_at,
        end_at=end_at,
        exclude_booking_id=exclude_booking_id,
    ):
        raise BookingConflictError()


def _lock_booking(*, booking: Booking) -> Booking:
    return (
        Booking.objects.select_for_update()
        .select_related("resource", "user")
        .get(pk=booking.pk)
    )


def _lock_resources_by_ids(*, resource_ids: list[int]) -> dict[int, Resource]:
    unique_ids = sorted(set(resource_ids))

    resources = list(
        Resource.objects.select_for_update().filter(pk__in=unique_ids).order_by("pk")
    )

    if len(resources) != len(unique_ids):
        raise Resource.DoesNotExist("One or more resources do not exist.")

    return {resource.pk: resource for resource in resources}


def _validate_booking_can_be_updated(*, booking: Booking) -> None:
    if booking.status in {BookingStatus.CANCELLED, BookingStatus.COMPLETED}:
        raise BookingStateError(
            "Cancelled or completed bookings cannot be updated.",
            code="booking_not_editable",
        )

    if booking.start_at <= timezone.now():
        raise BookingStateError(
            "Booking cannot be updated after it has started.",
            code="booking_already_started",
        )


@transaction.atomic
def update_booking(
    *,
    booking: Booking,
    resource: Resource | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    title: str | None = None,
    notes: str | None = None,
    changed_by=None,
) -> Booking:
    locked_booking = _lock_booking(booking=booking)

    _validate_booking_can_be_updated(booking=locked_booking)

    old_data = get_booking_snapshot(locked_booking)

    target_resource_id = (
        resource.pk if resource is not None else locked_booking.resource_id
    )

    locked_resources = _lock_resources_by_ids(
        resource_ids=[locked_booking.resource_id, target_resource_id]
    )

    target_resource = locked_resources[target_resource_id]

    target_start_at = start_at if start_at is not None else locked_booking.start_at

    target_end_at = end_at if end_at is not None else locked_booking.end_at

    target_title = title if title is not None else locked_booking.title

    target_notes = notes if notes is not None else locked_booking.notes

    validate_booking_creation(
        resource=target_resource,
        start_at=target_start_at,
        end_at=target_end_at,
    )

    _validate_no_booking_conflict(
        resource=target_resource,
        start_at=target_start_at,
        end_at=target_end_at,
        exclude_booking_id=locked_booking.id,
    )

    schedule_changed = (
        target_start_at != locked_booking.start_at
        or target_end_at != locked_booking.end_at
    )

    locked_booking.resource = target_resource
    locked_booking.start_at = target_start_at
    locked_booking.end_at = target_end_at
    locked_booking.title = target_title
    locked_booking.notes = target_notes

    if schedule_changed:
        locked_booking.reminder_sent_at = None

    new_data = get_booking_snapshot(locked_booking)

    if old_data == new_data:
        return locked_booking

    update_fields = [
        "resource",
        "start_at",
        "end_at",
        "title",
        "notes",
        "updated_at",
    ]

    if schedule_changed:
        update_fields.append("reminder_sent_at")

    locked_booking.save(update_fields=update_fields)

    record_booking_history(
        booking=locked_booking,
        action=BookingHistoryAction.UPDATED,
        changed_by=changed_by,
        old_data=old_data,
        new_data=new_data,
    )

    logger.info(
        "booking_updated",
        extra={
            "booking_id": locked_booking.id,
            "resource_id": locked_booking.resource_id,
            "owner_id": locked_booking.user_id,
            "actor_id": getattr(
                changed_by,
                "id",
                None,
            ),
        },
    )

    return locked_booking


@transaction.atomic
def cancel_booking(*, booking: Booking, changed_by=None) -> Booking:
    locked_booking = _lock_booking(booking=booking)

    if locked_booking.status not in {BookingStatus.PENDING, BookingStatus.CONFIRMED}:
        raise BookingStateError(
            "Only pending or confirmed bookings can be cancelled.",
            code="booking_cannot_be_cancelled",
        )

    old_data = get_booking_snapshot(locked_booking)

    locked_booking.status = BookingStatus.CANCELLED
    locked_booking.cancelled_at = timezone.now()

    locked_booking.save(update_fields=["status", "cancelled_at", "updated_at"])

    record_booking_history(
        booking=locked_booking,
        action=BookingHistoryAction.CANCELLED,
        changed_by=changed_by,
        old_data=old_data,
        new_data=get_booking_snapshot(locked_booking),
    )

    schedule_booking_cancellation(booking_id=locked_booking.id)

    logger.info(
        "booking_cancelled",
        extra={
            "booking_id": locked_booking.id,
            "resource_id": (locked_booking.resource_id),
            "owner_id": locked_booking.user_id,
            "actor_id": getattr(
                changed_by,
                "id",
                None,
            ),
        },
    )

    return locked_booking


@transaction.atomic
def complete_booking(*, booking: Booking, changed_by=None) -> Booking:
    locked_booking = _lock_booking(booking=booking)

    if locked_booking.status != BookingStatus.CONFIRMED:
        raise BookingStateError(
            "Only confirmed bookings can be completed.",
            code="booking_cannot_be_completed",
        )

    if locked_booking.end_at > timezone.now():
        raise BookingStateError(
            "Booking cannot be completed before it ends.", code="booking_not_finished"
        )

    old_data = get_booking_snapshot(locked_booking)

    locked_booking.status = BookingStatus.COMPLETED

    locked_booking.save(update_fields=["status", "updated_at"])

    record_booking_history(
        booking=locked_booking,
        action=BookingHistoryAction.COMPLETED,
        changed_by=changed_by,
        old_data=old_data,
        new_data=get_booking_snapshot(locked_booking),
    )

    logger.info(
        "booking_completed",
        extra={
            "booking_id": locked_booking.id,
            "resource_id": (locked_booking.resource_id),
            "owner_id": locked_booking.user_id,
            "actor_id": getattr(
                changed_by,
                "id",
                None,
            ),
        },
    )

    return locked_booking
