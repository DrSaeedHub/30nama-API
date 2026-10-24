"""Direct download files (.mkv/.mp4) from the `download` action.

Port of tizen-app/js/direct.js. The `download` result shape is not stable, so
links are found by walking the whole JSON and collecting strings that end in a
video extension; metadata (resolution, HDR, codec, source, audio, SxxEyy) is
parsed from the file name.
"""
import re
from urllib.parse import unquote

EXT = re.compile(r"\.(mkv|mp4|m4v)$", re.I)
SIZE_KEYS = ("size", "file_size", "filesize", "bytes", "volume")


def fmt_size(v):
    if isinstance(v, str) and not re.match(r"^\d+(\.\d+)?$", v):
        return v.strip() if re.search(r"\d", v) else ""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ""
    if v >= 1073741824:
        return "%.1f GB" % (v / 1073741824)
    if v >= 1048576:
        return "%d MB" % round(v / 1048576)
    return ""


def audio_of(name):
    """'ok' | 'bad' | 'unknown'. TVs can't decode DTS / TrueHD; AAC, AC3, EAC3, Opus, FLAC are fine."""
    a = " " + re.sub(r"[._\-()\[\]\s]+", " ", re.sub(r"\.(mkv|mp4|m4v)\b", " ", str(name), flags=re.I)) + " "
    good = bool(re.search(r"\b(DDP|DD\+|E ?AC ?3|AC ?3|AAC|Opus|FLAC|MP3|DD ?[257]|DD)(?![A-Za-z])", a, re.I))
    bad = bool(re.search(r"\bDTS|\bTrue ?HD|\bMLP\b", a, re.I)) or (bool(re.search(r"\bAtmos\b", a, re.I)) and not good)
    return "ok" if good else "bad" if bad else "unknown"


def fname(url):
    """Last path segment, decoded: a stable key for a URL whose ip/expiry/hash rotate."""
    seg = re.split(r"[?#]", str(url))[0].split("/")[-1]
    try:
        return unquote(seg)
    except Exception:
        return seg


def parse(url, hint=""):
    """File name -> metadata dict."""
    raw = fname(url)
    m = EXT.search(raw)
    ext = m.group(1).lower() if m else ""
    hp = bool(re.search(r"HDR10(\+|Plus)", raw, re.I))
    n = " " + re.sub(r"[._\-+()\[\]]+", " ", EXT.sub("", raw)) + " "
    if hint:
        n += " " + re.sub(r"[._\-+()\[\]]+", " ", str(hint)) + " "
    h = 0
    m = re.search(r"\b(2160|1080|720|480)p\b", n, re.I)
    if m:
        h = int(m.group(1))
    elif re.search(r"\b(UHD|4K)\b", n, re.I):
        h = 2160
    hdr = hp or bool(re.search(r"\bHDR(10)?\b", n, re.I))
    dv = bool(re.search(r"\b(DV|DoVi|Dolby Vision)\b", n, re.I))
    b10 = bool(re.search(r"\b10 ?bit\b", n, re.I))
    if re.search(r"\b(x265|h 265|h265|hevc)\b", n, re.I):
        codec = "HEVC"
    elif re.search(r"\bav1\b", n, re.I):
        codec = "AV1"
    elif re.search(r"\b(x264|h 264|h264|avc)\b", n, re.I):
        codec = "H.264"
    else:
        codec = ""
    if re.search(r"\bremux\b", n, re.I):
        src = "Remux"
    elif re.search(r"\b(blu ?ray|bdrip|brrip)\b", n, re.I):
        src = "BluRay"
    elif re.search(r"\bweb ?dl\b", n, re.I):
        src = "WEB-DL"
    elif re.search(r"\bweb ?rip\b", n, re.I):
        src = "WEBRip"
    else:
        src = ""
    se = re.search(r"\bS(\d{1,2}) ?E(\d{1,3})\b", n, re.I)
    return {
        "audio": audio_of(raw + " " + (hint or "")), "height": h, "hdr": hdr or dv, "hdr10plus": hp,
        "hdr_only": hdr, "dolby_vision": dv, "bit10": b10, "codec": codec, "source": src, "ext": ext,
        "season": int(se.group(1)) if se else None, "episode": int(se.group(2)) if se else None,
    }


def label(p, size=""):
    """'2160p HDR DV · HEVC · WEB-DL · MKV · 12.3 GB'"""
    first = [("%dp" % p["height"]) if p.get("height") else ""]
    f = "HDR10+" if p.get("hdr10plus") else "HDR" if p.get("hdr_only") else ""
    if p.get("dolby_vision"):
        f += (" " if f else "") + "DV"
    if not f and p.get("bit10"):
        f = "10bit"
    if f:
        first.append(f)
    parts = [" ".join(x for x in first if x)]
    for k in ("codec", "source"):
        if p.get(k):
            parts.append(p[k])
    if p.get("ext"):
        parts.append(p["ext"].upper())
    if size:
        parts.append(size)
    return " · ".join(x for x in parts if x)


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def extract(result):
    """Walk any JSON and return [{url, size, meta, label}] for each video link found.

    Parent objects pass `season`/`quality` down, so series results shaped
    {"download": {"s1": [{"season": 1, "quality": "BluRay 1080p", "link": [{"dl", "episode"}]}]}}
    get season/episode/quality even when the file name lacks them.
    """
    out, seen, count = [], set(), [0]

    def add(url, ctx, key, inherited):
        url = url.strip()
        if not re.match(r"^https?://", url, re.I) or not EXT.search(re.split(r"[?#]", url)[0]) or url in seen:
            return
        seen.add(url)
        size, info = "", ""
        if isinstance(ctx, dict):
            for k in SIZE_KEYS:
                if ctx.get(k) is not None:
                    size = fmt_size(ctx[k])
                    if size:
                        break
            for f in ("label", "quality", "title", "name"):
                if isinstance(ctx.get(f), str):
                    info += " " + ctx[f]
        if inherited.get("quality"):
            info += " " + inherited["quality"]
        if key and re.search(r"(\d{3,4}p|4k|uhd)", str(key), re.I):
            info += " " + str(key)
        meta = parse(url, info)
        if meta["episode"] is None and isinstance(ctx, dict) and _int(ctx.get("episode")) is not None:
            meta["episode"] = _int(ctx["episode"])
            meta["season"] = _int(ctx.get("season")) or inherited.get("season") or 1
        elif meta["season"] is None and meta["episode"] is not None and inherited.get("season"):
            meta["season"] = inherited["season"]
        out.append({"url": url, "size": size, "meta": meta, "label": label(meta, size)})

    def walk(o, depth, key, inherited):
        count[0] += 1
        if depth > 9 or count[0] > 20000 or o is None:
            return
        if isinstance(o, str):
            add(o, None, key, inherited)
        elif isinstance(o, list):
            for x in o:
                walk(x, depth + 1, key, inherited)
        elif isinstance(o, dict):
            here = dict(inherited)
            season = _int(o.get("season_int")) or _int(o.get("season"))
            if season:
                here["season"] = season
            if isinstance(o.get("quality"), str):
                here["quality"] = o["quality"]
            for k, v in o.items():
                if isinstance(v, str):
                    add(v, o, "%s %s" % (k, key), inherited)  # parent key too: {"1080p": {"link": url}}
                else:
                    walk(v, depth + 1, k, here)

    walk(result, 0, "", {})
    return out


def to_entry(x):
    """Extracted link -> an m3u8-list-shaped quality entry, flagged direct."""
    m = x["meta"]
    return {"label": x["label"], "default": x["url"], "direct": True, "height": m["height"],
            "hdr": bool(m["hdr"]), "size": x["size"], "source": m["source"], "audio": m["audio"], "meta": m}


def attach(items, links, is_series):
    """Append extracted downloads to stream `hls` items as extra qualities.

    Movie: every link goes on the single item. Series: matched by season+episode.
    Returns the number of links attached.
    """
    if not items or not links:
        return 0
    n = 0
    for it in items:
        if not is_series and len(items) == 1:
            mine = list(links)
        else:
            info = it.get("info") or {}
            try:
                s = int(info.get("season") or 1)
            except (TypeError, ValueError):
                s = 1
            try:
                e = int(info.get("episode_number") or info.get("episode"))
            except (TypeError, ValueError):
                e = None
            mine = [x for x in links if x["meta"]["episode"] is not None
                    and (x["meta"]["season"] or 1) == s and x["meta"]["episode"] == e]
        if not mine or not it.get("file"):
            continue
        mine.sort(key=lambda x: (-x["meta"]["height"], -int(bool(x["meta"]["hdr"]))))
        m = it["file"].get("m3u8")
        base = list(m) if isinstance(m, list) else [m] if isinstance(m, dict) else ([{"label": "HLS", "default": m}] if m else [])
        it["file"]["m3u8"] = base + [to_entry(x) for x in mine]
        n += len(mine)
    return n


def candidates(entries, failed=()):
    """Direct entries worth trying, best first: height, then known-good audio, then HDR."""
    out = []
    for i, e in enumerate(entries or []):
        url = e.get("direct") and (e.get("default") or e.get("url"))
        if not url or url.strip() in failed or e.get("audio") == "bad":
            continue
        out.append((e, i))
    out.sort(key=lambda t: (-(t[0].get("height") or 0), -(t[0].get("audio") == "ok"), -int(bool(t[0].get("hdr"))), t[1]))
    return [e for e, _ in out]
