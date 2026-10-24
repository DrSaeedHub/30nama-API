"""`Client`: one method per API action, plus session handling.

    from sinama import Client
    c = Client()                       # token from SINAMA_TOKEN or the saved session file
    home = c.home_stream()
    hits = c.search("inception", stream_only=True)
    post = c.single(hits["posts"][0]["id"])

Methods return the envelope's `result` and raise `ApiError` subclasses on
`success: false` (see errors.py). `call()` gives the raw envelope for any action.
"""
import os
import time

from . import config as C
from . import direct
from .api import Transport, check
from .errors import ApiError, CaptchaRequired, LoginRequired, NotFound, QRCodeExpired, SinamaError
from .library import Library
from .store import SessionStore

LIST_GROUPS = ("watchlist", "favorite", "downloadlist", "notify")
SORTS = ("date", "favorite", "update", "relevant", "year", "imdb")


class Client:
    def __init__(self, token=None, store=None, host=None, api_key=None, language=C.LANGUAGE,
                 version=C.VERSION_NUMBER, timeout=C.TIMEOUT, transport=None, persist=True):
        """
        token:   session token (c-token). Default: $SINAMA_TOKEN, else the saved session.
        store:   SessionStore (default ~/.sinama/session.json, or $SINAMA_SESSION_FILE).
        host:    API base like https://world.hana-api.com/api/v2. Default: $SINAMA_HOST or discovery.
        persist: save token/user/host to the store after login.
        """
        self.store = store or SessionStore()
        saved = self.store.load()
        self.persist = persist
        self.transport = transport or Transport(
            host=host or os.environ.get(C.ENV_HOST) or saved.get("host"), api_key=api_key,
            language=language, version=version, timeout=timeout)
        self.transport.token = token or os.environ.get(C.ENV_TOKEN) or saved.get("token")
        self.transport.on_login_required = self._on_login_required
        self.user_info = saved.get("user") if saved.get("token") == self.transport.token else None
        self.library = Library(self)

    # ------------------------------------------------------------------ plumbing
    @property
    def token(self):
        return self.transport.token

    @property
    def host(self):
        return self.transport.host

    @property
    def is_logged_in(self):
        return bool(self.transport.token)

    def init(self):
        """Discover and probe hosts now (otherwise done lazily on the first call)."""
        r = self.transport.init()
        if self.persist and self.transport.token:
            self.store.update(host=self.transport.host)
        return r

    def call(self, name, /, *, retry=None, **params):
        """Raw envelope for any action: {status, success, error, msg, result, action, seo, timestamp}.

        `name` is positional-only so actions can take a form field called `action` (user_list).
        """
        return self.transport.call(name, params, retry=retry)

    def get(self, name, /, *, retry=None, **params):
        """`result` of any action, raising ApiError on success:false."""
        return self.transport.get(name, params, retry=retry)

    def set_session(self, token, user=None):
        self.transport.token = token
        self.user_info = user
        self.library.clear()
        if self.persist:
            self.store.save({"token": token, "user": user, "host": self.transport.host})

    def clear_session(self):
        self.transport.token = None
        self.user_info = None
        self.library.clear()
        if self.persist:
            self.store.clear()

    def _on_login_required(self, err):
        # The token was rejected; keep it in memory (caller decides) but drop cached user data.
        self.user_info = None

    def _require_login(self, action):
        if not self.transport.token:
            raise LoginRequired("Login Required", envelope={"msg": "Login Required"}, action=action)

    def user_id(self):
        u = self.user_info or {}
        return u.get("user_id") or u.get("id") or ""

    # ------------------------------------------------------------------ auth & account
    def test(self):
        """Connection test: {ip: {ip, country, continent}, device: {...}, is_abroad, platform}."""
        return self.get("test")

    def captcha_required(self):
        """True when `login`/`otp`/`register` need a reCAPTCHA token for this client and IP."""
        r = self.get("captcha")
        return bool((r or {}).get("captcha"))

    def login(self, username=None, password=None, recaptcha_response=None):
        """Password login. Defaults to $site_30NAMA_email / $site_30NAMA_password.

        The server requires a Google reCAPTCHA token (`recaptcha_response`) whenever
        captcha_required() is True, which it is for the TV client keys. Without one this
        raises CaptchaRequired; use qr_login() instead, or pass a token solved in a browser.
        """
        username = username or os.environ.get(C.ENV_EMAIL)
        password = password or os.environ.get(C.ENV_PASSWORD)
        if not username or not password:
            raise SinamaError("username/password missing (set %s and %s)" % (C.ENV_EMAIL, C.ENV_PASSWORD))
        r = self.get("login", user_login=username, user_password=password, recaptcha_response=recaptcha_response)
        return self._finish_login(r)

    def otp_send(self, user_login, recaptcha_response=None):
        """Send a one-time code to an email or mobile number. Captcha-gated like login."""
        return self.get("otp", user_login=user_login, recaptcha_response=recaptcha_response)

    def otp_verify(self, user_login, code):
        """Exchange an OTP code for a session (logs the client in)."""
        r = self.get("otp_verify", user_login=user_login, user_code=code)
        return self._finish_login(r)

    def register(self, recaptcha_response=None, **fields):
        """Create an account. Captcha-gated; field names are not documented by any client."""
        return self.get("register", recaptcha_response=recaptcha_response, **fields)

    def qr_code(self):
        """New QR login code: {code, url}. Open `url` on a device logged in to 30nama.com."""
        return self.get("qrlogin_code")

    def qr_check(self, code):
        """Poll once. Returns the token when approved, None while pending (CODE_NOT_USED).

        Raises QRCodeExpired for "Code Expired" / "Wrong Code". On success the client is
        logged in and the profile is loaded.
        """
        env = self.call("qrlogin_login", auth_code=code)
        if not env.get("success"):
            if str(env.get("msg") or "").upper() == "CODE_NOT_USED":
                return None
            check("qrlogin_login", env)
        r = env.get("result") or {}
        self._finish_login(r)
        return self.token

    def qr_login(self, on_code=None, timeout=C.QR_TTL_SECONDS, poll=C.QR_POLL_SECONDS):
        """Blocking QR login. `on_code(code, url)` is called once so you can show/print the URL."""
        qr = self.qr_code()
        code, url = qr["code"], qr.get("url") or C.QR_BASE + qr["code"]
        if on_code:
            on_code(code, url)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.qr_check(code):
                return self.user_info or {"token": self.token}
            time.sleep(poll)
        raise QRCodeExpired("QR code not approved within %ss" % timeout, action="qrlogin_login")

    def _finish_login(self, r):
        r = r or {}
        user = r.get("user") if isinstance(r.get("user"), dict) else None
        token = r.get("token") or r.get("user_session") or r.get("usertoken") or (user or {}).get("user_session")
        if not token:
            raise ApiError("login answered without a token", envelope={"result": r}, action="login")
        self.set_session(token, user)
        try:
            self.user()
        except ApiError:
            pass
        return self.user_info or {"token": token}

    def user(self):
        """Profile of the logged-in user: {user_id, user_name, user_type, user_allowed_to_stream,
        user_avatar, user_expire: {days, g, j}, ...}. Cached on `user_info` and in the store."""
        self._require_login("user")
        r = self.get("user")
        u = r.get("user") if isinstance(r, dict) and isinstance(r.get("user"), dict) else r
        self.user_info = u
        if self.persist:
            self.store.update(token=self.token, user=u, host=self.transport.host)
        return u

    def logout(self):
        """End the session server-side (never retried) and forget it locally."""
        try:
            return self.call("logout") if self.token else None
        finally:
            self.clear_session()

    def plans(self):
        """Subscription plans and prices: {discount, plans: [{id, type, title, features, prices}]}."""
        return self.get("plans")

    # ------------------------------------------------------------------ browse
    def home(self):
        """Full home page: hero_header, new_releases, suggested, top_10, movies, series, anime,
        call_to_action. Each row is {posts: [...]}."""
        return self.get("home")

    def home_stream(self):
        """Streaming home (what the TV app shows): hero_header, suggested, movies, series, anime."""
        return self.get("home_stream")

    def menu(self):
        """Browse menu: {genres: [{id, name, slug, count, image}], categories: [...]}"""
        return self.get("menu")

    def single(self, post_id):
        """Title details: options, info, title, plot, genre, cast, crew, image, score, country,
        language, list, air, subtitle (external links), seo, continue_watching."""
        r = self.get("single", post_id=post_id)
        if not isinstance(r, dict) or not r.get("id"):
            raise NotFound("Post not found", envelope={"result": r}, action="single")
        return r

    def search(self, query, page=1, stream_only=False):
        """Title search: {posts, page, pages, total}. stream_only filters to playable titles."""
        return self.get("search", query=query, page=page, streamonly=True if stream_only else None)

    def archive(self, slugs, page=1, orderby="date", order="desc", stream_only=False):
        """Paged listing of a category or genre slug (see menu()). orderby: date | favorite |
        update | relevant | year | imdb. order: desc | asc."""
        return self.get("archive", slugs=slugs, page=page, orderby=orderby, order=order,
                        streamonly=True if stream_only else None)

    def advanced_search_parameters(self):
        """Filter vocabulary for advanced_search: genre, type, imdb_rate, country, language,
        min_year, max_year, channel, encoder, quality, x265, 3D, stream, age, ..."""
        return self.get("advanced_search_parameters")

    def advanced_search(self, parameters=None, page=1, orderby="relevant", order="desc", **filters):
        """Filtered search. List filters take lists (genre=["drama"]); scalars for imdb_rate,
        min_year, max_year, stream="true"; people via actor/director = IMDb id (nm...)."""
        params = dict(parameters or {})
        params.update(filters)
        return self.get("advanced_search", parameters=params, page=page, orderby=orderby, order=order)

    def iter_pages(self, method, *args, max_pages=None, **kwargs):
        """Yield posts across pages of any paged method (search, archive, advanced_search, list)."""
        page = kwargs.pop("page", 1)
        seen = 0
        while True:
            r = method(*args, page=page, **kwargs)
            for p in (r or {}).get("posts") or []:
                yield p
            seen += 1
            pages = int((r or {}).get("pages") or 1)
            if page >= pages or (max_pages and seen >= max_pages):
                return
            page += 1

    # ------------------------------------------------------------------ playback
    def stream(self, post_id, free=False):
        """HLS sources for a title: {info, image, continue_watching, hls: [items]}.
        Needs a streaming subscription unless the title is free (free=True)."""
        if not free:
            self._require_login("stream")
        return self.get("stream", post_id=post_id, free_stream=1 if free else None)

    def download(self, post_id, free=False):
        """Direct-download files for a title (raw result, grouped by season/quality)."""
        if not free:
            self._require_login("download")
        return self.get("download", post_id=post_id, free_download=1 if free else 0)

    def download_links(self, post_id, free=False):
        """download() flattened to [{url, size, label, meta}] via direct.extract."""
        return direct.extract(self.download(post_id, free=free))

    def subtitle(self, url_or_file):
        """Subtitle text (WebVTT) by full URL or by the `file` id of /action/subtitle/file/<id>."""
        s = str(url_or_file)
        if s.startswith("http"):
            r = self.transport.http.get(s, headers=self.transport.headers(), timeout=self.transport.timeout)
            r.raise_for_status()
            return r.text
        return self.transport.call("subtitle/file/" + s, raw=True)

    def observer(self, post_id, file_id, time, duration, token="", user_id=None):
        """Report playback position (seconds). Answers 204; never retried."""
        self._require_login("observer")
        env = self.call("observer", post_id=post_id, file_id=file_id,
                        user_id=user_id if user_id is not None else self.user_id(),
                        time=int(time), duration=int(duration), token=token)
        return check("observer", env)

    def continue_watching(self):
        """Titles in progress: {posts: [post + data: {id, season, episode, time, progress}]}"""
        self._require_login("continue_watching")
        return self.get("continue_watching")

    def continue_watching_dismiss(self, post_id):
        """Hide a title from the continue-watching list (msg DISMISS_SUCCESS); its resume point stays.

        Raises ApiError("DISMISS_FAILED") for a title with no watch progress.
        """
        self._require_login("continue_watching_dismiss")
        return check("continue_watching_dismiss", self.call("continue_watching_dismiss", id=post_id))

    # ------------------------------------------------------------------ library (raw)
    def my_lists(self):
        """Ids in each list: {watchlist: {post: [ids]}, favorite: {...}, downloadlist, notify}"""
        self._require_login("user_mylist")
        return self.get("user_mylist")

    def user_list(self, group="watchlist", page=1, orderby="add_list", order="DESC"):
        """Paged posts of one list group."""
        self._require_login("user_list")
        return self.get("user_list", action="list", group=group, page=page, orderby=orderby, order=order)

    def user_list_toggle(self, group, post_id):
        """`user_list action=add` TOGGLES membership: a second call removes. Prefer library.add/remove."""
        self._require_login("user_list")
        return self.call("user_list", action="add", group=group, post_id=post_id)

    # ------------------------------------------------------------------ notifications
    def notifications(self, page=1):
        """{notifications: [...], total_unread, page, pages}"""
        self._require_login("notification")
        return self.get("notification", page=page)

    def notification_read(self, notification_id):
        self._require_login("notification_read")
        return check("notification_read", self.call("notification_read", notification_id=notification_id))
