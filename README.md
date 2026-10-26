# sinama: Python client for the 30nama API

Unofficial, single-package (monolithic) Python library for both 30nama APIs:

- `sinama.Client`: the hana-api v2 RPC API used by the official TV apps and SDK (browse, search,
  stream, download, progress, lists, notifications, plans). Its module layout mirrors
  [msharifi99/30nama-tizenos](https://github.com/msharifi99/30nama-tizenos)'s `tizen-app/js/`.
- `sinama.WebClient`: the website's own API (`interface.30nama.com/api/v1`), mapped from the
  30nama.com JavaScript. It adds comments, ratings, collections, articles, top lists, box office,
  schedule, people, profiles, requests, watch history and full search.

> Not affiliated with 30nama. You need your own subscription for streaming and downloads.

## Install

```bash
pip install -e .[test]
```

Python 3.9+, one dependency (`requests`).

## Log in

Password login is protected by Google reCAPTCHA (`captcha` answers `true` for the TV client
keys), so it can't run unattended. Use the QR flow once; the session is saved to
`~/.sinama/session.json` and reused:

```bash
python -m sinama qr-login
```

Open the printed `https://30nama.com/auth/<code>` link on any device where you are signed in
to 30nama.com and approve it (codes last about 10 minutes). Alternatives: `SINAMA_TOKEN=<token>`,
or `Client().login(recaptcha_response=<token solved in a browser>)`, which reads
`SITE_30NAMA_EMAIL` / `SITE_30NAMA_PASSWORD` from the environment.

A website (v1) session is separate; link one from the v2 session without another approval:

```bash
python -m sinama web-login
```

## Use

```python
from sinama import Client, player

c = Client()
for p in c.search("dune", stream_only=True)["posts"]:
    print(p["id"], p["title"]["english"])

st = c.stream(8863)
print(player.pick_url(player.items(st)[0], max_height=1080))
```

```python
from sinama import WebClient

web = WebClient()
print(web.comments(8863, type="review")["total_comments"])
print([p["title"] for p in web.toplist("top-movie-imdb")["posts"][:5]])
```

Every action and path, with fields, responses and errors: [docs/API.md](docs/API.md).

## Layout

```
sinama/       the library (config, api, client, web, library, direct, player, screens, helpers, store, errors, app)
tests/        offline tests (fake HTTP) + live tests for every endpoint
docs/         API reference
tools/        probe.py: call any action and dump the raw JSON
```

## Tests

```bash
python -m pytest                  # offline + live public; logged-in tests run when a session exists
python -m pytest tests/test_offline.py   # no network
python -m pytest -m "live and not auth"  # live, anonymous only
```

The website API rate-limits hard (~30 requests a minute earns a ~4 minute block), so
`WebTransport` spaces requests 2.5 s apart and `tests/test_web_live.py` takes a few minutes.

Logged-in tests leave the account as they found it: list toggles are reverted, the progress
report re-sends an existing resume point unchanged, and dismiss targets a title that isn't in
continue watching. `logout` is only tested with `SINAMA_TEST_LOGOUT=1` because it ends the
session.

## License

MIT
