"""FontCop 入口：兼容开发模式（python run.py）与 PyInstaller 打包模式。
打包后 sys._MEIPASS 指向临时解压目录，据此找字体/索引/Web 资源。
"""
import os
import sys
from pathlib import Path


def bundle_root() -> Path:
    """返回项目根目录（开发模式下是运行目录 parent 两级，打包后取 _MEIPASS）。"""
    if getattr(sys, 'frozen', False):
        return Path(getattr(sys, '_MEIPASS', '/tmp'))
    # 从当前工作目录向上找 fonts/fonts.json
    for p in [Path.cwd(), Path(__file__).resolve().parent]:
        if (p / "fonts" / "fonts.json").exists():
            return p
    # fallback: __file__ 的 parent.parent
    return Path(__file__).resolve().parent.parent


def main() -> int:
    root = bundle_root()
    os.chdir(root)
    sys.path.insert(0, str(root / "src"))
    os.environ.setdefault("FONTOP_ROOT", str(root))
    if getattr(sys, 'frozen', False):
        os.environ.setdefault("FONTOP_MEIPASS", str(Path(sys._MEIPASS)))
    # 浏览器模式（最终方案）：启动本地服务并自动打开默认浏览器网页。
    # 不再用 pywebview 桌面壳——WebView2 环境差异会导致别人机器上样式丢失/无法运行。
    from src.server import main as server_main
    server_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
