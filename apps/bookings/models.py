from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.resources.models import Resource


class BookingStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    CONFIRMED = "CONFIRMED", "Confirmed"
    CANCELLED = "CANCELLED", "Cancelled"
    COMPLETED = "COMPLETED", "Completed"


class Booking(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings"
    )

    resource = models.ForeignKey(
        Resource, on_delete=models.PROTECT, related_name="bookings"
    )
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()

    status = models.CharField(
        max_length=20, choices=BookingStatus.choices, default=BookingStatus.CONFIRMED
    )

    title = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-start_at", "-created_at")

        constraints = [
            models.CheckConstraint(
                condition=Q(end_at__gt=F("start_at")), name="booking_end_at_gt_start_at"
            ),
        ]

        indexes = [
            models.Index(fields=("start_at",), name="booking_start_idx"),
            models.Index(fields=("end_at",), name="booking_end_idx"),
            models.Index(fields=("status",), name="booking_status_idx"),
            models.Index(
                fields=("resource", "start_at", "end_at"),
                name="booking_resource_time_idx",
            ),
            models.Index(
                fields=("status", "reminder_sent_at", "start_at"),
                name="booking_reminder_idx",
            ),
        ]

    def __str__(self):
        return f"{self.resource} | {self.start_at:%Y-%m-%d %H:%M} - {self.end_at:%H:%M}"
