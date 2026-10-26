"""Constants: hosts, client keys, headers, timeouts and scheduler tuning.

Mirrors tizen-app/js/config.js of the reference TV client. None of the keys are
secrets: they ship inside every official 30nama client and identify the platform,
not the user.
"""
import os

# Endpoint discovery: JSON lists of {location, host}. First one that answers wins.
DISCOVERY_URLS = [
    "https://pub-ac69cf865ce145f8b4c1ed87dc2a9fb7.r2.dev/sdk-endpoint.json",
    "https://30update.s3.ir-thr-at1.arvanstorage.ir/sdk-endpoint.json",
    # third source used by the official SDK bundled in 30nama.com
    "https://raw.githubusercontent.com/EternalC0der/30nama/main/sdk-endpoint.json",
]
FALLBACK_HOSTS = [
    {"location": "WORLD", "host": "https://world.hana-api.com/api/v2"},
    {"location": "IR", "host": "https://ir.kazem-api.com/api/v2"},
]

# Per-platform client keys (c-api-key). WEBTV is what the reference app verified live.
PLATFORM_KEYS = {
    "WEBTV": "83hRzBabjDnuv9SmV2GFaftpxjhZSHXYe7UnBuX5DdANdpzPvXu46jvKZHPb97As",
    "ANDROIDTV": "VdapnkLG9EHsSmF8yeKcb4253RAuN6YX",
}
API_KEYS = [PLATFORM_KEYS["WEBTV"], PLATFORM_KEYS["ANDROIDTV"]]

VERSION_NUMBER = "1.0.0"  # c-version-number
LANGUAGE = "en"  # c-language: "en" or "fa"
USER_AGENT = (
    "Mozilla/5.0 (SMART-TV; Linux; Tizen 6.5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) 85.0.4183.93/6.5 TV Safari/537.36"
)

QR_BASE = "https://30nama.com/auth/"
QR_POLL_SECONDS = 5
QR_TTL_SECONDS = 600  # measured live: a code answers "Code Expired" after ~10 minutes
HEARTBEAT_SECONDS = 10  # observer progress report interval used by the TV app

TIMEOUT = 20  # seconds per request
DISCOVERY_TIMEOUT = 6
PROBE_TIMEOUT = 8

# Scheduler: 30nama sits behind Cloudflare rate limiting (HTTP 429 / "error code: 1015").
MAX_IN_FLIGHT = 2
MIN_GAP_SECONDS = 0.1
BACKOFF_SECONDS = [1.0, 3.0]
MAX_RETRY_AFTER = 10.0
# Never retried: side effects or polling where a retry would do harm.
NO_RETRY = {"observer", "logout", "qrlogin_login", "qrlogin_auth", "login", "otp", "otp_verify", "register",
            "user_list", "voucher", "shaparak", "paypal"}

# Environment variables.
ENV_TOKEN = "SINAMA_TOKEN"
ENV_SESSION_FILE = "SINAMA_SESSION_FILE"
ENV_HOST = "SINAMA_HOST"
ENV_EMAIL = "SITE_30NAMA_EMAIL"
ENV_PASSWORD = "SITE_30NAMA_PASSWORD"

DEFAULT_SESSION_FILE = os.path.join(os.path.expanduser("~"), ".sinama", "session.json")

# Website API (interface.30nama.com/api/v1), from the 30nama.com bundle. Separate sessions.
WEB_HOST = "https://interface.30nama.com/api/v1"
WEB_API_KEY = "YygufGCvFgYR3g9sjD92Ct5ZSx7SJs4JXpuCeTS24nWAszaL4u3qCDZRULpejmzF"
WEB_APP_VERSION = "2.0.0"
WEB_PLATFORM = "Website"
WEB_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
# Measured: ~30 requests in under a minute earned a ~4 minute Cloudflare block on this host.
WEB_MIN_GAP_SECONDS = 2.5
ENV_WEB_TOKEN = "SINAMA_WEB_TOKEN"
ENV_WEB_SESSION_FILE = "SINAMA_WEB_SESSION_FILE"
DEFAULT_WEB_SESSION_FILE = os.path.join(os.path.expanduser("~"), ".sinama", "web-session.json")
