from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("delivery", "kind", "channel", "status", "sent_at", "created_at")
    list_filter = ("kind", "channel", "status")
    search_fields = ("delivery__recipient_name", "provider_message_id")
