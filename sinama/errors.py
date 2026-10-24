"""Exception hierarchy. Every server-side rejection carries the raw envelope."""


class SinamaError(Exception):
    """Base class for everything this library raises."""


class TransportError(SinamaError):
    """Network failure, timeout, or a response that is not JSON (Cloudflare page, 5xx).

    `retry` tells the scheduler the failure is transient.
    """

    def __init__(self, message, status=None, retry=True, retry_after=0.0, body=None):
        super().__init__(message)
        self.status = status
        self.retry = retry
        self.retry_after = retry_after
        self.body = body


class RateLimited(TransportError):
    """HTTP 429 or Cloudflare "error code: 1015"."""


class Blocked(TransportError):
    """Cloudflare challenge page or a REQUESTBLOCK / APIMAINTENANCE guard. Not retried."""

    def __init__(self, message, status=None, body=None):
        super().__init__(message, status=status, retry=False, body=body)


class NoEndpoint(SinamaError):
    """No discovered host answered the `test` action with any client key."""


class ApiError(SinamaError):
    """The API answered with `success: false`."""

    def __init__(self, message, status=None, envelope=None, action=None):
        super().__init__(message)
        self.msg = message
        self.status = status
        self.envelope = envelope or {}
        self.action = action  # the API action name that failed

    @property
    def hint(self):
        """The envelope's `action` field (e.g. ["retry"]), the server's hint to the client."""
        return self.envelope.get("action")


class LoginRequired(ApiError):
    """msg "Login Required": the action needs a session token, or the token expired."""


class NotFound(ApiError):
    """Unknown action (HTTP 404), missing post, unknown slug."""


class CaptchaRequired(ApiError):
    """reCAPTCHA failed or missing (msg "invalid-input-response"). Solve it in a browser."""


class QRCodeExpired(ApiError):
    """qrlogin_login answered "Code Expired" or "Wrong Code"."""
