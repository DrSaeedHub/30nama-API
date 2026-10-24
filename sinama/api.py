"""Transport: endpoint discovery, host/key probing, rate-limited scheduler, envelope parsing.

Mirrors tizen-app/js/api.js. Every action is `POST {host}/action/{name}` with a
form-urlencoded body and `c-*` headers. The JSON answer is an envelope:

    {"status": 200, "success": true, "error": false, "msg": "...", "result": ...,
     "action": null, "seo": null, "timestamp": 1792816087}

`call()` returns that envelope; `get()` returns `result` or raises an ApiError.
"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from . import config as C
from .errors import (
    ApiError,
    Blocked,
    CaptchaRequired,
    LoginRequired,
    NoEndpoint,
    NotFound,
    QRCodeExpired,
    RateLimited,
    TransportError,
)

# Guard strings the server or Cloudflare use to say "stop, don't retry".
_GUARDS = ("REQUESTBLOCK", "REQUESTCAPTCHA", "APIMAINTENANCE")


def encode(params):
    """Drop None values; booleans become "true"/"false" like the official clients send."""
    out = {}
    for k, v in (params or {}).items():
        if v is None:
            continue
        if isinstance(v, bool):
            v = "true" if v else "false"
        elif isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        out[k] = v
    return out


class Scheduler:
    """At most MAX_IN_FLIGHT requests at once, MIN_GAP between starts, global pause after 429."""

    def __init__(self, max_in_flight=C.MAX_IN_FLIGHT, min_gap=C.MIN_GAP_SECONDS):
        self._slots = threading.BoundedSemaphore(max_in_flight)
        self._lock = threading.Lock()
        self._min_gap = min_gap
        self._last_start = 0.0
        self._paused_until = 0.0

    def pause(self, seconds):
        with self._lock:
            self._paused_until = max(self._paused_until, time.perf_counter() + seconds)

    def run(self, fn):
        with self._slots:
            with self._lock:
                now = time.perf_counter()
                wait = max(self._paused_until - now, self._last_start + self._min_gap - now, 0)
                self._last_start = now + wait
            if wait:
                time.sleep(wait)
            return fn()


class Transport:
    """Low-level HTTP access to the hana-api v2 RPC endpoint."""

    def __init__(self, host=None, api_key=None, token=None, language=C.LANGUAGE,
                 version=C.VERSION_NUMBER, user_agent=C.USER_AGENT, timeout=C.TIMEOUT,
                 session=None, scheduler=None, backoff=None):
        self.host = host
        self.api_key = api_key or C.API_KEYS[0]
        self.token = token
        self.language = language
        self.version = version
        self.user_agent = user_agent
        self.timeout = timeout
        self.http = session or requests.Session()
        self.scheduler = scheduler or Scheduler()
        self.backoff = list(C.BACKOFF_SECONDS if backoff is None else backoff)
        self.on_login_required = None  # callback(ApiError) when a token is rejected

    # ---------- discovery ----------
    def discover(self):
        """Return the host list from the first discovery URL that answers, else the fallbacks."""
        def fetch(u):
            r = self.http.get(u, params={"t": int(time.time() * 1000)}, timeout=C.DISCOVERY_TIMEOUT,
                              headers={"User-Agent": self.user_agent})
            data = r.json()
            if not isinstance(data, list) or not data:
                raise ValueError("empty discovery list")
            return data

        with ThreadPoolExecutor(len(C.DISCOVERY_URLS)) as ex:
            futures = [ex.submit(fetch, u) for u in C.DISCOVERY_URLS]
            for f in as_completed(futures):
                try:
                    return f.result()
                except Exception:
                    continue
        return list(C.FALLBACK_HOSTS)

    def init(self):
        """Pick the first host that answers `test` successfully, trying each key in turn."""
        seen, hosts = set(), []
        for h in self.discover() + C.FALLBACK_HOSTS:
            if h.get("host") and h["host"] not in seen:
                seen.add(h["host"])
                hosts.append(h["host"])
        if self.host and self.host not in seen:
            hosts.insert(0, self.host)
        for key in C.API_KEYS:
            def probe(h, key=key):
                env = self._send(h, key, "test", {}, timeout=C.PROBE_TIMEOUT)
                if not env.get("success"):
                    raise ValueError("rejected")
                return h
            with ThreadPoolExecutor(len(hosts)) as ex:
                futures = [ex.submit(probe, h) for h in hosts]
                for f in as_completed(futures):
                    try:
                        self.host = f.result()
                        self.api_key = key
                        return {"host": self.host, "key": key}
                    except Exception:
                        continue
        raise NoEndpoint("no endpoint reachable: " + ", ".join(hosts))

    def ensure_host(self):
        if not self.host:
            self.init()
        return self.host

    # ---------- raw HTTP ----------
    def headers(self, key=None):
        return {
            "c-api-key": key or self.api_key,
            "c-token": self.token or "",
            "c-version-number": self.version,
            "c-language": self.language,
            "User-Agent": self.user_agent,
        }

    def url(self, name, host=None):
        return "%s/action/%s" % ((host or self.host).rstrip("/"), name)

    def _send(self, host, key, name, params, timeout=None, raw=False):
        """One HTTP round trip. Returns the parsed envelope (or text when raw=True)."""
        try:
            r = self.http.post(self.url(name, host), data=encode(params), headers=self.headers(key),
                               timeout=timeout or self.timeout)
        except requests.RequestException as e:
            raise TransportError("%s: %s" % (name, e)) from e
        text = r.text
        if raw:
            if r.status_code >= 400:
                raise TransportError("%s: HTTP %s" % (name, r.status_code), status=r.status_code, body=text)
            return text
        if r.status_code == 204 or (r.ok and not text.strip()):
            # Fire-and-forget actions (observer) answer 204 with no body.
            return {"status": r.status_code, "success": True, "error": False, "msg": None, "result": None,
                    "http_status": r.status_code}
        try:
            env = r.json()
        except ValueError:
            env = None
        if env is None:
            ra = r.headers.get("retry-after")
            try:
                ra = min(float(ra), C.MAX_RETRY_AFTER) if ra else 0.0
            except ValueError:
                ra = 0.0
            if r.status_code == 429 or "error code: 1015" in text:
                raise RateLimited("%s: rate limited (429)" % name, status=r.status_code, retry_after=ra, body=text[:500])
            if any(g in text for g in _GUARDS):
                raise Blocked("%s: server guard %s" % (name, next(g for g in _GUARDS if g in text)),
                              status=r.status_code, body=text[:500])
            if text.lstrip().startswith("<") and r.status_code in (403, 503) and "challenge" in text.lower():
                raise Blocked("%s: Cloudflare challenge (HTTP %s)" % (name, r.status_code),
                              status=r.status_code, body=text[:500])
            prefix = "5xx " if r.status_code >= 500 else ""
            raise TransportError("%sbad json from %s (HTTP %s)" % (prefix, name, r.status_code),
                                 status=r.status_code, retry_after=ra, body=text[:500])
        if isinstance(env, dict) and "success" not in env:
            # A few actions (captcha) answer bare JSON without the envelope.
            env = {"status": r.status_code, "success": r.ok, "error": not r.ok, "msg": None, "result": env}
        if isinstance(env, dict) and "results" in env and "result" not in env:
            env["result"] = env.pop("results")  # 404 envelopes spell it "results"
        if isinstance(env, dict):
            env.setdefault("http_status", r.status_code)
        return env

    # ---------- scheduled, retried calls ----------
    def call(self, name, params=None, retry=None, raw=False):
        """Run an action through the scheduler. Returns the envelope (dict) or text for raw=True."""
        self.ensure_host()
        tries = 0 if (retry is False or (retry is None and name in C.NO_RETRY)) else len(self.backoff)
        attempt = 0
        while True:
            try:
                return self.scheduler.run(lambda: self._send(self.host, self.api_key, name, params, raw=raw))
            except TransportError as e:
                if attempt >= tries or not e.retry:
                    raise
                delay = max(self.backoff[attempt], e.retry_after or 0)
                self.scheduler.pause(delay)
                attempt += 1

    def get(self, name, params=None, retry=None):
        """Run an action and return its `result`, raising a typed ApiError on success:false."""
        env = self.call(name, params, retry=retry)
        check(name, env, self)
        return env.get("result")


def check(name, env, transport=None):
    """Raise the matching ApiError subclass for a failed envelope."""
    if not isinstance(env, dict):
        raise ApiError("unexpected response from %s" % name, envelope={"result": env}, action=name)
    if env.get("success"):
        return env
    msg = env.get("msg") or "error"
    status = env.get("status")
    low = str(msg).lower()
    if "login required" in low or "access denied" in low:
        err = LoginRequired(msg, status, env, name)
        if transport is not None and transport.token and transport.on_login_required:
            transport.on_login_required(err)
        raise err
    if "invalid-input-response" in low or "missing-input-response" in low or "captcha" in low:
        raise CaptchaRequired(msg, status, env, name)
    if name == "qrlogin_login" and ("expired" in low or "wrong code" in low):
        raise QRCodeExpired(msg, status, env, name)
    if status == 404 or env.get("http_status") == 404 or "not found" in low or low == "no_slug_found":
        raise NotFound(msg, status, env, name)
    raise ApiError(msg, status, env, name)
