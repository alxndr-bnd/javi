from django import forms
from django.utils.translation import gettext_lazy as _

from common.phone import InvalidPhone, normalize_phone
from common.text import SHOP_NAME_MAX_LEN, clean_shop_name
from common.validators import validate_https_url

INVALID_PHONE_MSG = _("Invalid number. E.g. 064 123 4567")


class ShopOriginForm(forms.Form):
    """Название + адрес магазина (origin) + настройки исходящих вебхуков.

    Геокодинг адреса — в сервисе после валидации.
    """

    name = forms.CharField(
        label=_("Store name"),
        max_length=SHOP_NAME_MAX_LEN,
        widget=forms.TextInput(attrs={"autocomplete": "organization"}),
    )
    address = forms.CharField(
        label=_("Store address"),
        max_length=300,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "street-address",
                "placeholder": "Knez Mihailova 6, Beograd",
            }
        ),
    )
    webhook_url = forms.URLField(
        label=_("Webhook URL"),
        required=False,
        assume_scheme="https",
        validators=[validate_https_url],
        widget=forms.URLInput(attrs={"placeholder": "https://your-shop.example/javi-webhook"}),
    )
    # Только запись (SERBITO-362, JAVI-10): сохранённый секрет в форму не возвращаем —
    # пустое поле = оставить как есть, clear_webhook_secret = удалить.
    webhook_secret = forms.CharField(
        label=_("Webhook secret"),
        max_length=200,
        required=False,
        strip=True,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}, render_value=False),
    )
    clear_webhook_secret = forms.BooleanField(label=_("Remove the secret"), required=False)

    def clean_name(self):
        # Название уходит в Viber/SMS клиентам — без ссылок и номеров (SERBITO-345).
        return clean_shop_name(self.cleaned_data["name"])


class DeliveryForm(forms.Form):
    """Создание доставки: телефон первым (автоподстановка клиента), имя, адрес (+ описание)."""

    recipient_phone = forms.CharField(
        label=_("Phone"),
        max_length=32,
        widget=forms.TextInput(
            attrs={"inputmode": "tel", "placeholder": "064 123 4567", "autofocus": True}
        ),
    )
    recipient_name = forms.CharField(label=_("Name"), max_length=200)
    dest_address = forms.CharField(
        label=_("Address"),
        max_length=300,
        widget=forms.TextInput(
            attrs={"autocomplete": "street-address", "placeholder": _("Street and number, city")}
        ),
    )
    description = forms.CharField(label=_("Description (optional)"), max_length=300, required=False)

    def clean_recipient_phone(self):
        raw = self.cleaned_data["recipient_phone"]
        try:
            result = normalize_phone(raw)
        except InvalidPhone as exc:
            raise forms.ValidationError(INVALID_PHONE_MSG) from exc
        self.cleaned_data["phone_result"] = result
        return result.e164


class RecipientPhoneForm(forms.Form):
    """Правка номера получателя при переотправке (FR-25)."""

    recipient_phone = forms.CharField(label=_("Phone"), max_length=32)

    def clean_recipient_phone(self):
        try:
            result = normalize_phone(self.cleaned_data["recipient_phone"])
        except InvalidPhone as exc:
            raise forms.ValidationError(INVALID_PHONE_MSG) from exc
        self.cleaned_data["phone_result"] = result
        return result.e164


class ManualEtaForm(forms.Form):
    """Ручной ввод ETA при недоступности маршрута (FR-9)."""

    eta_time = forms.TimeField(
        label=_("Arrival time (HH:MM)"),
        input_formats=["%H:%M"],
        widget=forms.TimeInput(
            format="%H:%M", attrs={"inputmode": "numeric", "placeholder": "16:00"}
        ),
    )
