# sinama: Python client for the 30nama API

Unofficial, single-package Python library (and a small command line) for both 30nama APIs:

- `sinama.Client`: the hana-api v2 RPC API used by the official TV apps and SDK: browse, search, stream,
  download, subtitles, watch progress, lists, notifications and plans. Its module layout mirrors
  [msharifi99/30nama-tizenos](https://github.com/msharifi99/30nama-tizenos)'s `tizen-app/js/`.
- `sinama.WebClient`: the website's own API (`interface.30nama.com/api/v1`), mapped from the 30nama.com
  JavaScript. It adds comments, ratings, collections, articles, top lists, box office, schedule, people, profiles,
  requests, watch history and full search.

Every action, path, field, response and error is written down in [docs/API.md](docs/API.md).

> **Not affiliated with 30nama.** This library talks to 30nama's public endpoints the way its own apps do. You need
> your own 30nama subscription for streaming and downloads; use it within 30nama's terms.

**فارسی:** sinama یک کتابخانه‌ی پایتون (غیررسمی) برای API سی‌نما است: مرور، جستجو، پخش، دانلود، زیرنویس، ادامه‌ی
تماشا، لیست‌ها و اعلان‌ها، هم از API اپ‌های تلویزیون (hana-api v2) و هم از API خود سایت. ورود با کد QR انجام
می‌شود و برای پخش و دانلود اشتراک خود سی‌نما لازم است. این پروژه هیچ ارتباطی با سی‌نما ندارد.

## Contents

- [Install](#install) · [Log in](#log-in) · [Use](#use) · [Command line](#command-line) · [Errors](#errors)
- [Your own network and session storage](#your-own-network-and-session-storage) · [Cloudflare](#cloudflare)
- [Configuration](#configuration) · [Layout](#layout) · [Tests](#tests) · [Changelog](CHANGELOG.md) · [License](#license)

## Install

Python 3.9+, one dependency (`requests`); `httpx` only for `HttpxSession`.

```bash
pip install "sinama @ git+https://github.com/DrSaeedHub/30nama-API.git@v1.2.0"
pip install "sinama[httpx] @ git+https://github.com/DrSaeedHub/30nama-API.git@v1.2.0"   # with httpx
```

From a checkout, for development:

```bash
pip install -e .[test]
```

## Log in

Password login is protected by Google reCAPTCHA (`captcha` answers `true` for the TV client keys), so it can't
run unattended. Use the QR flow once; the session is saved to `~/.sinama/session.json` and reused:

```bash
python -m sinama qr-login
```

Open the printed `https://30nama.com/auth/<code>` link on any device where you are signed in to 30nama.com and
approve it (codes last about 10 minutes). Alternatives: `SINAMA_TOKEN=<token>`, or
`Client().login(recaptcha_response=<token solved in a browser>)`, which reads `SITE_30NAMA_EMAIL` /
`SITE_30NAMA_PASSWORD` from the environment.

A website (v1) session is separate; link one from the v2 session without another approval:

```bash
python -m sinama web-login
```

The saved session holds your token: keep `~/.sinama/session.json` private.

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
for link in c.download_links(8863):              # direct .mkv/.mp4 files with their quality parsed from the name
    print(link["label"], link["url"])

print(c.continue_watching()["posts"][:3])         # needs a session
for post in c.iter_pages(c.archive, "action", max_pages=2):   # posts across pages
    print(post["id"])
```

```python
from sinama import WebClient

web = WebClient()
print(web.comments(8863, type="review")["total_comments"])
print([p["title"] for p in web.toplist("top-movie-imdb")["posts"][:5]])
```

What `Client` covers, by area (every method in [docs/API.md](docs/API.md#python-library)):

| Area | Methods |
|---|---|
| Account | `qr_login`, `login`, `otp_send` / `otp_verify`, `register`, `user`, `logout`, `plans`, `offer`, `checks`, `voucher` |
| Browse | `home`, `home_stream`, `menu`, `single`, `search`, `archive`, `advanced_search_parameters`, `advanced_search`, `iter_pages` |
| Playback | `stream`, `download`, `download_links`, `subtitle`, `observer` (watch progress), `continue_watching`, `continue_watching_dismiss` |
| Lists | `my_lists`, `user_list`, `user_list_toggle` |
| Notifications | `notifications`, `notification_read` |
| Anything else | `call(action, **params)` sends any action and returns its result |

The helper modules work on those results: `player` (stream items and the best URL under a height), `direct`
(download files with resolution, HDR, codec, source and episode parsed from their names), `screens` (the home
screen as rows), `helpers` (titles, images).

## Command line

`python -m sinama` (or `sinama` once installed); `--json` prints the raw answer, `--lang fa` asks in Persian.

| Command | Does |
|---|---|
| `qr-login`, `login [--user U] [--captcha TOKEN]`, `web-login`, `logout`, `whoami` | sessions |
| `test`, `menu`, `plans` | the host, the menu, the plans |
| `home`, `continue` | the home rows, continue watching |
| `search QUERY [--page N] [--stream-only]`, `archive SLUG [--page N] [--sort date]` | find titles |
| `single ID`, `stream ID`, `downloads ID`, `subtitle URL` | one title, its stream, its files, a subtitle |
| `mylist [GROUP]` | a list (`watchlist` by default) |
| `call ACTION key=value …`, `web PATH key=value …` | any v2 action or website path |

```bash
python -m sinama search "the office" --stream-only
python -m sinama downloads 8863
python -m sinama call single id=8863 --json
```

Exit codes: 0 done, 2 an API or network error, 3 a captcha is needed.

## Errors

Everything raised is a `SinamaError`:

| Error | When |
|---|---|
| `TransportError` | network failure, timeout, or an answer that is not the API's JSON (retried) |
| `RateLimited` | HTTP 429 or Cloudflare's 1015 (a `TransportError`) |
| `Blocked` | Cloudflare or the API's own guard (`REQUESTBLOCK`, `APIMAINTENANCE`); not retried |
| `ChallengeRequired` | Cloudflare's bot challenge instead of the API (a `Blocked`; `.host` names the host) |
| `NoEndpoint` | no discovered host answered; the message says why each one failed |
| `ApiError` | the API answered `success: false` |
| `LoginRequired`, `NotFound`, `CaptchaRequired`, `QRCodeExpired` | the common `ApiError`s |

## Your own network and session storage

```python
from sinama import CallbackStore, Client, HttpxSession, Transport

c = Client(transport=Transport(session=HttpxSession(my_send)),        # my_send(method, url, **httpx_kwargs)
           store=CallbackStore(load=my_load, save=my_save))           # the session kept where you keep secrets
```

`HttpxSession` turns httpx's network errors into requests' (so retries work as usual) and lets any other error of
yours pass through untouched. `MemoryStore` keeps the session in memory only; `SessionStore` is the file store used by
default. Build your own httpx clients with `sinama.tls_context()`: Cloudflare in front of the API challenges
Python's default TLS greeting. See [docs/API.md](docs/API.md#python-library).

## Cloudflare

When Cloudflare puts its bot challenge in front of the API on your network, calls and host discovery raise
`ChallengeRequired` (a `Blocked`, so `except Blocked` still catches it; `.host` names the host): a person has to
confirm the challenge on that network. `sinama.is_challenge(status, headers, body)` classifies your own responses
the same way.

## Configuration

Environment variables (see [.env.example](.env.example)):

| Variable | Meaning |
|---|---|
| `SINAMA_TOKEN` | a session token to use instead of the saved session |
| `SINAMA_SESSION_FILE` | where the session is saved (default `~/.sinama/session.json`) |
| `SINAMA_HOST` | skip host discovery and use this API host |
| `SINAMA_PROXY` | send the default session through a proxy, e.g. `socks5h://user:pass@host:1080` |
| `SITE_30NAMA_EMAIL`, `SITE_30NAMA_PASSWORD` | defaults for `Client.login()` |
| `SINAMA_WEB_TOKEN`, `SINAMA_WEB_SESSION_FILE` | the same two for the website session (`WebClient`) |

## Layout

```
sinama/       the library (config, api, session, client, web, library, direct, player, screens, helpers, store, errors, app)
tests/        offline tests (fake HTTP) + live tests for every endpoint
docs/         API reference
tools/        probe.py: call any action and dump the raw JSON
```

## Tests

Live tests reach 30nama from your machine, so they run only through a proxy you name
(`SINAMA_PROXY=socks5h://user:pass@host:1080`, names resolved on the proxy) or when you allow your own connection
with `SINAMA_LIVE_DIRECT=1`.

```bash
python -m pytest                          # offline; + live public and logged-in tests with SINAMA_PROXY set
python -m pytest tests/test_offline.py    # no network
python -m pytest -m "live and not auth"   # live, anonymous only
```

The website API rate-limits hard (~30 requests a minute earns a ~4 minute block), so `WebTransport` spaces requests
2.5 s apart and `tests/test_web_live.py` takes a few minutes.

Logged-in tests leave the account as they found it: list toggles are reverted, the progress report re-sends an
existing resume point unchanged, and dismiss targets a title that isn't in continue watching. `logout` is only tested
with `SINAMA_TEST_LOGOUT=1` because it ends the session.

## Used by

Lumen, a media server and webOS TV app, plays 30nama's catalog
through sinama.

## License

[MIT](LICENSE)
