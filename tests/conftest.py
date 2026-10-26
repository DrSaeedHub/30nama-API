import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sinama import Client, MemoryStore, SessionStore, Transport  # noqa: E402
from sinama import config as C  # noqa: E402


# ---------------------------------------------------------------- offline fakes
class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self.text = body if isinstance(body, str) else ("" if body is None else json.dumps(body))
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.status_code)


class _Headers(dict):
    def get(self, k, d=None):
        return super().get(k.lower(), d)


class FakeHTTP:
    """Stands in for requests.Session. `handler(action, data, headers)` -> FakeResponse."""

    def __init__(self, handler=None):
        self.calls = []
        self.handler = handler or (lambda a, d, h: FakeResponse(200, ok({})))

    def post(self, url, data=None, headers=None, timeout=None):
        action = url.split("/action/", 1)[1] if "/action/" in url else url
        self.calls.append({"url": url, "action": action, "data": dict(data or {}), "headers": dict(headers or {})})
        r = self.handler(action, dict(data or {}), headers or {})
        r.headers = _Headers(r.headers)
        return r

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "action": None, "data": params, "headers": headers})
        return FakeResponse(200, [{"location": "WORLD", "host": "https://fake.test/api/v2"}])

    def last(self, action=None):
        for c in reversed(self.calls):
            if action is None or c["action"] == action:
                return c
        raise AssertionError("no call to %s" % action)


def ok(result, msg="OK"):
    return {"status": 200, "success": True, "error": False, "msg": msg, "result": result,
            "action": None, "seo": None, "timestamp": 1}


def fail(msg, status=200, action=None):
    return {"status": status, "success": False, "error": True, "msg": msg, "result": None,
            "action": action, "seo": None, "timestamp": 1}


@pytest.fixture
def fake():
    return FakeHTTP()


@pytest.fixture
def offline(fake):
    """Client wired to FakeHTTP with a fixed host, zero backoff and no pacing."""
    from sinama.api import Scheduler
    t = Transport(host="https://fake.test/api/v2", session=fake, scheduler=Scheduler(min_gap=0), backoff=[0, 0])
    c = Client(transport=t, store=MemoryStore(), token="TOKEN123")
    c.user_info = {"user_id": 42, "user_name": "tester"}
    return c


@pytest.fixture
def web_offline(fake):
    """WebClient wired to FakeHTTP, zero pacing/backoff, logged in."""
    from sinama import WebClient, WebTransport
    from sinama.api import Scheduler
    t = WebTransport(session=fake, scheduler=Scheduler(min_gap=0), backoff=[0, 0])
    w = WebClient(transport=t, store=MemoryStore(), token="WEBTOKEN")
    w.user_info = {"userid": 7, "username": "tester"}
    return w


# ---------------------------------------------------------------- live
def _saved_token():
    if os.environ.get(C.ENV_TOKEN):
        return os.environ[C.ENV_TOKEN]
    return SessionStore().load().get("token")


@pytest.fixture(scope="session")
def live():
    """Anonymous live client (no token, nothing persisted)."""
    c = Client(store=MemoryStore(), token=None)
    c.transport.token = None
    c.init()
    return c


@pytest.fixture(scope="session")
def auth():
    """Logged-in live client; skips when no session token is available."""
    token = _saved_token()
    if not token:
        pytest.skip("no session: run `python -m sinama qr-login` or set SINAMA_TOKEN")
    c = Client(token=token, store=MemoryStore({"token": token}), persist=False)
    c.init()
    try:
        c.user()
    except Exception as e:  # expired / revoked token
        pytest.skip("saved session rejected: %s" % e)
    return c


@pytest.fixture(scope="session")
def sample(live):
    """A streamable movie and series id from the live home page."""
    h = live.home_stream()
    movies = [p["id"] for p in h["movies"]["posts"] if p["options"]["stream"]]
    series = [p["id"] for p in h["series"]["posts"] if p["options"]["stream"]]
    # `candidates`: a title flagged stream:true can still answer "M3U8 file not found" (seen live).
    return {"movie": movies[0], "series": series[0], "candidates": {"movie": movies[:8], "series": series[:8]}}


# ---------------------------------------------------------------- live tests only through a proxy
def pytest_collection_modifyitems(config, items):
    """Live tests reach 30nama from this machine. They run only through $SINAMA_PROXY (every request of the
    default session goes through it, names resolved on the proxy), unless SINAMA_LIVE_DIRECT=1 allows the
    machine's own connection."""
    if os.environ.get(C.ENV_PROXY) or os.environ.get("SINAMA_LIVE_DIRECT") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set SINAMA_PROXY (or SINAMA_LIVE_DIRECT=1)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
