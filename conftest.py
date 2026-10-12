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


@pytest.fixture(autouse=True)
def _no_funnel_counting():
    """Landing views and sign-up form opens are counted in the DB (SERBITO-595).

    Most tests open the landing without database access; common/test_funnel.py turns counting on.
    """
    with override_settings(FUNNEL_COUNTING=False):
        yield


@pytest.fixture(autouse=True)
def _close_streaming_responses(monkeypatch):
    """Close every test-client response at teardown (SERBITO-613: warnings are errors).

    WhiteNoise serves the landing as a streaming FileResponse. Django closes its file only
    when a test reads the whole body; a test that checks only the status or the headers left
    the file open, and Python reported `ResourceWarning: unclosed file` later, in a random
    test. Production servers always close the response.
    """
    from django.test import Client

    responses = []
    request = Client.request

    def tracked(self, **kwargs):
        response = request(self, **kwargs)
        responses.append(response)
        return response

    monkeypatch.setattr(Client, "request", tracked)
    yield
    for response in responses:
        # Only the file closers: response.close() also sends request_finished, which touches
        # the DB. The test client re-wraps streaming_content, so file_to_stream is None here.
        for close in getattr(response, "_resource_closers", ()):
            close()
