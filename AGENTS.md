# FontCop — AI 代理项目指令

开源字体版权识别工具：截图 → OCR/框选提取字符 → 与内置开源字体白名单做字形级比对 → 四态判定（free / suspect / risky / unknown）。详细设计见 `README.md`。

**产品形态：三选一** —— ① Web 页面本地源码运行；② 部署为公网/内网 Web 服务（反代托管）；③ 本地桌面软件（Electron 外壳 + 内嵌 Python 比对后端，`desktop/` 目录，打包为 .app/.exe，比对全在本机、零服务器内存、OCR 保留）。**已放弃 exe / pywebview / 托盘 的独立打包路线，但 Electron 嵌 Python 是受支持的桌面形态。** 残留的 exe 时代产物（FontCop.spec、src/app.py、src/tray.py、start.sh、build-windows.yml、pyinstaller/frozen 分支）已删除；`.venv` 与 `desktop/python-runtime/`、`desktop/node_modules/` 各机器自建，勿提交。

## 常用命令

```bash
# 启动服务（本机模式：自动开浏览器；Windows 等价双击 _serve.bat / _start_hidden.vbs）
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
- `src/auto.py` — RapidOCR 自动模式（可选依赖）。`_OCR_LOCK` 串行化 onnxruntime 调用（session 非线程安全，比对仍并行）；未安装或 `FONTOP_NO_OCR=1` 时前端退回手动。
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
- **opencv 必须 <5**：opencv-python 5.0 起新版 NEON resize 核（kleidicv）在 macOS/arm64 的个别输入尺寸上必现 SIGSEGV（如 3080×2117），会把整个服务进程打死，前端表现为「自动识别失败：Load failed」。requirements 已锁 `opencv-python>=4.11.0.86,<5`；重建环境/升级依赖时勿装 5.x。另外 `web/app.js` 与 `src/auto.py` 都会在 OCR 前把图缩到合适边长（≤1600/2200），降低超大图对 OCR 的检出与内存压力。
- **OCR 建议独立子进程隔离**：RapidOCR 在异常输入（超大图、依赖版本不合）下可能 SIGSEGV/永久挂起。目前 ocr 与 HTTP 服务在同一进程内运行，一次 OCR 崩溃就会打死整个服务（前端表现为「自动识别失败：Load failed / 卡自动识别中」）。已知可穷举到的崩点已靠 opencv 锁 <5 堵住，但无法枚举所有输入；若再次出现 OCR 引发整服务死亡，应把 RapidOCR 挪进独立子进程（子进程内初始化、可超时/重启隔离），不要继续在同一进程里堆锁。前端已做 60s 超时与按钮恢复兜底，但根治靠隔离，勿回退为依赖前端容错。
- **自动模式不依赖 OCR 文本的兜底**：OCR 行置信度 <0.6，或列投影段数与 OCR 字数对不齐（`len(segs) != len(chars)`，宽间距 logo 字常部分检出/误读，如 4 字读成「美城d」）时，OCR 文本不可靠，弃字符引导改走列投影逐段全索引搜索（不依赖 OCR 文本，避免误读字贴到正确字形上）；勿改回整行跳过或 `> chars+1` 的旧条件。段数与字数碰巧对齐但标签误读（`_labels_consistent` 逐字全索引校验任一不符）同样整行回退逐段搜索。**左右结构汉字（绿/创/城…）部件间竖隙会被列投影切碎**（如「创」→仓+刂），`_mask_votes` 必须用 `_column_segs(ink, filter_narrow=False)` 保留窄段再经 `_merge_narrow`（宽高比 <0.5 视为碎片）合并后搜索——勿改回 `filter_narrow=True`（会把「刂」当噪声剔除，剩半字匹配成垃圾字如 'd'），也不要改成按相对宽度过滤（会把正常窄字如「创」0.62 误并）。`_sub_wide` 粘连细分阈值为宽高比 1.35。索引外字符（如「绿/航」不在 794 字集内）逐段搜索会落到形近索引字或低于 `_MIN_AUTO` 被过滤，仅影响逐字标签、不影响字体判定。回归见 `tests/test_auto_wide.py`。
- **`.bak` 文件是历史快照**，不要读取或基于其改动；根目录日志/临时文件（`*.log`、`nul`、`_tmp_*`、`_probe*`）均已 gitignore。

## 维护规则

当项目结构、构建/测试命令、架构边界、开发约定或本文件记录的其他事实发生变化时，必须在同一次改动中同步更新本文件。