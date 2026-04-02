from datetime import time, timedelta

import pytest
from django.contrib.auth import get_user_model

from apps.resources.models import Resource, ResourceCategory

User = get_user_model()


@pytest.fixture
def user():
    return User.objects.create_user(
        email="user@example.com",
        password="StrongPassword123!",
    )


@pytest.fixture
def category():
    return ResourceCategory.objects.create(
        name="Meeting Room",
        slug="meeting-room",
    )


@pytest.fixture
def resource(category):
    return Resource.objects.create(
        name="Conference Room A",
        slug="conference-room-a",
        category=category,
        location="Building A",
        capacity=10,
        booking_min_duration=timedelta(minutes=30),
        booking_max_duration=timedelta(hours=4),
        available_from=time(8, 0),
        available_to=time(20, 0),
    )
