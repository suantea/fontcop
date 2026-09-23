# FontCop — AI 代理项目指令

开源字体版权识别工具：截图 → OCR/框选提取字符 → 与内置开源字体白名单做字形级比对 → 四态判定（free / suspect / risky / unknown）。详细设计见 `README.md`。

**产品形态：两种** —— ① 本地源码运行（`.venv` + `python -m src.server`，浏览器访问）；② 绿色分发版（打包为解压即用的 zip：项目源码 + 独立 `python-runtime/` + 字体子集 + 字形索引，双击 `start.command`/`start.bat` 启动，**比对全在本机、零服务器内存、OCR 保留**）。**已放弃 Electron/.app/.exe/pywebview/托盘 等所有打包壳路线**——它们本质是带 Python 后端的 webview，对"本地起服务+开浏览器"是过度工程。`.venv` 与 `python-runtime/`（绿色版独立 Python）、`FontCop-*.zip` 各机器按平台自建/打包，勿提交。

### 绿色分发版（解压即用 zip）

- 构建独立 Python 运行时：`bash build_python.sh`（自动按 OS/ARCH 下载 python-build-standalone，装好依赖，产物 `python-runtime/`；Windows 上二进制是 `python-runtime/python.exe`，mac/linux 是 `python-runtime/bin/python3`）。
- 建字形索引：`python-runtime/bin/python3 -m src.indexer`（首次必做）。
- 打包 zip：`bash package.sh` → 产物 `FontCop-<platform>.zip`（mac 实测 ~112MB），含 项目源码 + `fonts/subset/` + `data/glyph_index.npz` + `python-runtime/`，解压后双击 `start.command`(mac)/`start.bat`(win) 即起服务并开浏览器。
- **打包瘦身（`package.sh` 的 `SKIP_ANY`/`SKIP_PART`）**：剔除运行期用不到的 `site-packages/pip`（11MB）、`fontTools`（20MB，仅 `tools/subset_fonts.py` 等构建脚本用，服务/OCR 零引用）、`include/`、`share/`、`*.dist-info/`、`__pycache__/`，共省 ~60MB。规则按 `"/site-packages/pip/"` 这类路径片段匹配，**mac/win 同一套逻辑**（Windows 侧是 `.pyd`，同样不动 C 扩展）。新增依赖前先确认它运行期是否需要，别再打进去。
- **不再做 Electron/.dmg/.exe**：分发就是一份 zip + 一份独立 Python，体积主要来自 OCR 引擎（onnxruntime 80MB，必需）。**已彻底剥掉 opencv（原 120MB）**：RapidOCR 只用 24 个 cv2 函数，`src/cv2_shim.py` 用 Pillow+NumPy 等价实现，在 OCR 子进程 `import rapidocr` 前经 `sys.modules["cv2"]` 顶替（RapidOCR 全是 `import cv2`，故无需改上游源码）。未剥的还有 shapely（7.1MB，`Polygon.area/.length` 在 unclip 路径上是活的，剥不掉）。
- **关闭服务**：`src/server.py` 的 `POST /api/shutdown` 优雅退出（`os._exit(0)`，先回响应再退），**仅接受回环来源**（`_is_loopback_client()`，非回环返回 403），防止公网部署被任意关停。前端 `web/index.html` 右上角「⏻ 关闭服务」按钮调它。桌面壳不额外做 GUI（tkinter 壳已删）。
- **mac `.app`（可选）**：`bash tools/make_mac_app.sh` 生成 `FontCop.app`（osacompile 骨架 + 覆盖 `Contents/MacOS/FontCop` 为 shell 脚本，非 Electron/webview），双击起服务并开浏览器；关服务走页面按钮。产物 gitignore。

## 常用命令

```bash
# 启动服务（本机模式：自动开浏览器）
.venv/bin/python -m src.server         # macOS/Linux   http://127.0.0.1:8642
.venv/Scripts/python.exe -m src.server # Windows

# 重建字形索引（改字体白名单/阈值后必须重建，否则比对用旧索引）
.venv/bin/python -m src.indexer   # 耗时 ~15min；sdfs 存 float16（内存减半），粗排用 _fonts_bin（packbits 预打包位图加速）

# 下载白名单字体到 fonts/files/（可重复执行，已存在则跳过）
.venv/bin/python tools/fetch_fonts.py

# 字体子集化：把 fonts/files/ 全量字体裁剪到索引字符集，输出 fonts/subset/
.venv/bin/python tools/subset_fonts.py   # 改 indexer.CHARS 后需重跑

# 生成模拟截图测试集（依赖 src/render.render_char）
.venv/bin/python tools/gen_testset.py
```

无 lint / format / pytest 配置，纯 Python + NumPy + Pillow，标准库 HTTP 服务，无框架。

## 架构

- `src/server.py` — HTTP 服务 + API（/api/match 手动框选、/api/auto OCR 自动、/api/fonts、/healthz 健康检查）。`start_server()` 本机模式下带单实例保护+自动开浏览器；**部署模式（FONTOP_HOST 非回环）跳过单实例/开浏览器，供反代与 systemd 托管**。验证见 `tests/test_e2e.py`。
- `src/pipeline.py` — 比对管线（IoU 粗排 top50 → SDF+NCC+HOG 精排 → 多字投票），OCR 与手动共用。
- `src/features.py` — 相似度算法与判定阈值 `THRESHOLD_FREE=0.90`、`THRESHOLD_SUSPECT=0.75`；判定统一走 `verdict_of(score)`，`unknown` 只在 0 票/0 可比字时由调用方返回。
- `src/edt.py` — 纯 NumPy 精确欧氏距离变换（Felzenszwalb 抛物线，O(n)），替代 scipy.ndimage.distance_transform_edt。
- `src/auto.py` — RapidOCR 自动模式（可选依赖）。**OCR 运行在独立子进程**（持久 worker + 超时 + 崩溃重启隔离），OCR 崩溃/挂起只影响子进程，父进程（HTTP 服务）超时后重启它并回退逐段搜索，绝不再打死整个服务（AGENTS.md 历史坑：OCR 与 HTTP 同进程时一次 SIGSEGV 会拖垮整服务）。未安装或 `FONTOP_NO_OCR=1` 时前端退回手动。
- `src/indexer.py` — 生成 `data/glyph_index.npz`（gitignore，构建时可缺失）。字符集在 `fonts/common_chars.txt`（jieba 词频 top3500 + 原形近字，共 3502 汉字 + 80 标点字母数字），改字表必须重建索引。
- `web/app.js` — 原生 JS 前端，含逐字堆叠图与 font_id→名称映射守卫。

### 部署配置（环境变量，详见 README「部署」）

`FONTOP_HOST` / `FONTOP_PORT` / `FONTOP_MAX_BODY` / `FONTOP_TOKEN` / `FONTOP_CORS_ORIGIN` / `FONTOP_AUTO_MAX_EDGE` / `FONTOP_NO_OCR`。

## 项目特有注意事项

- **unknown 是设计决策**：无可比对字/OCR 空跑时必须返回中性 `unknown`，严禁兜底判 `risky` 或残留上次判定——这是用户明确反馈过的坑，改动判定逻辑时不得回退。
- **数据文件链条**：`fonts/download_list.txt` → `tools/fetch_fonts.py` 下载 → `fonts/fonts.json` 白名单 → `tools/subset_fonts.py` 子集化（输出 `fonts/subset/`）→ `src/indexer.py` 建索引。改上游任何一环都要跑下游命令。`fonts/files/*.ttf|otf`、`fonts/subset/`、`data/` 均已 gitignore。**注意**：`fonts/common_chars.txt` 是字符集数据源（非 gitignore），改字表需同步改本文件并重建索引。
- **子集化字体**：比对/打包只用 `fonts/subset/`（12 款共 ~4MB，`src/render.glyph_files()` 优先子集、缺则回退 `fonts/files/` 全量）。全量 `fonts/files/` 192MB 仅本地校验用、不打包。`inter`/`jetbrains-mono`/`dejavu-sans` 缺源文件，未子集化、空字形不参与比对（`tests/test_m1_regression.py` 依赖全量字体文件，缺文件时会 AssertionError——已知）。
- **同源字体合并展示**：Noto/思源等字形相同的字体在 `fonts.json` 中各占一条（比对引擎需要各自的 font_id）。识别结果（候选 + 逐字 top）与白名单弹窗均按 `src/pipeline.py` 的 `DUP_GROUPS`/`_group_of()` 归并：组内第一个成员为展示代表（优先中文名「思源黑体/思源宋体」），其余成员（Noto 等英文名）只参与比对、不单独出现。改字体列表时留意此机制。
- **`.venv` 是机器相关产物**：跨机器/跨平台必须重建（macOS/Linux：`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`；Windows 路径不同）。requirements 用宽松下界（>=），已在 Python 3.9/3.14 跑通。**当前索引内存**：`glyph_index.npz` 存 float16（SDF 450MB + 位图 225MB + _fonts_bin 28MB ≈ 700MB），若需降内存可考虑 sdfs 恢复 float32（精度不变、内存翻倍）或按项目需求裁剪 CHARS。
- **已剥离 opencv（不再依赖 opencv-python）**：RapidOCR 只用到 24 个 cv2 函数，`src/cv2_shim.py` 用 Pillow+NumPy 等价实现，在 OCR 子进程 `import rapidocr` 前经 `sys.modules["cv2"]` 顶替（RapidOCR 全部是 `import cv2`，无 from-import，故无需改上游源码）。**`ocr_available()` 也必须先装 shim** —— 它跑在父进程，不装会因缺 cv2 误报「RapidOCR 未安装」（501）。`build_python.sh` 的依赖校验已覆盖这条路径。历史坑（保留）：opencv 5.0 起新版 NEON resize 核（kleidicv）在 macOS/arm64 个别尺寸（如 3080×2117）必现 SIGSEGV，会把整个服务进程打死；不再依赖 opencv 后这类崩溃面直接消失。若需真 opencv 调试，`pip install "opencv-python>=4.11.0.86,<5"` 即可（shim 仅在 cv2 缺失时兜底）。另外 `web/app.js` 与 `src/auto.py` 仍会在 OCR 前把图缩到合适边长（≤1600/2200），降低超大图对 OCR 的检出与内存压力。
- **OCR 子进程隔离（已实现，勿回退）**：RapidOCR 在异常输入（超大图、依赖版本不合）下可能 SIGSEGV/永久挂起。OCR 已挪进独立子进程（持久 worker + 超时 + 崩溃重启），一次 OCR 崩溃只影响该子进程，父进程（HTTP 服务）超时后重启它并回退逐段搜索，不会打死整个服务。前端另有 60s 超时与按钮恢复兜底，但那是容错不是根治——根治靠隔离，勿回退为「同一进程内堆锁 + 靠前端兜底」。历史上 opencv 5.x 的 SIGSEGV 曾是最大崩点，现已随 opencv 剥离消失（见上条）。
- **自动模式不依赖 OCR 文本的兜底**：OCR 行置信度 <0.6，或列投影段数与 OCR 字数对不齐（`len(segs) != len(chars)`，宽间距 logo 字常部分检出/误读，如 4 字读成「美城d」）时，OCR 文本不可靠，弃字符引导改走列投影逐段全索引搜索（不依赖 OCR 文本，避免误读字贴到正确字形上）；勿改回整行跳过或 `> chars+1` 的旧条件。段数与字数碰巧对齐但标签误读（`_labels_consistent` 逐字全索引校验任一不符）同样整行回退逐段搜索。**左右结构汉字（绿/创/城…）部件间竖隙会被列投影切碎**（如「创」→仓+刂），`_mask_votes` 必须用 `_column_segs(ink, filter_narrow=False)` 保留窄段再经 `_merge_narrow`（宽高比 <0.5 视为碎片）合并后搜索——勿改回 `filter_narrow=True`（会把「刂」当噪声剔除，剩半字匹配成垃圾字如 'd'），也不要改成按相对宽度过滤（会把正常窄字如「创」0.62 误并）。`_sub_wide` 粘连细分阈值为宽高比 1.35。索引外字符（如「绿/航」不在 794 字集内）逐段搜索会落到形近索引字或低于 `_MIN_AUTO` 被过滤，仅影响逐字标签、不影响字体判定。回归见 `tests/test_auto_wide.py`。
- **`.bak` 文件是历史快照**，不要读取或基于其改动；根目录日志/临时文件（`*.log`、`nul`、`_tmp_*`、`_probe*`）均已 gitignore。

## 维护规则

当项目结构、构建/测试命令、架构边界、开发约定或本文件记录的其他事实发生变化时，必须在同一次改动中同步更新本文件。