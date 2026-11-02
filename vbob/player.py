"""外部播放器探测与启动。

按平台扫描 PATH 及常见安装目录，解析用户指定/已配置的播放器，
并拼装参数后以独立子进程启动，不阻塞服务。
"""

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
    """探测到的播放器。

    属性:
        name: 播放器标识（mpv/vlc/potplayer 等）。
        path: 规范化后的可执行文件路径。
        source: 来源标记，``path`` 表示来自 PATH，``common_dir`` 表示常见安装目录。
    """

    name: str
    path: str
    source: str


def _candidates() -> list[tuple[str, str, str]]:
    """按偏好顺序返回 ``(name, path, source)`` 候选，可能包含不存在的路径。"""
    items: list[tuple[str, str, str]] = []
    # Windows：先查 PATH（通常代表用户自行安装的版本），再补常见安装目录。
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
        # macOS 应用包内的可执行文件通常不在 PATH 中，需要显式补充。
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
    """探测当前系统上实际存在的播放器。

    候选路径会先规范化，再按平台大小写规则去重，只保留真实文件。
    """
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
    """返回可直接序列化为 JSON 的播放器列表。"""
    return [asdict(player) for player in detect_players()]


def player_name_for_path(path: str) -> str:
    """根据可执行文件名推断播放器标识，用于内置的 seek 参数匹配。"""
    stem = Path(path).stem.casefold()
    if "potplayer" in stem:
        return "potplayer"
    if "mpv" in stem:
        return "mpv"
    if "vlc" in stem:
        return "vlc"
    return stem or "custom"


_WINDOWS_PICK_SCRIPT = (
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8;"
    "Add-Type -AssemblyName System.Windows.Forms;"
    "$dialog = New-Object System.Windows.Forms.OpenFileDialog;"
    "$dialog.Title = '选择播放器';"
    "$dialog.Filter = '可执行文件 (*.exe)|*.exe|所有文件 (*.*)|*.*';"
    "$dialog.CheckFileExists = $true;"
    "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK)"
    "{[Console]::Write($dialog.FileName)}"
)


def _pick_with_windows_dialog() -> str | None:
    """通过 PowerShell 打开 Windows 原生文件选择框。

    后端和浏览器运行在同一台机器上，因此由后端弹出对话框才能拿到完整路径；
    浏览器 file input 出于安全限制不会暴露本地真实路径。
    """
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", _WINDOWS_PICK_SCRIPT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            # 避免在服务端弹出额外的 PowerShell 控制台窗口。
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.exception("failed to open player file dialog")
        raise PlaybackError("无法打开文件选择框", code="picker_failed") from exc
    if completed.returncode != 0:
        log.warning("player file dialog failed: %s", completed.stderr)
        raise PlaybackError("无法打开文件选择框", code="picker_failed")
    path = completed.stdout.strip()
    return path or None


def _pick_with_macos_dialog() -> str | None:
    """通过 osascript 打开 macOS 原生文件选择框。"""
    script = 'POSIX path of (choose file with prompt "选择播放器")'
    try:
        completed = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.exception("failed to open player file dialog")
        raise PlaybackError("无法打开文件选择框", code="picker_failed") from exc
    if completed.returncode != 0:
        # 用户取消时 osascript 返回非 0，状态码 1 视为取消而不是错误。
        if "User canceled" in (completed.stderr or ""):
            return None
        raise PlaybackError("无法打开文件选择框", code="picker_failed")
    path = completed.stdout.strip()
    return path or None


def _pick_with_linux_dialog() -> str | None:
    """优先使用 zenity/kdialog；两者都没有时提示手动填写路径。"""
    commands = [
        ["zenity", "--file-selection", "--title=选择播放器"],
        ["kdialog", "--getopenfilename", ".", "*"],
    ]
    for command in commands:
        if shutil.which(command[0]) is None:
            continue
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if completed.returncode == 0:
            path = completed.stdout.strip()
            return path or None
        # 用户取消同样返回非 0，继续尝试下一个工具没有意义。
        return None
    raise PlaybackError(
        "当前系统没有可用的文件选择框，请手动填写播放器路径",
        code="picker_unsupported",
    )


def pick_executable() -> str | None:
    """打开系统文件选择框并返回选中的可执行文件路径；取消返回 None。"""
    if sys.platform == "win32":
        return _pick_with_windows_dialog()
    if sys.platform == "darwin":
        return _pick_with_macos_dialog()
    return _pick_with_linux_dialog()


def resolve_player(
    settings: dict[str, Any], requested: str | None = None
) -> dict[str, Any]:
    """决定本次播放使用的播放器。

    优先级：显式请求的播放器 > 设置中保存的播放器 > 探测到的第一个播放器。
    名称比较不区分大小写。

    参数:
        settings: 完整设置字典，读取 ``playback.player``。
        requested: 前端指定的播放器名称，可为 ``None``。

    返回:
        含 ``name``/``path``/``args``/``source`` 的播放器配置。

    异常:
        PlaybackError（409）：指定名称未找到时 code 为 ``player_not_found``；
        未配置且未探测到可用播放器时 code 为 ``no_player``。
    """
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
    """把秒数格式化为播放器参数：整数值去掉 ``.0``，其余保留原样。"""
    return str(int(seek)) if float(seek).is_integer() else str(seek)


def build_args(player: dict[str, Any], video_path: str, seek: float | None = None) -> list[str]:
    """拼装播放器命令行参数。

    若配置了 ``args`` 模板，则替换其中的 ``{path}`` 与 ``{seek}`` 占位符；
    模板未包含 ``{path}`` 时自动在末尾追加视频路径。未配置模板时，
    仅对 mpv/vlc 追加各自的起播位置参数。

    参数:
        player: 播放器配置，可含 ``name`` 与 ``args``。
        video_path: 视频文件路径。
        seek: 起播秒数，``None`` 表示从头播放。

    返回:
        传给可执行文件的参数列表（不含可执行文件本身）。
    """
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
    """启动播放器进程并立即返回，不等待其退出。

    参数:
        player: 播放器配置，至少包含 ``path``。
        video_path: 要播放的视频路径。
        seek: 起播秒数，``None`` 表示从头播放。

    返回:
        播放器进程的 PID。

    异常:
        PlaybackError（409，code ``player_not_found``）：可执行文件不存在或启动失败。
    """
    executable = canonical_path(player["path"])
    if not Path(executable).is_file():
        raise PlaybackError(f"播放器不存在: {executable}", code="player_not_found")
    args = build_args(player, video_path, seek)
    try:
        # 子进程完全脱离服务：不共享标准流，并在非 Windows 上新建会话，
        # 避免关闭/重启 VBob 时连带终止播放器。
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
