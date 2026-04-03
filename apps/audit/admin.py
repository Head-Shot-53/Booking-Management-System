from django.contrib import admin

from .models import BookingHistory


@admin.register(BookingHistory)
class BookingHistoryAdmin(admin.ModelAdmin):
    list_display = ("booking", "action", "changed_by", "created_at")

    list_filter = ("action", "created_at")

    search_fields = ("booking__title", "booking__user__email", "changed_by__email")

    readonly_fields = (
        "booking",
        "changed_by",
        "action",
        "old_data",
        "new_data",
        "created_at",
    )

    ordering = ("-created_at",)

    list_select_related = ("booking", "changed_by")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_staff
