"""Session persistence (the TV app's `N.store` / `n30.session`), as a JSON file.

Shape on disk: {"token": "...", "user": {...}, "host": "https://..."}.
"""
import json
import os

from . import config as C


class SessionStore:
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

    def update(self, **fields):
        data = self.load()
        data.update({k: v for k, v in fields.items() if v is not None})
        self.save(data)
        return data

    def clear(self):
        try:
            os.remove(self.path)
        except OSError:
            pass


class MemoryStore(SessionStore):
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
