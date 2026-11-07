"""Portable rules for the private Windows pipe endpoint.

The endpoint module itself is Windows-only; only these rules are importable
everywhere, so the required inventory can enforce them on every runner.
"""

import pytest

from mesh_chat.core_api.pipe_policy import allowed_images, image_allowed, pipe_name


def test_only_the_product_pipe_namespace_is_accepted():
    assert pipe_name(r"\\.\pipe\mesh-chat-desktop-1").endswith("desktop-1")
    for value in (r"\\.\pipe\other", r"\\.\pipe\mesh-chat-", r"\\.\pipe\mesh-chat-Bad",
                  r"\\.\pipe\mesh-chat-" + "a" * 70, "mesh-chat-desktop", None, 7):
        with pytest.raises(ValueError):
            pipe_name(value)


def test_image_allowlist_requires_absolute_unique_paths():
    good = (r"C:\Program Files\Mesh Chat\mesh-chat.exe", r"D:\apps\mesh-chat.exe")
    assert allowed_images(good) == good
    for value in (r"mesh-chat.exe", ("relative.exe",), (), good + good,
                  tuple(rf"C:\app{index}.exe" for index in range(17)), "C:\\app.exe", [""]):
        with pytest.raises(ValueError):
            allowed_images(value)


def test_image_matching_is_exact_and_case_insensitive():
    images = allowed_images((r"C:\Program Files\Mesh Chat\mesh-chat.exe",))
    assert image_allowed(r"c:\program files\mesh chat\MESH-CHAT.EXE", images)
    assert not image_allowed(r"C:\Program Files\Mesh Chat\mesh-chat.exe.bak", images)
    assert not image_allowed(r"C:\Program Files\Mesh Chat\python.exe", images)
    assert not image_allowed("", images)
    assert not image_allowed(None, images)

