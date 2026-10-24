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
        action = url.split("/action/", 1)[1]
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
    movie = next(p for p in h["movies"]["posts"] if p["options"]["stream"])
    series = next(p for p in h["series"]["posts"] if p["options"]["stream"])
    return {"movie": movie["id"], "series": series["id"]}
