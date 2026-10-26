"""Where a client keeps its session (the TV app's `N.store` / `n30.session`): {"token", "user", "host"}.

`Store` is the interface: load, save, update, clear. `SessionStore` keeps it in a JSON file (the default),
`MemoryStore` nowhere, and `CallbackStore` wherever an app keeps its secrets (an encrypted settings table):

    Client(store=CallbackStore(load=lambda: vault.get("30nama") or {}, save=lambda d: vault.put("30nama", d)))

The session holds the token (and `user` repeats it as user_session): treat everything saved as a secret.
"""
import json
import os

from . import config as C


class Store:
    """The session store interface. Subclasses implement load() and save(); update() and clear() follow."""

    def load(self):
        """The saved session, {} when there is none."""
        return {}

    def save(self, data):
        raise NotImplementedError

    def update(self, **fields):
        data = self.load()
        data.update({k: v for k, v in fields.items() if v is not None})
        self.save(data)
        return data

    def clear(self):
        self.save({})


class SessionStore(Store):
    """A JSON file: ~/.sinama/session.json, or $SINAMA_SESSION_FILE, or the path given."""

    def __init__(self, path=None):
        self.path = path or os.environ.get(C.ENV_SESSION_FILE) or C.DEFAULT_SESSION_FILE

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, data):
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def clear(self):
        try:
            os.remove(self.path)
        except OSError:
            pass


class MemoryStore(Store):
    """Non-persistent store (tests, one-off scripts)."""

    def __init__(self, data=None):
        self.path = None
        self._data = dict(data or {})

    def load(self):
        return dict(self._data)

    def save(self, data):
        self._data = dict(data)

    def clear(self):
        self._data = {}


class CallbackStore(Store):
    """The session kept by the app: load() -> dict, save(dict), and optionally clear() (default: save({}))."""

    def __init__(self, load, save, clear=None):
        self.path = None
        self._load, self._save, self._clear = load, save, clear

    def load(self):
        data = self._load()
        return dict(data) if isinstance(data, dict) else {}

    def save(self, data):
        self._save(dict(data))

    def clear(self):
        if self._clear is not None:
            self._clear()
        else:
            self._save({})
