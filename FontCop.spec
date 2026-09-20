# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包规格：FontCop — 单可执行文件（server + 自动运行）。"""
import os
from pathlib import Path

block_cipher = None

import os
import sys
import rapidocr_onnxruntime
_RAPIDOCR_PKG = os.path.dirname(rapidocr_onnxruntime.__file__)
# rapidocr 运行时按 __file__ 相对路径读取 config.yaml 和 onnx 模型，必须整体打进包
_rapidocr_datas = []
for _root, _dirs, _files in os.walk(_RAPIDOCR_PKG):
    for _f in _files:
        if _f.endswith((".yaml", ".onnx")):
            _p = os.path.join(_root, _f)
            _rapidocr_datas.append((_p, os.path.relpath(os.path.dirname(_p), os.path.dirname(_RAPIDOCR_PKG))))

# pystray 后端模块按平台不同：macOS 用 _util_darwin，Windows 用 _util_win32
_pystray_extras = []
if sys.platform == "darwin":
    _pystray_extras = ["pystray._util_darwin"]

# datas 容错：system_fonts.json / symbols.json 是 macOS 扫描产物（gitignore），
# fonts/files/*.ttf 字体二进制也 gitignore（体积大），构建机上不存在时跳过。
# 注意：PyInstaller 对"无匹配的 glob"会直接报错，所以这里自行展开 glob。
import glob as _glob

_base_datas = [
    ('fonts/fonts.json', 'fonts'),
    ('fonts/system_fonts.json', 'fonts'),
    ('fonts/symbols.json', 'fonts'),
    # 子集化字体（tools/subset_fonts.py 生成，4MB 级别，替代全量 fonts/files 192MB）
    ('fonts/subset/*.ttf', 'fonts/subset'),
    ('fonts/subset/*.otf', 'fonts/subset'),
    ('data/glyph_index.npz', 'data'),
    ('web/index.html', 'web'),
    ('web/app.js', 'web'),
    ('web/style.css', 'web'),
    ('LICENSE', '.'),
]
_datas = []
for _src, _dst in _base_datas:
    if '*' in _src:
        _datas.extend((_f, _dst) for _f in _glob.glob(_src))  # 无匹配则自然为空
    elif os.path.exists(_src):
        _datas.append((_src, _dst))
    else:
        print(f"[spec] skip missing data: {_src}")

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=_datas + _rapidocr_datas,
    hiddenimports=[
        'rapidocr_onnxruntime',
        'rapidocr_onnxruntime.ch_ppocr_v3_det',
        'rapidocr_onnxruntime.ch_ppocr_v3_det.text_detect',
        'rapidocr_onnxruntime.ch_ppocr_v3_rec',
        'rapidocr_onnxruntime.ch_ppocr_v3_rec.text_recognize',
        'rapidocr_onnxruntime.ch_ppocr_v2_cls',
        'rapidocr_onnxruntime.ch_ppocr_v2_cls.text_cls',
        'rapidocr_onnxruntime.utils',
        'rapidocr_onnxruntime.rapid_ocr_api',
        'fontTools.ttLib',
        'fontTools.subset',
        'PIL',
        'numpy',
        'pystray',
        # pywebview 桌面壳（Windows 走 EdgeChromium + pythonnet/clr_loader）
        'webview',
        'webview.platforms.edgechromium',
        'webview.platforms.winforms',
        'webview.platforms.win32',
        'webview.platforms.clr',
        'webview.util',
        'clr_loader',
        'pythonnet',
    ] + _pystray_extras,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='FontCop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI 应用，不弹终端
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/FontCop.ico',  # exe/任务栏/窗口图标
)
