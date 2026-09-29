"""Общие фикстуры pytest для всего репозитория."""

import pytest
from django.test import override_settings


@pytest.fixture(scope="session", autouse=True)
def _static_root(tmp_path_factory):
    """STATIC_ROOT — пустой временный каталог на всю сессию.

    Тесты идут без collectstatic, поэтому ./staticfiles/ в CI нет, и WhiteNoise на каждом
    новом тестовом клиенте предупреждал «No directory at: …/staticfiles/» (~136 раз,
    SERBITO-289). Существующий каталог устраняет причину, не глуша предупреждения и не
    меняя режим WhiteNoise (autorefresh/finders), так что тесты идут по пути прода.
    Локальный ./staticfiles/ (после collectstatic) тестам тоже не виден — как в CI.
    """
    with override_settings(STATIC_ROOT=tmp_path_factory.mktemp("staticfiles")):
        yield


@pytest.fixture(scope="session", autouse=True)
def _fast_password_hasher():
    """Быстрый хешер паролей в тестах (SERBITO-364).

    PBKDF2 по умолчанию стоит ~0,1–0,3 с на каждый create_user/вход, а тесты создают
    магазины сотнями: хеширование было больше половины времени всего гейта. Что проверяют
    тесты — вход, блокировка, лимиты — от алгоритма хеша не зависит; в проде хешер
    по умолчанию не меняется (settings.py его не трогает).
    """
    with override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]):
        yield
