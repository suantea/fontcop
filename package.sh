#!/usr/bin/env bash
# 打包 FontCop 绿色发行版（解压即用，无需安装）。
# 产物：FontCop-<platform>.zip，含 项目源码 + fonts/subset + data 索引 + python-runtime。
# 前置：先跑 build_python.sh 生成 ./python-runtime，且 data/glyph_index.npz 已建好。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ ! -x python-runtime/bin/python3 && ! -x python-runtime/python.exe ]]; then
  echo "[package] 缺少 python-runtime，请先运行 bash build_python.sh"
  exit 1
fi
if [[ ! -f data/glyph_index.npz ]]; then
  echo "[package] 缺少 data/glyph_index.npz，请先运行 python-runtime/bin/python3 -m src.indexer"
  exit 1
fi

OS="$(uname -s)"
case "$OS" in
  Darwin) TAG="macos" ;;
  Linux)  TAG="linux" ;;
  MINGW*|MSYS*|Windows*) TAG="windows" ;;
  *) TAG="$(uname -m)" ;;
esac
ZIP="FontCop-${TAG}.zip"

echo "== 打包 ${ZIP}（排除源码级缓存与开发产物）=="
# 排除：git/venv/缓存/旧打包产物/大体积全量字体
zip -r "$ZIP" . \
  -x '*.git*' \
  -x '.venv/*' \
  -x '**/__pycache__/*' \
  -x '*.pyc' \
  -x 'dist-win/*' \
  -x 'fonts/files/*' \
  -x 'desktop/dist/*' \
  -x '.DS_Store' \
  -x "$ZIP"
echo "== 完成：$ZIP = $(du -h "$ZIP" | cut -f1) =="
echo "解压后双击 start.$( [[ "$OS" == Darwin ]] && echo command || echo bat ) 即可启动"
