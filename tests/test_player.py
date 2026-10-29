from __future__ import annotations

from vbob.player import build_args


def test_mpv_seek_argument() -> None:
    args = build_args({"name": "mpv", "args": []}, "/media/a.mp4", 90)
    assert args == ["--start=90", "/media/a.mp4"]


def test_vlc_seek_argument() -> None:
    args = build_args({"name": "vlc", "args": []}, "/media/a.mp4", 90.5)
    assert args == ["--start-time=90.5", "/media/a.mp4"]


def test_custom_args_template() -> None:
    player = {"name": "mpv", "args": ["--fullscreen", "--start={seek}", "{path}"]}
    assert build_args(player, "/media/a.mp4", 30) == [
        "--fullscreen",
        "--start=30",
        "/media/a.mp4",
    ]


def test_template_without_path_placeholder_appends_path() -> None:
    player = {"name": "potplayer", "args": ["/fullscreen"]}
    assert build_args(player, "/media/a.mp4") == ["/fullscreen", "/media/a.mp4"]
