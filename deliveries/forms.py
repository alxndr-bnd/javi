from django import forms

from common.phone import InvalidPhone, normalize_phone


class ShopOriginForm(forms.Form):
    """Адрес магазина (origin). Геокодинг — в сервисе после валидации формы."""

    address = forms.CharField(
        label="Adresa prodavnice",
        max_length=300,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "street-address",
                "placeholder": "Npr. Knez Mihailova 6, Beograd",
            }
        ),
    )


class DeliveryForm(forms.Form):
    """Создание доставки: имя, телефон, адрес получателя (+ описание опц.)."""

    recipient_name = forms.CharField(label="Ime", max_length=200)
    recipient_phone = forms.CharField(
        label="Telefon",
        max_length=32,
        widget=forms.TextInput(attrs={"inputmode": "tel", "placeholder": "064 123 4567"}),
    )
    dest_address = forms.CharField(
        label="Adresa",
        max_length=300,
        widget=forms.TextInput(
            attrs={"autocomplete": "street-address", "placeholder": "Ulica i broj, grad"}
        ),
    )
    description = forms.CharField(label="Opis (opciono)", max_length=300, required=False)

    def clean_recipient_phone(self):
        raw = self.cleaned_data["recipient_phone"]
        try:
            result = normalize_phone(raw)
        except InvalidPhone as exc:
            raise forms.ValidationError("Neispravan broj. Npr. 064 123 4567") from exc
        # Кладём разобранный номер для view/сервиса; в поле — нормализованный E.164.
        self.cleaned_data["phone_result"] = result
        return result.e164


class ManualEtaForm(forms.Form):
    """Ручной ввод ETA при недоступности маршрута (FR-9)."""

    eta_time = forms.TimeField(
        label="Vreme dolaska (HH:MM)",
        input_formats=["%H:%M"],
        widget=forms.TimeInput(
            format="%H:%M", attrs={"inputmode": "numeric", "placeholder": "16:00"}
        ),
    )
