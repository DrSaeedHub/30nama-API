"""Offline tests of Cloudflare's bot challenge as its own outcome: `is_challenge` on made-up statuses, headers and
bodies, `ChallengeRequired` from every place a response is checked (actions, raw text, subtitles, the website API),
and choosing a host when hosts answer with the challenge. Nothing here touches the network."""
import httpx
import pytest
import requests

from conftest import FakeHTTP, FakeResponse, fail, ok
from sinama import (Blocked, ChallengeRequired, LoginRequired, NoEndpoint, RateLimited, Transport, TransportError,
                    is_challenge)
from sinama import config as C
from sinama.api import CHALLENGE_SCAN, Scheduler

HOST = "https://fake.test/api/v2"
HOSTS = [HOST] + [h["host"] for h in C.FALLBACK_HOSTS]   # the order init() tries them in (FakeHTTP discovers HOST)
CF = {"Server": "cloudflare", "Content-Type": "text/html; charset=UTF-8"}
PAGE = ('<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title></head><body>'
        '<script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1?ray=8"></script></body></html>')
SAYS = "Cloudflare asks a person to confirm a challenge on this network"


def challenge(status=403, body=PAGE, **headers):
    return FakeResponse(status, body, dict(CF, **headers))


def transport(fake, host=None):
    return Transport(host=host, session=fake, scheduler=Scheduler(min_gap=0), backoff=[0, 0])


class ByHost(FakeHTTP):
    """FakeHTTP whose answer depends on the host: `answers[host](action, headers)` -> FakeResponse (or raises)."""

    def __init__(self, answers, default):
        super().__init__()
        self.answers, self.default = answers, default

    def post(self, url, data=None, headers=None, timeout=None):
        host, action = url.split("/action/", 1)
        self.calls.append({"url": url, "action": action, "data": dict(data or {}), "headers": dict(headers or {})})
        return self.answers.get(host, self.default)(action, headers or {})


def dead(action, headers):
    raise requests.ConnectionError("connection reset")


# ------------------------------------------------------------------ the classifier
@pytest.mark.parametrize("status,headers,body", [
    (200, {"cf-mitigated": "challenge"}, ""),
    (403, {"CF-Mitigated": "Challenge"}, None),                                 # any case, no body needed
    (403, {"cf-mitigated": " challenge "}, "{}"),
    (403, CF, PAGE),
    (403, {"server": "cloudflare"}, "<html><title>Just a moment...</title></html>"),
    (503, {"Server": "Cloudflare"}, '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'),
    (429, {"SERVER": "cloudflare"}, "<script>(function(){window._cf_chl_opt={cvId: '3'}})();</script>"),
    (403, {"Server": "cloudflare"}, '<div id="CF-CHALLENGE-running">checking</div>'),
    (403, {"Server": "cloudflare"}, PAGE.encode("utf-8")),                     # bytes
    ("403", {"Server": "cloudflare"}, PAGE),                                    # a status given as text
    (403, httpx.Headers({"Server": "cloudflare"}), PAGE),                       # httpx headers
    (403, requests.structures.CaseInsensitiveDict({"Server": "cloudflare"}), PAGE),
], ids=lambda v: str(v)[:30])
def test_is_challenge(status, headers, body):
    assert is_challenge(status, headers, body) is True


@pytest.mark.parametrize("status,headers,body", [
    (403, {}, PAGE),                                                            # not from Cloudflare
    (403, {"Server": "nginx"}, PAGE),
    (403, {"Server": "cloudflare"}, '{"status": 403, "success": false, "msg": "403 Access Denied"}'),
    (403, {"Server": "cloudflare"}, "<html><title>Access denied | Error 1020</title></html>"),
    (403, {"Server": "cloudflare"}, "Forbidden"),
    (429, {"Server": "cloudflare"}, "error code: 1015"),                        # rate limit, not a challenge
    (200, {"Server": "cloudflare"}, PAGE),                                      # status outside 403/429/503
    (404, {"Server": "cloudflare"}, PAGE),
    (502, {"Server": "cloudflare"}, PAGE),
    (403, {"cf-mitigated": "block"}, ""),
    (403, {"Server": "cloudflare"}, "x" * CHALLENGE_SCAN + PAGE),               # marks past the first few KB
    (403, None, None),
    (None, {"Server": "cloudflare"}, PAGE),
], ids=lambda v: str(v)[:30])
def test_is_not_challenge(status, headers, body):
    assert is_challenge(status, headers, body) is False


def test_challenge_required_is_blocked_and_says_so():
    e = ChallengeRequired(host=HOST, status=403)
    assert isinstance(e, Blocked) and isinstance(e, TransportError)
    assert e.host == HOST and e.status == 403 and e.retry is False
    assert str(e) == SAYS + " (%s)" % HOST
    assert str(ChallengeRequired()) == SAYS and ChallengeRequired().host is None
    assert str(ChallengeRequired("menu: custom", host="h")) == "menu: custom"


# ------------------------------------------------------------------ actions
@pytest.mark.parametrize("answer", [
    challenge(),
    challenge(503),
    challenge(429, **{"Retry-After": "0"}),                                     # not mistaken for a rate limit
    FakeResponse(403, PAGE, {"cf-mitigated": "challenge"}),                     # the header alone
], ids=["403", "503", "429", "cf-mitigated"])
def test_action_raises_challenge_required_once(offline, fake, answer):
    fake.handler = lambda a, d, h: answer
    with pytest.raises(Blocked) as ei:                                          # code catching Blocked still works
        offline.menu()
    e = ei.value
    assert isinstance(e, ChallengeRequired) and not isinstance(e, RateLimited)
    assert e.host == HOST and e.status == answer.status_code and SAYS in str(e) and str(e).startswith("menu: ")
    assert "Just a moment" in e.body
    assert len(fake.calls) == 1                                                 # never retried


def test_raw_text_answer_raises_challenge_required(offline, fake):
    fake.handler = lambda a, d, h: challenge()
    with pytest.raises(ChallengeRequired) as ei:
        offline.subtitle("Zm9v")
    assert ei.value.host == HOST and len(fake.calls) == 1


def test_subtitle_url_raises_challenge_required(offline):
    class Subs(FakeHTTP):
        def get(self, url, params=None, headers=None, timeout=None):
            self.calls.append({"url": url})
            return challenge()
    offline.transport.http = Subs()
    with pytest.raises(ChallengeRequired) as ei:
        offline.subtitle("https://subs.test/files/a.vtt?x=1")
    assert ei.value.host == "https://subs.test" and ei.value.status == 403


def test_website_api_raises_challenge_required(web_offline, fake):
    fake.handler = lambda a, d, h: challenge()
    with pytest.raises(ChallengeRequired) as ei:
        web_offline.test()
    assert ei.value.host == C.WEB_HOST
    with pytest.raises(ChallengeRequired):
        web_offline.transport.init()


# ------------------------------------------------------------------ a 403 that is not the challenge: as before
def test_plain_403_page_is_blocked_as_before(offline, fake):
    # Looks like a challenge page but not from Cloudflare's server: the old Blocked, not ChallengeRequired.
    fake.handler = lambda a, d, h: FakeResponse(403, PAGE)
    with pytest.raises(Blocked) as ei:
        offline.menu()
    assert type(ei.value) is Blocked and str(ei.value) == "menu: Cloudflare challenge (HTTP 403)"
    assert len(fake.calls) == 1


def test_cloudflare_403_without_challenge_is_as_before(offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(403, "Forbidden", {"Server": "cloudflare"})
    with pytest.raises(TransportError) as ei:
        offline.menu()
    assert type(ei.value) is TransportError and ei.value.status == 403
    assert len(fake.calls) == 3                                                 # retried, as before
    fake.calls.clear()
    fake.handler = lambda a, d, h: FakeResponse(403, fail("403 Access Denied", 403), {"Server": "cloudflare"})
    with pytest.raises(LoginRequired):
        offline.get("menu")


def test_cloudflare_rate_limit_is_as_before(offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(429, "error code: 1015", {"Server": "cloudflare"})
    with pytest.raises(RateLimited):
        offline.menu()
    assert len(fake.calls) == 3


# ------------------------------------------------------------------ choosing a host
def test_init_ends_with_challenge_required_when_every_host_challenges():
    fake = ByHost({}, lambda a, h: challenge())
    with pytest.raises(ChallengeRequired) as ei:
        transport(fake).init()
    e = ei.value
    assert not isinstance(e, NoEndpoint) and e.host == HOSTS[0] and e.status == 403
    assert SAYS in str(e) and all(h in str(e) for h in HOSTS)


def test_init_ends_with_challenge_required_when_the_other_hosts_are_dead():
    fake = ByHost({HOSTS[1]: lambda a, h: challenge()}, dead)
    with pytest.raises(ChallengeRequired) as ei:
        transport(fake).init()
    assert ei.value.host == HOSTS[1]


def test_init_moves_on_from_a_challenged_host_to_one_that_answers():
    fake = ByHost({HOSTS[0]: lambda a, h: challenge(), HOSTS[2]: dead}, lambda a, h: FakeResponse(200, ok({})))
    t = transport(fake)
    assert t.init()["host"] == HOSTS[1] and t.host == HOSTS[1]


def test_init_uses_menu_when_only_test_is_challenged():
    fake = ByHost({}, lambda a, h: challenge() if a == "test" else FakeResponse(200, ok({}, "DISCOVER_MENU")))
    t = transport(fake)
    assert t.init()["key"] == C.API_KEYS[0] and t.host in HOSTS


def test_init_reports_the_api_not_the_challenge_when_the_api_answered():
    # `test` challenged, `menu` reached the API and was refused for the key: the host is not behind a challenge.
    fake = ByHost({}, lambda a, h: challenge() if a == "test" else FakeResponse(200, fail("bad key")))
    with pytest.raises(NoEndpoint) as ei:
        transport(fake).init()
    assert "bad key" in str(ei.value)


def test_init_with_a_preset_host_names_it_first():
    preset = "https://preset.test/api/v2"
    fake = ByHost({}, lambda a, h: challenge())
    with pytest.raises(ChallengeRequired) as ei:
        transport(fake, preset).init()
    assert ei.value.host == preset


def test_client_init_raises_challenge_required():
    from sinama import Client, MemoryStore
    c = Client(transport=transport(ByHost({}, lambda a, h: challenge())), store=MemoryStore())
    with pytest.raises(ChallengeRequired):
        c.init()
