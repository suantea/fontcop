# FontCop — AI 代理项目指令

开源字体版权识别工具：截图 → OCR/框选提取字符 → 与内置开源字体白名单做字形级比对 → 四态判定（free / suspect / risky / unknown）。详细设计见 `README.md`。

**产品形态：Web 页面（本地源码运行 + 可部署为公网/内网 Web 服务）。已放弃 exe / pywebview / 托盘。** 残留的 exe 时代产物（FontCop.spec、src/app.py、src/tray.py、start.sh、build-windows.yml、pyinstaller/frozen 分支）已删除；`.venv` 各机器自建，勿提交。

## 常用命令

```bash
# 启动服务（本机模式：自动开浏览器；Windows 等价双击 _serve.bat / _start_hidden.vbs）
.venv/bin/python -m src.server         # macOS/Linux   http://127.0.0.1:8642
.venv/Scripts/python.exe -m src.server # Windows

# 重建字形索引（改字体白名单/阈值后必须重建，否则比对用旧索引）
.venv/bin/python -m src.indexer

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
- `src/indexer.py` — 生成 `data/glyph_index.npz`（gitignore，构建时可缺失）。
- `web/app.js` — 原生 JS 前端，含逐字堆叠图与 font_id→名称映射守卫。

### 部署配置（环境变量，详见 README「部署」）

`FONTOP_HOST` / `FONTOP_PORT` / `FONTOP_MAX_BODY` / `FONTOP_TOKEN` / `FONTOP_CORS_ORIGIN` / `FONTOP_NO_OCR`。

## 项目特有注意事项

- **unknown 是设计决策**：无可比对字/OCR 空跑时必须返回中性 `unknown`，严禁兜底判 `risky` 或残留上次判定——这是用户明确反馈过的坑，改动判定逻辑时不得回退。
- **数据文件链条**：`fonts/download_list.txt` → `tools/fetch_fonts.py` 下载 → `fonts/fonts.json` 白名单 → `tools/subset_fonts.py` 子集化（输出 `fonts/subset/`）→ `src/indexer.py` 建索引。改上游任何一环都要跑下游命令。`fonts/files/*.ttf|otf`、`fonts/subset/`、`data/` 均已 gitignore。
- **子集化字体**：比对/打包只用 `fonts/subset/`（12 款共 ~4MB，`src/render.glyph_files()` 优先子集、缺则回退 `fonts/files/` 全量）。全量 `fonts/files/` 192MB 仅本地校验用、不打包。`inter`/`jetbrains-mono`/`dejavu-sans` 缺源文件，未子集化、空字形不参与比对（`tests/test_m1_regression.py` 依赖全量字体文件，缺文件时会 AssertionError——已知）。
- **同源字体合并展示**：Noto/思源等字形相同的字体在 `fonts.json` 中各占一条（比对引擎需要各自的 font_id）。识别结果（候选 + 逐字 top）与白名单弹窗均按 `src/pipeline.py` 的 `DUP_GROUPS`/`_group_of()` 归并：组内第一个成员为展示代表（优先中文名「思源黑体/思源宋体」），其余成员（Noto 等英文名）只参与比对、不单独出现。改字体列表时留意此机制。
- **`.venv` 是机器相关产物**：跨机器/跨平台必须重建（macOS/Linux：`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`；Windows 路径不同）。requirements 用宽松下界（>=），已在 Python 3.9/3.14 跑通。
- **`.bak` 文件是历史快照**，不要读取或基于其改动；根目录日志/临时文件（`*.log`、`nul`、`_tmp_*`、`_probe*`）均已 gitignore。

## 维护规则

当项目结构、构建/测试命令、架构边界、开发约定或本文件记录的其他事实发生变化时，必须在同一次改动中同步更新本文件。