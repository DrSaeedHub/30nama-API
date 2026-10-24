# 30nama API reference (hana-api v2)

Unofficial reference for the RPC API behind the official 30nama TV clients, as used by
[msharifi99/30nama-tizenos](https://github.com/msharifi99/30nama-tizenos) and verified live
on 2026-10-23 from this repository's test suite. The API is undocumented and can change at
any time. Each action lists the `sinama` method that wraps it.

> **Verification status.** Every action below was exercised live on 2026-10-23, anonymously and
> with a logged-in (golden plan) session obtained by QR login. `register` and password `login`
> were only verified up to their captcha rejection. The `notification` item shape is
> unverified (the test account had none).

- [Transport](#transport) · [Envelope and errors](#envelope-and-errors) · [Rate limiting](#rate-limiting)
- Actions: [Connection](#connection) · [Auth](#auth) · [Account](#account) · [Browse](#browse) ·
  [Playback](#playback) · [Library](#library) · [Notifications](#notifications)
- [Shared objects](#shared-objects) · [Python library](#python-library) · [CLI](#cli)

---

## Transport

| | |
|---|---|
| Base URL | `https://world.hana-api.com/api/v2` (WORLD) or `https://ir.kazem-api.com/api/v2` (IR) |
| Discovery | `GET https://pub-ac69cf865ce145f8b4c1ed87dc2a9fb7.r2.dev/sdk-endpoint.json` or `GET https://30update.s3.ir-thr-at1.arvanstorage.ir/sdk-endpoint.json` → `[{"location": "WORLD", "host": "https://…/api/v2"}, …]` |
| Request | `POST {base}/action/{name}`, body `application/x-www-form-urlencoded` (GET also works for parameterless actions) |
| Response | JSON [envelope](#envelope-and-errors); a few exceptions are noted per action |

Choose a host by calling [`test`](#test) on every discovered host and keeping the first that
answers `success: true` (the library races them in parallel; `Transport.init()`).

### Headers

| Header | Value | Notes |
|---|---|---|
| `c-api-key` | client key | Identifies the *platform*, not the user. WEBTV: `83hRzBab…dZHPb97As`, ANDROIDTV: `VdapnkLG9EHsSmF8yeKcb4253RAuN6YX` (full values in `sinama/config.py`). `test` reports the platform it maps to. |
| `c-token` | session token or empty | Required by every [private action](#auth). Obtained from QR/password/OTP login. |
| `c-version-number` | `1.0.0` | Client version. |
| `c-language` | `en` \| `fa` | Language of `msg`, titles, and some labels. |
| `User-Agent` | any browser/TV UA | The library sends a Tizen TV UA. |

### Parameter conventions

- Booleans filter only when sent as the string `"true"` (`streamonly=true`); `1`/`0` are ignored by `search`/`archive`. The library sends `"true"` for `stream_only=True` and omits the field otherwise.
- Nested values (`advanced_search.parameters`) are JSON strings inside the form body.
- Pages are 1-based. Paged results always carry `page`, `pages`, `total`.

---

## Envelope and errors

```json
{"status": 200, "success": true, "error": false, "msg": "Search",
 "result": { … }, "action": null, "seo": null, "timestamp": 1792816087}
```

`status` inside the body is the logical status (it can say `403` on HTTP 200). `action` is a
hint list for the client, e.g. `["retry"]` after a captcha failure. On HTTP 404 the payload
key is spelled `results`.

| Condition | `msg` | Library exception |
|---|---|---|
| Missing/expired token | `Login Required` (also `Access Denied` for a token from another API) | `LoginRequired` |
| reCAPTCHA missing/invalid | `invalid-input-response` (`status: 403`, `action: ["retry"]`) | `CaptchaRequired` |
| Unknown action (HTTP 404) | `404 Not Found` | `NotFound` |
| Unknown post | `Post not found` (no `post_id`) or `success: true` with only `continue_watching` (unknown id) | `NotFound` |
| Unknown archive slug | `NO_SLUG_FOUND` | `NotFound` |
| QR code | `Code Expired`, `Wrong Code` | `QRCodeExpired` |
| Anything else with `success: false` | | `ApiError` |
| Cloudflare 429 / `error code: 1015` | (HTML/text) | `RateLimited` (retried) |
| Cloudflare challenge page, `REQUESTBLOCK`, `REQUESTCAPTCHA`, `APIMAINTENANCE` | (HTML/text) | `Blocked` (not retried) |
| Network error, timeout, other non-JSON (5xx) | | `TransportError` (retried) |

All `ApiError`s expose `.msg`, `.status`, `.envelope`, `.action` (the action name) and `.hint` (the envelope's `action`).

## Rate limiting

The hosts are behind Cloudflare rate limiting. Clients should mirror the TV app's scheduler,
which the library implements in `sinama.api.Scheduler`:

- at most **2** requests in flight, at least **100 ms** between request starts;
- transient failures (429, 5xx, non-JSON, timeout) are retried after **1 s** then **3 s**, honouring `Retry-After` (capped at 10 s); a 429 pauses *all* requests;
- never retried: `observer`, `logout`, `qrlogin_login`, `login`, `otp`, `otp_verify`, `register`, `user_list` (side effects, or polling where a retry is harmful).

---

## Connection

### `test`
Connection test; also the host/key probe. Public.

**Result**
```json
{"ip": {"ip": "203.0.113.10", "country": "DE", "continent": "EU"},
 "device": {"client": "Safari", "os": "Other Mobile 6.5", "device": "Tv", "brand": "-", "model": "-"},
 "is_abroad": false, "platform": "WebTV"}
```
`platform` is derived from `c-api-key` (any or no key still answers). → `Client.test()`

---

## Auth

Private actions (need `c-token`): `user`, `stream`, `download`, `continue_watching`,
`continue_watching_dismiss`, `user_mylist`, `user_list`, `notification`, `notification_read`.
Without a token they answer `Login Required`. `observer` and `logout` answer success either way.

### `captcha`
Whether `login`/`otp`/`register` need a reCAPTCHA token for this client and IP. Public.
**Not enveloped**: the body is bare JSON `{"captcha": true}`. It is `true` for both TV keys. → `Client.captcha_required()`

### `login`
Password login. **Captcha-gated**: without a valid Google reCAPTCHA response the server answers
`invalid-input-response` / `action: ["retry"]`. A captcha token can only come from a human
solving it on 30nama.com; for unattended use, log in with QR instead.

| Field | Type | |
|---|---|---|
| `user_login` | string | email, mobile or username |
| `user_password` | string | |
| `recaptcha_response` | string | reCAPTCHA token (required while `captcha` is true) |

**Result** contains the session token (`token`; some versions use `user_session`/`usertoken`).
→ `Client.login(username=None, password=None, recaptcha_response=None)`; username/password default to `$site_30NAMA_email` / `$site_30NAMA_password`.

### `otp`
Send a one-time code to an email or mobile number. Captcha-gated like `login`.
Fields: `user_login`, `recaptcha_response`. Result `{user_id, resend, valid}`. → `Client.otp_send(user_login, recaptcha_response=None)`

### `otp_verify`
Exchange the code for a session. Fields: `user_login`, `user_code`. Wrong code: `Invalid verification code.` → `Client.otp_verify(user_login, code)` (logs the client in)

### `register`
Account sign-up. Captcha-gated (`invalid-input-response` without a token). Field names are
not used by any open client and are unverified. → `Client.register(recaptcha_response=None, **fields)`

### `qrlogin_code`
Start a QR login. Public. **Result** `{"code": "07f7438f", "url": "https://30nama.com/auth/07f7438f"}`.
Show `url` (or a QR of it); the user opens it on a device that is signed in to 30nama.com and
approves. Codes expire after **~600 s**. → `Client.qr_code()`

### `qrlogin_login`
Poll a QR code (the TV app polls every 5 s). Field: `auth_code`.

| Answer | Meaning |
|---|---|
| `success: false`, `msg: "CODE_NOT_USED"` | not approved yet, keep polling |
| `success: true`, `result: {"token": "…"}` | approved; send `token` as `c-token` from now on |
| `msg: "Code Expired"` / `"Wrong Code"` | start over with a new code |

The result has only the token; call [`user`](#user) for the profile. Never retried.
→ `Client.qr_check(code)` (one poll), `Client.qr_login(on_code=None, timeout=600, poll=5)` (blocking).

### `logout`
End the session server-side. Always `success: true` (`You have been logged out successfully`). Never retried. → `Client.logout()` (also clears the local session)

---

## Account

### `user`
Private. Profile of the logged-in user:

```json
{"user_session": "<the session token>", "user_id": 123456, "user_name": "u_12345678",
 "user_type": "golden", "user_allowed_to_download": true, "user_allowed_to_stream": true,
 "user_email": "…", "user_mobile": null,
 "user_expire": {"days": 52, "g": "2026-12-16 01:56:28", "j": "۱۴۰۵-۰۹-۲۵ ۰۱:۵۶:۲۸"},
 "user_avatar": "https://…", "is_new_user": false, "is_abroad_user": false, "is_admin": false}
```

`user_type` is the plan (`golden`, `red`, `blue`, … as in `plans`). `user_session` repeats the
token, so treat the whole object as a secret. → `Client.user()`; cached as `Client.user_info`.

### `plans`
Public. Subscription plans: `{discount: {use_discount, discount_error}, plans: [{id, type, title, order, features: [{title, enable}], prices: {"30"|"90"|"180": {id, note, price, currency, discount}}}]}`. → `Client.plans()`

---

## Browse

All public. Rows and pages contain [post objects](#post).

### `home`
Full home page. Result keys: `hero_header` (`{posts, notes}`), `new_releases`, `suggested`,
`top_10`, `movies`, `series`, `anime` (each `{posts}`), `call_to_action`, `cache`. → `Client.home()`

### `home_stream`
Streaming home, what the TV app renders: `hero_header`, `suggested`, `movies`, `series`, `anime`, `cache`. → `Client.home_stream()`

### `menu`
Browse menu: `{genres: [menu item], categories: [menu item]}`.
Menu item: `{id, name, slug, count, image: {webp: {thumb, full}, jpg: {thumb, full}}}`.
Category slugs: `movies, series, anime, miniseries, suggested, concert, coming-soon, ceremony, new-releases`. → `Client.menu()`

### `single`
Title details. Field: `post_id`. Result: a [post](#post) with every detail field
(`plot, genre, cast, crew, score, country, language, list, air, note, subtitle, seo,
continue_watching`). `subtitle` here lists *external* subtitle pages
(`[{language, quality, link, single, type, season}]`), not playable files.
Missing `post_id` → `Post not found`; unknown id → success with only `continue_watching`
(the library raises `NotFound` for both). → `Client.single(post_id)`

### `search`
| Field | Type | Default | |
|---|---|---|---|
| `query` | string | | title words |
| `page` | int | 1 | |
| `streamonly` | `"true"` | absent | only streamable titles (`batman`: 28 vs 68) |

Result: [page](#page). → `Client.search(query, page=1, stream_only=False)`

### `archive`
Paged listing of a category or genre slug from `menu`.

| Field | Type | Default | |
|---|---|---|---|
| `slugs` | string | | category or genre slug, e.g. `movies`, `drama` |
| `page` | int | 1 | |
| `orderby` | string | | `date` (newest), `favorite` (popular), `update` (updated), `relevant`, `year`, `imdb` |
| `order` | string | `desc` | `desc` \| `asc` |
| `streamonly` | `"true"` | absent | |

Unknown slug → `NO_SLUG_FOUND`. → `Client.archive(slugs, page=1, orderby="date", order="desc", stream_only=False)`

### `advanced_search_parameters`
Vocabulary for `advanced_search`: `genre, type, imdb_rate, country, language, channel, quality`
(lists of `{name, value}`), `encoder, age` (lists of strings), `x265, 3D, stream` (`[{name: "All", value: ""}, {name: "Only", value: "true"}]`),
`min_year`, `max_year` (ints), `cast, director, creator` (`"ENTER_NAME"`). → `Client.advanced_search_parameters()`

### `advanced_search`
| Field | Type | |
|---|---|---|
| `parameters` | JSON string | filters, see below |
| `page` | int | |
| `orderby` | string | `relevant` and `year` change the order |
| `order` | string | `desc` \| `asc` |

Filters: list values for `genre`, `type`, `country`, `language` (`{"genre": ["drama"]}`);
scalars for `imdb_rate`, `min_year`, `max_year`, `stream: "true"`; people by IMDb id with
`actor` / `director` (`{"actor": "nm0000138"}`). Unparseable `parameters` returns everything.
Result: [page](#page). → `Client.advanced_search(parameters=None, page=1, orderby="relevant", order="desc", **filters)`

---

## Playback

### `stream`
Private (unless the title has `options.free_stream`; then send `free_stream=1` without a token).
Needs a streaming plan. Fields: `post_id`, `free_stream` (optional).

```json
{"vast2": "https://servedby.…/fc.php?script=apVideo:vast2&zoneid=1",
 "info": {"post_id": 12382, "title": {"english": "…", "local": null}},
 "image": { … },
 "continue_watching": {"post_id": 140140, "file_id": 27272, "time": 450, "display_time": "00:07:30",
                       "progress": 6},
 "hls": [{
   "info": {"file_id": 39301, "season": 1, "episode": "1", "episode_number": 1,
            "episode_name": "Season 1 - Episode 1"},
   "file": {"m3u8": [{"label": "1080p", "default": "https://…m3u8", "2ch": "https://…", "6ch": "https://…"},
                     {"label": "720p", …}, {"label": "480p", …}, {"label": "360p", …},
                     {"label": "Auto", "default": "https://…"}],
            "subtitle": {"en": "https://world.hana-api.com/api/v2/action/subtitle/file/<b64>",
                         "fa": "https://world.hana-api.com/api/v2/action/subtitle/file/<b64>"}},
   "options": {"intro_start": "00:03:48", "intro_end": "00:04:07", "previously_start": null,
               "previously_end": null, "end": "00:57:12", "token": "<42 chars>"}}]}
```

A movie has one `hls` item whose `info` is just `{file_id}` and whose `options` has only
`intro_start`, `intro_end`, `token`; a series has one item per episode (62 for a 5-season
show). `continue_watching` is `null` for a title never played; `progress` is an integer
percent here. `vast2` is an ad (VAST) tag. HLS URLs are signed with the
requesting IP and expire; fetch them from the machine that plays them. Keep `options.token`
for `observer`. → `Client.stream(post_id, free=False)`; helpers in `sinama.player`.

### `download`
Private (or `free_download=1` for free titles). Needs a download plan. Fields: `post_id`,
`free_download` (`0`/`1`). Two shapes. Movie, a flat list with one entry per file:

```json
{"download": [{"id": 1401402063969, "quality": "x265 BrRip 1080p", "size": "3.52 GB",
               "resolution": "1920x804", "encoder": "30nama", "version": null, "tags": ["x265", "10bit"],
               "part": null, "note": null, "source": "<original release name>",
               "dl": "https://…/October_2018_10bit_1080p_x265_BrRip_30nama_30NAMA.mkv",
               "persian_subtitle": null, "screenshot": "https://…", "mediainfo": "https://…"}]}
```

Series, groups per season and quality, then one link per episode:

```json
{"seasons": [1, 2, 3, 4, 5], "total_seasons": 5,
 "download": {"s1": [{"id": 18125, "season": 1, "season_int": 1, "season_name": null,
                      "first_episode": 1, "last_episode": 7, "total_episode": 7,
                      "quality": "BluRay 1080p", "size": "782 MB", "encoder": "30nama", "note": null,
                      "persian_subtitle": true, "tags": [],
                      "link": [{"id": 1238218125375046, "episode": 1, "source": null,
                                "dl": "https://…/Breaking_Bad_S01E01_1080p_BluRay_6CH_30nama_30NAMA.mkv",
                                "mediainfo": "https://…", "persian_subtitle": "https://…"}]}],
              "s2": […]}}
```

`source` is the release the encode was made from (its audio, e.g. DTS, is not this file's).
`sinama.direct.extract()` handles both shapes: it walks the JSON, takes `season`/`quality`
from parent groups and `episode` from each link, and parses the file name for resolution,
HDR/DV, codec, source and audio (503 links for a 5-season show). Links are IP-signed URLs.
→ `Client.download(post_id, free=False)`, `Client.download_links(post_id)`.

### `subtitle`
`GET`/`POST {base}/action/subtitle/file/{id}` returns the subtitle as **plain text WebVTT**
(not enveloped). Stream items carry full URLs of this form (`…/action/subtitle/file/<base64 path>`); the library also converts SRT. → `Client.subtitle(url_or_file_id)`, `player.parse_cues(text)`

### `observer`
Report playback progress (the TV app sends it every 10 s and on close).

| Field | | |
|---|---|---|
| `post_id` | int | title |
| `file_id` | int | `hls[i].info.file_id` |
| `user_id` | int | from `user` |
| `time` | int | position, seconds |
| `duration` | int | seconds |
| `token` | string | `hls[i].options.token` |

Answers with an **empty body**: HTTP 200 with a token, HTTP 204 without one (anonymous reports
are ignored). Never retried. Behaviour measured live:

- Reports are applied **asynchronously**: the new position shows up in `stream.continue_watching`
  and in the `continue_watching` list after **80–120 s**.
- `success` does not mean "recorded yet". Identical, well-formed requests were sometimes applied
  within 2 minutes, sometimes only after more than 5 minutes, and some never showed up within
  the observation window (a jump of under 1% of the runtime, and reports sent soon after a
  dismiss). The rules are server-side and undocumented; don't rely on read-after-write.
- `progress` is computed from the server's own runtime; the `duration` you send is not used for it.
- An applied report for a title that isn't listed (re)adds it to the `continue_watching` list.
→ `Client.observer(post_id, file_id, time, duration, token="", user_id=None)`, `player.ProgressReporter`.

### `continue_watching`
Private. Titles in progress, most recent first: `{posts: [post + data], total, cache}` with
`data: {id, time, display_time, progress}` (`progress` is a string percent here, e.g. `"4.3253"`;
series entries also carry `season`, `episode`, `episode_title`). `data.id` is the post id.
→ `Client.continue_watching()`

### `continue_watching_dismiss`
Private. Field: `id` (post id). Hides a row of the list.

| Title state | Answer |
|---|---|
| in the list | `success: true`, `msg: "DISMISS_SUCCESS"`; the row disappears within ~60–80 s |
| not in the list (never watched, or already dismissed) | `success: false`, `msg: "DISMISS_FAILED"` |

Dismiss does **not** clear the title's resume point (`stream.continue_watching` keeps it), and a
later applied `observer` report re-adds the row. → `Client.continue_watching_dismiss(post_id)`
(raises `ApiError("DISMISS_FAILED")`)

---

## Library

### `user_mylist`
Private. Ids per list: `{watchlist: {post: [ids]}, favorite: {post: [ids], person: [ids]}, downloadlist: {post: [...]}, notify: {post: [...]}}` (favorites also track people). → `Client.my_lists()`

### `user_list`
Private. Two modes selected by the `action` *form field*:

| `action` | Fields | Effect |
|---|---|---|
| `list` | `group` (`watchlist`\|`favorite`\|…), `page`, `orderby=add_list`, `order=DESC` | [page](#page) of that list |
| `add` | `group`, `post_id` | **toggles** membership: a second call removes it (verified live; `user_mylist` reflects it immediately) |

→ `Client.user_list(group, page=1)`, `Client.user_list_toggle(group, post_id)`; the idempotent
`Client.library.add(group, id)` / `.remove(group, id)` check membership first.

---

## Notifications

### `notification`
Private. Field: `page`. Result `{notifications: [...], page, pages, total, total_unread, cache: {cache, cache_key, cache_time}}`. → `Client.notifications(page=1)`

### `notification_read`
Private. Field: `notification_id`. Not exercised with a real id (the account had no notifications). → `Client.notification_read(notification_id)` (raises on `success: false`)

---

## Shared objects

### Post
One shape everywhere (home rows, search, archive, lists, single; `single` adds the detail fields):

```json
{"id": 312361, "post_type": "title",
 "options": {"title_type": "series", "stream": true, "is_series": true, "persian_subtitle": true,
             "exclusive_subtitle": false, "coming_soon": false, "free_download": false, "free_stream": false},
 "info": {"seasons": 4, "year": 2021, "year_end": null, "budget": null, "age": "TV-MA",
          "time": {"default": 45, "others": []}},
 "release_dates": {"screen": null, "web": null, "bluray": null},
 "network": ["Netflix"],
 "title": {"english": "Lupin 2021", "local": null},
 "plot": {"english": "…", "local": "…"},
 "genre": [{"name": "Action", "slug": "action"}],
 "cast": [{"name": "Omar Sy", "as": "Assane Diop", "imdb": "nm1082477", "order": 0, "id": 148072, "image": {…}}],
 "crew": {"director": null, "creator": null, "writer": [{"name": "George Kay", "imdb": "nm0443047", "order": 0}]},
 "image": {"poster": {"preview": "<blurhash>", "webp": {"small", "medium", "large", "big"}, "jpg": {…}},
           "cover": {"webp": "https://cdn-world.hana-api.com/cover/…webp", "jpg": "…"}},
 "score": {"30nama": {"score": 7.39, "votes": 109, "top_100": null},
           "imdb": {"link": "https://www.imdb.com/title/tt2531336", "score": 7.5, "votes": 162820, "top_250": ""}},
 "country": [{"name": "France", "code": "FR", "order": 0}],
 "language": {"primary": {"name": "French", "code": "fr", "order": 0}, "others": null},
 "list": {"watchlist": 1405, "favorite": 1123},
 "air": {"air_status": "Season End", "air_data": " 4", "next_episode_caption": null, "next_episode_date": null}}
```

Helpers: `sinama.helpers.title/plot/poster/cover/imdb_id/is_series/is_streamable`.

### Page
`{"posts": [post, …], "page": 1, "pages": 457, "total": 10949}`. Iterate with `Client.iter_pages(method, *args, max_pages=None, **kwargs)`.

---

## Python library

```python
from sinama import Client, screens, player

c = Client()                       # token: $SINAMA_TOKEN, else ~/.sinama/session.json
c.qr_login(on_code=lambda code, url: print("approve", url))   # once; session is saved

hits = c.search("dune", stream_only=True)
post = c.single(hits["posts"][0]["id"])
st = c.stream(post["id"])
item = player.items(st)[0]
print(player.pick_url(item, max_height=1080))

c.library.add("watchlist", post["id"])
for p in c.iter_pages(c.archive, "drama", orderby="favorite", max_pages=3):
    print(p["id"], p["title"]["english"])
```

| Module | Mirrors (reference app) | Contents |
|---|---|---|
| `sinama/config.py` | `js/config.js` | hosts, keys, headers, timeouts, scheduler tuning, env var names |
| `sinama/api.py` | `js/api.js` | `Transport` (discovery, probing, HTTP, envelope), `Scheduler`, `check()` |
| `sinama/client.py` | `js/api.js` (actions) | `Client`: one method per action, session handling |
| `sinama/library.py` | `N.lib` in `js/api.js` | watchlist/favorites cache, idempotent add/remove |
| `sinama/direct.py` | `js/direct.js` | download link extraction and file-name parsing |
| `sinama/player.py` | `js/player.js` | items/seasons/resume, quality pick, markers, subtitles, `ProgressReporter` |
| `sinama/screens.py` | `js/screens.js` | composed Home / Details / Search / Browse / My list |
| `sinama/helpers.py` | `N.img/N.title/…` | post field helpers |
| `sinama/store.py` | `N.store` | JSON session file (`SessionStore`), `MemoryStore` |
| `sinama/errors.py` | | exception hierarchy |
| `sinama/app.py` | `js/app.js` | CLI entry point |

`Client(token=None, store=None, host=None, api_key=None, language="en", version="1.0.0", timeout=20, transport=None, persist=True)`.
`Client.call(name, **fields)` returns the raw envelope of any action and `Client.get(name, **fields)` its `result`.

Environment: `SINAMA_TOKEN` (session token), `SINAMA_SESSION_FILE` (default `~/.sinama/session.json`),
`SINAMA_HOST` (skip discovery), `site_30NAMA_email` / `site_30NAMA_password` (defaults for `login()`).

## CLI

```
python -m sinama qr-login                    # prints a URL to approve, saves the session
python -m sinama login --captcha <token>     # password login (needs a solved reCAPTCHA)
python -m sinama whoami | logout | test | plans | menu
python -m sinama home
python -m sinama search "the office" --stream-only --page 2
python -m sinama archive drama --sort favorite
python -m sinama single 8863 | stream 8863 | downloads 8863
python -m sinama mylist favorite | continue
python -m sinama --json call archive slugs=anime page=2 streamonly=true
```
