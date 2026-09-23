#!/usr/bin/env bash
# 生成 FontCop.app（AppleScript 小壳，非 Electron）。
# 双击 → 起本地服务（python-runtime）+ 自动打开浏览器；要停服务用页面右上角
# 「⏻ 关闭服务」按钮（调 /api/shutdown）。不再是 Electron/webview 壳。
# 仅 macOS。产物 FontCop.app 在项目根目录，已 gitignore。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/FontCop.app"

[[ -x "$ROOT/python-runtime/bin/python3" ]] || {
  echo "缺少 python-runtime/bin/python3，先跑 bash build_python.sh"; exit 1; }

rm -rf "$APP"

# 用 osacompile 生成 applet 骨架，再把可执行文件换成 shell 脚本：
# 双击 .app 时 macOS 执行的正是 Contents/MacOS/<CFBundleExecutable>。
# 这样不依赖 AppleScript 的 UI 能力（osacompile 生成的是 applet，非 AppleScriptObjC）。
osacompile -o "$APP" -e 'return' >/dev/null 2>&1

cat > "$APP/Contents/MacOS/FontCop" <<'SHELL'
#!/bin/bash
# FontCop.app 入口：定位 .app 所在目录（= 项目根），起 python-runtime 的服务。
# 服务自身会打开浏览器；本脚本待服务退出后返回（关服务走页面按钮 /api/shutdown）。
APP_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$APP_DIR" || exit 1

if [[ ! -x python-runtime/bin/python3 ]]; then
  osascript -e 'display alert "FontCop 启动失败" message "未找到 python-runtime，请先运行 bash build_python.sh。" as critical'
  exit 1
fi

# 已在运行（healthz 通）则只开浏览器，不重复起服务
if curl -s -m 1 http://127.0.0.1:8642/healthz >/dev/null 2>&1; then
  open "http://127.0.0.1:8642"
  exit 0
fi

exec python-runtime/bin/python3 -m src.server
SHELL
chmod +x "$APP/Contents/MacOS/FontCop"

/usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string com.fontcop.launcher" \
  "$APP/Contents/Info.plist" >/dev/null 2>&1 || \
  /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier com.fontcop.launcher" \
  "$APP/Contents/Info.plist" >/dev/null 2>&1 || true

# 关键：osacompile 的 Info.plist 里 CFBundleExecutable 是 "applet"，
# 不改成 FontCop 的话双击跑的是 AppleScript 存根，我们写的启动脚本根本不会执行。
# osacompile 会预编译脚本并缓存到 Info.plist，改可执行名后必须删掉这段缓存，
# 否则 Finder 仍按旧入口启动。
/usr/libexec/PlistBuddy -c "Set :CFBundleExecutable FontCop" "$APP/Contents/Info.plist" \
  >/dev/null 2>&1 || /usr/libexec/PlistBuddy -c "Add :CFBundleExecutable string FontCop" \
  "$APP/Contents/Info.plist" >/dev/null 2>&1 || true

# 清掉 applet 残留：存根可执行文件与预编译脚本缓存
rm -f "$APP/Contents/MacOS/applet"

# 重新签名（改了可执行文件后原签名失效）
codesign --force --sign - "$APP" >/dev/null 2>&1 || true

echo "已生成：$APP"
echo "双击或在终端运行：open '$APP'"
