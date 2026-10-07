"""SERBITO-374: the "focus never hidden" fallback (SERBITO-352) must not scroll the page when the
browser window gets focus back.

On window refocus (another app, another tab) the browser fires focus/focusin again on
document.activeElement. That is not a keyboard move, so the page must stay where it was; Tab onto
a control under the banner must still bring it into view (WCAG 2.4.11).

Runs the real landing (landing/, served from disk) in full Chromium headless (channel
"chromium", not the headless shell), with Playwright's focus emulation off: otherwise window
blur/focus never fire and the test passes for nothing. Fails, never skips, without the browser.
"""

from pathlib import Path

import pytest

try:
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import sync_playwright
except ImportError:  # loud at collection, not a quiet skip
    pytest.fail("No Playwright: uv sync (dev group)", pytrace=False)

LANDING = Path(__file__).resolve().parent.parent / "landing"
BASE = "https://javi.test"
PHONE = {"width": 390, "height": 844}
WAIT_MS = 5000
TYPES = {".html": "text/html", ".js": "text/javascript", ".png": "image/png"}

# Put the element's middle at the banner's middle; is the element covered by the banner?
UNDER_BANNER = """el => { const b = document.querySelector('.jc').getBoundingClientRect(),
  r = el.getBoundingClientRect(); scrollBy(0, r.top + r.height / 2 - (b.top + b.height / 2)); }"""
COVERED = """el => { const b = document.querySelector('.jc').getBoundingClientRect(),
  r = el.getBoundingClientRect(); return r.bottom > b.top && r.top < b.bottom; }"""


def _serve(route):
    """The landing from disk at its site paths; anything external (GA, Cloudflare) is cut off."""
    url = route.request.url
    if not url.startswith(BASE + "/"):
        return route.abort()
    path = url[len(BASE) + 1 :].split("?")[0].split("#")[0] or "index.html"
    file = LANDING / path
    if not file.is_file():
        return route.fulfill(status=404, body="")
    return route.fulfill(
        status=200,
        body=file.read_bytes(),
        content_type=TYPES.get(file.suffix, "application/octet-stream"),
    )


@pytest.fixture
def page():
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chromium")
        except PWError as e:
            if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
                pytest.fail(
                    "No Chromium for Playwright: uv run playwright install chromium", pytrace=False
                )
            raise
        ctx = browser.new_context(viewport=PHONE, locale="en-US")
        ctx.route("**/*", _serve)
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        yield pg
        assert not errors, errors
        browser.close()


def _settle(page):
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")


def test_window_refocus_does_not_scroll_and_tab_still_clears_the_banner(page):
    page.goto(BASE + "/")
    page.wait_for_selector(".jc:not([hidden])", state="visible", timeout=WAIT_MS)
    cdp = page.context.new_cdp_session(page)
    cdp.send("Emulation.setFocusEmulationEnabled", {"enabled": False})
    page.bring_to_front()
    assert page.evaluate("document.hasFocus()"), "the window has no focus: nothing to test"
    page.evaluate("window.__focusins = 0; document.addEventListener('focusin', () => __focusins++)")
    links = page.locator("#crosspromo ul a")
    first, second = links.nth(0), links.nth(1)

    first.evaluate("el => el.focus()")
    _settle(page)
    first.evaluate(UNDER_BANNER)
    _settle(page)
    assert first.evaluate(COVERED), "the link is not under the banner"
    y, seen = page.evaluate("scrollY"), page.evaluate("__focusins")
    other = page.context.new_page()  # the tab loses focus, then gets it back
    other.bring_to_front()
    page.bring_to_front()
    other.close()
    page.wait_for_function(f"__focusins > {seen}", timeout=WAIT_MS)  # the refocus focusin came
    _settle(page)
    assert first.evaluate("el => el === document.activeElement")
    assert page.evaluate("scrollY") == y, "getting the window focus back scrolled the page"

    second.evaluate(UNDER_BANNER)
    _settle(page)
    assert second.evaluate(COVERED), "the second link is not under the banner"
    page.keyboard.press("Tab")
    _settle(page)
    assert second.evaluate("el => el === document.activeElement"), "Tab went elsewhere"
    assert not second.evaluate(COVERED), "Tab left focus under the banner"
