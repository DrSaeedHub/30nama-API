"""Live tests for the website API (interface.30nama.com/api/v1) and the v2 actions found in
the official SDK. The v1 host rate-limits hard (~30 requests/minute), so WebTransport paces
requests 2.5 s apart and this module takes a couple of minutes.

Logged-in v1 tests use the saved web session (~/.sinama/web-session.json or
SINAMA_WEB_TOKEN). If there is none but a v2 session exists, one is linked once with
WebClient.qr_login(approve_with=<v2 Client>) and saved. Nothing visible changes on the
account: the only write (a watchlist toggle) is reverted; comments, ratings, requests,
payments and history dismissal are covered offline only.
"""
import pytest
import requests

from sinama import ApiError, CaptchaRequired, LoginRequired, MemoryStore, NotFound, QRCodeExpired, SessionStore, WebClient
from sinama import config as C

pytestmark = pytest.mark.live

MOVIE = 8863  # Inception (2010)
PERSON = 151410  # Leonardo DiCaprio


@pytest.fixture(scope="module")
def web():
    w = WebClient(store=MemoryStore(), persist=False, token=None)
    w.transport.token = None
    return w


@pytest.fixture(scope="module")
def web_auth(auth):
    store = SessionStore(C.DEFAULT_WEB_SESSION_FILE)
    w = WebClient(store=store)
    if w.token:
        try:
            w.user()
            return w
        except LoginRequired:
            w.clear_session()
    w.qr_login(approve_with=auth)  # link a website session from the v2 session, once
    w.user()
    return w


# ------------------------------------------------------------------ v1 public
def test_web_test(web):
    assert web.test() is True


def test_web_menu(web):
    m = web.menu()
    assert {"genres", "categories", "toplists", "boxoffice"} <= set(m)
    assert {t["slug"] for t in m["toplists"]} >= {"top-movie-imdb", "top-series-imdb"}


@pytest.mark.parametrize("method,keys", [
    ("home", {"featured", "hero_section", "new_releases", "suggested", "movies", "series", "anime"}),
    ("home_v2", {"featured", "hero_section", "suggested", "top10", "news"}),
    ("stream_home", {"hero_section", "movies", "series"}),
])
def test_web_home(web, method, keys):
    assert keys <= set(getattr(web, method)())


def test_web_genres(web):
    g = web.genres()
    assert isinstance(g, list) and len(g) > 20


def test_web_single_title_is_rich(web):
    s = web.single(MOVIE)
    assert s["id"] in (MOVIE, str(MOVIE))
    assert {"collections", "soundtracks", "reviews", "quotes", "related_posts", "metacritic_score",
            "rottentomatoes_score", "imdb_score", "cast", "director"} <= set(s)
    assert s["seo"]["canonical"].startswith("https://30nama.com/")
    assert not any("link://" in str(v) for v in (s.get("image"), s.get("cast")))


def test_web_person(web):
    p = web.person(PERSON)
    assert p["imdb"].rstrip("/").endswith("nm0000138")  # v1 gives the full IMDb URL
    assert {"name", "gender", "profession"} <= set(p)


def test_web_single_not_found(web):
    with pytest.raises(NotFound):
        web.single(999999999)


def test_web_search_and_autocomplete(web):
    r = web.search("inception")
    assert r["posts"] and r["pages"] >= 1
    assert any(str(p.get("id")) == str(MOVIE) for p in web.autocomplete("inception")["posts"])


@pytest.mark.parametrize("type", ["all", "person"])
def test_web_full_search(web, type):
    r = web.full_search("nolan", type=type)
    assert {"title", "person", "news"} <= set(r)


def test_web_archive_and_list(web):
    a = web.archive("series", stream_only=True)
    assert a["posts"] and a["pages"] > 1
    assert web.list("category", "movie")["posts"]


def test_web_advanced_search(web):
    params = web.advanced_search_parameters()
    assert {"genre", "type", "min_year", "max_year"} <= set(params)
    drama = next(g["value"] for g in params["genre"] if g.get("slug") == "drama")  # v1 uses numeric ids (3362)
    everything, filtered = web.advanced_search({}), web.advanced_search(genre=[drama])
    assert filtered["posts"] and filtered["pages"] < everything["pages"]
    hits = web.advanced_search(keyword="inception", stream=True)["posts"]
    assert any("Inception" in str(p.get("title")) for p in hits)


@pytest.mark.parametrize("type", ["comment", "review"])
def test_web_comments(web, type):
    r = web.comments(MOVIE, type=type)
    assert {"page", "pages", "total_comments", "comments"} <= set(r)
    if r["comments"]:
        assert isinstance(r["comments"], list)


@pytest.mark.parametrize("type", ["news", "announcement"])
def test_web_articles(web, type):
    r = web.articles(type)
    assert r["posts"] and r["pages"] >= 1


def test_web_collections(web):
    r = web.collections()
    assert r["collections"] and r["pages"] >= 1
    first = r["collections"][0]
    titles = web.collection(first["id"])
    assert titles


@pytest.mark.parametrize("slug", ["top-movie-imdb", "top-series-30nama"])
def test_web_toplist(web, slug):
    assert len(web.toplist(slug)["posts"]) >= 50


@pytest.mark.parametrize("iran", [False, True])
def test_web_boxoffice(web, iran):
    assert isinstance(web.boxoffice(iran)["posts"], list)  # empty on the server as of 2026-10-24


@pytest.mark.parametrize("type", ["series", "anime"])
def test_web_schedule(web, type):
    assert "posts" in web.schedule(type)


def test_web_people(web):
    assert web.people("male", "actor")["posts"]


@pytest.mark.parametrize("method", ["tos", "dmca"])
def test_web_pages(web, method):
    assert getattr(web, method)()["content"]


def test_web_event_and_plans(web):
    assert "status" in web.event()
    assert {"golden", "red"} <= set(web.plans())
    assert {"free", "red", "golden"} <= set(web.plans_features())


def test_web_errors(web):
    with pytest.raises(LoginRequired):
        web.get("request_parameters")
    with pytest.raises(NotFound):
        web.get("no_such_action_zz")  # plain-text 404
    with pytest.raises(QRCodeExpired):
        web.qr_check("00000000")
    with pytest.raises(CaptchaRequired):
        web.get("loginV2", userlogin="nobody@example.invalid", userpassword="x")
    with pytest.raises(NotFound):
        web.url_to_post("https://30nama.com/movie/8863/Inception-2010")


# ------------------------------------------------------------------ v1 logged in (read-only + one reverted toggle)
def test_web_user(web_auth):
    u = web_auth.user()
    assert u["username"] and "allowed_to_stream" in u and "active_sessions" in u


def test_web_lists_and_history(web_auth):
    assert {"watchlist", "favorite"} <= set(web_auth.my_lists())
    assert "posts" in web_auth.my_list("watchlist")
    assert isinstance(web_auth.watched(), list)
    assert "notifications" in web_auth.notifications()


def test_web_stream_plays(web_auth):
    s = web_auth.stream(MOVIE)
    assert {"data", "file", "options", "subtitle"} <= set(s)
    src = s["file"]["source"]
    assert src and {"label", "auto"} <= set(src[0]) and s["options"].get("key")
    r = requests.get(src[0]["auto"], timeout=20)
    assert r.status_code == 200 and "#EXTM3U" in r.text


def test_web_download(web_auth):
    d = web_auth.download(MOVIE)
    assert "download" in d


def test_web_account_reads(web_auth):
    assert "list" in web_auth.transactions()
    assert {"golden", "red"} <= set(web_auth.check_upgrade())
    assert "requests" in web_auth.requests()
    assert {"options", "parameters"} <= set(web_auth.request_parameters())
    assert "is_new_user" in web_auth.is_new_user()
    assert web_auth.profile(web_auth.user_info["username"])


def test_web_list_toggle_roundtrip(web_auth):
    def has():
        return str(MOVIE) in {str(i) for i in (web_auth.my_lists().get("watchlist") or {}).get("post", [])}
    before = has()
    try:
        web_auth.list_toggle("watchlist", MOVIE)
        assert has() is (not before)
    finally:
        if has() is not before:
            web_auth.list_toggle("watchlist", MOVIE)
    assert has() is before


# ------------------------------------------------------------------ v2 actions found in the SDK
def test_v2_endpoints(live):
    hosts = live.endpoints()
    assert hosts and all(h["host"].startswith("https://") for h in hosts)


def test_v2_offer_checks(live):
    assert live.offer() is None or isinstance(live.offer(), (dict, list))
    live.checks()


def test_v2_plans_gateway(live):
    default, paypal = live.plans(), live.plans(gateway="paypal")
    assert {p["id"] for p in default["plans"]} != {p["id"] for p in paypal["plans"]}
    assert live.plans(discount_code="NOT-A-CODE")["discount"]["use_discount"] is False


def test_v2_voucher_rejects_bad_code(auth):
    with pytest.raises(ApiError) as ei:
        auth.voucher("INVALID-0000")
    assert ei.value.msg == "INVALID_VOUCHER_CODE"


def test_v2_qr_approve(auth, live):
    with pytest.raises(LoginRequired):
        live.get("qrlogin_auth", auth_code="00000000")
    with pytest.raises(QRCodeExpired):
        auth.qr_approve("00000000")
