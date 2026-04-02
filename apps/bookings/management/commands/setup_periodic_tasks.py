import json

from django.core.management.base import BaseCommand
from django_celery_beat.models import IntervalSchedule, PeriodicTask


class Command(BaseCommand):
    help = "Create or update Booking Management System periodic Celery tasks."

    def handle(self, *args, **options):
        every_minute, _ = IntervalSchedule.objects.get_or_create(
            every=1, period=IntervalSchedule.MINUTES
        )

        periodic_tasks = [
            {
                "name": ("Complete expired bookings"),
                "task": ("bookings.complete_expired_bookings"),
                "kwargs": {},
                "description": (
                    "Automatically completes "
                    "confirmed bookings whose "
                    "end time has passed."
                ),
            },
            {
                "name": ("Send upcoming booking reminders"),
                "task": ("bookings.send_upcoming_booking_reminders"),
                "kwargs": {
                    "minutes_before": 60,
                    "batch_size": 100,
                },
                "description": (
                    "Queues one reminder for "
                    "confirmed bookings starting "
                    "within the next hour."
                ),
            },
        ]

        for task_config in periodic_tasks:
            periodic_task, created = PeriodicTask.objects.update_or_create(
                name=task_config["name"],
                defaults={
                    "task": (task_config["task"]),
                    "interval": every_minute,
                    "enabled": True,
                    "args": "[]",
                    "kwargs": json.dumps(task_config["kwargs"]),
                    "description": (task_config["description"]),
                },
            )

            action = "Created" if created else "Updated"

            self.stdout.write(
                self.style.SUCCESS(f"{action} periodic task: {periodic_task.name}")
            )
