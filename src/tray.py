"""FontCop 托盘：菜单栏图标 + 快捷键截图识别（macOS/Windows）。

依赖：pystray + Pillow（.venv 内 pip install pystray）
macOS：⌥F 或菜单[截图识别] → screencapture 交互截图 → 剪贴板 → 网页自动读取
Windows：托盘菜单[打开界面]，网页内 ⌘V/拖拽/选择文件（系统无 CLI 截图命令）
"""
import subprocess
import sys
import time
import webbrowser

IS_MACOS = sys.platform == "darwin"

SERVER_URL = "http://127.0.0.1:8642"


def server_up() -> bool:
    import urllib.request
    try:
        urllib.request.urlopen(SERVER_URL + "/api/fonts", timeout=2)
        return True
    except OSError:
        return False


def start_server() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "src.server"],
        cwd=str(__import__("pathlib").Path(__file__).resolve().parent.parent),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def screenshot_and_open() -> None:
    """macOS：交互截图进剪贴板 → 打开网页自动读取。非 macOS：仅打开网页。"""
    if IS_MACOS:
        subprocess.run(["screencapture", "-i", "-c"], check=False)
    webbrowser.open(SERVER_URL)


def main() -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        print("需要 pystray: .venv/bin/pip install pystray")
        sys.exit(1)

    if not server_up():
        start_server()
        for _ in range(30):
            if server_up():
                break
            time.sleep(0.5)

    # 16x16 简单图标：蓝色圆 + 白色 F
    im = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([0, 0, 15, 15], fill=(22, 93, 255, 255))
    d.text((5, 1), "F", fill="white")

    menu = pystray.Menu(
        pystray.MenuItem("截图识别 (⌥F)" if IS_MACOS else "打开界面",
                         lambda: screenshot_and_open(), default=True),
        pystray.MenuItem("打开界面", lambda: webbrowser.open(SERVER_URL)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", lambda: on_quit(icon)),
    )
    icon = pystray.Icon("fontcop", im, "FontCop 字体版权快查", menu)

    # 全局快捷键（仅 macOS：⌥F；Windows 无内置全局热键，托盘菜单即可）
    if IS_MACOS:
        try:
            import threading
            threading.Thread(target=register_hotkey, daemon=True).start()
        except Exception:  # noqa: BLE001
            pass

    print("FontCop 托盘已启动")
    icon.run()


def register_hotkey() -> None:
    """macOS 全局快捷键 ⌥F → 截图识别。用 Quartz event tap 实现。"""
    import Quartz

    def callback(_proxy, _type, event, _ref):
        flags = Quartz.CGEventGetFlags(event)
        # Option(Alt) 按下 + F 键
        if flags & Quartz.kCGEventFlagMaskAlternative:
            keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
            if keycode == 3:  # F
                screenshot_and_open()
        return event

    tap = Quartz.CGEventTapCreate(
        Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
        Quartz.kCGEventTapOptionListen,
        Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown), callback,
    )
    if tap is None:
        print("快捷键注册失败（需在 系统设置→隐私→辅助功能 中授权）")
        return
    Quartz.CGEventTapEnable(tap, True)
    Quartz.CFRunLoopAddSource(
        Quartz.CFRunLoopGetCurrent(),
        Quartz.CFMachPortCreateRunLoopSource(None, tap, 0),
        Quartz.kCFRunLoopCommonModes,
    )
    Quartz.CFRunLoopRun()


def on_quit(icon) -> None:
    icon.stop()
    import subprocess
    subprocess.run(["pkill", "-f", "src.server"], check=False)
    sys.exit(0)


if __name__ == "__main__":
    main()
