# sinama: Python client for the 30nama API

Unofficial, single-package (monolithic) Python library for the hana-api v2 RPC API that the
official 30nama TV clients use. Its module layout mirrors
[msharifi99/30nama-tizenos](https://github.com/msharifi99/30nama-tizenos)'s `tizen-app/js/`.

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
`site_30NAMA_email` / `site_30NAMA_password` from the environment.

## Use

```python
from sinama import Client, player

c = Client()
for p in c.search("dune", stream_only=True)["posts"]:
    print(p["id"], p["title"]["english"])

st = c.stream(8863)
print(player.pick_url(player.items(st)[0], max_height=1080))
```

Every action, its fields, responses and errors: [docs/API.md](docs/API.md).

## Layout

```
sinama/       the library (config, api, client, library, direct, player, screens, helpers, store, errors, app)
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

Logged-in tests leave the account as they found it: list toggles are reverted, the progress
report re-sends an existing resume point unchanged, and dismiss targets a title that isn't in
continue watching. `logout` is only tested with `SINAMA_TEST_LOGOUT=1` because it ends the
session.

## License

MIT
