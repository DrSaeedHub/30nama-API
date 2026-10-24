"""Live tests for the endpoints that need a logged-in session.

Needs a token: `python -m sinama qr-login` once (saved to ~/.sinama/session.json),
or SINAMA_TOKEN=... in the environment. Skipped otherwise.

Nothing visible changes on the account: list toggles are reverted, the progress
report re-sends an existing resume point unchanged, and dismiss targets a title that
is not in continue watching. Logout is NOT called (it would
end the session you are testing with) unless SINAMA_TEST_LOGOUT=1.
"""
import os

import pytest
import requests

from sinama import ApiError, LoginRequired, direct, player, screens

pytestmark = [pytest.mark.live, pytest.mark.auth]



def test_user(auth):
    u = auth.user()
    assert u.get("user_id") and u.get("user_name")
    assert "user_allowed_to_stream" in u


@pytest.fixture(scope="module")
def streamable(auth, sample):
    """A movie and a series the account can stream, with their stream results."""
    out = {}
    for kind in ("movie", "series"):
        try:
            out[kind] = (sample[kind], auth.stream(sample[kind]))
        except ApiError as e:
            pytest.skip("stream refused (%s): the account needs a streaming plan" % e)
    return out


def test_stream_movie(streamable):
    pid, st = streamable["movie"]
    items = player.items(st)
    assert len(items) == 1
    it = items[0]
    assert it["info"]["file_id"] and it["options"].get("token") is not None
    url = player.pick_url(it)
    assert url and url.startswith("http")
    r = requests.get(url, timeout=20)
    assert r.status_code == 200 and "#EXTM3U" in r.text  # the HLS playlist really plays


def test_stream_series(streamable):
    pid, st = streamable["series"]
    items = player.items(st)
    assert len(items) > 1
    seasons = player.seasons(st)
    assert seasons and all(seasons.values())


def test_subtitle_from_stream(auth, streamable):
    for pid, st in streamable.values():
        for it in player.items(st):
            subs = player.subtitle_urls(it)
            if subs:
                text = auth.subtitle(next(iter(subs.values())))
                assert player.parse_cues(text), "subtitle has no cues"
                return
    pytest.skip("no subtitles on the sampled titles")


def test_download(auth, sample):
    try:
        raw = auth.download(sample["movie"])
    except ApiError as e:
        pytest.skip("download refused (%s): the account needs a download plan" % e)
    assert isinstance(raw["download"], list)
    e = raw["download"][0]
    assert {"quality", "size", "resolution", "encoder", "dl"} <= set(e)
    links = direct.extract(raw)
    assert links and all(x["url"].startswith("http") for x in links)
    assert any(x["meta"]["height"] for x in links)


def test_download_series(auth, sample):
    try:
        raw = auth.download(sample["series"])
    except ApiError as e:
        pytest.skip("download refused (%s)" % e)
    # {"seasons": [1, 2], "total_seasons": 2, "download": {"s1": [{season, quality, link: [{dl, episode}]}]}}
    assert raw["total_seasons"] == len(raw["seasons"]) and set(raw["download"]) == {"s%d" % s for s in raw["seasons"]}
    group = raw["download"]["s%d" % raw["seasons"][0]][0]
    assert {"season", "quality", "link"} <= set(group) and {"dl", "episode"} <= set(group["link"][0])
    links = direct.extract(raw)
    assert links and all(x["meta"]["season"] and x["meta"]["episode"] for x in links)
    items = player.items(auth.stream(sample["series"]))
    assert direct.attach(items, links, True) > 0
    assert any(q["direct"] for q in player.qualities(items[0]))


def _continue_rows(auth):
    return auth.continue_watching().get("posts") or []


def test_continue_watching_shape(auth):
    r = auth.continue_watching()
    assert {"posts", "total"} <= set(r)
    for p in r["posts"]:
        assert {"id", "time", "display_time", "progress"} <= set(p["data"]) and p["data"]["id"] == p["id"]


def test_resume_point_from_stream(auth):
    rows = _continue_rows(auth)
    if not rows:
        pytest.skip("continue watching is empty")
    pid = rows[0]["id"]
    st = auth.stream(pid)
    cw = st["continue_watching"]
    assert {"post_id", "file_id", "time", "display_time", "progress"} <= set(cw)
    idx, at = player.resume_point(st)
    assert str(player.items(st)[idx]["info"]["file_id"]) == str(cw["file_id"]) and at == float(cw["time"])


def test_observer_accepted(auth):
    """Re-report an existing resume point unchanged, so the account's watch state stays the same.

    Only acceptance is asserted. Whether a report changes the stored position is decided
    server-side: live, identical requests were sometimes applied (after 80-120 s) and
    sometimes dropped, so a "position moved" assertion would be flaky (see docs/API.md).
    """
    rows = _continue_rows(auth)
    if not rows:
        pytest.skip("no existing resume point to re-report without changing your watch state")
    pid = rows[0]["id"]
    st = auth.stream(pid)
    cw = st["continue_watching"]
    item = next(i for i in player.items(st) if str(i["info"]["file_id"]) == str(cw["file_id"]))
    env = auth.observer(pid, cw["file_id"], cw["time"], 7200, token=item["options"].get("token", ""))
    assert env["success"] and env["http_status"] == 200 and env["result"] is None  # empty body when logged in
    rep = player.ProgressReporter(auth, pid, item, lambda: (cw["time"], 7200))
    assert rep.report(final=True) and rep.reports == 1, rep.last_error


def test_continue_watching_dismiss(auth, sample):
    """Exercise dismiss only where it has no visible effect: a title not in the list.

    DISMISS_SUCCESS is answered only for a listed title (seen live while cleaning up
    test reports); anything else, resume point or not, answers DISMISS_FAILED.
    """
    listed = {p["id"] for p in _continue_rows(auth)}
    pid = next((sample[k] for k in ("movie", "series") if sample[k] not in listed), None)
    if pid is None:
        pytest.skip("both sample titles are in your continue watching list")
    with pytest.raises(ApiError) as ei:
        auth.continue_watching_dismiss(pid)
    assert ei.value.msg == "DISMISS_FAILED"
    assert {p["id"] for p in _continue_rows(auth)} == listed


def test_my_lists(auth):
    r = auth.my_lists()
    assert {"watchlist", "favorite"} <= set(r)
    assert isinstance(r["watchlist"]["post"], list)


@pytest.mark.parametrize("group", ["watchlist", "favorite"])
def test_user_list_pages(auth, group):
    r = auth.user_list(group)
    assert "posts" in r


@pytest.mark.parametrize("group", ["watchlist", "favorite"])
def test_library_toggle_roundtrip(auth, sample, group):
    lib, pid = auth.library, sample["series"]
    lib.refresh()
    before = lib.has(group, pid)
    try:
        assert lib.toggle(group, pid) is (not before)
        assert lib.refresh() is not None and lib.has(group, pid) is (not before)  # server agrees
    finally:
        if lib.has(group, pid) is not before:
            lib.toggle(group, pid)
    assert lib.refresh() is not None and lib.has(group, pid) is before


def test_notifications(auth):
    r = auth.notifications()
    assert isinstance(r, dict)
    items = r.get("notifications") or r.get("posts") or []
    read = [n for n in items if n.get("read")]
    if read:  # marking an already-read one changes nothing
        assert auth.notification_read(read[0]["id"])["success"]


def test_screens_logged_in(auth, sample):
    h = screens.home(auth)
    assert isinstance(h["continue_watching"], list)
    d = screens.details(auth, sample["series"], with_downloads=True)
    assert d["post"]["id"] == sample["series"]


@pytest.mark.skipif(os.environ.get("SINAMA_TEST_LOGOUT") != "1", reason="ends the session; set SINAMA_TEST_LOGOUT=1")
def test_logout(auth):
    token = auth.token
    auth.logout()
    assert auth.token is None
    auth.transport.token = token
    with pytest.raises(LoginRequired):
        auth.get("user")
