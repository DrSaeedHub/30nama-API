"""Offline tests for the website API client (sinama.web) and the v2 actions found in the
official SDK bundled on 30nama.com."""
import pytest

from conftest import FakeResponse, fail, ok
from sinama import ApiError, CaptchaRequired, LoginRequired, NotFound, QRCodeExpired, RateLimited, config as C
from sinama.web import _fix_links

WEB = [
    # (method, args, kwargs, path, form)
    ("home", (), {}, "main/", {}),
    ("home_v2", (), {}, "mainV2/", {}),
    ("stream_home", (), {}, "main/streamonly/yes", {}),
    ("menu", (), {}, "menu", {}),
    ("genres", (), {}, "genres/", {}),
    ("search", ("dune",), {}, "search/page/1/order/desc/orderby/relevant/", {"query": "dune"}),
    ("autocomplete", ("dune",), {}, "search/page/1/order/desc/orderby/imdb/", {"query": "dune"}),
    ("full_search", ("nolan",), {"type": "person", "page": 2}, "full_search/type/person/orderby/relevant/order/desc/page/2",
     {"query": "nolan"}),
    ("archive", ("series",), {"page": 3, "orderby": "update", "stream_only": True},
     "pagination/type/series/page/3/order/desc/orderby/update/streamonly/yes", {}),
    ("list", (), {"type": "genre", "value": "drama"}, "list/type/genre/value/drama/page/1/orderby/date/order/desc/streamonly/no/", {}),
    ("advanced_search_parameters", (), {}, "advanced_search_parametres", {}),
    ("comments", (8863,), {"page": 2, "type": "review", "orderby": "like"}, "comment/id/8863/page/2/type/review/orderby/like", {}),
    ("articles", (), {"type": "announcement"}, "article/type/announcement/page/1", {}),
    ("collections", (), {"page": 2}, "collection/page/2", {}),
    ("collections", (), {"query": "marvel"}, "collection/page/1", {"query": "marvel"}),
    ("collection", (55,), {}, "collection/id/55", {}),
    ("toplist", ("top-series-imdb",), {}, "toplist/list/top-series-imdb", {}),
    ("boxoffice", (), {}, "boxoffice/iran/no", {}),
    ("boxoffice", (), {"iran": True}, "boxoffice/iran/yes", {}),
    ("schedule", ("anime",), {}, "schedule/type/anime", {}),
    ("people", (), {"gender": "female", "profession": "director", "page": 2}, "person/gender/female/profession/director/page/2", {}),
    ("url_to_post", ("https://30nama.com/x",), {}, "url", {"url": "https://30nama.com/x"}),
    ("tos", (), {}, "tos", {}),
    ("dmca", (), {}, "dmca", {}),
    ("event", (), {}, "event", {}),
    ("profile", ("someone",), {}, "profile/user/someone", {}),
    ("profile_list", ("someone",), {"group": "favorite"}, "profile/user/someone/list/favorite/page/1/orderby/date/order/desc/type/all", {}),
    ("user", (), {}, "user", {}),
    ("stream", (8863,), {}, "stream/id/8863", {"freeStream": 0}),
    ("download", (8863,), {}, "download/id/8863", {"freeDownload": 0}),
    ("watched", (), {}, "stream_watched/sortBy/1/sortBy/", {}),
    ("dismiss_watched", (8863,), {}, "stream_watched_dismiss/id/8863", {}),
    ("my_lists", (), {}, "user_mylist", {}),
    ("my_list", ("favorite", 2), {}, "mylist/group/favorite/page/2", {}),
    ("list_toggle", ("watchlist", 8863), {}, "add_to_mylist/id/8863/group/watchlist", {}),
    ("send_comment", (8863, "nice"), {}, "sendcomment/post_id/8863", {"text": "nice"}),
    ("send_comment", (8863, "agreed"), {"reply_to": 5}, "sendcomment/post_id/8863/comment_id/5", {"text": "agreed"}),
    ("rate_comment", (5, 8863, 1), {}, "rate_comment/id/5/post_id/8863/rate/1", {}),
    ("rate_post", (8863, 9), {}, "rate_post/id/8863/rate/9", {}),
    ("request_parameters", (), {}, "request_parameters", {}),
    ("requests", (), {}, "requests/page/1", {}),
    ("submit_request", ("movie", "new", "Dune 3"), {}, "request", {"type": "movie", "subtype": "new", "title": "Dune 3", "note": ""}),
    ("notifications", (), {"status": "unread"}, "notification/status/unread/page/1", {}),
    ("read_notification", (12,), {}, "readnotification/id/12", {}),
    ("plans", (), {}, "plans", {}),
    ("plans", (), {"discount_code": "OFF10"}, "plans/discountcode/OFF10", {}),
    ("plans_features", (), {}, "plans_features", {}),
    ("check_discount", ("OFF10", 45), {}, "discount/discountcode/OFF10/planid/45", {}),
    ("transactions", (), {}, "transactions", {}),
    ("transaction_status", ("abc",), {}, "txn/txnid/abc", {}),
    ("check_upgrade", (), {}, "check_upgrade", {}),
    ("upgrade_red_to_golden_check", (), {}, "upgrade_red_to_golden_check", {}),
    ("use_voucher", ("V-1",), {}, "voucher/vouchercode/V-1", {}),
    ("create_transaction_shaparak", (45,), {}, "shaparak/planid/45/discountcode/", {}),
    ("create_transaction_crypto", (45, "usdt"), {}, "cryptocurrency/planid/45/currency/usdt/discountcode/", {}),
    ("create_transaction_perfectmoney", (45,), {}, "perfectmoney/planid/45/discountcode/", {}),
    ("is_new_user", (), {}, "is_new_user", {}),
    ("popup_users", (), {}, "popup_users", {}),
    ("update_user", (), {"first_name": "A"}, "update_user", {"first_name": "A"}),
    ("update_password", ("old", "new"), {}, "update_user_password",
     {"current_password": "old", "new_password": "new", "confirm_new_password": "new"}),
    ("send_otp", ("a@b.c",), {"recaptcha_response": "R"}, "send_otp", {"userlogin": "a@b.c", "g-recaptcha-response": "R"}),
    ("register", ("a@b.c",), {"recaptcha_response": "R"}, "registerV2/", {"userlogin": "a@b.c", "g-recaptcha-response": "R"}),
    ("verify_registration", ("a@b.c", "123"), {}, "verifyV2", {"userlogin": "a@b.c", "code": "123"}),
    ("reset_password", ("a@b.c",), {}, "resetpasswordV2", {"userlogin": "a@b.c"}),
    ("verify_reset_password", ("a@b.c", "1"), {}, "verifyresetpasswordV2", {"userlogin": "a@b.c", "code": "1"}),
]


@pytest.mark.parametrize("method,args,kwargs,path,form", WEB, ids=["%s-%d" % (e[0], i) for i, e in enumerate(WEB)])
def test_web_request(web_offline, fake, method, args, kwargs, path, form):
    fake.handler = lambda a, d, h: FakeResponse(200, {"success": True, "msg": None, "result": {"id": 1, "posts": []}})
    getattr(web_offline, method)(*args, **kwargs)
    call = fake.last(path)
    assert call["url"] == C.WEB_HOST + "/action/" + path
    assert call["data"] == form
    h = call["headers"]
    assert h["c-api-key"] == C.WEB_API_KEY and h["c-platform"] == "Website" and h["c-app-version"] == "2.0.0"
    assert h["c-token"] == "WEBTOKEN" and h["c-useragent"]


def test_web_single_and_person(web_offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(200, {"success": True, "result": {"id": 151410, "name": "Leonardo"}})
    assert web_offline.person(151410, page=2)["name"] == "Leonardo"
    assert fake.last()["action"] == "single/id/151410/page/2"
    fake.handler = lambda a, d, h: FakeResponse(200, {"success": True, "result": []})
    with pytest.raises(NotFound):
        web_offline.single(999999999)


def test_web_no_token_header_when_logged_out(web_offline, fake):
    web_offline.transport.token = None
    fake.handler = lambda a, d, h: FakeResponse(200, {"success": True, "result": {}})
    web_offline.menu()
    assert "c-token" not in fake.last()["headers"]
    with pytest.raises(LoginRequired):
        web_offline.user()  # refused locally


def test_web_persian_errors(web_offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(200, {"success": False, "msg": "ابتدا وارد حساب خود شوید", "result": None})
    with pytest.raises(LoginRequired):
        web_offline.get("request_parameters")
    fake.handler = lambda a, d, h: FakeResponse(200, {"success": False, "msg": "چنین پستی وجود ندارد", "result": []})
    with pytest.raises(NotFound):
        web_offline.url_to_post("https://30nama.com/nope")
    fake.handler = lambda a, d, h: FakeResponse(200, {"success": False, "msg": "پارامتر های کپچا نامعتبر است", "result": None})
    with pytest.raises(CaptchaRequired):
        web_offline.login("a@b.c", "pw")
    fake.handler = lambda a, d, h: FakeResponse(200, {"success": False, "msg": "کد فعالسازی اشتباه است", "result": None})
    with pytest.raises(QRCodeExpired):
        web_offline.qr_check("bad")


def test_web_unknown_action_plain_404(web_offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(404, "404 Not Found")
    with pytest.raises(NotFound):
        web_offline.get("no_such_action")
    assert len(fake.calls) == 1


def test_web_link_placeholders():
    assert _fix_links({"a": ["link://cdn.x/p.jpg", {"b": "linkDownload://dl.x/f.mkv"}], "c": "linkStream://s.x/m.m3u8",
                       "d": "https://ok", "n": 5}) == \
        {"a": ["https://cdn.x/p.jpg", {"b": "https://dl.x/f.mkv"}], "c": "https://s.x/m.m3u8", "d": "https://ok", "n": 5}


def test_web_test_plain_text(web_offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(200, "OK")
    assert web_offline.test() is True


def test_web_qr_login_approved_by_v2(web_offline, offline, fake):
    state = {"approved": False}

    def handler(a, d, h):
        if a == "qrcode/":
            return FakeResponse(200, {"success": True, "result": {"code": "c0de", "url": "https://30nama.com/auth/c0de"}})
        if a == "qrlogin_auth":  # v2 approval from the logged-in Client
            assert d == {"auth_code": "c0de"} and h["c-token"] == "TOKEN123"
            state["approved"] = True
            return FakeResponse(200, ok(None, "Authentication success."))
        if a == "qrlogin/code/c0de":
            if not state["approved"]:
                return FakeResponse(200, {"success": False, "msg": None, "result": None})
            return FakeResponse(200, {"success": True, "msg": "ok", "result": {"usertoken": "V1TOKEN", "username": "u"}})
    fake.handler = handler
    web_offline.transport.token = None
    u = web_offline.qr_login(approve_with=offline, poll=0, timeout=5)
    assert u["username"] == "u" and web_offline.token == "V1TOKEN"
    assert web_offline.store.load()["token"] == "V1TOKEN"


def test_web_qr_pending_and_web_approve(web_offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(200, {"success": False, "msg": None, "result": None})
    assert web_offline.qr_check("abc") is None
    fake.handler = lambda a, d, h: FakeResponse(200, {"success": True, "msg": "ok", "result": None})
    web_offline.qr_approve("abc")
    assert fake.last()["action"] == "auth/code/abc"


def test_web_observer_url(web_offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(200, "")
    r = web_offline.observer(8863, 99, 61.5, 8880, key="K")
    call = fake.last()
    assert call["url"] == "https://interface.30nama.com/observer/observer"
    assert call["data"] == {"fid": 99, "pid": 8863, "t": 61, "d": 8880, "k": "K", "uid": 7}
    assert call["headers"]["c-output-requests"] == "true" and r["http_status"] == 200


def test_web_writes_not_retried(web_offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(502, "<html>bad</html>")
    for fn in (lambda: web_offline.send_comment(1, "x"), lambda: web_offline.rate_post(1, 5),
               lambda: web_offline.list_toggle("watchlist", 1)):
        fake.calls.clear()
        with pytest.raises(Exception):
            fn()
        assert len(fake.calls) == 1


# ------------------------------------------------------------------ v2 additions
V2 = [
    ("offer", (), {}, "offer", {}),
    ("checks", (), {"key": "k"}, "checks", {"key": "k"}),
    ("endpoints", (), {}, "endpoint", {}),
    ("plans", (), {"gateway": "paypal", "discount_code": "OFF"}, "plans", {"gateway": "paypal", "discount_code": "OFF"}),
    ("voucher", ("V-1",), {}, "voucher", {"voucher_code": "V-1"}),
    ("qr_approve", ("c0de",), {}, "qrlogin_auth", {"auth_code": "c0de"}),
    ("payment_shaparak", (45,), {}, "shaparak", {"plan_id": 45}),
    ("payment_paypal", (23,), {"discount_code": "OFF"}, "paypal", {"plan_id": 23, "discount_code": "OFF"}),
]


@pytest.mark.parametrize("method,args,kwargs,action,form", V2, ids=[e[0] for e in V2])
def test_v2_new_actions(offline, fake, method, args, kwargs, action, form):
    fake.handler = lambda a, d, h: FakeResponse(200, ok(None))
    getattr(offline, method)(*args, **kwargs)
    assert fake.last(action)["data"] == form


def test_v2_endpoint_bare_list(offline, fake):
    hosts = [{"location": "WORLD", "host": "https://world.hana-api.com/api/v2"}]
    fake.handler = lambda a, d, h: FakeResponse(200, hosts)
    assert offline.endpoints() == hosts


def test_v2_qr_approve_and_voucher_errors(offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(200, fail("Wrong Code"))
    with pytest.raises(QRCodeExpired):
        offline.qr_approve("bad")
    fake.handler = lambda a, d, h: FakeResponse(200, fail("INVALID_VOUCHER_CODE"))
    with pytest.raises(ApiError) as ei:
        offline.voucher("bad")
    assert ei.value.msg == "INVALID_VOUCHER_CODE"
    assert sum(1 for c in fake.calls if c["action"] == "voucher") == 1


def test_long_rate_limit_fails_fast(offline, fake):
    fake.handler = lambda a, d, h: FakeResponse(429, "<html>Access denied</html>", {"Retry-After": "257"})
    with pytest.raises(RateLimited) as ei:
        offline.menu()
    assert ei.value.retry_after == 257 and not ei.value.retry
    assert len(fake.calls) == 1  # not retried: the block outlasts MAX_RETRY_AFTER
