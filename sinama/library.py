"""Watchlist / favorites with a membership cache (the TV app's `N.lib`).

`user_list action=add` toggles on the server, so add()/remove() check the cached
membership first and only call the API when the state actually has to change.
"""
import threading


class Library:
    def __init__(self, client):
        self.client = client
        self._data = None
        self._lock = threading.Lock()

    def clear(self):
        self._data = None

    def refresh(self):
        raw = self.client.my_lists() or {}
        data = {}
        for group, v in raw.items():
            ids = v.get("post") if isinstance(v, dict) else v
            data[group] = {str(i) for i in ids} if isinstance(ids, list) else set()
        self._data = data
        return data

    def ready(self):
        if self._data is None:
            self.refresh()
        return self._data

    def has(self, group, post_id):
        return str(post_id) in self.ready().get(group, set())

    def ids(self, group):
        return sorted(self.ready().get(group, set()), key=lambda x: int(x) if x.isdigit() else 0)

    def toggle(self, group, post_id):
        """Flip membership. Returns True if the title is now in the list."""
        with self._lock:
            members = self.ready().setdefault(group, set())
            key = str(post_id)
            was = key in members
            env = self.client.user_list_toggle(group, post_id)
            if not env.get("success"):
                from .api import check
                check("user_list", env)
            if was:
                members.discard(key)
            else:
                members.add(key)
            return not was

    def add(self, group, post_id):
        """Idempotent add. Returns True if a server call was made."""
        if self.has(group, post_id):
            return False
        self.toggle(group, post_id)
        return True

    def remove(self, group, post_id):
        """Idempotent remove. Returns True if a server call was made."""
        if not self.has(group, post_id):
            return False
        self.toggle(group, post_id)
        return True

    def list(self, group="watchlist", page=1):
        return self.client.user_list(group, page=page)
