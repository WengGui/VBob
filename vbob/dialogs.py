"""本机原生对话框：选择目录。

浏览器出于安全限制拿不到本地真实路径，因此由后端在桌面环境弹出系统对话框，
前端只负责把返回的路径填入表单。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys

from .errors import InvalidError

log = logging.getLogger(__name__)

_WINDOWS_FOLDER_SCRIPT = (
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8;"
    "Add-Type -AssemblyName System.Windows.Forms;"
    "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog;"
    "$dialog.Description = '选择视频目录';"
    "$dialog.ShowNewFolderButton = $false;"
    "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK)"
    "{[Console]::Write($dialog.SelectedPath)}"
)


def pick_directory() -> str | None:
    """打开系统目录选择框，返回绝对路径；用户取消时返回 None。"""
    if sys.platform == "win32":
        return _pick_with_windows_dialog()
    if sys.platform == "darwin":
        return _pick_with_macos_dialog()
    return _pick_with_linux_dialog()


def _pick_with_windows_dialog() -> str | None:
    """通过 PowerShell 打开 Windows 原生目录选择框。"""
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", _WINDOWS_FOLDER_SCRIPT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            # 避免在服务端弹出额外的 PowerShell 控制台窗口。
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.exception("failed to open directory dialog")
        raise InvalidError("无法打开目录选择框", code="picker_failed") from exc
    if completed.returncode != 0:
        log.warning("directory dialog failed: %s", completed.stderr)
        raise InvalidError("无法打开目录选择框", code="picker_failed")
    return completed.stdout.strip() or None


def _pick_with_macos_dialog() -> str | None:
    """通过 osascript 打开 macOS 原生目录选择框。"""
    script = 'POSIX path of (choose folder with prompt "选择视频目录")'
    try:
        completed = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.exception("failed to open directory dialog")
        raise InvalidError("无法打开目录选择框", code="picker_failed") from exc
    if completed.returncode != 0:
        return None
    return completed.stdout.strip().rstrip("/") or None


def _pick_with_linux_dialog() -> str | None:
    """优先使用 zenity，其次 kdialog。"""
    if shutil.which("zenity"):
        command = ["zenity", "--file-selection", "--directory", "--title=选择视频目录"]
    elif shutil.which("kdialog"):
        command = ["kdialog", "--getexistingdirectory", "."]
    else:
        raise InvalidError(
            "当前系统没有可用的目录选择框，请直接输入路径", code="picker_failed"
        )
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        log.exception("failed to open directory dialog")
        raise InvalidError("无法打开目录选择框", code="picker_failed") from exc
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None
