"""从 ``doc/vbob_icon.png`` 生成网站 favicon 与 Windows exe 图标。

需要 Pillow，可用临时依赖运行：

    uv run --with pillow python scripts/make_icons.py

生成的图标已提交到仓库，正常构建不需要重复执行本脚本。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "doc" / "vbob_icon.png"
PUBLIC = ROOT / "web" / "public"
ASSETS = ROOT / "assets"


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"找不到图标源文件：{SOURCE}")

    PUBLIC.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)

    image = Image.open(SOURCE).convert("RGBA")

    # 网站图标：浏览器标签页、iOS 主屏、PWA 尺寸。
    image.resize((32, 32), Image.LANCZOS).save(PUBLIC / "favicon-32.png", optimize=True)
    image.resize((180, 180), Image.LANCZOS).save(
        PUBLIC / "apple-touch-icon.png", optimize=True
    )
    image.resize((192, 192), Image.LANCZOS).save(PUBLIC / "icon-192.png", optimize=True)
    image.save(
        PUBLIC / "favicon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)],
    )

    # Windows 资源管理器与任务栏使用多尺寸 ico。
    image.save(
        ASSETS / "vbob.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    for path in sorted([*PUBLIC.glob("*"), ASSETS / "vbob.ico"]):
        if path.is_file():
            print(f"{path.relative_to(ROOT)}  {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
