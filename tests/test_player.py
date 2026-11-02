from __future__ import annotations

import pytest

from vbob.errors import PlaybackError
from vbob.player import (
    _pick_with_windows_dialog,
    build_args,
    player_name_for_path,
)


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


def test_player_name_inference() -> None:
    assert player_name_for_path(r"C:\Program Files\mpv\mpv.exe") == "mpv"
    assert player_name_for_path(r"D:\Tools\PotPlayerMini64.exe") == "potplayer"
    assert player_name_for_path("/usr/bin/vlc") == "vlc"
    assert player_name_for_path(r"C:\Apps\MyPlayer.exe") == "myplayer"


class _Completed:
    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def test_windows_picker_returns_selected_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "vbob.player.subprocess.run",
        lambda *args, **kwargs: _Completed(r"C:\Tools\mpv\mpv.exe" + "\n"),
    )
    assert _pick_with_windows_dialog() == r"C:\Tools\mpv\mpv.exe"


def test_windows_picker_cancel_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "vbob.player.subprocess.run", lambda *args, **kwargs: _Completed("")
    )
    assert _pick_with_windows_dialog() is None


def test_windows_picker_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "vbob.player.subprocess.run",
        lambda *args, **kwargs: _Completed("", returncode=1, stderr="boom"),
    )
    with pytest.raises(PlaybackError) as excinfo:
        _pick_with_windows_dialog()
    assert excinfo.value.code == "picker_failed"
