"""Offline tests: request building for every endpoint, envelope/error mapping, retries,
the scheduler, the library cache, and the pure helpers (direct, player, helpers, store)."""
import json
import threading
import time

import pytest

from conftest import FakeResponse, fail, ok
from sinama import (
    ApiError,
    Blocked,
    CaptchaRequired,
    LoginRequired,
    MemoryStore,
    NotFound,
    QRCodeExpired,
    RateLimited,
    SessionStore,
    TransportError,
    direct,
    helpers,
    player,
    screens,
)
from sinama.api import Scheduler, encode


# ------------------------------------------------------------------ request building
ENDPOINTS = [
    # (method, args, kwargs, action, expected form fields)
    ("test", (), {}, "test", {}),
    ("captcha_required", (), {}, "captcha", {}),
    ("qr_code", (), {}, "qrlogin_code", {}),
    ("user", (), {}, "user", {}),
    ("plans", (), {}, "plans", {}),
    ("home", (), {}, "home", {}),
    ("home_stream", (), {}, "home_stream", {}),
    ("menu", (), {}, "menu", {}),
    ("search", ("dune",), {}, "search", {"query": "dune", "page": 1}),
    ("search", ("dune",), {"page": 2, "stream_only": True}, "search", {"query": "dune", "page": 2, "streamonly": "true"}),
    ("archive", ("movies",), {}, "archive", {"slugs": "movies", "page": 1, "orderby": "date", "order": "desc"}),
    ("archive", ("drama",), {"page": 3, "orderby": "favorite", "order": "asc", "stream_only": True}, "archive",
     {"slugs": "drama", "page": 3, "orderby": "favorite", "order": "asc", "streamonly": "true"}),
    ("advanced_search_parameters", (), {}, "advanced_search_parameters", {}),
    ("stream", (5,), {}, "stream", {"post_id": 5}),
    ("stream", (5,), {"free": True}, "stream", {"post_id": 5, "free_stream": 1}),
    ("download", (5,), {}, "download", {"post_id": 5, "free_download": 0}),
    ("download", (5,), {"free": True}, "download", {"post_id": 5, "free_download": 1}),
    ("continue_watching", (), {}, "continue_watching", {}),
    ("continue_watching_dismiss", (9,), {}, "continue_watching_dismiss", {"id": 9}),
    ("my_lists", (), {}, "user_mylist", {}),
    ("user_list", ("favorite",), {"page": 2}, "user_list",
     {"action": "list", "group": "favorite", "page": 2, "orderby": "add_list", "order": "DESC"}),
    ("user_list_toggle", ("watchlist", 77), {}, "user_list", {"action": "add", "group": "watchlist", "post_id": 77}),
    ("notifications", (), {"page": 3}, "notification", {"page": 3}),
    ("notification_read", (11,), {}, "notification_read", {"notification_id": 11}),
    ("otp_send", ("a@b.c",), {"recaptcha_response": "R"}, "otp", {"user_login": "a@b.c", "recaptcha_response": "R"}),
    ("register", (), {"recaptcha_response": "R", "user_email": "a@b.c"}, "register",
     {"recaptcha_response": "R", "user_email": "a@b.c"}),
]


@pytest.mark.parametrize("method,args,kwargs,action,fields", ENDPOINTS,
                         ids=["%s-%d" % (e[0], i) for i, e in enumerate(ENDPOINTS)])
def test_endpoint_request(offline, fake, method, args, kwargs, action, fields):
    fake.handler = lambda a, d, h: FakeResponse(200, ok({"id": 1, "posts": [], "captcha": False}))
    getattr(offline, method)(*args, **kwargs)
    call = fake.last(action)
    assert call["url"] == "https://fake.test/api/v2/action/" + action
    assert call["data"] == fields
    h = call["headers"]
    assert h["c-token"] == "TOKEN123" and h["c-api-key"] and h["c-version-number"] and h["c-language"] == "en"


def test_single_request_and_not_found(offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(200, ok({"id": 8863, "title": {"english": "Inception"}}))
    assert offline.single(8863)["id"] == 8863
    assert fake.last("single")["data"] == {"post_id": 8863}
    # Unknown id: success:true with only continue_watching in the result.
    fake.handler = lambda a, d, h: FakeResponse(200, ok({"continue_watching": None}))
    with pytest.raises(NotFound):
        offline.single(999999999)


def test_advanced_search_serializes_parameters(offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(200, ok({"posts": []}))
    offline.advanced_search({"genre": ["drama"]}, page=2, imdb_rate=8, stream="true")
    d = fake.last("advanced_search")["data"]
    assert json.loads(d["parameters"]) == {"genre": ["drama"], "imdb_rate": 8, "stream": "true"}
    assert d["page"] == 2 and d["orderby"] == "relevant" and d["order"] == "desc"


def test_observer_params_and_204(offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(204, "")
    env = offline.observer(10, 20, 61.7, 3600, token="tk")
    assert env["success"] is True
    assert fake.last("observer")["data"] == {"post_id": 10, "file_id": 20, "user_id": 42, "time": 61,
                                             "duration": 3600, "token": "tk"}


def test_encode():
    assert encode({"a": None, "b": True, "c": False, "d": [1], "e": {"x": "y"}, "f": 3}) == \
        {"b": "true", "c": "false", "d": "[1]", "e": '{"x": "y"}', "f": 3}


# ------------------------------------------------------------------ auth flows
def test_login_sends_fields_and_saves_session(offline, fake, monkeypatch):
    def handler(a, d, h):
        if a == "login":
            return FakeResponse(200, ok({"token": "NEWTOKEN"}))
        if a == "user":
            assert h["c-token"] == "NEWTOKEN"
            return FakeResponse(200, ok({"user_id": 7, "user_name": "me"}))
        return FakeResponse(404, fail("404 Not Found", 404))
    fake.handler = handler
    u = offline.login("me@x.y", "pw", recaptcha_response="CAP")
    assert fake.last("login")["data"] == {"user_login": "me@x.y", "user_password": "pw", "recaptcha_response": "CAP"}
    assert u["user_name"] == "me" and offline.token == "NEWTOKEN"
    assert offline.store.load()["token"] == "NEWTOKEN"


def test_login_defaults_to_env(offline, fake, monkeypatch):
    monkeypatch.setenv("site_30NAMA_email", "env@x.y")
    monkeypatch.setenv("site_30NAMA_password", "envpw")
    fake.handler = lambda a, d, h: FakeResponse(200, fail("invalid-input-response", 403, ["retry"]))
    with pytest.raises(CaptchaRequired) as ei:
        offline.login()
    assert ei.value.hint == ["retry"]
    assert fake.last("login")["data"] == {"user_login": "env@x.y", "user_password": "envpw"}


def test_qr_flow(offline, fake):
    state = {"polls": 0}

    def handler(a, d, h):
        if a == "qrlogin_code":
            return FakeResponse(200, ok({"code": "abc", "url": "https://30nama.com/auth/abc"}))
        if a == "qrlogin_login":
            assert d == {"auth_code": "abc"}
            state["polls"] += 1
            if state["polls"] < 3:
                return FakeResponse(200, fail("CODE_NOT_USED"))
            return FakeResponse(200, ok({"token": "QRTOKEN"}))
        if a == "user":
            return FakeResponse(200, ok({"user_id": 1, "user_name": "qr"}))
    fake.handler = handler
    seen = []
    u = offline.qr_login(on_code=lambda code, url: seen.append(url), poll=0, timeout=5)
    assert seen == ["https://30nama.com/auth/abc"] and u["user_name"] == "qr" and offline.token == "QRTOKEN"
    assert state["polls"] == 3
    assert sum(1 for c in fake.calls if c["action"] == "qrlogin_login") == 3  # never retried internally


@pytest.mark.parametrize("msg", ["Code Expired", "Wrong Code"])
def test_qr_expired(offline, fake, msg):
    fake.handler = lambda a, d, h: FakeResponse(200, fail(msg))
    with pytest.raises(QRCodeExpired):
        offline.qr_check("zzz")


def test_otp_verify_logs_in(offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(200, ok({"token": "OTP"} if a == "otp_verify" else {"user_id": 3}))
    offline.otp_verify("a@b.c", "123456")
    assert fake.last("otp_verify")["data"] == {"user_login": "a@b.c", "user_code": "123456"}
    assert offline.token == "OTP"


def test_dismiss_failure_raises(offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(200, fail("DISMISS_FAILED"))
    with pytest.raises(ApiError) as ei:
        offline.continue_watching_dismiss(5)
    assert ei.value.msg == "DISMISS_FAILED"


def test_logout_clears_session(offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(200, ok(None, "You have been logged out successfully"))
    offline.store.save({"token": "TOKEN123"})
    offline.logout()
    assert offline.token is None and offline.store.load() == {}
    assert sum(1 for c in fake.calls if c["action"] == "logout") == 1


def test_private_methods_need_token(offline, fake):
    offline.transport.token = None
    for name, args in [("user", ()), ("stream", (1,)), ("download", (1,)), ("continue_watching", ()),
                       ("my_lists", ()), ("user_list", ()), ("notifications", ()), ("observer", (1, 2, 3, 4))]:
        with pytest.raises(LoginRequired):
            getattr(offline, name)(*args)
    assert fake.calls == []  # rejected locally, no request sent


# ------------------------------------------------------------------ envelope & errors
@pytest.mark.parametrize("env,exc", [
    (fail("Login Required"), LoginRequired),
    (fail("Access Denied"), LoginRequired),
    (fail("invalid-input-response", 403, ["retry"]), CaptchaRequired),
    (fail("Post not found"), NotFound),
    (fail("NO_SLUG_FOUND"), NotFound),
    (fail("Something else"), ApiError),
])
def test_error_mapping(offline, fake, env, exc):
    fake.handler = lambda a, d, h: FakeResponse(200, env)
    with pytest.raises(exc) as ei:
        offline.get("anything")
    assert ei.value.envelope["msg"] == env["msg"] and ei.value.action == "anything"


def test_unknown_action_404_results_key(offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(404, {"status": 404, "success": False, "error": True,
                                                     "msg": "404 Not Found", "results": None})
    env = offline.call("nope")
    assert env["result"] is None and "results" not in env
    with pytest.raises(NotFound):
        offline.get("nope")


def test_bare_json_is_wrapped(offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(200, {"captcha": True})
    assert offline.captcha_required() is True


def test_subtitle_raw_text(offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(200, "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nhi\n")
    assert offline.subtitle("Zm9v").startswith("WEBVTT")
    assert fake.last()["action"] == "subtitle/file/Zm9v"


def test_retry_on_429_then_success(offline, fake):
    seq = [FakeResponse(429, "error code: 1015", {"Retry-After": "0"}), FakeResponse(502, "<html>bad</html>"),
           FakeResponse(200, ok({"posts": []}))]
    fake.handler = lambda a, d, h: seq.pop(0)
    assert offline.home_stream() == {"posts": []}
    assert len(fake.calls) == 3


def test_retry_gives_up(offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(429, "error code: 1015")
    with pytest.raises(RateLimited):
        offline.menu()
    assert len(fake.calls) == 3  # 1 + len(backoff)


def test_no_retry_actions(offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(502, "<html>bad</html>")
    for action in ("observer", "logout", "qrlogin_login"):
        fake.calls.clear()
        with pytest.raises(TransportError):
            offline.call(action)
        assert len(fake.calls) == 1


def test_guard_and_challenge_not_retried(offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(200, "APIMAINTENANCE")
    with pytest.raises(Blocked):
        offline.menu()
    assert len(fake.calls) == 1
    fake.calls.clear()
    fake.handler = lambda a, d, h: FakeResponse(403, "<html><title>Just a moment</title>challenge-platform</html>")
    with pytest.raises(Blocked):
        offline.menu()
    assert len(fake.calls) == 1


def test_network_error_is_transport_error(offline, fake):
    import requests

    def boom(a, d, h):
        raise requests.ConnectionError("down")
    fake.handler = boom
    with pytest.raises(TransportError):
        offline.menu()
    assert len(fake.calls) == 3


def test_discovery_and_init(fake):
    from sinama import Transport
    fake.handler = lambda a, d, h: FakeResponse(200, ok({"platform": "WebTV"}))
    t = Transport(session=fake)
    r = t.init()
    assert r["host"] in ("https://fake.test/api/v2", "https://world.hana-api.com/api/v2", "https://ir.kazem-api.com/api/v2")
    assert t.host == r["host"]


def test_init_falls_back_to_second_key(fake):
    from sinama import Transport, config as C
    fake.handler = lambda a, d, h: FakeResponse(200, ok({}) if h["c-api-key"] == C.API_KEYS[1] else fail("bad key"))
    t = Transport(session=fake)
    assert t.init()["key"] == C.API_KEYS[1]


# ------------------------------------------------------------------ scheduler
def test_scheduler_limits_concurrency():
    s = Scheduler(max_in_flight=2, min_gap=0)
    live, peak, lock = [0], [0], threading.Lock()

    def job():
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.05)
        with lock:
            live[0] -= 1

    threads = [threading.Thread(target=s.run, args=(job,)) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert peak[0] == 2


def test_scheduler_spacing_and_pause():
    s = Scheduler(max_in_flight=2, min_gap=0.05)
    t0 = time.perf_counter()
    for _ in range(4):
        s.run(lambda: None)
    assert time.perf_counter() - t0 >= 0.14
    s.pause(0.2)
    t0 = time.perf_counter()
    s.run(lambda: None)
    assert time.perf_counter() - t0 >= 0.18


# ------------------------------------------------------------------ library
def test_library_add_remove_idempotent(offline, fake):
    state = {"watchlist": [1, 2]}

    def handler(a, d, h):
        if a == "user_mylist":
            return FakeResponse(200, ok({g: {"post": ids} for g, ids in state.items()}))
        if a == "user_list" and d["action"] == "add":
            ids = state.setdefault(d["group"], [])
            pid = int(d["post_id"])
            ids.remove(pid) if pid in ids else ids.append(pid)
            return FakeResponse(200, ok(None))
    fake.handler = handler
    lib = offline.library
    assert lib.has("watchlist", 1) and not lib.has("favorite", 1)
    assert lib.add("watchlist", 1) is False  # already there: no call
    assert lib.add("favorite", 5) is True and state["favorite"] == [5]
    assert lib.remove("favorite", 5) is True and state["favorite"] == []
    assert lib.remove("favorite", 5) is False
    assert lib.toggle("watchlist", 3) is True and lib.ids("watchlist") == ["1", "2", "3"]
    assert sum(1 for c in fake.calls if c["action"] == "user_list") == 3


# ------------------------------------------------------------------ screens
def test_screens_home_and_details(offline, fake):
    post = {"id": 1, "posts": [], "options": {"is_series": True, "stream": True}}
    stream = {"hls": [
        {"info": {"file_id": 11, "season": 1, "episode_number": 2}, "file": {"m3u8": [{"label": "720p", "default": "u2"}]}, "options": {}},
        {"info": {"file_id": 10, "season": 1, "episode_number": 1}, "file": {"m3u8": [{"label": "720p", "default": "u1"}]}, "options": {}},
    ], "continue_watching": {"file_id": 11, "time": 50}}
    dl = {"links": ["https://dl.test/Show.S01E02.1080p.WEB-DL.DDP5.1.x265.mkv"]}
    res = {"home_stream": ok({"hero_header": {"posts": [{"id": 1}]}, "movies": {"posts": [{"id": 2}]}}),
           "continue_watching": ok({"posts": [{"id": 3}]}), "single": ok(post), "stream": ok(stream), "download": ok(dl)}
    fake.handler = lambda a, d, h: FakeResponse(200, res[a])
    h = screens.home(offline)
    assert h["hero"] == [{"id": 1}] and h["continue_watching"] == [{"id": 3}] and h["rows"][0]["key"] == "movies"
    d = screens.details(offline, 1, with_downloads=True)
    assert [i["info"]["file_id"] for i in d["items"]] == [10, 11]
    assert d["resume"] == (1, 50.0)
    assert len(d["items"][1]["file"]["m3u8"]) == 2 and d["items"][1]["file"]["m3u8"][1]["direct"]
    assert len(d["items"][0]["file"]["m3u8"]) == 1


# ------------------------------------------------------------------ direct
def test_direct_parse_and_label():
    p = direct.parse("https://x/Dune.Part.Two.2024.2160p.UHD.BluRay.REMUX.HDR10Plus.DV.TrueHD.Atmos.HEVC.mkv?t=1")
    assert p["height"] == 2160 and p["hdr10plus"] and p["dolby_vision"] and p["codec"] == "HEVC"
    assert p["source"] == "Remux" and p["ext"] == "mkv" and p["audio"] == "bad"
    assert direct.label(p, "60.1 GB") == "2160p HDR10+ DV · HEVC · Remux · MKV · 60.1 GB"
    e = direct.parse("https://x/The.Show.S02E05.720p.WEB-DL.AAC.x264.mp4")
    assert (e["season"], e["episode"], e["height"], e["audio"], e["codec"]) == (2, 5, 720, "ok", "H.264")


def test_direct_extract_walks_nested_json():
    res = {"seasons": [{"q": {"1080p": {"link": "https://a/x.S01E01.mkv", "size": 2147483648}}},
                       {"files": ["https://a/x.S01E02.720p.mp4", "https://a/readme.txt", "not a url.mkv"]}]}
    out = direct.extract(res)
    assert [x["url"] for x in out] == ["https://a/x.S01E01.mkv", "https://a/x.S01E02.720p.mp4"]
    assert out[0]["size"] == "2.0 GB" and out[0]["meta"]["height"] == 1080  # height from the "1080p" key


def test_direct_extract_series_shape_uses_structured_fields():
    # Real `download` shape for a series; file names deliberately carry no SxxEyy or resolution.
    res = {"seasons": [1, 2], "total_seasons": 2, "download": {
        "s2": [{"id": 1, "season": 2, "season_int": 2, "quality": "x265 WEB-DL 2160p", "size": "5 GB",
                "link": [{"id": 11, "dl": "https://dl.test/show-a.mkv", "episode": 3},
                         {"id": 12, "dl": "https://dl.test/show-b.mkv", "episode": "4"}]}]}}
    out = direct.extract(res)
    assert [(x["meta"]["season"], x["meta"]["episode"], x["meta"]["height"]) for x in out] == [(2, 3, 2160), (2, 4, 2160)]
    assert out[0]["meta"]["codec"] == "HEVC" and out[0]["label"].startswith("2160p · HEVC · WEB-DL")
    items = [{"info": {"season": 2, "episode_number": 4}, "file": {"m3u8": []}}]
    assert direct.attach(items, out, True) == 1 and items[0]["file"]["m3u8"][0]["default"] == "https://dl.test/show-b.mkv"


def test_direct_extract_movie_shape():
    res = {"download": [{"id": 1, "quality": "x265 BrRip 1080p", "size": "3.52 GB", "resolution": "1920x804",
                         "tags": ["x265", "10bit"], "source": "Film.2018.BluRay.1080p.DTS-HD.MA.5.1.REMUX",
                         "dl": "https://dl.test/Film_2018_10bit_1080p_x265_BrRip_30nama.mkv"}]}
    (x,) = direct.extract(res)
    assert x["label"] == "1080p 10bit · HEVC · BluRay · MKV · 3.52 GB"
    assert x["meta"]["audio"] != "bad"  # the `source` release name (DTS) describes the original, not this file


def test_direct_candidates_order():
    entries = [{"direct": True, "default": "a", "height": 1080, "audio": "unknown"},
               {"direct": True, "default": "b", "height": 1080, "audio": "ok"},
               {"direct": True, "default": "c", "height": 2160, "audio": "bad"},
               {"label": "HLS", "default": "d"}]
    assert [e["default"] for e in direct.candidates(entries)] == ["b", "a"]
    assert [e["default"] for e in direct.candidates(entries, failed={"b"})] == ["a"]


# ------------------------------------------------------------------ player / helpers
ITEM = {"info": {"file_id": 5, "season": 1, "episode_number": 1},
        "file": {"m3u8": [{"label": "480p", "default": "u480"}, {"label": "1080p", "default": "u1080", "2ch": "s", "6ch": "m"},
                          {"label": "720p", "default": "u720"}], "subtitle": {"fa": "https://s/fa", "en": {"url": "https://s/en"}}},
        "options": {"intro_start": "00:00:10", "intro_end": "00:01:30", "token": "obs"}}


def test_player_helpers():
    assert player.pick_url(ITEM) == "u1080"
    assert player.pick_url(ITEM, max_height=720) == "u720"
    assert player.pick_url(ITEM, audio="6ch") == "m"
    assert player.markers(ITEM)["intro_end"] == 90
    assert player.subtitle_urls(ITEM) == {"fa": "https://s/fa", "en": "https://s/en"}
    assert player.observer_params(9, ITEM, 42, 12.9, 100) == {"post_id": 9, "file_id": 5, "user_id": 42, "time": 12,
                                                              "duration": 100, "token": "obs"}
    assert player.resume_point({"hls": [ITEM], "continue_watching": {"file_id": 5, "time": 33}}) == (0, 33.0)
    assert player.seasons({"hls": [ITEM]}) == {1: [ITEM]}


def test_subtitles():
    srt = "1\r\n00:00:01,500 --> 00:00:03,000\r\n<i>Hello</i>\r\n\r\n2\r\n00:01:00,000 --> 00:01:02,250\r\nWorld\r\n"
    vtt = player.srt_to_vtt(srt)
    assert vtt.startswith("WEBVTT") and "00:00:01.500" in vtt
    assert player.parse_cues(srt) == [{"start": 1.5, "end": 3.0, "text": "Hello"}, {"start": 60.0, "end": 62.25, "text": "World"}]


def test_progress_reporter(offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(204, "")
    pos = [0, 100]
    r = player.ProgressReporter(offline, 9, ITEM, lambda: tuple(pos), interval=0.05).start()
    time.sleep(0.03)
    pos[0] = 30
    time.sleep(0.15)
    r.stop(final=True)
    sent = [c for c in fake.calls if c["action"] == "observer"]
    assert r.reports >= 2 and sent[-1]["data"]["time"] == 30 and sent[-1]["data"]["token"] == "obs"


def test_post_helpers():
    p = {"title": {"english": "Dune", "local": "تل‌ماسه"}, "plot": {"english": "Sand"},
         "image": {"poster": {"webp": {"medium": "w"}, "jpg": {"medium": "j"}}, "cover": {"webp": "cw"}},
         "options": {"is_series": False, "stream": True}, "score": {"imdb": {"link": "https://www.imdb.com/title/tt1160419"}}}
    assert helpers.title(p) == "Dune" and helpers.title(p, "fa") == "تل‌ماسه" and helpers.plot(p, "fa") == "Sand"
    assert helpers.poster(p) == "j" and helpers.poster(p, fmt="webp") == "w" and helpers.cover(p) == "cw"
    assert helpers.imdb_id(p) == "tt1160419" and helpers.is_streamable(p) and not helpers.is_series(p)
    assert helpers.hms("01:00:30") == 3630 and helpers.hms(None) is None and helpers.hms("x") is None
    assert helpers.posts({"posts": [1]}) == [1] and helpers.posts(None) == []


def test_session_store(tmp_path):
    s = SessionStore(str(tmp_path / "d" / "s.json"))
    assert s.load() == {}
    s.save({"token": "t"})
    assert s.update(user={"id": 1})["user"] == {"id": 1} and s.load()["token"] == "t"
    s.clear()
    assert s.load() == {}
    m = MemoryStore({"token": "x"})
    assert m.load() == {"token": "x"}
