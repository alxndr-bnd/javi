from django.contrib import admin

from .models import Delivery, Shop


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "created_at")
    search_fields = ("name", "owner__email")


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ("recipient_name", "shop", "status", "dest_address", "created_at")
    list_filter = ("status", "shop")
    search_fields = ("recipient_name", "recipient_phone", "dest_address")
