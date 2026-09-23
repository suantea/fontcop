#!/usr/bin/env bash
# FontCop 本地启动脚本（macOS）：双击即起服务并打开浏览器。
# 依赖同目录的 python-runtime/（独立 Python，由 build_python.sh 生成）；
# 若没有，会提示用 build_python.sh 构建。
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x python-runtime/bin/python3 ]]; then
  echo "[FontCop] 未找到 python-runtime/bin/python3"
  echo "请先运行：bash build_python.sh  （首次需联网下载独立 Python + 依赖，约 5 分钟）"
  read -r -p "按回车退出…"
  exit 1
fi

echo "[FontCop] 启动本地服务…"
python-runtime/bin/python3 -m src.server
