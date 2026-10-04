"""client_ip: XFF behind Cloud Run (JAVI-8) and CF-Connecting-IP behind Cloudflare (SERBITO-420)."""

import ipaddress

import pytest
from django.test import RequestFactory, override_settings

from common.client_ip import CLOUDFLARE_IPS_FILE, client_ip, cloudflare_networks, is_cloudflare_ip

rf = RequestFactory()

FRONT_END = "169.254.1.1"  # REMOTE_ADDR on Cloud Run: the Google front end connects from link-local
CF_EDGE_V4 = "172.70.1.1"  # in 172.64.0.0/13
CF_EDGE_V6 = "2a06:98c1:3120::3"  # in 2a06:98c0::/29
VISITOR = "203.0.113.7"
# Python counts the TEST-NET ranges as private, so a public peer needs a real public address.
PUBLIC_PEER = "93.184.216.34"


def _req(xff=None, cf=None, peer=FRONT_END):
    meta = {"REMOTE_ADDR": peer}
    if xff is not None:
        meta["HTTP_X_FORWARDED_FOR"] = xff
    if cf is not None:
        meta["HTTP_CF_CONNECTING_IP"] = cf
    return rf.get("/", **meta)


# --- vendored Cloudflare list ---


def test_cloudflare_list_parses_and_has_both_families():
    nets = cloudflare_networks()
    data_lines = [
        line
        for line in CLOUDFLARE_IPS_FILE.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert len(nets) == len(data_lines)  # no line silently skipped
    assert {net.version for net in nets} == {4, 6}
    assert all(not net.is_private for net in nets)
    for line in data_lines:  # canonical CIDRs, no host bits: catches a paste typo
        assert str(ipaddress.ip_network(line, strict=True)) == line


@pytest.mark.parametrize(
    ("ip", "expected"),
    [
        (CF_EDGE_V4, True),
        (CF_EDGE_V6, True),
        ("104.16.0.1", True),
        (VISITOR, False),
        ("2001:db8::1", False),
        ("not-an-ip", False),
        ("", False),
    ],
)
def test_is_cloudflare_ip(ip, expected):
    assert is_cloudflare_ip(ip) is expected


# --- XFF behind Cloud Run (no Cloudflare) ---


def test_rightmost_xff_entry_behind_cloud_run():
    assert client_ip(_req(xff=f"6.6.6.6, {VISITOR}")) == VISITOR


def test_google_front_end_and_link_local_hops_are_skipped():
    assert client_ip(_req(xff=f"6.6.6.6, {VISITOR}, 35.191.3.4, 169.254.8.1")) == VISITOR


def test_public_peer_ignores_xff_and_cf_header():
    request = _req(xff="6.6.6.6", cf="7.7.7.7", peer=PUBLIC_PEER)
    assert client_ip(request) == PUBLIC_PEER


@pytest.mark.parametrize("xff", ["", "not-an-ip", " , "])
def test_no_usable_xff_falls_back_to_peer(xff):
    assert client_ip(_req(xff=xff, peer=PUBLIC_PEER)) == PUBLIC_PEER
    assert client_ip(_req(xff=xff)) == FRONT_END


def test_invalid_peer_is_unknown():
    assert client_ip(_req(peer="")) == "unknown"


@override_settings(TRUSTED_PROXIES=["34.120.1.0/24"])
def test_trusted_proxy_peer_and_hop_are_skipped():
    request = _req(xff=f"6.6.6.6, {VISITOR}, 34.120.1.9", peer="34.120.1.10")
    assert client_ip(request) == VISITOR


# --- CF-Connecting-IP (SERBITO-420) ---


def test_spoofed_cf_header_without_cloudflare_hop_is_ignored():
    # DNS-only today: the edge peer is the visitor; the header is theirs to forge.
    assert client_ip(_req(xff=VISITOR, cf="1.2.3.4")) == VISITOR


def test_spoofed_cloudflare_address_left_of_real_hop_is_ignored():
    # A Cloudflare address the client wrote into XFF is not the edge peer.
    assert client_ip(_req(xff=f"{CF_EDGE_V4}, {VISITOR}", cf="1.2.3.4")) == VISITOR


def test_cloudflare_hop_uses_cf_connecting_ip():
    # visitor → Cloudflare (appends visitor) → Google front end (appends the edge address).
    request = _req(xff=f"6.6.6.6, {VISITOR}, {CF_EDGE_V4}", cf=VISITOR)
    assert client_ip(request) == VISITOR


def test_cloudflare_ipv6_edge_and_ipv6_visitor():
    visitor_v6 = "2001:db8:85a3::8a2e:370:7334"
    request = _req(xff=f"{visitor_v6}, {CF_EDGE_V6}", cf=visitor_v6)
    assert client_ip(request) == visitor_v6


@pytest.mark.parametrize("cf", [None, "", "garbage"])
def test_cloudflare_hop_without_usable_cf_header_keeps_edge(cf):
    assert client_ip(_req(xff=f"{VISITOR}, {CF_EDGE_V4}", cf=cf)) == CF_EDGE_V4


def test_cloudflare_peer_without_google_front_end():
    # Not our setup, but a Cloudflare peer connecting straight to gunicorn is still trusted.
    assert client_ip(_req(cf=VISITOR, peer=CF_EDGE_V4)) == VISITOR
