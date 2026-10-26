"""A requests-shaped session over httpx, for apps that send their HTTP their own way.

`Transport` needs only `get(url, params=, headers=, timeout=)` and `post(url, data=, headers=, timeout=)`,
returning responses with `status_code`, `text`, `content`, `headers` (case-insensitive), `ok`, `json()` and
`raise_for_status()`. requests.Session is the default. `HttpxSession` gives that shape to anything that sends
the way httpx does: an `httpx.Client`, or a callable `send(method, url, **httpx_kwargs) -> httpx.Response`
(an app's own router, with its proxies and rules):

    from sinama import Client, Transport, HttpxSession
    c = Client(transport=Transport(session=HttpxSession(my_router_send)))

httpx's network errors become the matching requests exceptions, so the library's retries and messages stay
the same. Any other error the callable raises (the app refusing to send: its proxy is down, say) passes
through untouched and is never retried.

TLS: a plain httpx client greets with Python's default TLS settings, which Cloudflare's bot screen in front of
the API answers with a "Just a moment" challenge (HTTP 403). `tls_context()` is the context requests itself
uses (no session tickets, post-handshake auth), which is not challenged; HttpxSession() without a sender
builds its own client with it, and an app's client should use it too.
"""
import ssl

import requests

try:  # httpx is optional: only HttpxSession needs it
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


def tls_context():
    """The TLS context requests (urllib3) uses: TLS 1.2 or later, no session tickets, post-handshake auth."""
    import certifi
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.options |= ssl.OP_NO_TICKET | ssl.OP_NO_COMPRESSION
    if getattr(ctx, "post_handshake_auth", None) is not None:
        ctx.post_handshake_auth = True
    return ctx


class Response:
    """An httpx.Response with the requests attributes the library reads (`ok`, a requests HTTPError)."""

    def __init__(self, r):
        self._r = r
        self.status_code = r.status_code
        self.headers = r.headers
        self.url = str(r.url)

    @property
    def ok(self):
        return self.status_code < 400

    @property
    def text(self):
        return self._r.text

    @property
    def content(self):
        return self._r.content

    def json(self):
        return self._r.json()

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError("HTTP %s for %s" % (self.status_code, self.url), response=self)

    def close(self):
        self._r.close()


def _translate(e):
    """httpx's exception -> the requests exception the library knows; None for anything that is not httpx's."""
    if httpx is None or not isinstance(e, httpx.HTTPError):
        return None
    msg = str(e) or type(e).__name__
    if isinstance(e, httpx.TimeoutException):
        return requests.Timeout(msg)
    if isinstance(e, httpx.ProxyError):
        return requests.exceptions.ProxyError(msg)
    if isinstance(e, (httpx.ConnectError, httpx.NetworkError, httpx.RemoteProtocolError)):
        return requests.ConnectionError(msg)
    if isinstance(e, httpx.TooManyRedirects):
        return requests.TooManyRedirects(msg)
    if isinstance(e, httpx.InvalidURL):
        return requests.exceptions.InvalidURL(msg)
    return requests.RequestException(msg)


class HttpxSession:
    """requests.Session's get/post over httpx. `send` is an httpx.Client, a callable
    `send(method, url, **kwargs) -> httpx.Response`, or None for a client of its own (with tls_context())."""

    def __init__(self, send=None, timeout=20):
        if httpx is None:  # pragma: no cover
            raise ImportError("HttpxSession needs httpx: pip install httpx")
        self._own = None
        if send is None:
            self._own = httpx.Client(verify=tls_context(), timeout=timeout, follow_redirects=True)
            send = self._own
        self._send = send.request if hasattr(send, "request") else send

    def request(self, method, url, params=None, data=None, headers=None, timeout=None, **kwargs):
        kw = {k: v for k, v in (("params", params), ("data", data), ("headers", headers), ("timeout", timeout)) if v is not None}
        kw.update(kwargs)
        try:
            return Response(self._send(method, url, **kw))
        except Exception as e:
            mapped = _translate(e)
            if mapped is None:
                raise
            raise mapped from e

    def get(self, url, params=None, headers=None, timeout=None, **kwargs):
        return self.request("GET", url, params=params, headers=headers, timeout=timeout, **kwargs)

    def post(self, url, data=None, headers=None, timeout=None, **kwargs):
        return self.request("POST", url, data=data, headers=headers, timeout=timeout, **kwargs)

    def close(self):
        if self._own is not None:
            self._own.close()
