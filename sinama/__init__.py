"""sinama: unofficial Python client for the 30nama hana-api v2 RPC API."""
from . import config, direct, helpers, player, screens
from .api import Scheduler, Transport
from .client import Client
from .errors import (
    ApiError,
    Blocked,
    CaptchaRequired,
    LoginRequired,
    NoEndpoint,
    NotFound,
    QRCodeExpired,
    RateLimited,
    SinamaError,
    TransportError,
)
from .library import Library
from .store import MemoryStore, SessionStore

__version__ = "1.0.0"
__all__ = [
    "Client", "Transport", "Scheduler", "Library", "SessionStore", "MemoryStore",
    "SinamaError", "TransportError", "RateLimited", "Blocked", "NoEndpoint", "ApiError",
    "LoginRequired", "NotFound", "CaptchaRequired", "QRCodeExpired",
    "config", "direct", "helpers", "player", "screens",
]
