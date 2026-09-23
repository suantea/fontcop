#!/usr/bin/env bash
# 构建 FontCop 所需的独立 Python 运行时（python-build-standalone + 依赖）。
# 产物：./python-runtime/ （含 python3 + 已装依赖，启动脚本用相对路径调用）
# 用法：bash build_python.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$ROOT/python-runtime"

# 平台：自动按当前 OS/ARCH 选 python-build-standalone 资产（也可用 PBS_ARCH 覆盖）
PY_FULL="3.14.7"         # 具体补丁版本（release 资产按此命名）
PBS_VER="20260901"       # python-build-standalone 发布日期标签
case "${PBS_ARCH:-$(uname -s)-$(uname -m)}" in
  Darwin-arm64)  ARCH="aarch64-apple-darwin" ;;
  Darwin-x86_64) ARCH="x86_64-apple-darwin" ;;
  Linux-x86_64)  ARCH="x86_64-unknown-linux-gnu" ;;
  Linux-aarch64) ARCH="aarch64-unknown-linux-gnu" ;;
  MINGW*-x86_64*|Windows*-x86_64*|MSYS*-x86_64*) ARCH="x86_64-pc-windows-msvc" ;;
  *) echo "不支持的平台: $(uname -s)-$(uname -m)（可用 PBS_ARCH 覆盖）"; exit 1 ;;
esac
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_VER}/cpython-${PY_FULL}+${PBS_VER}-${ARCH}-install_only.tar.gz"
if [[ "$ARCH" == *windows* ]]; then
  PY_EXE_REL="python.exe"
else
  PY_EXE_REL="bin/python3"
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "== 下载 python-build-standalone (cpython-${PY_FULL}+${PBS_VER}-${ARCH}) =="
curl -fL --retry 5 --retry-all-errors -C - --http1.1 -o "$TMP/py.tgz" "$URL"
tar -tzf "$TMP/py.tgz" >/dev/null || { echo "下载不完整或 corrupted，请重试"; exit 1; }

echo "== 解压到 $OUT =="
rm -rf "$OUT"
mkdir -p "$OUT"
tar -xzf "$TMP/py.tgz" -C "$TMP"
cp -R "$TMP/python"/* "$OUT/"

echo "== 安装依赖 =="
PY_EXE="$OUT/$PY_EXE_REL"
"$PY_EXE" -m ensurepip
"$PY_EXE" -m pip install -r "$ROOT/requirements.txt"

# rapidocr-onnxruntime 把 opencv-python 声明为传递依赖，pip 必然装回来（且是 5.x）。
# pip 没有「负向依赖」，只能装完卸载 —— 这是剥离 opencv 唯一可靠的落点。
# 校验卡在下游：卸载失败会直接让构建红掉，不会把带 opencv 的包发出去。
echo "== 移除 opencv（改用 src/cv2_shim.py）=="
"$PY_EXE" -m pip uninstall -y opencv-python opencv-python-headless 2>/dev/null || true

echo "== 校验关键依赖 =="
# cv2 不再随包安装（见 requirements.txt）：src/cv2_shim.py 在 OCR 子进程内顶替它。
# 校验必须覆盖「无 opencv 也能起 OCR」这条真实路径，否则打包出去才发现是 501。
"$PY_EXE" -c "import numpy, PIL, rapidocr_onnxruntime; print('deps ok')"
"$PY_EXE" -c "
try:
    import cv2
except ImportError:
    pass
else:
    raise SystemExit('opencv 仍可导入，卸载步骤失效：%s' % getattr(cv2, '__file__', '?'))
import sys
sys.path.insert(0, '$ROOT')
from src.auto import _install_cv2_shim_if_needed
_install_cv2_shim_if_needed()
import cv2
assert 'cv2_shim' in (cv2.__file__ or ''), 'cv2 应来自 shim 而非 opencv'
print('cv2 shim ok:', getattr(cv2, '__version__', '?'))
"

echo "== 完成：python-runtime 已就绪 =="
"$PY_EXE" --version
