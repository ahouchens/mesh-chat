import json
import threading
import time
from unittest.mock import Mock

import pytest

from mesh_chat import link_previews as previews
from mesh_chat.errors import ValidationError


@pytest.mark.parametrize("provider,identifier", [
    ("website", "https://127.0.0.1"), ("x", "20/../../secret"),
    ("youtube", "short"), ("youtube", "aqz-KE-bpKQ?"), ([], "20"), ("x", 20),
])
def test_only_known_providers_and_strict_ids(provider, identifier, monkeypatch):
    fetch = Mock()
    monkeypatch.setattr(previews, "fetch_preview", fetch)
    with pytest.raises(ValidationError):
        previews.LinkPreviews().get(provider, identifier)
    fetch.assert_not_called()


def test_x_fallback_is_text_without_provider_html_or_script(monkeypatch):
    body = {"author_name": "An author", "html": '<blockquote><p>Hello &amp; world<br><a href="javascript:bad()">a link</a><script>bad()</script></p>— date</blockquote>'}
    fetch = Mock(return_value=json.dumps(body).encode())
    monkeypatch.setattr(previews, "_get", fetch)
    card = previews.fetch_preview("x", "20")
    assert card == {"status": "ready", "title": "", "author": "An author",
                    "text": "Hello & world\na link", "image": None}
    assert fetch.call_args.args[0].startswith("https://publish.x.com/oembed?")
    assert "omit_script=true" in fetch.call_args.args[0]
    assert "url=https%3A%2F%2Fx.com%2Fi%2Fstatus%2F20" in fetch.call_args.args[0]


def test_youtube_ignores_response_urls_and_fetches_only_fixed_thumbnail(monkeypatch):
    fetch = Mock(side_effect=[json.dumps({"title": "Film", "author_name": "Studio",
        "thumbnail_url": "http://127.0.0.1/secret", "html": "<script>bad()</script>"}).encode(), b"\xff\xd8\xfftest"])
    monkeypatch.setattr(previews, "_get", fetch)
    card = previews.fetch_preview("youtube", "aqz-KE-bpKQ")
    assert card["title"] == "Film"
    assert card["image"].startswith("data:image/jpeg;base64,")
    assert fetch.call_args.args == ("https://i.ytimg.com/vi/aqz-KE-bpKQ/hqdefault.jpg", 300 * 1024)
    assert "html" not in card


@pytest.mark.parametrize("image", [b"<svg onload=bad()>", OSError("offline")])
def test_thumbnail_failure_preserves_metadata(monkeypatch, image):
    monkeypatch.setattr(previews, "_get", Mock(side_effect=[b'{"title":"Film"}', image]))
    card = previews.fetch_preview("youtube", "aqz-KE-bpKQ")
    assert card["title"] == "Film"
    assert card["image"] is None


def test_http_response_bounded_and_redirects_disabled(monkeypatch):
    response = Mock(status=200)
    response.read.return_value = b"12345"
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    opener = Mock()
    opener.open.return_value = response
    build = Mock(return_value=opener)
    monkeypatch.setattr(previews.urllib.request, "build_opener", build)
    with pytest.raises(ValueError, match="too large"):
        previews._get("https://www.youtube.com/oembed", 4)
    assert isinstance(build.call_args.args[0], previews._NoRedirect)
    assert build.call_args.args[0].redirect_request(None, None, 302, None, None, "http://127.0.0.1") is None
    response.read.assert_called_once_with(5)
    assert opener.open.call_args.kwargs["timeout"] == 3


def test_fetches_are_nonblocking_coalesced_and_bounded(monkeypatch):
    release = threading.Event()
    started = threading.Event()
    def fetch(*args):
        started.set()
        assert release.wait(3)
        return {"status": "ready", "title": "Film"}
    fetch_mock = Mock(side_effect=fetch)
    monkeypatch.setattr(previews, "fetch_preview", fetch_mock)
    cards = previews.LinkPreviews()
    try:
        assert cards.get("x", "20") == {"status": "loading"}
        assert started.wait(1)
        assert cards.get("x", "20") == {"status": "loading"}
        cards.get("x", "21")
        cards.get("x", "22")
        assert len(cards._active) == 2
    finally:
        release.set()
    deadline = time.monotonic() + 2
    while cards._active and time.monotonic() < deadline:
        time.sleep(.005)
    assert cards.get("x", "20")["status"] == "ready"
    assert fetch_mock.call_count == 2
    assert len(cards._cache) == 2


def test_failed_fetch_redacts_provider_error_and_allows_retry(monkeypatch):
    monkeypatch.setattr(previews, "fetch_preview", Mock(side_effect=ValueError("private provider response")))
    cards = previews.LinkPreviews()
    cards._fetch(("x", "20"))
    assert cards.get("x", "20") == {"status": "unavailable"}
    assert cards._cache[("x", "20")][0] <= time.monotonic() + 15


def test_mobile_and_desktop_dispatch_preview_without_persisting_payload(tmp_path, monkeypatch):
    import RNS
    from mesh_chat import mobile_bridge
    from test_workspace_service import _service
    service, _ = _service(tmp_path, RNS.Identity(), "Preview test")
    try:
        monkeypatch.setattr(service._link_previews, "get", Mock(return_value={"status": "loading"}))
        monkeypatch.setattr(mobile_bridge, "_service", service)
        request = {"command": "link_preview", "payload": {"provider": "x", "identifier": "20"}}
        mobile = json.loads(mobile_bridge.command(json.dumps(request)))
        desktop, _ = service.dispatch({"v": 1, "id": "preview-test", **request})
        assert mobile == desktop == {"ok": True, "result": {"status": "loading"}}
        assert service.store.command_response("preview-test") is None
    finally:
        service.close()
