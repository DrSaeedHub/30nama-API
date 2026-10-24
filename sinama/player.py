"""Playback helpers over a `stream` result: episodes, qualities, subtitles, progress.

Port of the non-UI parts of tizen-app/js/player.js. A `stream` result looks like:

    {"info": {"post_id": ..}, "continue_watching": {"file_id": .., "time": ..} | null,
     "hls": [{"info": {"file_id", "season", "episode", "episode_number", "episode_name"},
              "file": {"m3u8": [{"label": "1080p", "default": url, "2ch": url, "6ch": url}],
                       "subtitle": {"fa": url, "en": url}},
              "options": {"intro_start", "intro_end", "previously_start", "previously_end",
                          "end", "token"}}]}
"""
import re
import threading
import time

from . import config as C
from .helpers import hms


def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def items(stream):
    """The playable items of a stream result, sorted by season then episode."""
    hls = list((stream or {}).get("hls") or [])

    def key(it):
        info = it.get("info") or {}
        return (_int(info.get("season"), 1), _int(info.get("episode_number") or info.get("episode"), 0))

    return sorted(hls, key=key)


def seasons(stream):
    """{season_number: [items]}"""
    out = {}
    for it in items(stream):
        out.setdefault(_int((it.get("info") or {}).get("season"), 1), []).append(it)
    return out


def resume_point(stream):
    """(item_index, seconds) to resume from `continue_watching`, or (0, 0)."""
    cw = (stream or {}).get("continue_watching") or {}
    fid = cw.get("file_id")
    if not fid:
        return 0, 0.0
    for i, it in enumerate(items(stream)):
        if str((it.get("info") or {}).get("file_id")) == str(fid):
            return i, float(cw.get("time") or 0)
    return 0, 0.0


def qualities(item):
    """Normalised quality list: [{label, height, url, url_2ch, url_6ch, direct}] best first."""
    m = ((item or {}).get("file") or {}).get("m3u8")
    if isinstance(m, dict):
        m = [m]
    elif isinstance(m, str):
        m = [{"label": "HLS", "default": m}]
    out = []
    for e in m or []:
        lab = str(e.get("label") or "")
        mh = re.search(r"(\d{3,4})p", lab)
        height = e.get("height") or (int(mh.group(1)) if mh else (2160 if re.search(r"4k|uhd", lab, re.I) else 0))
        out.append({"label": lab, "height": height, "url": (e.get("default") or e.get("url") or "").strip(),
                    "url_2ch": e.get("2ch"), "url_6ch": e.get("6ch"), "direct": bool(e.get("direct")), "raw": e})
    out.sort(key=lambda q: (-(q["height"] or 0), q["direct"]))
    return out


def pick_url(item, max_height=None, prefer_direct=False, audio="default"):
    """Best URL for an item. audio: "default" | "2ch" | "6ch". Auto/unknown labels rank lowest."""
    qs = [q for q in qualities(item) if q["url"]]
    if not prefer_direct:
        qs = [q for q in qs if not q["direct"]] or qs
    if max_height:
        capped = [q for q in qs if q["height"] and q["height"] <= max_height]
        qs = capped or qs
    if not qs:
        return None
    q = qs[0]
    if audio == "2ch" and q["url_2ch"]:
        return q["url_2ch"]
    if audio == "6ch" and q["url_6ch"]:
        return q["url_6ch"]
    return q["url"]


def markers(item):
    """Intro / recap / credits markers in seconds (None when absent)."""
    o = (item or {}).get("options") or {}
    return {k: hms(o.get(k)) for k in ("intro_start", "intro_end", "previously_start", "previously_end", "end")}


def subtitle_urls(item):
    """{lang: url} from item.file.subtitle (values may be strings or {url|file|src|link|vtt})."""
    subs = ((item or {}).get("file") or {}).get("subtitle") or {}
    out = {}
    if isinstance(subs, dict):
        for lang, v in subs.items():
            if isinstance(v, dict):
                v = v.get("url") or v.get("file") or v.get("src") or v.get("link") or v.get("vtt")
            if v:
                out[lang] = v
    return out


# ---------- subtitles ----------
_TS = re.compile(r"(\d+:)?(\d{1,2}):(\d{2})[.,](\d{1,3})")


def _ts(s):
    m = _TS.search(s)
    if not m:
        return None
    h = int((m.group(1) or "0:")[:-1])
    return h * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4).ljust(3, "0")) / 1000.0


def srt_to_vtt(text):
    """SRT -> WebVTT (comma decimal separators and a header). VTT input is returned unchanged."""
    text = text.lstrip("﻿")
    if text.lstrip().startswith("WEBVTT"):
        return text
    body = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", text.replace("\r\n", "\n"))
    return "WEBVTT\n\n" + body


def parse_cues(text):
    """WebVTT/SRT -> [{start, end, text}] in seconds."""
    cues = []
    for block in re.split(r"\n\s*\n", srt_to_vtt(text).replace("\r\n", "\n")):
        lines = [l for l in block.strip().split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if "-->" in line:
                a, b = line.split("-->", 1)
                start, end = _ts(a), _ts(b)
                if start is not None and end is not None:
                    txt = re.sub(r"<[^>]+>", "", "\n".join(lines[i + 1:])).strip()
                    cues.append({"start": start, "end": end, "text": txt})
                break
    return cues


# ---------- progress reporting (observer) ----------
def observer_params(post_id, item, user_id, time_s, duration_s):
    info = (item or {}).get("info") or {}
    return {
        "post_id": info.get("post_id") or post_id,
        "file_id": info.get("file_id"),
        "user_id": user_id or "",
        "time": int(time_s),
        "duration": int(duration_s),
        "token": ((item or {}).get("options") or {}).get("token") or "",
    }


class ProgressReporter:
    """Heartbeat that reports playback position with `observer` every HEARTBEAT_SECONDS.

    `position` is a callable returning (time_s, duration_s). Call `stop(final=True)` on
    close to send a last report (retried twice, like the TV app).
    """

    def __init__(self, client, post_id, item, position, interval=C.HEARTBEAT_SECONDS):
        self.client, self.post_id, self.item, self.position = client, post_id, item, position
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self.reports = 0
        self.last_error = None

    def report(self, final=False):
        t, d = self.position()
        if t is None or d is None or t < 1 or d <= 0:
            return False
        for attempt in range(3 if final else 1):
            try:
                self.client.observer(self.post_id, (self.item.get("info") or {}).get("file_id"), int(t), int(d),
                                     token=((self.item.get("options") or {}).get("token") or ""))
                self.reports += 1
                return True
            except Exception as e:  # a failed heartbeat is replaced by the next one
                self.last_error = e
                if final and attempt < 2:
                    time.sleep(2)
        return False

    def _loop(self):
        while not self._stop.wait(self.interval):
            self.report()

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def stop(self, final=True):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval + 1)
        if final:
            self.report(final=True)
