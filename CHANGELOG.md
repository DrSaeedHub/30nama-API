# Changelog

Versions follow `MAJOR.MINOR.PATCH`; each release is tagged `vX.Y.Z`, and that tag is what you install from
(`pip install "sinama @ git+https://github.com/DrSaeedHub/30nama-API.git@v1.2.0"`).

## Unreleased

- README completed: installing from a tag, the command line, the errors, the configuration, what `Client` covers.
- LICENSE (MIT) and this changelog; package metadata (authors, links, keywords, classifiers).

## 1.2.0 — 2026-10-27

Cloudflare's bot challenge as its own outcome.

- `ChallengeRequired`, a subclass of `Blocked` (so `except Blocked` still catches it): Cloudflare answered with its
  challenge instead of the API, and a person has to confirm it on this network. Carries `host`, and is never retried.
- `is_challenge(status, headers, body_head)`: the one test for it (`cf-mitigated: challenge`, or a 403/429/503 from
  `Server: cloudflare` whose first 8 KB hold the challenge page). Used for every action, raw text answers, subtitle
  URLs and the website API; exported for an app's own responses.
- A host that answers with the challenge is no longer a dead host: another host that answers is still taken, and when
  none can be used `init()` raises `ChallengeRequired` instead of a vague `NoEndpoint`.

## 1.1.0 — 2026-10-26

A second probe for the host, the network and the session from outside.

- `Transport.init()` asks a host that refuses `test` once more with `menu`; `NoEndpoint` says why each host failed.
- `HttpxSession`: requests' shape over an httpx client or an app's own sender. `tls_context()`: the TLS context
  requests uses, since Cloudflare challenges Python's default TLS greeting.
- A `Store` interface (`load`, `save`, `update`, `clear`) with `SessionStore`, `MemoryStore` and `CallbackStore`.
- `SINAMA_PROXY` sends the default session through a proxy; live tests run only with it (or `SINAMA_LIVE_DIRECT=1`).
- Follows API changes: `observer` answers 204 with a token too; `stream.continue_watching` lost `display_time`.

## 1.0.0 — 2026-10-23

- `Client` for the hana-api v2 RPC API (the TV apps' API) and `WebClient` for the website's API, with QR login,
  saved sessions, host discovery, retries and rate limiting; the `sinama` command line; docs/API.md.
