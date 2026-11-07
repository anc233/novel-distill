"""便携版入口：PyInstaller 从仓库根的 packaging/launcher.py 开始打包。

用户双击 exe（无参数）时 novel_distill.cli.main 会走 FROZEN 分支直接进 GUI；
带参数调用时就是完整命令行，例如 `novel-distill.exe stats my-novel`。
"""

import sys

from novel_distill.cli import main

if __name__ == "__main__":
    sys.exit(main())
