from datetime import datetime, time, timedelta
from threading import Barrier, Lock, Thread
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.utils import timezone

from apps.bookings.exceptions import BookingConflictError
from apps.bookings.models import Booking
from apps.bookings.services import create_booking
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


@pytest.mark.django_db(transaction=True)
def test_concurrent_booking_creation_allows_only_one(user, resource):
    if connection.vendor != "postgresql":
        pytest.skip("Concurrency locking test requires PostgreSQL.")

    user_id = user.id
    resource_id = resource.id

    start_at = future_datetime(10)
    end_at = future_datetime(11)

    barrier = Barrier(2)
    results = []
    results_lock = Lock()

    def create_booking_in_thread(title):
        close_old_connections()

        result = None

        try:
            thread_user = User.objects.get(pk=user_id)
            thread_resource = Resource.objects.get(pk=resource_id)

            barrier.wait(timeout=5)

            booking = create_booking(
                user=thread_user,
                resource=thread_resource,
                start_at=start_at,
                end_at=end_at,
                title=title,
            )

            result = ("created", booking.id)

        except BookingConflictError:
            result = ("conflict", None)

        except Exception as exc:
            result = ("error", exc)

        finally:
            close_old_connections()

            with results_lock:
                results.append(result)

    thread_a = Thread(target=create_booking_in_thread, args=("Booking A",))

    thread_b = Thread(target=create_booking_in_thread, args=("Booking B",))

    with patch("apps.bookings.tasks.send_booking_confirmation_email.delay"):
        thread_a.start()
        thread_b.start()

        thread_a.join(timeout=10)
        thread_b.join(timeout=10)

    assert not thread_a.is_alive()
    assert not thread_b.is_alive()

    errors = [result for result in results if result[0] == "error"]

    assert errors == []

    statuses = [result[0] for result in results]

    assert statuses.count("created") == 1
    assert statuses.count("conflict") == 1

    assert Booking.objects.count() == 1
