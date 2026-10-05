"""SERBITO-430: a request to *.run.app skips Cloudflare in front of javi.serbito.rs.

RunAppHostGuardMiddleware: on a run.app host, GET/HEAD get a 301 to the same path on
PUBLIC_BASE_URL and other methods get a 403. Only the deploy tag host candidate---…run.app is
served. Other hosts are not affected."""

import pytest

from common.run_app_guard import host_name, is_run_app_host, public_origin

SERVICE_HOST = "javi-aay5lcpxha-ew.a.run.app"
REGIONAL_HOST = "javi-488744139718.europe-west1.run.app"
CANDIDATE = "candidate---javi-aay5lcpxha-ew.a.run.app"
REAL = "https://javi.serbito.rs"


@pytest.fixture(autouse=True)
def hosts(settings):
    settings.ALLOWED_HOSTS = ["javi.serbito.rs", ".run.app", "testserver"]
    settings.PUBLIC_BASE_URL = REAL


@pytest.mark.parametrize("host", [SERVICE_HOST, REGIONAL_HOST])
@pytest.mark.parametrize(
    "path", ["/", "/index.html", "/accounts/login/", "/app/", "/t/abc/", "/api/v1/deliveries/"]
)
def test_get_on_run_app_redirects_to_the_real_domain(client, host, path):
    r = client.get(path, HTTP_HOST=host)
    assert r.status_code == 301 and r["Location"] == REAL + path


def test_redirect_keeps_the_query(client):
    r = client.get("/t/abc/?lang=sr&x=%2F", HTTP_HOST=SERVICE_HOST)
    assert r.status_code == 301 and r["Location"] == REAL + "/t/abc/?lang=sr&x=%2F"


def test_head_on_run_app_redirects_too(client):
    r = client.head("/", HTTP_HOST=SERVICE_HOST)
    assert r.status_code == 301 and r["Location"] == REAL + "/"


@pytest.mark.parametrize(
    "path",
    [
        "/tasks/send-rating/1/",
        "/tasks/escalate/1/",
        "/webhooks/infobip/reports/",
        "/webhooks/telegram/webhook/",
        "/accounts/login/",
        "/api/v1/deliveries/",
    ],
)
def test_post_on_run_app_gets_403(client, path):
    r = client.post(path, data="{}", content_type="application/json", HTTP_HOST=REGIONAL_HOST)
    assert r.status_code == 403 and REAL in r.content.decode()
    assert "Location" not in r


@pytest.mark.parametrize("method", ["put", "patch", "delete", "options"])
def test_other_methods_on_run_app_get_403(client, method):
    assert getattr(client, method)("/app/", HTTP_HOST=SERVICE_HOST).status_code == 403


@pytest.mark.parametrize(
    "host", ["JAVI-AAY5LCPXHA-EW.A.RUN.APP", f"{SERVICE_HOST}:443", f"{SERVICE_HOST}."]
)
def test_host_case_port_and_trailing_dot_do_not_bypass(client, host):
    r = client.get("/", HTTP_HOST=host)
    assert r.status_code == 301 and r["Location"] == REAL + "/"


def test_redirect_and_403_keep_the_security_headers(client, settings):
    settings.SECURE_CONTENT_TYPE_NOSNIFF = True
    assert client.get("/", HTTP_HOST=SERVICE_HOST)["X-Content-Type-Options"] == "nosniff"
    assert client.post("/app/", HTTP_HOST=SERVICE_HOST)["X-Content-Type-Options"] == "nosniff"


def test_candidate_tag_host_is_served(client):
    # The deploy smoke-checks `/` and checks its security headers on the tag URL.
    r = client.get("/", HTTP_HOST=CANDIDATE)
    assert r.status_code == 200
    assert client.head("/", HTTP_HOST=CANDIDATE).status_code == 200
    assert client.get("/accounts/login/", HTTP_HOST=CANDIDATE).status_code == 200


@pytest.mark.parametrize("host", ["javi.serbito.rs", "testserver"])
def test_other_hosts_are_untouched(client, host):
    assert client.get("/", HTTP_HOST=host).status_code == 200
    assert client.get("/accounts/login/", HTTP_HOST=host).status_code == 200
    r = client.post("/tasks/send-rating/1/", HTTP_HOST=host)
    assert f"Use {REAL}" not in r.content.decode()  # the task secret check answers, not the guard


def test_guard_is_off_when_the_public_url_is_run_app(client, settings):
    # A self-host without its own domain: the redirect would point back at the same host.
    settings.PUBLIC_BASE_URL = f"https://{SERVICE_HOST}"
    assert public_origin() == ""
    assert client.get("/", HTTP_HOST=SERVICE_HOST).status_code == 200


def test_host_helpers():
    assert public_origin() == REAL
    assert is_run_app_host(host_name("Javi-X.a.run.app.:8080"))
    for host in ["javi.serbito.rs", "run.app.example.com", "notrun.app", "[::1]:8000", ""]:
        assert not is_run_app_host(host_name(host)), host
