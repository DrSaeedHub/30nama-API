"""Live tests against the real API for every endpoint that works without a session.

Run: python -m pytest tests/test_live_public.py -v
"""
import json
import os

import pytest
import requests

from sinama import (
    ApiError,
    CaptchaRequired,
    Client,
    LoginRequired,
    MemoryStore,
    NotFound,
    QRCodeExpired,
    Transport,
    config as C,
    helpers,
    screens,
)

pytestmark = pytest.mark.live

POST_KEYS = {"id", "post_type", "options", "info", "title", "image"}


def assert_post(p):
    missing = POST_KEYS - set(p)
    assert not missing, "post %s missing %s" % (p.get("id"), missing)
    assert isinstance(p["id"], int)
    assert {"title_type", "stream", "is_series"} <= set(p["options"])
    assert helpers.title(p)


def assert_page(r, min_total=1):
    assert {"posts", "page", "pages", "total"} <= set(r), r.keys()
    assert r["total"] >= min_total and r["pages"] >= 1 and r["page"] >= 1
    for p in r["posts"]:
        assert_post(p)


# ------------------------------------------------------------------ discovery / connection
def test_discovery_lists_hosts():
    hosts = Transport().discover()
    assert hosts and all(h["host"].startswith("https://") for h in hosts)


def test_init_picks_working_host(live):
    assert live.host in {h["host"] for h in C.FALLBACK_HOSTS} or live.host.startswith("https://")
    assert live.transport.api_key in C.API_KEYS


def test_test_action(live):
    r = live.test()
    assert {"ip", "device", "platform"} <= set(r)
    assert r["platform"] in ("WebTV", "AndroidTV")


def test_unknown_action_is_not_found(live):
    with pytest.raises(NotFound):
        live.get("definitely_not_an_action")


# ------------------------------------------------------------------ auth endpoints (anonymous side)
def test_captcha_is_required(live):
    assert live.captcha_required() is True


def test_password_login_without_captcha_is_rejected(live):
    if not os.environ.get(C.ENV_EMAIL) or not os.environ.get(C.ENV_PASSWORD):
        pytest.skip("set %s / %s" % (C.ENV_EMAIL, C.ENV_PASSWORD))
    c = Client(store=MemoryStore(), token=None, host=live.host, persist=False)
    c.transport.token = None
    with pytest.raises(CaptchaRequired) as ei:
        c.login()  # credentials from the environment
    assert ei.value.hint == ["retry"]
    assert c.token is None


def test_register_is_captcha_gated(live):
    with pytest.raises(CaptchaRequired):
        live.register()


def test_otp_verify_rejects_bad_code(live):
    with pytest.raises(ApiError) as ei:
        live.otp_verify("nobody@example.invalid", "000000")
    assert "invalid" in ei.value.msg.lower()
    assert live.token is None


def test_qr_code_and_pending_poll(live):
    qr = live.qr_code()
    assert len(qr["code"]) >= 6 and qr["url"] == C.QR_BASE + qr["code"]
    assert live.qr_check(qr["code"]) is None  # CODE_NOT_USED while nobody approved it
    assert live.token is None


def test_qr_wrong_code(live):
    with pytest.raises(QRCodeExpired):
        live.qr_check("00000000")


def test_logout_without_session(live):
    env = Client(store=MemoryStore(), token="", host=live.host, persist=False).call("logout")
    assert env["success"] is True


def test_plans(live):
    r = live.plans()
    assert r["plans"] and {"id", "type", "title", "features", "prices"} <= set(r["plans"][0])


# ------------------------------------------------------------------ private endpoints refuse anonymous calls
@pytest.mark.parametrize("action,params", [
    ("user", {}), ("stream", {"post_id": 8863}), ("download", {"post_id": 8863}),
    ("continue_watching", {}), ("continue_watching_dismiss", {"id": 8863}), ("user_mylist", {}),
    ("user_list", {"action": "list", "group": "watchlist"}), ("notification", {}),
    ("notification_read", {"notification_id": 1}),
])
def test_private_actions_require_login(live, action, params):
    with pytest.raises(LoginRequired):
        live.get(action, **params)


def test_observer_anonymous_is_accepted_silently(live):
    env = live.call("observer", post_id=8863, file_id=1, time=10, duration=100)
    assert env["success"] is True and env["http_status"] == 204


# ------------------------------------------------------------------ browse
@pytest.mark.parametrize("method,rows", [
    ("home", {"hero_header", "new_releases", "suggested", "top_10", "movies", "series", "anime"}),
    ("home_stream", {"hero_header", "suggested", "movies", "series", "anime"}),
])
def test_home(live, method, rows):
    r = getattr(live, method)()
    assert rows <= set(r)
    for k in rows:
        assert r[k]["posts"], k
        assert_post(r[k]["posts"][0])


def test_menu(live):
    r = live.menu()
    slugs = {c["slug"] for c in r["categories"]}
    assert {"movies", "series", "anime"} <= slugs
    g = r["genres"][0]
    assert {"id", "name", "slug", "count", "image"} <= set(g) and g["count"] > 0


def test_single_movie(live, sample):
    p = live.single(sample["movie"])
    assert_post(p)
    assert p["id"] == sample["movie"] and not p["options"]["is_series"]
    for k in ("plot", "genre", "cast", "crew", "score", "country", "list", "air", "subtitle"):
        assert k in p, k


def test_single_series(live, sample):
    p = live.single(sample["series"])
    assert p["options"]["is_series"] and p["info"]["seasons"]


def test_single_not_found(live):
    with pytest.raises(NotFound):
        live.single(999999999)


def test_search(live):
    r = live.search("inception")
    assert_page(r)
    assert any("Inception" in helpers.title(p) for p in r["posts"])


def test_search_stream_only_filters(live):
    all_, only = live.search("batman"), live.search("batman", stream_only=True)
    assert 0 < only["total"] < all_["total"]
    assert all(p["options"]["stream"] for p in only["posts"])


def test_search_paging(live):
    p1, p2 = live.search("batman", page=1), live.search("batman", page=2)
    assert p2["page"] == 2
    assert {p["id"] for p in p1["posts"]}.isdisjoint({p["id"] for p in p2["posts"]})


@pytest.mark.parametrize("sort", ["date", "favorite", "update", "relevant", "year"])
def test_archive_sorts(live, sort):
    r = live.archive("movies", orderby=sort, stream_only=True)
    assert_page(r, 100)
    assert all(p["options"]["stream"] for p in r["posts"])


def test_archive_genre_and_order(live):
    asc = live.archive("drama", orderby="year", order="asc")
    desc = live.archive("drama", orderby="year", order="desc")
    assert_page(asc, 1000)
    assert asc["posts"][0]["info"]["year"] <= desc["posts"][0]["info"]["year"]


def test_archive_unknown_slug(live):
    with pytest.raises(NotFound):
        live.archive("no-such-slug-zz")


def test_advanced_search_parameters(live):
    r = live.advanced_search_parameters()
    assert {"genre", "type", "imdb_rate", "country", "language", "min_year", "max_year"} <= set(r)
    assert r["min_year"] < r["max_year"]


def test_advanced_search_filters(live):
    everything = live.advanced_search({})
    drama = live.advanced_search(genre=["drama"], imdb_rate=8, stream="true")
    assert_page(drama)
    assert drama["total"] < everything["total"]
    assert all(p["options"]["stream"] for p in drama["posts"])


def test_advanced_search_by_actor(live):
    r = live.advanced_search(actor="nm0000138")  # Leonardo DiCaprio
    assert_page(r)
    assert any("Inception" in helpers.title(p) for p in live.iter_pages(live.advanced_search, actor="nm0000138"))


def test_iter_pages(live):
    ids = [p["id"] for p in live.iter_pages(live.search, "batman", max_pages=2)]
    assert len(ids) == len(set(ids)) > 20


def test_subtitle_action(live):
    text = live.subtitle("dGVzdA==")
    assert text.startswith("WEBVTT")


# ------------------------------------------------------------------ screens
def test_screen_home(live):
    h = screens.home(live)
    assert h["hero"] and h["rows"] and h["continue_watching"] == []


def test_screen_details_anonymous(live, sample):
    d = screens.details(live, sample["movie"])
    assert d["post"]["id"] == sample["movie"] and d["stream"] is None and d["items"] == []


def test_screen_search_and_browse(live):
    assert screens.search(live, "")["popular"] is True
    assert screens.search(live, "dune")["total"] >= 1
    b = screens.browse(live)
    assert b["categories"] and b["genres"]
    assert_page(screens.archive_list(live, "series"))


# ------------------------------------------------------------------ CLI
def test_cli(capsys):
    from sinama.app import main
    assert main(["search", "inception", "--stream-only"]) == 0
    assert "Inception" in capsys.readouterr().out
    assert main(["--json", "call", "test"]) == 0
    assert json.loads(capsys.readouterr().out)["success"] is True
