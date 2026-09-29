from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils.translation import gettext_lazy as _

from common.text import SHOP_NAME_MAX_LEN, clean_shop_name

from .lockout import is_locked

User = get_user_model()


class RegisterForm(UserCreationForm):
    """Self-service signup: email, store name and a password."""

    store_name = forms.CharField(
        label=_("Store name"),
        max_length=SHOP_NAME_MAX_LEN,
        widget=forms.TextInput(attrs={"autocomplete": "organization"}),
    )

    class Meta:
        model = User
        fields = ("email",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs.update(
            {"autocomplete": "email", "autofocus": True}
        )
        self.fields["password1"].widget.attrs.update({"autocomplete": "new-password"})
        self.fields["password2"].widget.attrs.update({"autocomplete": "new-password"})

    def clean_store_name(self):
        # Название уходит в Viber/SMS клиентам — без ссылок и номеров (SERBITO-345).
        return clean_shop_name(self.cleaned_data["store_name"])

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"]).lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("An account with this email already exists."))
        return email


class LoginForm(AuthenticationForm):
    """Sign-in that says so when it is locked after too many failures (SERBITO-362)."""

    error_messages = {
        **AuthenticationForm.error_messages,
        "locked": _("Too many failed sign-in attempts. Try again in %(minutes)d minutes."),
    }

    def clean(self):
        if is_locked(self.request, self.data.get("username")):
            raise forms.ValidationError(
                self.error_messages["locked"],
                code="locked",
                params={"minutes": settings.LOGIN_LOCKOUT_MINUTES},
            )
        return super().clean()
