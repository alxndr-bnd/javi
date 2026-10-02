/* Javi — analytics consent banner (SERBITO-321, owner decision SERBITO-285).
 *
 * Shared by the static landing, the privacy page and the Django app (templates/base.html loads
 * /consent.js; WhiteNoise serves landing/ at the site root). The Consent Mode v2 default (all
 * denied, or the stored choice) is set inline in each page's <head> before gtag config; this
 * file only asks the question and updates consent.
 *
 * - Choice + date live in localStorage "javi_consent" as {"v":"granted"|"denied","t":<ms>};
 *   older than 12 months counts as no choice, so the banner asks again.
 * - Accept grants analytics_storage only: the site runs GA4 and no ads tags, so ad_* stay denied.
 * - Decline keeps analytics denied and deletes _ga* cookies (withdrawal from "Cookie settings").
 *   GA is configured with cookie_domain 'none' (host-only), so that means the host's cookies;
 *   the first withdrawal also clears _ga* left on parent domains (.serbito.rs) by earlier
 *   versions, which set them there — once, so later ones never touch sibling sites' cookies.
 * - Language: <html lang> (the landing switches it client-side; the app sets it via Django
 *   i18n); data-consent-lang="visitor" (privacy page) uses the landing's saved choice instead.
 * - Any [data-consent-open] element reopens the banner; its value, if any, forces the language.
 * - /t/ tracking pages do not load this file (SERBITO-306).
 * - The banner never hides the focused element (SERBITO-352, WCAG 2.4.11): while it is up the page
 *   gets bottom scroll-padding and padding of its height, and a control it still covers after
 *   focus moves is scrolled above it. The focusin a window refocus repeats on the same element
 *   is not a move and scrolls nothing (SERBITO-374); nor does a fixed control.
 * - Accept and Decline carry equal weight (SERBITO-352): one .jc-btn rule styles both — same size,
 *   fill and prominence; .jc-accept/.jc-decline are behaviour hooks only and are never styled.
 */
(function () {
  "use strict";
  var KEY = "javi_consent";
  var LEGACY = "javi_ga_parent_cleared"; // parent-domain _ga* cleanup done (see dropGaCookies)
  var YEAR = 365 * 864e5;
  var GAP = 12; // the banner's offset from the viewport bottom; also kept clear above it
  var T = {
    sr: {
      label: "Saglasnost za kolačiće",
      text: "Koristimo kolačiće Google Analytics da vidimo kako se sajt koristi — samo ako se složite.",
      more: "Politika privatnosti",
      accept: "Prihvati",
      decline: "Odbij"
    },
    en: {
      label: "Cookie consent",
      text: "We use Google Analytics cookies to see how the site is used — only if you agree.",
      more: "Privacy policy",
      accept: "Accept",
      decline: "Decline"
    },
    ru: {
      label: "Согласие на cookies",
      text: "Мы используем cookies Google Analytics, чтобы понимать, как используется сайт, — только с вашего согласия.",
      more: "Политика конфиденциальности",
      accept: "Принять",
      decline: "Отклонить"
    }
  };
  var CSS =
    ".jc{position:fixed;left:12px;right:12px;bottom:12px;z-index:1000;max-width:720px;margin:0 auto;" +
    "display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px;padding:12px 16px;box-sizing:border-box;" +
    "background:var(--card,var(--surface,#fff));color:var(--ink,#161b29);" +
    "border:1px solid var(--line,#e4e8f0);border-radius:14px;box-shadow:0 10px 30px rgba(0,0,0,.25);" +
    "font-family:inherit;font-size:14px;line-height:1.45;text-align:left}" +
    ".jc[hidden]{display:none}" +
    ".jc .jc-text{margin:0;flex:1 1 260px;color:inherit;font-size:14px}" +
    ".jc a{color:inherit;font-weight:600;text-decoration:underline}" +
    // Two equal columns: both buttons take the wider label's width, in every language.
    ".jc-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;flex:0 0 auto}" +
    ".jc .jc-btn{font-family:inherit;font-size:14px;font-weight:700;min-height:36px;padding:7px 16px;" +
    "border-radius:10px;cursor:pointer;width:auto;" +
    "background:#3a5bd0;border:1px solid #3a5bd0;color:#fff}" +
    ".jc a:focus-visible,.jc button:focus-visible{outline:2px solid var(--brand,#4f7cff);outline-offset:2px}";

  var banner = null;
  var forced = null; // language forced by a [data-consent-open="xx"] trigger
  var returnTo = null; // element to refocus after a reopened banner closes
  var away = null; // the focused element when the window lost focus

  // Room for the banner at the bottom of the page while it is up: scroll-padding keeps focus
  // scrolling above it, and padding lets the last controls (footer links) scroll clear of it.
  function reserve() {
    var root = document.documentElement.style;
    var room = banner.hidden ? "" : banner.offsetHeight + 2 * GAP + "px";
    root.scrollPaddingBottom = room;
    root.paddingBottom = room;
  }

  function fixed(el) {
    for (; el && el.nodeType === 1; el = el.parentElement) {
      if (window.getComputedStyle(el).position === "fixed") return true;
    }
    return false;
  }

  // A focused control the banner still covers (browsers do not always honour scroll-padding
  // when focus moves) is scrolled up just enough to show it; its top never leaves the viewport.
  function unobscure(el) {
    if (!banner || banner.hidden || !el || !el.getBoundingClientRect || banner.contains(el)) return;
    if (fixed(el)) return; // scrolling cannot move it out from under the banner
    var r = el.getBoundingClientRect();
    var limit = banner.getBoundingClientRect().top - GAP;
    if (r.bottom > limit) window.scrollBy(0, Math.min(r.bottom - limit, Math.max(r.top, 0)));
  }

  function gtag() {
    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push(arguments);
  }

  function stored() {
    try {
      var c = JSON.parse(localStorage.getItem(KEY));
      if (c && (c.v === "granted" || c.v === "denied") && Date.now() - c.t < YEAR) return c.v;
    } catch (e) { /* storage blocked or corrupt: ask again */ }
    return null;
  }

  function lang() {
    var html = document.documentElement;
    var l = forced || html.getAttribute("data-consent-lang") || html.lang;
    if (l === "visitor") {
      try { l = localStorage.getItem("javi_lang"); } catch (e) { l = null; }
      l = l || navigator.language || "";
    }
    l = String(l || "").slice(0, 2).toLowerCase();
    return T[l] ? l : "sr";
  }

  function dropGaCookies() {
    var parent = true; // storage blocked: clean parent domains every time rather than never
    try { parent = !localStorage.getItem(LEGACY); localStorage.setItem(LEGACY, "1"); } catch (e) { /* keep true */ }
    var parts = location.hostname.split(".");
    document.cookie.split(";").forEach(function (c) {
      var name = c.split("=")[0].trim();
      if (name.indexOf("_ga") !== 0) return;
      document.cookie = name + "=; Max-Age=0; path=/"; // host-only, as GA sets them now
      if (!parent) return;
      for (var i = 1; i < parts.length - 1; i++) { // .serbito.rs for javi.serbito.rs
        document.cookie = name + "=; Max-Age=0; path=/; domain=." + parts.slice(i).join(".");
      }
    });
  }

  function choose(value) {
    try { localStorage.setItem(KEY, JSON.stringify({ v: value, t: Date.now() })); } catch (e) { /* session only */ }
    gtag("consent", "update", { analytics_storage: value });
    if (value === "denied") dropGaCookies();
    banner.hidden = true;
    reserve();
    forced = null;
    if (returnTo && document.contains(returnTo)) returnTo.focus();
    returnTo = null;
  }

  function render() {
    var l = lang();
    var t = T[l];
    banner.setAttribute("aria-label", t.label);
    banner.setAttribute("lang", l);
    banner.querySelector(".jc-text span").textContent = t.text + " ";
    var more = banner.querySelector(".jc-text a");
    more.textContent = t.more;
    more.href = "/privacy.html#" + l;
    banner.querySelector(".jc-accept").textContent = t.accept;
    banner.querySelector(".jc-decline").textContent = t.decline;
  }

  function build() {
    var style = document.createElement("style");
    style.textContent = CSS;
    document.head.appendChild(style);
    banner = document.createElement("div");
    banner.className = "jc";
    banner.setAttribute("role", "region");
    banner.hidden = true;
    banner.innerHTML =
      '<p class="jc-text"><span></span><a></a></p>' +
      '<div class="jc-actions">' +
      '<button type="button" class="jc-btn jc-decline"></button>' +
      '<button type="button" class="jc-btn jc-accept"></button></div>';
    banner.querySelector(".jc-accept").addEventListener("click", function () { choose("granted"); });
    banner.querySelector(".jc-decline").addEventListener("click", function () { choose("denied"); });
    // First in the tab order, so keyboard and screen-reader users meet it early; fixed at the
    // bottom visually, so the page content never moves.
    document.body.insertBefore(banner, document.body.firstChild);
    render();
  }

  function show(focus) {
    render();
    banner.hidden = false;
    reserve();
    if (focus) banner.querySelector(".jc-decline").focus();
  }

  function init() {
    build();
    if (!stored()) show(false);
    document.addEventListener("click", function (e) {
      var el = e.target.closest && e.target.closest("[data-consent-open]");
      if (!el) return;
      e.preventDefault();
      forced = el.getAttribute("data-consent-open") || null;
      returnTo = el;
      show(true);
    });
    // When the window gets focus back (another app or tab), the browser fires focusin again on
    // the element that had it: not a focus move, so nothing scrolls (SERBITO-374).
    window.addEventListener("blur", function (e) {
      if (e.target === window) away = document.activeElement;
    });
    // After the browser's own focus scrolling, so only what it left covered moves.
    document.addEventListener("focusin", function (e) {
      var back = e.target === away;
      away = null;
      if (back) return;
      window.requestAnimationFrame(function () { unobscure(e.target); });
    });
    window.addEventListener("resize", reserve);
    // The landing switches language by changing <html lang>; the banner follows.
    if (window.MutationObserver) {
      new MutationObserver(function () { if (!forced) { render(); reserve(); } })
        .observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
