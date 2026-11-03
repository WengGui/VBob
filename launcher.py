"""PyInstaller 入口：以包方式导入并启动 VBob。

直接以 ``python vbob/__main__.py`` 运行会破坏相对导入，因此打包统一使用本文件。
"""

from vbob.__main__ import main

if __name__ == "__main__":
    main()
