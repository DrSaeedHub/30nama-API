"""Screen-level operations composed from several actions, as the TV app's screens do them.

Port of the data flow in tizen-app/js/screens.js (Home, Details, Search, Archive, My list).
"""
from . import direct, player
from .errors import ApiError
from .helpers import posts

HOME_ROWS = ("new_releases", "suggested", "top_10", "movies", "series", "anime")


def home(client, full=False):
    """Home rows plus continue watching (when logged in).

    Returns {"hero": [posts], "rows": [{"key", "posts"}], "continue_watching": [posts]}.
    full=True uses `home` (adds new_releases/top_10) instead of `home_stream`.
    """
    h = client.home() if full else client.home_stream()
    cw = []
    if client.is_logged_in:
        try:
            cw = posts(client.continue_watching())
        except ApiError:
            cw = []
    rows = []
    for k in HOME_ROWS:
        ps = posts(h.get(k))
        if ps:
            rows.append({"key": k, "posts": ps[:10] if k == "top_10" else ps})
    return {"hero": posts(h.get("hero_header"))[:8], "rows": rows, "continue_watching": cw, "raw": h}


def details(client, post_id, with_stream=True, with_downloads=False):
    """Title + its playable items (+ direct downloads attached as extra qualities).

    Returns {"post", "stream", "items", "resume": (index, seconds), "downloads"}.
    Stream/download failures (no subscription, not logged in) leave those fields empty.
    """
    post = client.single(post_id)
    opts = post.get("options") or {}
    free_stream = bool(opts.get("free_stream"))
    stream, links = None, []
    if with_stream and (client.is_logged_in or free_stream):
        try:
            stream = client.stream(post["id"], free=not client.is_logged_in)
        except ApiError:
            stream = None
    if with_downloads and (client.is_logged_in or opts.get("free_download")):
        try:
            links = client.download_links(post["id"], free=not client.is_logged_in)
        except ApiError:
            links = []
    items = player.items(stream)
    if items and links:
        direct.attach(items, links, bool(opts.get("is_series")))
    return {"post": post, "stream": stream, "items": items,
            "resume": player.resume_point(stream) if stream else (0, 0.0), "downloads": links}


def search(client, query, page=1, stream_only=False):
    """Search; an empty query falls back to the 'popular now' row like the TV app."""
    q = (query or "").strip()
    if not q:
        h = client.home_stream()
        return {"posts": (posts(h.get("suggested")) or posts(h.get("movies")))[:15], "popular": True}
    return client.search(q, page=page, stream_only=stream_only)


def browse(client):
    """Archive landing: {"categories": [...], "genres": [...]} from `menu`."""
    m = client.menu()
    return {"categories": m.get("categories") or [], "genres": m.get("genres") or []}


def archive_list(client, slug, page=1, sort="date"):
    """A category/genre grid page; sort is date | favorite | update (the TV app's tabs)."""
    return client.archive(slug, page=page, orderby=sort, order="desc", stream_only=True)


def mylist(client, group="watchlist", page=1):
    return client.library.list(group, page)
