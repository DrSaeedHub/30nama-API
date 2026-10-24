"""Call any action and print / save the raw envelope.

    python tools/probe.py search query=dune streamonly=true
    python tools/probe.py --out probes single post_id=8863
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sinama import Client  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action")
    ap.add_argument("params", nargs="*", help="key=value")
    ap.add_argument("--out", help="directory to save <action>.json into")
    ap.add_argument("--anon", action="store_true", help="send no session token")
    a = ap.parse_args()
    c = Client(persist=False)
    if a.anon:
        c.transport.token = None
    env = c.call(a.action, retry=False, **dict(kv.split("=", 1) for kv in a.params))
    text = json.dumps(env, ensure_ascii=False, indent=1)
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, a.action.replace("/", "_") + ".json"), "w", encoding="utf-8") as f:
            f.write(text)
    sys.stdout.write(text + "\n")


if __name__ == "__main__":
    main()
