"""Offline tests of what an app plugs in from outside: the session that sends the HTTP (HttpxSession, its
errors), the store that keeps the session (CallbackStore), the proxy of the default session, and choosing a
host when `test` is refused while the API answers."""
import json
import ssl

import httpx
import pytest
import requests

from conftest import FakeHTTP, FakeResponse, fail, ok
from sinama import (CallbackStore, Client, HttpxSession, MemoryStore, NoEndpoint, Transport, TransportError,
                    default_session, tls_context)
from sinama import config as C
from sinama.api import Scheduler

HOSTS = {"https://fake.test/api/v2"} | {h["host"] for h in C.FALLBACK_HOSTS}
CHALLENGE = '<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title></head><body>challenge</body></html>'


def transport(fake, host=None):
    return Transport(host=host, session=fake, scheduler=Scheduler(min_gap=0), backoff=[0, 0])


class Refused(Exception):
    """An app's own refusal to send (its proxy is down)."""


# ------------------------------------------------------------------ choosing a host
def test_init_falls_back_to_menu_when_test_is_refused(fake):
    def handler(action, data, headers):
        if action == "test":
            return FakeResponse(403, {"status": 403, "success": False, "error": True, "msg": "403 Access Denied",
                                      "results": None})
        return FakeResponse(200, ok({"genres": [], "categories": []}, "DISCOVER_MENU"))
    fake.handler = handler
    t = transport(fake)
    assert t.init()["key"] == C.API_KEYS[0] and t.host in HOSTS
    first = [c["action"] for c in fake.calls if c["action"] and c["url"].startswith(t.host)]
    assert first == ["test", "menu"]


def test_init_falls_back_when_test_gets_a_challenge_page(fake):
    fake.handler = lambda a, d, h: FakeResponse(403, CHALLENGE) if a == "test" else FakeResponse(200, ok({}))
    assert transport(fake).init()["host"] in HOSTS


def test_init_gives_up_with_the_reasons(fake):
    fake.handler = lambda a, d, h: FakeResponse(403, CHALLENGE)
    with pytest.raises(NoEndpoint) as e:
        transport(fake).init()
    assert "test:" in str(e.value) and "menu:" in str(e.value)


def test_init_raises_the_sessions_own_error():
    class Down(FakeHTTP):
        def post(self, url, data=None, headers=None, timeout=None):
            raise Refused("the proxy is not answering")
    with pytest.raises(Refused):
        transport(Down()).init()


# ------------------------------------------------------------------ HttpxSession
def mock_session(handler):
    return HttpxSession(httpx.Client(transport=httpx.MockTransport(handler)))


def test_httpx_session_has_the_requests_shape():
    seen = {}

    def handler(req):
        seen.update(method=req.method, url=str(req.url), body=req.content, key=req.headers.get("c-api-key"))
        return httpx.Response(200, json=ok({"id": 1}))
    s = mock_session(handler)
    r = s.post("https://fake.test/api/v2/action/single", data={"post_id": 5}, headers={"c-api-key": "K"}, timeout=5)
    assert r.ok and r.status_code == 200 and r.json()["result"] == {"id": 1}
    assert seen["method"] == "POST" and seen["body"] == b"post_id=5" and seen["key"] == "K"
    assert r.headers["Content-Type"] == r.headers["content-type"]
    g = s.get("https://fake.test/x.json", params={"t": 1})
    assert seen["url"] == "https://fake.test/x.json?t=1" and g.ok


def test_httpx_session_drives_a_client():
    t = Transport(host="https://fake.test/api/v2", scheduler=Scheduler(min_gap=0), backoff=[0, 0],
                  session=mock_session(lambda req: httpx.Response(200, json=ok({"posts": []}, "Search"))))
    c = Client(transport=t, store=MemoryStore(), token="T")
    assert c.search("dune") == {"posts": []}


def test_httpx_session_errors_become_requests_errors():
    def refused(req):
        raise httpx.ConnectError("refused")

    def slow(req):
        raise httpx.ReadTimeout("slow")
    with pytest.raises(requests.ConnectionError):
        mock_session(refused).get("https://fake.test/")
    with pytest.raises(requests.Timeout):
        mock_session(slow).get("https://fake.test/")
    r = mock_session(lambda req: httpx.Response(404, text="404 Not Found")).get("https://fake.test/")
    assert not r.ok
    with pytest.raises(requests.HTTPError):
        r.raise_for_status()


def test_network_errors_are_retried_and_reported_as_transport_errors():
    calls = []

    def handler(req):
        calls.append(1)
        raise httpx.ConnectError("reset")
    t = Transport(host="https://fake.test/api/v2", session=mock_session(handler), scheduler=Scheduler(min_gap=0),
                  backoff=[0, 0])
    with pytest.raises(TransportError):
        t.call("menu")
    assert len(calls) == 3                        # the first try and two retries


def test_an_apps_own_error_passes_through_and_is_not_retried():
    calls = []

    def send(method, url, **kw):
        calls.append(url)
        raise Refused("the proxy chain is down")
    t = Transport(host="https://fake.test/api/v2", session=HttpxSession(send), scheduler=Scheduler(min_gap=0),
                  backoff=[0, 0])
    with pytest.raises(Refused):
        t.call("menu")
    assert len(calls) == 1


def test_tls_context_is_the_requests_one():
    ctx = tls_context()
    assert ctx.options & ssl.OP_NO_TICKET and ctx.minimum_version == ssl.TLSVersion.TLSv1_2
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


# ------------------------------------------------------------------ the store
def test_callback_store_keeps_the_session_where_the_app_says(fake):
    vault = {}
    store = CallbackStore(load=lambda: json.loads(vault.get("s", "{}")),
                          save=lambda d: vault.__setitem__("s", json.dumps(d)))

    def handler(action, data, headers):
        if action == "qrlogin_login":
            return FakeResponse(200, ok({"token": "NEW"}))
        if action == "user":
            return FakeResponse(200, ok({"user_id": 7, "user_type": "golden", "user_session": "NEW"}))
        return FakeResponse(200, fail("x"))
    fake.handler = handler
    c = Client(transport=transport(fake, "https://fake.test/api/v2"), store=store)
    assert c.qr_check("abc") == "NEW"
    saved = json.loads(vault["s"])
    assert saved["token"] == "NEW" and saved["user"]["user_type"] == "golden"
    again = Client(transport=transport(fake, "https://fake.test/api/v2"), store=store)
    assert again.token == "NEW" and again.user_info["user_id"] == 7
    again.clear_session()
    assert json.loads(vault["s"]) == {}


def test_callback_store_clear_callback():
    cleared = []
    store = CallbackStore(load=lambda: {"token": "x"}, save=lambda d: None, clear=lambda: cleared.append(1))
    store.clear()
    assert cleared == [1]
    assert store.update(user=None, host="h") == {"token": "x", "host": "h"}


# ------------------------------------------------------------------ the default session's proxy
def test_default_session_goes_through_sinama_proxy(monkeypatch):
    monkeypatch.setenv(C.ENV_PROXY, "socks5h://u:p@127.0.0.1:1")
    s = default_session()
    assert s.proxies == {"http": "socks5h://u:p@127.0.0.1:1", "https": "socks5h://u:p@127.0.0.1:1"}
    assert s.trust_env is False
    monkeypatch.delenv(C.ENV_PROXY)
    assert default_session().proxies == {}
