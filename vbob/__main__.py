from __future__ import annotations

import argparse
import logging
import logging.handlers
import threading
import webbrowser
from pathlib import Path

import uvicorn

from . import __version__
from .app import create_app
from .config import default_data_dir

log = logging.getLogger(__name__)


def _setup_logging(data_dir: Path) -> None:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "vbob.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="vbob", description="VBob 本地视频管理器")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8080, help="监听端口（默认 8080）")
    parser.add_argument("--data-dir", type=Path, default=None, help="数据目录")
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    parser.add_argument("--version", action="version", version=f"vbob {__version__}")
    args = parser.parse_args(argv)

    data_dir = (args.data_dir or default_data_dir()).expanduser().resolve()
    _setup_logging(data_dir)

    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        log.warning(
            "正在监听非回环地址 %s；本工具不提供鉴权，请勿暴露到不受信任的网络。",
            args.host,
        )

    app = create_app(data_dir)
    url = f"http://{args.host if args.host != '0.0.0.0' else '127.0.0.1'}:{args.port}"
    if args.open:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    log.info("VBob listening on %s", url)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
