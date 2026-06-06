from django.contrib import admin

from .models import ApiKey, Delivery, Shop


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "created_at")
    search_fields = ("name", "owner__email")


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("masked", "shop", "name", "created_at", "last_used_at", "revoked_at")
    list_filter = ("shop",)
    search_fields = ("prefix", "name", "shop__name")
    readonly_fields = ("prefix", "key_hash", "created_at", "last_used_at")


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ("recipient_name", "shop", "status", "dest_address", "created_at")
    list_filter = ("status", "shop")
    search_fields = ("recipient_name", "recipient_phone", "dest_address")
