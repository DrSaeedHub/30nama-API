"""Command line: `python -m sinama <command>` (or the `sinama` script).

    sinama qr-login               approve the printed URL on a logged-in device
    sinama login [--captcha TOK]  password login from $SITE_30NAMA_EMAIL / $SITE_30NAMA_PASSWORD
    sinama whoami | logout | test
    sinama home | menu | plans
    sinama search QUERY [--page N] [--stream-only]
    sinama archive SLUG [--page N] [--sort date|favorite|update]
    sinama single ID | stream ID | downloads ID | subtitle URL
    sinama mylist [watchlist|favorite] | continue
    sinama call ACTION [key=value ...]   any action, raw envelope
    sinama web-login              link a website (v1) session using the saved v2 session
    sinama web PATH [key=value ...]      any website-API path, e.g. `web comment/id/8863/page/1/type/comment/orderby/date`
"""
import argparse
import json
import sys

from . import screens
from .client import Client
from .web import WebClient
from .errors import CaptchaRequired, SinamaError
from .helpers import title


def _print(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


def _rows(ps):
    for p in ps:
        o = p.get("options") or {}
        sys.stdout.write("%8s  %-6s %s %s\n" % (p.get("id"), o.get("title_type", ""), title(p),
                                               "" if o.get("stream") else "(no stream)"))


def build_parser():
    ap = argparse.ArgumentParser(prog="sinama", description="30nama API client")
    ap.add_argument("--json", action="store_true", help="print raw JSON")
    ap.add_argument("--lang", default="en", choices=["en", "fa"])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("qr-login")
    p = sub.add_parser("login")
    p.add_argument("--user")
    p.add_argument("--captcha", help="reCAPTCHA response token solved in a browser")
    for name in ("whoami", "logout", "test", "home", "menu", "plans", "continue"):
        sub.add_parser(name)
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--stream-only", action="store_true")
    p = sub.add_parser("archive")
    p.add_argument("slug")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--sort", default="date")
    for name in ("single", "stream", "downloads"):
        sub.add_parser(name).add_argument("id", type=int)
    sub.add_parser("subtitle").add_argument("url")
    sub.add_parser("mylist").add_argument("group", nargs="?", default="watchlist")
    p = sub.add_parser("call")
    p.add_argument("action")
    p.add_argument("params", nargs="*", help="key=value")
    sub.add_parser("web-login")
    p = sub.add_parser("web")
    p.add_argument("path")
    p.add_argument("params", nargs="*", help="key=value")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    c = Client(language=a.lang)
    try:
        return run(c, a)
    except CaptchaRequired as e:
        sys.stderr.write("captcha required (%s): use `sinama qr-login`, or pass --captcha\n" % e)
        return 3
    except SinamaError as e:
        sys.stderr.write("error: %s: %s\n" % (type(e).__name__, e))
        return 2


def run(c, a):
    cmd = a.cmd
    if cmd == "qr-login":
        u = c.qr_login(on_code=lambda code, url: sys.stderr.write(
            "Open %s on a device logged in to 30nama.com (code %s). Waiting...\n" % (url, code)))
        sys.stderr.write("logged in as %s; session saved to %s\n" % (u.get("user_name", "?"), c.store.path))
        return 0
    if cmd == "login":
        u = c.login(username=a.user, recaptcha_response=a.captcha)
        sys.stderr.write("logged in as %s\n" % u.get("user_name", "?"))
        return 0
    if cmd == "call":
        _print(c.call(a.action, **dict(kv.split("=", 1) for kv in a.params)))
        return 0
    if cmd == "web-login":
        w = WebClient()
        u = w.qr_login(approve_with=c)
        sys.stderr.write("website session for %s saved to %s\n" % (u.get("username", "?"), w.store.path))
        return 0
    if cmd == "web":
        _print(WebClient().call(a.path, **dict(kv.split("=", 1) for kv in a.params)))
        return 0
    simple = {"whoami": c.user, "test": c.test, "menu": c.menu, "plans": c.plans, "logout": c.logout}
    if cmd in simple:
        _print(simple[cmd]())
        return 0
    if cmd == "home":
        h = screens.home(c)
        if a.json:
            _print(h["raw"])
        else:
            for row in [{"key": "continue_watching", "posts": h["continue_watching"]}] + h["rows"]:
                if row["posts"]:
                    sys.stdout.write("== %s\n" % row["key"])
                    _rows(row["posts"])
        return 0
    if cmd in ("search", "archive", "mylist", "continue"):
        if cmd == "search":
            r = c.search(a.query, page=a.page, stream_only=a.stream_only)
        elif cmd == "archive":
            r = c.archive(a.slug, page=a.page, orderby=a.sort)
        elif cmd == "mylist":
            r = c.user_list(a.group)
        else:
            r = c.continue_watching()
        if a.json:
            _print(r)
        else:
            sys.stdout.write("page %s/%s, %s results\n" % (r.get("page", 1), r.get("pages", 1), r.get("total", "?")))
            _rows(r.get("posts") or [])
        return 0
    if cmd == "single":
        _print(c.single(a.id))
    elif cmd == "stream":
        _print(c.stream(a.id))
    elif cmd == "downloads":
        for x in c.download_links(a.id):
            sys.stdout.write("%-45s %s\n" % (x["label"], x["url"]))
    elif cmd == "subtitle":
        sys.stdout.write(c.subtitle(a.url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
