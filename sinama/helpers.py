"""Read helpers over the shared `post` object (home rows, search, archive, lists, single).

Mirrors the N.img / N.cover / N.title / N.plot helpers at the end of api.js.
"""


def title(post, lang="en"):
    t = (post or {}).get("title") or {}
    if lang == "fa" and t.get("local"):
        return t["local"]
    return t.get("english") or t.get("local") or ""


def plot(post, lang="en"):
    t = (post or {}).get("plot") or {}
    if lang == "fa" and t.get("local"):
        return t["local"]
    return t.get("english") or t.get("local") or ""


def poster(post, size="medium", fmt="jpg"):
    """Poster URL. size: small | medium | large | big. fmt: jpg | webp."""
    po = ((post or {}).get("image") or {}).get("poster") or {}
    other = "webp" if fmt == "jpg" else "jpg"
    for f in (fmt, other):
        sizes = po.get(f) or {}
        url = sizes.get(size) or sizes.get("large") or sizes.get("medium")
        if url:
            return url
    return ""


def cover(post, fmt="jpg"):
    c = ((post or {}).get("image") or {}).get("cover") or {}
    return c.get(fmt) or c.get("webp" if fmt == "jpg" else "jpg") or ""


def is_series(post):
    return bool(((post or {}).get("options") or {}).get("is_series"))


def is_streamable(post):
    return bool(((post or {}).get("options") or {}).get("stream"))


def imdb_id(post):
    link = (((post or {}).get("score") or {}).get("imdb") or {}).get("link") or ""
    return link.rstrip("/").rsplit("/", 1)[-1] if "/tt" in link else ""


def hms(value):
    """"00:01:30" -> 90. Numbers pass through; None/garbage -> None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    total = 0.0
    try:
        for part in str(value).split(":"):
            total = total * 60 + float(part)
    except ValueError:
        return None
    return total


def posts(page):
    """The `posts` list of any paged result (search, archive, user_list, continue_watching)."""
    if isinstance(page, list):
        return page
    if isinstance(page, dict):
        for k in ("posts", "items", "list"):
            if isinstance(page.get(k), list):
                return page[k]
    return []
