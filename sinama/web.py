"""`WebClient`: the website's own API, interface.30nama.com/api/v1.

The 30nama.com website (Nuxt) talks to this API instead of hana-api v2. It covers what
the TV API lacks: comments and ratings, collections, articles/news, top lists, box office,
release schedule, people, requests, user profiles, watch history and full search.
Mapped from the site's bundled client (`30nama-api` 1.3.198) and verified live.

Differences from v2 (see docs/API.md, "Website API"):
- parameters are mostly URL path segments: `single/id/8863`, `comment/id/8863/page/1/...`;
- headers `c-api-key`, `c-useragent`, `c-app-version`, `c-platform: Website`, `c-token`;
- sessions are separate from v2 (a v2 token is rejected and vice versa). Log in with
  `qr_login(approve_with=<logged-in v2 Client>)` to link one without user interaction;
- `msg` texts are Persian; URLs in results may use `link://`-style placeholders;
- Cloudflare rate limits harder: ~30 requests in under a minute earned a ~4 minute block.

    from sinama import Client, WebClient
    web = WebClient()
    web.qr_login(approve_with=Client())          # once; session saved to ~/.sinama/web-session.json
    print(web.comments(8863)["comments"][0]["text"])
"""
import os
import re
import time

from . import config as C
from .api import Scheduler, Transport, check
from .errors import ApiError, CaptchaRequired, LoginRequired, NotFound, QRCodeExpired, SinamaError
from .store import SessionStore

PLACEHOLDERS = re.compile(r"\b(link|linkDownload|linkStream)://")


def _q(value):
    """One URL path segment."""
    return str(value).strip("/").replace("/", "%2F")


def _yes(flag):
    return "yes" if flag else "no"


def _fix_links(obj):
    """Replace the API's link:// / linkDownload:// / linkStream:// placeholders with https://."""
    if isinstance(obj, str):
        return PLACEHOLDERS.sub("https://", obj) if "://" in obj else obj
    if isinstance(obj, list):
        return [_fix_links(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _fix_links(v) for k, v in obj.items()}
    return obj


class WebTransport(Transport):
    """Transport for interface.30nama.com/api/v1 (fixed host, website headers, slower pacing)."""

    def __init__(self, host=C.WEB_HOST, api_key=C.WEB_API_KEY, token=None, app_version=C.WEB_APP_VERSION,
                 platform=C.WEB_PLATFORM, user_agent=C.WEB_USER_AGENT, timeout=C.TIMEOUT, session=None,
                 scheduler=None, backoff=None):
        super().__init__(host=host, api_key=api_key, token=token, user_agent=user_agent, timeout=timeout,
                         session=session, scheduler=scheduler or Scheduler(min_gap=C.WEB_MIN_GAP_SECONDS),
                         backoff=backoff)
        self.app_version = app_version
        self.platform = platform

    def init(self):
        """No discovery for v1: probe `test` (plain-text "OK") on the fixed host."""
        text = self._send(self.host, self.api_key, "test", {}, timeout=C.PROBE_TIMEOUT, raw=True)
        if text.strip() != "OK":
            raise SinamaError("unexpected test answer from %s: %r" % (self.host, text[:80]))
        return {"host": self.host, "key": self.api_key}

    def headers(self, key=None):
        h = {
            "c-api-key": key or self.api_key,
            "c-useragent": self.user_agent,
            "c-app-version": self.app_version,
            "c-platform": self.platform,
            "User-Agent": self.user_agent,
        }
        if self.token:
            h["c-token"] = self.token
        return h

    def _send(self, host, key, name, params, timeout=None, raw=False):
        env = super()._send(host, key, name, params, timeout=timeout, raw=raw)
        return env if raw else _fix_links(env)


class WebClient:
    def __init__(self, token=None, store=None, transport=None, persist=True, timeout=C.TIMEOUT):
        """
        token:   v1 session token. Default: $SINAMA_WEB_TOKEN, else the saved web session.
        store:   SessionStore (default ~/.sinama/web-session.json, or $SINAMA_WEB_SESSION_FILE).
        """
        self.store = store or SessionStore(os.environ.get(C.ENV_WEB_SESSION_FILE) or C.DEFAULT_WEB_SESSION_FILE)
        saved = self.store.load()
        self.persist = persist
        self.transport = transport or WebTransport(timeout=timeout)
        self.transport.token = token or os.environ.get(C.ENV_WEB_TOKEN) or saved.get("token")
        self.user_info = saved.get("user") if saved.get("token") == self.transport.token else None

    # ------------------------------------------------------------------ plumbing
    @property
    def token(self):
        return self.transport.token

    @property
    def is_logged_in(self):
        return bool(self.transport.token)

    def call(self, path, /, *, retry=None, **form):
        """Raw envelope for any v1 path, e.g. call("single/id/8863")."""
        return self.transport.call(path, form, retry=retry)

    def get(self, path, /, *, retry=None, **form):
        """`result` of any v1 path, raising ApiError on success:false."""
        return web_check(path, self.call(path, retry=retry, **form))

    def _auth(self, path):
        if not self.transport.token:
            raise LoginRequired("Login Required", envelope={"msg": "Login Required"}, action=path)

    def set_session(self, token, user=None):
        self.transport.token = token
        self.user_info = user
        if self.persist:
            self.store.save({"token": token, "user": user})

    def clear_session(self):
        self.transport.token = None
        self.user_info = None
        if self.persist:
            self.store.clear()

    def test(self):
        """Health check: the API answers plain text "OK"."""
        return self.transport.call("test", raw=True).strip() == "OK"

    # ------------------------------------------------------------------ auth
    def qr_code(self):
        """New login code: {code, url}. Approve it at `url`, with qr_approve(), or a v2 Client."""
        return self.get("qrcode/")

    def qr_check(self, code):
        """Poll once: None while pending, else logs in and returns the user dict."""
        env = self.call("qrlogin/code/" + _q(code), retry=False)
        if not env.get("success"):
            if env.get("msg") is None:  # pending: success:false with msg null
                return None
            web_check("qrlogin", env)
        r = env.get("result") or {}
        token = r.get("usertoken")
        if not token:
            raise ApiError("qrlogin answered without usertoken", envelope=env, action="qrlogin")
        self.set_session(token, r)
        return r

    def qr_approve(self, code):
        """Approve another device's QR code with this session (what 30nama.com/auth/<code> does)."""
        self._auth("auth/code")
        return self.get("auth/code/" + _q(code), retry=False)

    def qr_login(self, approve_with=None, on_code=None, timeout=C.QR_TTL_SECONDS, poll=C.QR_POLL_SECONDS):
        """QR login. With `approve_with` (a logged-in v2 `Client`, or another WebClient) the code
        is approved immediately; otherwise `on_code(code, url)` is called so a person can approve it."""
        qr = self.qr_code()
        code = qr["code"]
        if approve_with is not None:
            approve_with.qr_approve(code)
        elif on_code:
            on_code(code, qr.get("url") or C.QR_BASE + code)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            u = self.qr_check(code)
            if u:
                return u
            time.sleep(poll)
        raise QRCodeExpired("QR code not approved within %ss" % timeout, action="qrlogin")

    def login(self, username=None, password=None, recaptcha_response=None):
        """Password login (loginV2). Needs a reCAPTCHA token solved on 30nama.com."""
        username = username or os.environ.get(C.ENV_EMAIL)
        password = password or os.environ.get(C.ENV_PASSWORD)
        r = self.get("loginV2", retry=False, userlogin=username, userpassword=password,
                     **{"g-recaptcha-response": recaptcha_response})
        self.set_session(r.get("usertoken"), r)
        return r

    def send_otp(self, userlogin, recaptcha_response=None):
        return self.get("send_otp", retry=False, userlogin=userlogin, **{"g-recaptcha-response": recaptcha_response})

    def verify_otp(self, userlogin, code):
        r = self.get("verify_otp", retry=False, userlogin=userlogin, code=code)
        if isinstance(r, dict) and r.get("usertoken"):
            self.set_session(r["usertoken"], r)
        return r

    def register(self, userlogin, recaptcha_response=None):
        """Start sign-up (registerV2); finish with verify_registration()."""
        return self.get("registerV2/", retry=False, userlogin=userlogin, **{"g-recaptcha-response": recaptcha_response})

    def verify_registration(self, userlogin, code):
        return self.get("verifyV2", retry=False, userlogin=userlogin, code=code)

    def resend_verification(self, userlogin):
        return self.get("resendV2", retry=False, userlogin=userlogin)

    def reset_password(self, userlogin, recaptcha_response=None):
        return self.get("resetpasswordV2", retry=False, userlogin=userlogin,
                        **{"g-recaptcha-response": recaptcha_response})

    def verify_reset_password(self, userlogin, code):
        return self.get("verifyresetpasswordV2", retry=False, userlogin=userlogin, code=code)

    def logout(self):
        try:
            return self.call("logout", retry=False) if self.token else None
        finally:
            self.clear_session()

    # ------------------------------------------------------------------ account
    def user(self):
        """Profile: username, useremail, usertype, expire, allowed_to_stream/download, avatar,
        active_sessions, social links, ..."""
        self._auth("user")
        u = self.get("user")
        self.user_info = u
        if self.persist:
            self.store.update(token=self.token, user=u)
        return u

    def update_user(self, **fields):
        """Edit profile fields (first_name, last_name, description, instagram, ...)."""
        self._auth("update_user")
        return self.get("update_user", retry=False, **fields)

    def update_password(self, current_password, new_password):
        self._auth("update_user_password")
        return self.get("update_user_password", retry=False, current_password=current_password,
                        new_password=new_password, confirm_new_password=new_password)

    def is_new_user(self):
        self._auth("is_new_user")
        return self.get("is_new_user")

    def popup_users(self):
        """{is_loyal_user, is_new_user}"""
        self._auth("popup_users")
        return self.get("popup_users")

    def profile(self, username):
        """Public profile of a user."""
        return self.get("profile/user/" + _q(username))

    def profile_list(self, username, group="watchlist", page=1, orderby="date", order="desc", type="all"):
        """A user's public list (watchlist, favorite, ...)."""
        return self.get("profile/user/%s/list/%s/page/%s/orderby/%s/order/%s/type/%s"
                        % (_q(username), _q(group), page, _q(orderby), _q(order), _q(type)))

    # ------------------------------------------------------------------ browse
    def home(self):
        """featured, freestream, hero_section, new_releases, suggested, top, movies, series, anime,
        top10, quote, today_birthdays."""
        return self.get("main/")

    def home_v2(self):
        """featured, hero_section, suggested, top10, news, review, faq, tweets, call_to_action."""
        return self.get("mainV2/")

    def stream_home(self):
        return self.get("main/streamonly/yes")

    def menu(self):
        """genres, categories, toplists, boxoffice."""
        return self.get("menu")

    def genres(self):
        return self.get("genres/")

    def single(self, post_id, page=None):
        """A title, person or article by id (one id space). Titles include collections,
        soundtracks, reviews, news, quotes, related_posts, metacritic/rottentomatoes scores and
        30nama_userrate. `page` pages a person's filmography."""
        path = "single/id/%s" % _q(post_id) + ("/page/%s" % page if page else "")
        r = self.get(path)
        if not r or not isinstance(r, dict) or not r.get("id"):
            raise NotFound("not found", envelope={"result": r}, action="single")
        return r

    person = single

    def search(self, query, page=1, orderby="relevant", order="desc"):
        """Title search: {page, pages, posts}. orderby: relevant | imdb | date | ..."""
        return self.get("search/page/%s/order/%s/orderby/%s/" % (page, _q(order), _q(orderby)), query=query)

    def autocomplete(self, query):
        """What the site's search box uses: first page ordered by IMDb votes."""
        return self.search(query, 1, "imdb", "desc")

    def full_search(self, query, type="all", page=1, orderby="relevant", order="desc"):
        """Titles, people and news at once: {title, person, news}. type: all | title | person | news."""
        return self.get("full_search/type/%s/orderby/%s/order/%s/page/%s" % (_q(type), _q(orderby), _q(order), page),
                        query=query)

    def archive(self, type="movie", page=1, orderby="date", order="desc", stream_only=False):
        """Category listing (`pagination`): type from menu()["categories"] slugs."""
        return self.get("pagination/type/%s/page/%s/order/%s/orderby/%s/streamonly/%s"
                        % (_q(type), page, _q(order), _q(orderby), _yes(stream_only)))

    def list(self, type="category", value="movie", page=1, orderby="date", stream_only=False, extra=""):
        """Generic listing: type category|genre|country|..., value its slug."""
        return self.get("list/type/%s/value/%s/page/%s/orderby/%s/order/desc/streamonly/%s/%s"
                        % (_q(type), _q(value), page, _q(orderby), _yes(stream_only), extra))

    def advanced_search_parameters(self):
        return self.get("advanced_search_parametres")  # sic: the API spells it this way

    def advanced_search(self, parameters=None, page=1, orderby="relevant", order="desc", **filters):
        params = dict(parameters or {})
        params.update(filters)
        return self.get("advanced_search/page/%s/orderby/%s/order/%s" % (page, _q(orderby), _q(order)),
                        parameters=params)

    def comments(self, post_id, page=1, type="comment", orderby="date"):
        """{page, pages, total_comments, type, comments}. type: comment | review. orderby: date | like."""
        return self.get("comment/id/%s/page/%s/type/%s/orderby/%s" % (_q(post_id), page, _q(type), _q(orderby)))

    def articles(self, type="news", page=1):
        """News and site posts: type news | announcement | knowledgebase | ..."""
        return self.get("article/type/%s/page/%s" % (_q(type), page))

    def article(self, article_id):
        return self.single(article_id)

    def collections(self, page=1, query=None):
        """{collections, page, pages}; with `query`, a collection search."""
        return self.get("collection/page/%s" % page, **({"query": query} if query else {}))

    def collection(self, collection_id):
        """Titles of one collection."""
        return self.get("collection/id/%s" % _q(collection_id))

    def toplist(self, slug="top-movie-imdb"):
        """Slugs from menu()["toplists"]: top-movie-imdb, top-series-imdb, top-movie-30nama, top-series-30nama."""
        return self.get("toplist/list/%s" % _q(slug))

    def boxoffice(self, iran=False):
        """Weekend box office: US by default, Iran with iran=True."""
        return self.get("boxoffice/iran/%s" % _yes(iran))

    def schedule(self, type="series"):
        """Airing schedule: series | anime."""
        return self.get("schedule/type/%s" % _q(type))

    def people(self, gender="male", profession="actor", page=1):
        """Browse people (the site's 'characters' pages)."""
        return self.get("person/gender/%s/profession/%s/page/%s" % (_q(gender), _q(profession), page))

    def url_to_post(self, url):
        """Resolve a 30nama.com page URL to its post (`UrlToPost` in the site's client).

        The site itself never calls it, and no URL form tried live was accepted (full canonical
        URL, path with or without a leading slash): all answered NotFound.
        """
        return self.get("url", url=url)

    def tos(self):
        return self.get("tos")

    def dmca(self):
        return self.get("dmca")

    def event(self):
        """Live event (30nama Party): status, title, hls, date, chatServer, ..."""
        return self.get("event")

    # ------------------------------------------------------------------ playback
    def stream(self, post_id, free=False):
        """{data, file: {url, ip, source: [{label, auto, 2ch, 6ch}]}, subtitle: {fa, en},
        options: {intro_start, intro_end, key}, watched, image, vast2}"""
        if not free:
            self._auth("stream")
        return self.get("stream/id/%s" % _q(post_id), freeStream=1 if free else 0)

    def download(self, post_id, free=False):
        if not free:
            self._auth("download")
        return self.get("download/id/%s" % _q(post_id), freeDownload=1 if free else 0)

    def observer(self, post_id, file_id, time_s, duration_s, key, user_id=None):
        """Progress report. v1 posts to {host}/observer/observer (outside /api/v1) with
        fid, pid, t, d, k (stream options.key) and uid."""
        self._auth("observer")
        uid = user_id or (self.user_info or {}).get("userid") or ""
        t = self.transport
        url = re.sub(r"/api/v\d+/?$", "", t.host) + "/observer/observer"
        r = t.http.post(url, data={"fid": file_id, "pid": post_id, "t": int(time_s), "d": int(duration_s),
                                   "k": key, "uid": uid},
                        headers=dict(t.headers(), **{"c-output-requests": "true"}), timeout=t.timeout)
        return {"http_status": r.status_code, "text": r.text[:200]}

    def watched(self, sort_by=1):
        """Watch history (stream_watched): list of posts with progress."""
        self._auth("stream_watched")
        return self.get("stream_watched/sortBy/%s/sortBy/" % _q(sort_by))

    def dismiss_watched(self, post_id):
        self._auth("stream_watched_dismiss")
        return self.get("stream_watched_dismiss/id/%s" % _q(post_id), retry=False)

    # ------------------------------------------------------------------ library
    def my_lists(self):
        """Ids per group: watchlist, favorite, downloadlist, notify."""
        self._auth("user_mylist")
        return self.get("user_mylist")

    def my_list(self, group="watchlist", page=1):
        self._auth("mylist")
        return self.get("mylist/group/%s/page/%s" % (_q(group), page))

    def list_toggle(self, group, post_id):
        """add_to_mylist TOGGLES membership like v2 user_list action=add."""
        self._auth("add_to_mylist")
        return self.get("add_to_mylist/id/%s/group/%s" % (_q(post_id), _q(group)), retry=False)

    # ------------------------------------------------------------------ social (writes are public)
    def send_comment(self, post_id, text, reply_to=None):
        """Post a public comment (or a reply). Visible to everyone."""
        self._auth("sendcomment")
        path = "sendcomment/post_id/%s" % _q(post_id) + ("/comment_id/%s" % _q(reply_to) if reply_to else "")
        return self.get(path, retry=False, text=text)

    def rate_comment(self, comment_id, post_id, rate):
        """Like (1) or dislike (-1, presumably) a comment."""
        self._auth("rate_comment")
        return self.get("rate_comment/id/%s/post_id/%s/rate/%s" % (_q(comment_id), _q(post_id), _q(rate)), retry=False)

    def rate_post(self, post_id, rate):
        """Rate a title (1-10)."""
        self._auth("rate_post")
        return self.get("rate_post/id/%s/rate/%s" % (_q(post_id), _q(rate)), retry=False)

    def request_parameters(self):
        """Vocabulary for submit_request (types, subtypes)."""
        self._auth("request_parameters")
        return self.get("request_parameters")

    def requests(self, page=1):
        """Your title/subtitle requests."""
        self._auth("requests")
        return self.get("requests/page/%s" % page)

    def submit_request(self, type, subtype, title, note="", recaptcha_response=None):
        self._auth("request")
        return self.get("request", retry=False, type=type, subtype=subtype, title=title, note=note,
                        **{"g-recaptcha-response": recaptcha_response})

    # ------------------------------------------------------------------ notifications
    def notifications(self, status="all", page=1):
        """status: all | unread"""
        self._auth("notification")
        return self.get("notification/status/%s/page/%s" % (_q(status), page))

    def read_notification(self, notification_id):
        self._auth("readnotification")
        return self.get("readnotification/id/%s" % _q(notification_id), retry=False)

    # ------------------------------------------------------------------ plans & payments
    def plans(self, discount_code=None):
        return self.get("plans" + ("/discountcode/%s" % _q(discount_code) if discount_code else ""))

    def plans_features(self, discount_code=None):
        return self.get("plans_features" + ("/discountcode/%s" % _q(discount_code) if discount_code else ""))

    def check_discount(self, discount_code, plan_id):
        self._auth("discount")
        return self.get("discount/discountcode/%s/planid/%s" % (_q(discount_code), _q(plan_id)))

    def transactions(self):
        self._auth("transactions")
        return self.get("transactions")

    def transaction_status(self, txn_id):
        self._auth("txn")
        return self.get("txn/txnid/%s" % _q(txn_id))

    def check_upgrade(self):
        """Upgrade options and prices for the current plan."""
        self._auth("check_upgrade")
        return self.get("check_upgrade")

    def upgrade_red_to_golden_check(self):
        self._auth("upgrade_red_to_golden_check")
        return self.get("upgrade_red_to_golden_check")

    def use_voucher(self, voucher_code):
        """Redeem a voucher code (changes the subscription)."""
        self._auth("voucher")
        return self.get("voucher/vouchercode/%s" % _q(voucher_code), retry=False)

    def upgrade_code(self, code):
        self._auth("upgrade_code")
        return self.get("upgrade_code/upgrade_code/%s" % _q(code), retry=False)

    def create_transaction_shaparak(self, plan_id, discount_code=""):
        """Start an Iranian bank-gateway payment; returns a payment link. Not exercised by tests."""
        self._auth("shaparak")
        return self.get("shaparak/planid/%s/discountcode/%s" % (_q(plan_id), _q(discount_code)), retry=False)

    def create_transaction_crypto(self, plan_id, currency, discount_code=""):
        """Start a cryptocurrency payment. Not exercised by tests."""
        self._auth("cryptocurrency")
        return self.get("cryptocurrency/planid/%s/currency/%s/discountcode/%s"
                        % (_q(plan_id), _q(currency), _q(discount_code)), retry=False)

    def create_transaction_perfectmoney(self, plan_id, discount_code=""):
        """Start a Perfect Money payment. Not exercised by tests."""
        self._auth("perfectmoney")
        return self.get("perfectmoney/planid/%s/discountcode/%s" % (_q(plan_id), _q(discount_code)), retry=False)


# Persian / v1-specific messages (verified live), mapped onto the shared exception types.
_V1_LOGIN = ("ابتدا وارد حساب خود شوید",)  # "log in to your account first"
_V1_NOT_FOUND = ("چنین پستی وجود ندارد", "یافت نشد")  # "no such post", "not found"
_V1_CAPTCHA = ("کپچا",)  # "captcha parameters are invalid"
_V1_BAD_CODE = ("کد فعالسازی اشتباه است",)  # "the activation code is wrong" (QR codes)


def web_check(path, env):
    """check() for v1 envelopes: adds the Persian messages, then defers to the shared mapping."""
    if isinstance(env, dict) and not env.get("success"):
        msg = str(env.get("msg") or "")
        st = env.get("status")
        if any(m in msg for m in _V1_LOGIN):
            raise LoginRequired(msg, st, env, path)
        if any(m in msg for m in _V1_NOT_FOUND):
            raise NotFound(msg, st, env, path)
        if any(m in msg for m in _V1_CAPTCHA):
            raise CaptchaRequired(msg, st, env, path)
        if any(m in msg for m in _V1_BAD_CODE):
            raise QRCodeExpired(msg, st, env, path)
    return check(path, env).get("result")
