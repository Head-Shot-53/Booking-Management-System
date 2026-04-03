from datetime import timedelta

import pytest
from django.utils import timezone

from apps.bookings.models import Booking


@pytest.fixture
def booking(user, resource):
    start_at = timezone.now() + timedelta(days=1)

    start_at = start_at.replace(
        hour=10,
        minute=0,
        second=0,
        microsecond=0,
    )

    return Booking.objects.create(
        user=user,
        resource=resource,
        start_at=start_at,
        end_at=start_at + timedelta(hours=1),
        title="Test booking",
    )
