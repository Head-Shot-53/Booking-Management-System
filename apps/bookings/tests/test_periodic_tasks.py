import pytest
from django.core.management import call_command
from django_celery_beat.models import PeriodicTask


@pytest.mark.django_db
def test_setup_periodic_tasks_creates_completion_task():
    call_command("setup_periodic_tasks")

    periodic_task = PeriodicTask.objects.get(name="Complete expired bookings")

    assert periodic_task.task == "bookings.complete_expired_bookings"

    assert periodic_task.enabled is True

    assert periodic_task.interval.every == 1


@pytest.mark.django_db
def test_setup_periodic_tasks_is_idempotent():
    call_command("setup_periodic_tasks")

    call_command("setup_periodic_tasks")

    assert PeriodicTask.objects.filter(name="Complete expired bookings").count() == 1


@pytest.mark.django_db
def test_setup_creates_reminder_periodic_task():
    call_command("setup_periodic_tasks")

    periodic_task = PeriodicTask.objects.get(name=("Send upcoming booking reminders"))

    assert periodic_task.task == ("bookings.send_upcoming_booking_reminders")

    assert periodic_task.enabled is True
    assert periodic_task.interval.every == 1


@pytest.mark.django_db
def test_setup_periodic_tasks_remains_idempotent():
    call_command("setup_periodic_tasks")

    call_command("setup_periodic_tasks")

    assert PeriodicTask.objects.filter(name="Complete expired bookings").count() == 1

    assert (
        PeriodicTask.objects.filter(name=("Send upcoming booking reminders")).count()
        == 1
    )
