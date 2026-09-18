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
# Windows 构建机上不存在，跳过即可（渲染层对缺失字体已优雅降级）
_base_datas = [
    ('fonts/fonts.json', 'fonts'),
    ('fonts/system_fonts.json', 'fonts'),
    ('fonts/symbols.json', 'fonts'),
    ('fonts/files/*.ttf', 'fonts/files'),
    ('fonts/files/*.otf', 'fonts/files'),
    ('data/glyph_index.npz', 'data'),
    ('web/index.html', 'web'),
    ('web/app.js', 'web'),
    ('web/style.css', 'web'),
]
_datas = []
for _src, _dst in _base_datas:
    if '*' in _src:
        _datas.append((_src, _dst))  # glob 交给 PyInstaller 自行匹配（空结果不报错）
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
        'PIL',
        'numpy',
        'scipy.ndimage',
        'pystray',
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
    icon=None,
)
