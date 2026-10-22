import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from django.utils import translation

from deliveries.models import Shop

pytestmark = pytest.mark.django_db


def test_create_shop_command():
    """AC#1/#2: команда create_shop заводит пользователя и магазин."""
    call_command(
        "create_shop",
        email="milan@pizza.rs",
        password="pass12345",
        name="Pizza Napoli",
    )
    user = get_user_model().objects.get(email="milan@pizza.rs")
    assert user.check_password("pass12345")
    assert Shop.objects.get(owner=user).name == "Pizza Napoli"


def test_email_login(client):
    """AC#2: вход по email + паролю."""
    call_command("create_shop", email="a@shop.rs", password="pass12345", name="A")
    assert client.login(username="a@shop.rs", password="pass12345")


def test_register_get_renders_form(client):
    """GET на /accounts/register/ отдаёт форму."""
    resp = client.get(reverse("accounts:register"))
    assert resp.status_code == 200
    assert b'name="email"' in resp.content
    assert b'name="store_name"' in resp.content


def test_register_creates_user_shop_and_authenticates(client):
    """Регистрация заводит User + связанный Shop и логинит (редирект на /app/)."""
    resp = client.post(
        reverse("accounts:register"),
        {
            "email": "Nina@Shop.rs",
            "store_name": "Nina Bakery",
            "password1": "s3cret-pass-9",
            "password2": "s3cret-pass-9",
        },
    )
    assert resp.status_code == 302
    assert resp.url == "/app/"
    user = get_user_model().objects.get(email="nina@shop.rs")
    assert user.check_password("s3cret-pass-9")
    assert Shop.objects.get(owner=user).name == "Nina Bakery"
    # пользователь аутентифицирован в сессии
    assert resp.wsgi_request.user.is_authenticated


def test_register_duplicate_email_rejected(client):
    """Дубликат email отклоняется, второй пользователь не создаётся."""
    call_command("create_shop", email="dup@shop.rs", password="pass12345", name="Existing")
    resp = client.post(
        reverse("accounts:register"),
        {
            "email": "dup@shop.rs",
            "store_name": "Another",
            "password1": "s3cret-pass-9",
            "password2": "s3cret-pass-9",
        },
    )
    assert resp.status_code == 200
    assert get_user_model().objects.filter(email="dup@shop.rs").count() == 1
    assert Shop.objects.count() == 1


def test_register_weak_password_rejected(client):
    """Короткий пароль отклоняется валидаторами; пользователь не создаётся."""
    resp = client.post(
        reverse("accounts:register"),
        {
            "email": "weak@shop.rs",
            "store_name": "Weak",
            "password1": "ab1",
            "password2": "ab1",
        },
    )
    assert resp.status_code == 200
    assert not get_user_model().objects.filter(email="weak@shop.rs").exists()
    assert Shop.objects.count() == 0


@pytest.mark.parametrize("name", ["accounts:login", "accounts:register"])
@pytest.mark.parametrize("lang,home", [("en", "/en/"), ("sr-latn", "/")])
def test_logo_links_to_landing_in_same_language(client, name, lang, home):
    """Логотип на входе и регистрации ведёт на лендинг на языке страницы."""
    client.cookies["django_language"] = lang
    # LocaleMiddleware leaves the language active in this thread: restore it after.
    with translation.override(None):
        resp = client.get(reverse(name))
    assert f'<a class="logo" href="{home}"'.encode() in resp.content
