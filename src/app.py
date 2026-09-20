"""FontCop 桌面壳：用 pywebview 把本地 Web UI 包成原生窗口（Windows）。

流程：启动 HTTP 服务（复用 src.server.start_server，单实例保护）
→ pywebview 窗口加载 http://127.0.0.1:8642 → 窗口关闭时停掉服务。

降级：pywebview 不可用/初始化失败（缺 WebView2 Runtime 等）时，
回退到「自动打开默认浏览器」的旧模式，保证应用始终可用。
"""
from __future__ import annotations

import threading

from src.server import HOST, PORT, start_server

WINDOW_TITLE = "FontCop — 字体版权快查"
WINDOW_SIZE = (980, 680)      # 默认小窗，适配普通笔记本屏
WINDOW_MIN_SIZE = (760, 540)
ICON_PATH = None  # 打包/开发通用：项目根 assets/FontCop.ico
from pathlib import Path as _Path
_icon = _Path(__file__).resolve().parent.parent / "assets" / "FontCop.ico"
if _icon.exists():
    ICON_PATH = str(_icon)


def run_gui() -> bool:
    """启动服务并弹出 pywebview 原生窗口。返回 True 表示窗口正常展示。"""
    try:
        import webview  # noqa: WPS433  （pywebview 可选依赖）
    except ImportError:
        print("pywebview 未安装，回退浏览器模式", flush=True)
        return False

    httpd = start_server(open_browser=False)  # 壳内不再开外部浏览器
    if httpd is None:
        # 已有实例在跑：直接展示窗口指向它即可（不开新服务）
        try:
            webview.create_window(WINDOW_TITLE, f"http://{HOST}:{PORT}",
                                  width=WINDOW_SIZE[0], height=WINDOW_SIZE[1],
                                  min_size=WINDOW_MIN_SIZE)
            webview.start()
            return True
        except Exception as e:  # noqa: BLE001
            print(f"GUI 窗口启动失败: {e}；请直接访问 http://{HOST}:{PORT}", flush=True)
            return False

    # 服务在本进程内：窗口关闭时优雅停掉 httpd
    def _serve() -> None:
        httpd.serve_forever()

    threading.Thread(target=_serve, daemon=True).start()

    try:
        webview.create_window(WINDOW_TITLE, f"http://{HOST}:{PORT}",
                              width=WINDOW_SIZE[0], height=WINDOW_SIZE[1],
                              min_size=WINDOW_MIN_SIZE)
        webview.start(icon=ICON_PATH)  # 窗口/任务栏图标（打包 exe 另由 spec icon= 嵌入）
        return True
    except Exception as e:  # noqa: BLE001
        print(f"GUI 窗口启动失败: {e}", flush=True)
        import webbrowser
        webbrowser.open(f"http://{HOST}:{PORT}")
        return False
    finally:
        try:
            httpd.shutdown()
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    if not run_gui():
        # 降级：浏览器模式（启动服务并打开默认浏览器）
        from src.server import main as server_main
        server_main()


if __name__ == "__main__":
    main()
