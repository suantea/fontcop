"""FontCop 入口：启动本地服务（等价于 python -m src.server）。

部署模式示例（交给反代或直接公网）：
    FONTOP_HOST=0.0.0.0 FONTOP_PORT=8642 FONTOP_TOKEN=xxx python run.py
"""
from src.server import main

if __name__ == "__main__":
    raise SystemExit(main())