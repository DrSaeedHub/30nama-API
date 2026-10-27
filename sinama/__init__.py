"""sinama: unofficial Python client for the 30nama hana-api v2 RPC API."""
from . import config, direct, helpers, player, screens
from .api import Scheduler, Transport, default_session, is_challenge
from .client import Client
from .errors import (
    ApiError,
    Blocked,
    CaptchaRequired,
    ChallengeRequired,
    LoginRequired,
    NoEndpoint,
    NotFound,
    QRCodeExpired,
    RateLimited,
    SinamaError,
    TransportError,
)
from .library import Library
from .session import HttpxSession, tls_context
from .store import CallbackStore, MemoryStore, SessionStore, Store
from .web import WebClient, WebTransport

__version__ = "1.2.0"
__all__ = [
    "Client", "WebClient", "Transport", "WebTransport", "Scheduler", "Library", "Store", "SessionStore", "MemoryStore",
    "CallbackStore", "HttpxSession", "tls_context", "default_session", "is_challenge",
    "SinamaError", "TransportError", "RateLimited", "Blocked", "ChallengeRequired", "NoEndpoint", "ApiError",
    "LoginRequired", "NotFound", "CaptchaRequired", "QRCodeExpired",
    "config", "direct", "helpers", "player", "screens",
]
