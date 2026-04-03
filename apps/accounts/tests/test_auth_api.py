import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import UserRole

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user():
    return User.objects.create_user(
        email="user@example.com",
        password="StrongPassword123!",
        first_name="John",
        last_name="Doe",
    )


@pytest.mark.django_db
def test_register_user(api_client):
    url = reverse("accounts:register")

    payload = {
        "email": "new@example.com",
        "password": "StrongPassword123!",
        "first_name": "New",
        "last_name": "User",
    }

    response = api_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_201_CREATED

    assert User.objects.filter(email="new@example.com").exists()

    created_user = User.objects.get(email="new@example.com")

    assert created_user.role == UserRole.USER
    assert created_user.check_password("StrongPassword123!")

    assert "password" not in response.data


@pytest.mark.django_db
def test_register_duplicate_email(api_client, user):
    url = reverse("accounts:register")

    payload = {
        "email": user.email,
        "password": "AnotherStrongPassword123!",
        "first_name": "Another",
        "last_name": "User",
    }

    response = api_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert User.objects.filter(email=user.email).count() == 1


@pytest.mark.django_db
def test_login_returns_tokens(api_client, user):
    url = reverse("accounts:login")

    payload = {"email": user.email, "password": "StrongPassword123!"}

    response = api_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_200_OK

    assert "access" in response.data
    assert "refresh" in response.data


@pytest.mark.django_db
def test_login_with_invalid_password(api_client, user):
    url = reverse("accounts:login")

    payload = {"email": user.email, "password": "WrongPassword123!"}

    response = api_client.post(url, payload, format="json")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_me_requires_authentication(api_client):
    url = reverse("accounts:me")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_me_returns_current_user(api_client, user):
    url = reverse("accounts:me")

    api_client.force_authenticate(user=user)

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK

    assert response.data["id"] == user.id
    assert response.data["email"] == user.email
    assert response.data["first_name"] == user.first_name
    assert response.data["last_name"] == user.last_name
    assert response.data["role"] == UserRole.USER


@pytest.mark.django_db
def test_refresh_token_returns_new_access_token(api_client, user):
    refresh = RefreshToken.for_user(user)

    url = reverse("accounts:token-refresh")

    response = api_client.post(url, {"refresh": str(refresh)}, format="json")

    assert response.status_code == status.HTTP_200_OK
    assert "access" in response.data


@pytest.mark.django_db
def test_registration_cannot_set_admin_role(api_client):
    response = api_client.post(
        reverse("accounts:register"),
        {
            "email": "attacker@example.com",
            "password": ("StrongPassword123!"),
            "first_name": "Attacker",
            "role": "ADMIN",
        },
        format="json",
    )

    assert response.status_code == 201

    user = User.objects.get(email="attacker@example.com")

    assert user.role == UserRole.USER
    assert user.is_staff is False
    assert user.is_superuser is False
