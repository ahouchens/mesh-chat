"""Opt-in provider cards. Network work never holds the messaging dispatch lock."""
from __future__ import annotations

import base64
import json
import re
import ssl
import threading
import time
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlencode

import certifi

from .errors import ValidationError


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _get(url: str, maximum: int) -> bytes:
    # All URLs are constructed here from validated IDs, never from response HTML
    # or thumbnail_url. Redirects cannot turn this into an arbitrary URL fetcher.
    opener = urllib.request.build_opener(
        _NoRedirect(), urllib.request.HTTPSHandler(
            context=ssl.create_default_context(cafile=certifi.where())))
    request = urllib.request.Request(url, headers={"User-Agent": "MeshChat-LinkPreview/1"})
    with opener.open(request, timeout=3) as response:
        if response.status != 200:
            raise ValueError("Preview unavailable")
        body = response.read(maximum + 1)
    if len(body) > maximum:
        raise ValueError("Preview too large")
    return body


class _PostText(HTMLParser):
    """Extract fallback paragraph text; never send provider HTML to the renderer."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraph = False
        self.blocked = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.blocked += 1
        if tag == "p":
            self.paragraph = True
        if tag == "br" and self.paragraph and not self.blocked:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.blocked = max(0, self.blocked - 1)
        if tag == "p":
            self.paragraph = False
            self.parts.append("\n")

    def handle_data(self, data):
        if self.paragraph and not self.blocked:
            self.parts.append(data)


def _text(value, limit=500):
    return value[:limit].strip() if isinstance(value, str) else ""


def fetch_preview(provider: str, identifier: str) -> dict:
    if provider == "youtube":
        endpoint = "https://www.youtube.com/oembed?" + urlencode({
            "url": f"https://www.youtube.com/watch?v={identifier}", "format": "json"})
    else:
        endpoint = "https://publish.x.com/oembed?" + urlencode({
            "url": f"https://x.com/i/status/{identifier}", "omit_script": "true", "dnt": "true"})
    payload = json.loads(_get(endpoint, 64 * 1024))
    if not isinstance(payload, dict):
        raise ValueError("Invalid preview")
    result = {"status": "ready", "title": _text(payload.get("title")),
              "author": _text(payload.get("author_name")), "text": "", "image": None}
    if provider == "x":
        parser = _PostText()
        parser.feed(_text(payload.get("html"), 64 * 1024))
        result["text"] = "".join(parser.parts).strip()[:5000]
        if not result["text"]:
            raise ValueError("Post text unavailable")
    else:
        if not result["title"]:
            raise ValueError("Video title unavailable")
        try:
            image = _get(f"https://i.ytimg.com/vi/{identifier}/hqdefault.jpg", 300 * 1024)
            if image.startswith(b"\xff\xd8\xff"):
                result["image"] = "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii")
        except Exception:
            pass  # A missing thumbnail must not discard the title and author.
    return result


class LinkPreviews:
    def __init__(self):
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, str], tuple[float, dict]] = {}
        self._active: set[tuple[str, str]] = set()

    def get(self, provider, identifier):
        pattern = {"youtube": r"[A-Za-z0-9_-]{11}", "x": r"[0-9]{1,20}"}.get(provider) if isinstance(provider, str) else None
        if not pattern or not isinstance(identifier, str) or not re.fullmatch(pattern, identifier):
            raise ValidationError("Invalid preview identifier")
        key = (provider, identifier)
        with self._lock:
            now = time.monotonic()
            self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
            if key in self._cache:
                return dict(self._cache[key][1])
            if key not in self._active and len(self._active) < 2:
                self._active.add(key)
                threading.Thread(target=self._fetch, args=(key,), daemon=True,
                                 name="link-preview").start()
        return {"status": "loading"}

    def _fetch(self, key):
        try:
            result = fetch_preview(*key)
        except Exception:
            # No private URLs, post text, or provider responses in errors/logs.
            result = {"status": "unavailable"}
        with self._lock:
            self._active.discard(key)
            while len(self._cache) >= 32:
                self._cache.pop(next(iter(self._cache)))
            ttl = 300 if result["status"] == "ready" else 15
            self._cache[key] = (time.monotonic() + ttl, result)
