from django import forms


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
