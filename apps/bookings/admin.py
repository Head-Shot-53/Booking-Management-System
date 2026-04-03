from django.contrib import admin

from .models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "user", "resource", "start_at", "end_at", "status")

    list_filter = ("status", "resource", "start_at")
    search_fields = ("title", "user__email", "resource__name")

    readonly_fields = (
        "id",
        "user",
        "resource",
        "start_at",
        "end_at",
        "status",
        "title",
        "notes",
        "cancelled_at",
        "reminder_sent_at",
        "created_at",
        "updated_at",
    )

    def has_view_permission(self, request, obj=None):
        return request.user.is_staff

    def has_add_permission(
        self,
        request,
    ):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
