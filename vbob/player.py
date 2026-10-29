from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .errors import PlaybackError
from .paths import canonical_path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlayerInfo:
    name: str
    path: str
    source: str


def _candidates() -> list[tuple[str, str, str]]:
    """(name, path, source) candidates in preference order."""
    items: list[tuple[str, str, str]] = []
    if sys.platform == "win32":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        for name, executable in (("mpv", "mpv"), ("vlc", "vlc")):
            found = shutil.which(executable)
            if found:
                items.append((name, found, "path"))
        for path in (
            os.path.join(pf, "mpv", "mpv.exe"),
            os.path.join(local, "Programs", "mpv", "mpv.exe"),
            os.path.join(pf, "mpv.net", "mpvnet.exe"),
        ):
            items.append(("mpv", path, "common_dir"))
        for path in (
            os.path.join(pf, "VideoLAN", "VLC", "vlc.exe"),
            os.path.join(pf86, "VideoLAN", "VLC", "vlc.exe"),
        ):
            items.append(("vlc", path, "common_dir"))
        for path in (
            os.path.join(pf, "DAUM", "PotPlayer", "PotPlayerMini64.exe"),
            os.path.join(pf, "DAUM", "PotPlayer", "PotPlayerMini.exe"),
            os.path.join(pf86, "DAUM", "PotPlayer", "PotPlayerMini64.exe"),
            os.path.join(pf86, "DAUM", "PotPlayer", "PotPlayerMini.exe"),
        ):
            items.append(("potplayer", path, "common_dir"))
    elif sys.platform == "darwin":
        for name, executable in (("mpv", "mpv"), ("vlc", "vlc")):
            found = shutil.which(executable)
            if found:
                items.append((name, found, "path"))
        items.extend(
            [
                ("mpv", "/Applications/mpv.app/Contents/MacOS/mpv", "common_dir"),
                ("vlc", "/Applications/VLC.app/Contents/MacOS/VLC", "common_dir"),
            ]
        )
    else:
        for name in ("mpv", "vlc", "celluloid"):
            found = shutil.which(name)
            if found:
                items.append((name, found, "path"))
    return items


def detect_players() -> list[PlayerInfo]:
    result: list[PlayerInfo] = []
    seen: set[str] = set()
    for name, path, source in _candidates():
        if not path:
            continue
        resolved = canonical_path(path)
        key = os.path.normcase(resolved)
        if key in seen or not Path(resolved).is_file():
            continue
        seen.add(key)
        result.append(PlayerInfo(name=name, path=resolved, source=source))
    return result


def players_payload() -> list[dict[str, str]]:
    return [asdict(player) for player in detect_players()]


def resolve_player(
    settings: dict[str, Any], requested: str | None = None
) -> dict[str, Any]:
    configured = settings["playback"].get("player")
    requested_name = requested.casefold() if requested else None
    detected = detect_players()

    if requested_name:
        if configured and configured["name"].casefold() == requested_name:
            return {**configured, "source": "settings"}
        for player in detected:
            if player.name.casefold() == requested_name:
                return {
                    "name": player.name,
                    "path": player.path,
                    "args": [],
                    "source": player.source,
                }
        raise PlaybackError(f"未找到播放器: {requested}", code="player_not_found")

    if configured:
        return {**configured, "source": "settings"}
    if detected:
        player = detected[0]
        return {
            "name": player.name,
            "path": player.path,
            "args": [],
            "source": player.source,
        }
    raise PlaybackError("未找到可用的播放器，请在设置中指定", code="no_player")


def _seek_value(seek: float) -> str:
    return str(int(seek)) if float(seek).is_integer() else str(seek)


def build_args(player: dict[str, Any], video_path: str, seek: float | None = None) -> list[str]:
    template = [str(arg) for arg in player.get("args") or []]
    seek_text = _seek_value(seek) if seek is not None else ""
    if template:
        args = [
            arg.replace("{path}", video_path).replace("{seek}", seek_text)
            for arg in template
        ]
        if not any("{path}" in arg for arg in template):
            args.append(video_path)
        return args

    args: list[str] = []
    name = str(player.get("name", "")).casefold()
    if seek is not None:
        if name == "mpv":
            args.append(f"--start={seek_text}")
        elif name == "vlc":
            args.append(f"--start-time={seek_text}")
    args.append(video_path)
    return args


def launch(player: dict[str, Any], video_path: str, seek: float | None = None) -> int:
    executable = canonical_path(player["path"])
    if not Path(executable).is_file():
        raise PlaybackError(f"播放器不存在: {executable}", code="player_not_found")
    args = build_args(player, video_path, seek)
    try:
        process = subprocess.Popen(
            [executable, *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=sys.platform != "win32",
        )
    except OSError as exc:
        log.exception("failed to launch %s", executable)
        raise PlaybackError(f"启动播放器失败: {exc}", code="player_not_found") from exc
    return int(process.pid)
