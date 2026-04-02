from datetime import date, datetime, timedelta

from django.db.models import QuerySet
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.resources.models import Resource

from .models import Booking, BookingStatus


def can_manage_all_bookings(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and (
            getattr(user, "is_superuser", False)
            or getattr(user, "role", None)
            in {
                UserRole.MANAGER,
                UserRole.ADMIN,
            }
        )
    )


def get_bookings_for_user(*, user) -> QuerySet[Booking]:
    queryset = Booking.objects.select_related("user", "resource", "resource__category")

    if can_manage_all_bookings(user):
        return queryset

    return queryset.filter(user=user)


def _resource_day_boundary(*, target_date: date, time_value) -> datetime:
    naive_datetime = datetime.combine(target_date, time_value)

    return timezone.make_aware(naive_datetime, timezone.get_current_timezone())


def get_resource_availability(*, resource: Resource, target_date: date) -> dict:
    current_timezone = timezone.get_current_timezone()

    window_start = _resource_day_boundary(
        target_date=target_date, time_value=resource.available_from
    )

    window_end = _resource_day_boundary(
        target_date=target_date, time_value=resource.available_to
    )

    bookings = (
        Booking.objects.filter(
            resource=resource, start_at__lt=window_end, end_at__gt=window_start
        )
        .exclude(status=BookingStatus.CANCELLED)
        .order_by("start_at")
        .values_list("start_at", "end_at")
    )

    busy_intervals = []

    for start_at, end_at in bookings:
        local_start = timezone.localtime(start_at, current_timezone)

        local_end = timezone.localtime(end_at, current_timezone)

        busy_start = max(local_start, window_start)

        busy_end = min(local_end, window_end)

        if busy_start >= busy_end:
            continue

        if busy_intervals and busy_start <= busy_intervals[-1][1]:
            previous_start, previous_end = busy_intervals[-1]

            busy_intervals[-1] = (previous_start, max(previous_end, busy_end))
        else:
            busy_intervals.append((busy_start, busy_end))

    available_intervals = []
    cursor = window_start

    for busy_start, busy_end in busy_intervals:
        if cursor < busy_start:
            free_duration = busy_start - cursor

            if free_duration >= resource.booking_min_duration:
                available_intervals.append((cursor, busy_start))

        cursor = max(cursor, busy_end)

    if cursor < window_end:
        free_duration = window_end - cursor

        if free_duration >= resource.booking_min_duration:
            available_intervals.append((cursor, window_end))

    return {
        "resource": {"id": resource.id, "name": resource.name},
        "date": target_date.isoformat(),
        "timezone": str(current_timezone),
        "working_hours": {
            "available_from": (resource.available_from.isoformat()),
            "available_to": (resource.available_to.isoformat()),
        },
        "busy_slots": [
            {"start_at": start_at.isoformat(), "end_at": end_at.isoformat()}
            for start_at, end_at in busy_intervals
        ],
        "available_slots": [
            {"start_at": start_at.isoformat(), "end_at": end_at.isoformat()}
            for start_at, end_at in available_intervals
        ],
    }


def get_expired_confirmed_booking_ids(
    *, current_time: datetime, limit: int = 100
) -> list[int]:
    return list(
        Booking.objects.filter(status=BookingStatus.CONFIRMED, end_at__lte=current_time)
        .order_by("end_at", "id")
        .values_list("id", flat=True)[:limit]
    )


def get_upcoming_booking_reminder_ids(
    *,
    current_time: datetime,
    reminder_window: timedelta = timedelta(hours=1),
    limit: int = 100,
) -> list[int]:

    window_end = current_time + reminder_window

    return list(
        Booking.objects.filter(
            status=BookingStatus.CONFIRMED,
            reminder_sent_at__isnull=True,
            start_at__gt=current_time,
            start_at__lte=window_end,
        )
        .order_by("start_at", "id")
        .values_list(
            "id",
            flat=True,
        )[:limit]
    )
