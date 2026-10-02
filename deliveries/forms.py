from datetime import datetime

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from common.i18n import CUSTOMER_LANGUAGES, DEFAULT_CUSTOMER_LANGUAGE
from common.phone import InvalidPhone, normalize_phone
from common.text import SHOP_NAME_MAX_LEN, clean_shop_name
from common.timewindow import BELGRADE
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
    contact_phone = forms.CharField(
        label=_("Phone for customers (optional)"),
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={"inputmode": "tel", "autocomplete": "tel"}),
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

    def clean_contact_phone(self):
        # Только на странице статуса (не в SMS), поэтому годится и городской номер.
        raw = self.cleaned_data["contact_phone"].strip()
        if not raw:
            return ""
        try:
            return normalize_phone(raw).e164
        except InvalidPhone as exc:
            raise forms.ValidationError(INVALID_PHONE_MSG) from exc


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
    # Язык SMS/Viber и страницы статуса для этого клиента (SERBITO-356), по умолчанию сербский.
    recipient_language = forms.ChoiceField(
        label=_("Customer's language"),
        choices=CUSTOMER_LANGUAGES,
        initial=DEFAULT_CUSTOMER_LANGUAGE,
        required=False,  # старые клиенты формы/скрипты без поля — сербский
    )
    dest_address = forms.CharField(
        label=_("Address"),
        max_length=300,
        widget=forms.TextInput(
            attrs={"autocomplete": "street-address", "placeholder": _("Street and number, city")}
        ),
    )
    description = forms.CharField(label=_("Description (optional)"), max_length=300, required=False)

    def clean_recipient_language(self):
        return self.cleaned_data.get("recipient_language") or DEFAULT_CUSTOMER_LANGUAGE

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
    """Время прибытия на экране подтверждения (FR-9): дата + время, только в будущем.

    Дата (SERBITO-356): без неё ETA после полуночи или на завтра не задать, а прошедшее
    время принималось и висело на странице клиента как «stiže do 14:00».
    """

    eta_date = forms.DateField(
        label=_("Arrival date"),
        required=False,  # старые формы без даты — сегодня
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    eta_time = forms.TimeField(
        label=_("Arrival time (HH:MM)"),
        input_formats=["%H:%M"],
        widget=forms.TimeInput(
            format="%H:%M", attrs={"inputmode": "numeric", "placeholder": "16:00"}
        ),
    )

    def clean(self):
        cleaned = super().clean()
        eta_time = cleaned.get("eta_time")
        if eta_time is None:
            return cleaned
        day = cleaned.get("eta_date") or timezone.now().astimezone(BELGRADE).date()
        eta_at = datetime.combine(day, eta_time, tzinfo=BELGRADE)
        if eta_at <= timezone.now():
            raise forms.ValidationError(
                _("This time has already passed. Enter a time in the future."), code="past"
            )
        cleaned["eta_at"] = eta_at
        return cleaned
