# FontCop 纯前端比对方案（PRE/设计文档）

> 状态：**设计评估**，尚未实现。目标：把字形比对从服务端搬到浏览器，服务端只托管静态文件 + 索引数据，内存 ≈ 0，解决"服务器慢/性能弱/访问卡"的痛点。

## 1. 动机与约束

- 当前服务端常驻内存 **~1.1–1.3GB**（索引 703MB + RapidOCR 300–500MB + Python/numpy）。
- 用户服务器性能弱、访问慢，且使用频率低 → 重服务端不划算。
- **自动识别（OCR）暂不搬前端**：RapidOCR 无法纯前端跑，且用户已表示"自动识别不管"。本期只做**手动框选比对**的前端化。
- 浏览器端不做 OCR，意味着 `/api/auto` 整条路径本期不迁移；用户仍需「贴图 → 画框 → 打该字」的手动模式。

## 2. 核心障碍：索引体积

服务端 `glyph_index.npz` 构成：

| 组件 | 体积 | 前端用途 |
|---|---|---|
| glyphs (uint8 64×64) | 225MB | 二值图，可 packbits 压缩 |
| sdfs (float16 64×64) | 450MB | **SDF+NCC 精排用，前端舍弃** |
| `_fonts_bin` (packbits 64×64) | 28MB | 粗排位图 |

**结论**：纯前端必须丢弃 SDF/NCC/HOG 精排（否则 450MB 无法下发，且 JS 跑 SDF 极慢）。只保留 **packbits 二值索引**做 IoU 粗排。

### 体积分级（下发方案）

| 方案 | 分辨率 | 下发体积 | 精度 |
|---|---|---|---|
| 现状服务端 | 64×64 + SDF | 703MB | 最高（SDF+NCC+HOG） |
| **A. 瘦索引（推荐）** | 64×64 packbits | **28MB** | IoU 级，清晰图够用 |
| A-降采 | 48×48 | 16MB | 略糙 |
| A-极限 | 32×32 | 7MB | 明显变糙 |

> 单字比对需在浏览器做 **54930 次 512B popcount**（15 字体 × 3662 字）。JS 用 `Uint8Array` + 位运算，单次 ~ns 级，整字 ~1–3ms，**可接受**。

## 3. 两条前端路线对比

### 路线 A：瘦索引 IoU（推荐）

- **数据**：服务端构建时额外导出 `web/glyph_index.packbits`（28MB，`[F, C, 512]` uint8）+ `web/chars.json`（字表）+ `web/fonts_meta.json`（font_id→名称/同源组）。
- **前端逻辑**（直接平移 `pipeline.match_char` 粗排部分）：
  1. canvas 取框 → 灰度 → 二值化（Otsu）→ 缩到 64×64 → `packbits` 成 512B 查询向量
  2. 对索引 `Uint8Array` 逐字体逐字 `popcount(a & b) / popcount(a | b)` 算 IoU
  3. 取 top-N 字体 → 加权投票（同源组归并，逻辑同 `pipeline.match`）
- **改动量**：新增 `web/match_client.js`（~150 行），`app.js` 把 `/api/match` 的 fetch 换成本地调用。服务端删 `/api/match` 或保留为降级。
- **精度损失**：放弃 SDF 平移对齐 + HOG 笔画方向，对**模糊/变形/粘连**字误判率升高；对清晰截图（"绿美创城"级）IoU 0.9+ 仍正确。

### 路线 B：字体渲染比对

- **数据**：下发子集字体 ~4MB（`fonts/subset/` 已有）+ opentype.js。
- **前端逻辑**：用户输入某字 → opentype.js 实时渲染该字参考字形 → 与用户框选图二值化后算 IoU/轮廓差。
- **代价**：每字要实时渲染 15 字体，查询慢（数十 ms/字）；且渲染字形与"真实字体截图"的笔画细节差异大，对识别 logo 字体反而更不准。
- **结论**：不如 A，除非要"无预计算索引"。

## 4. 推荐实施切片（最小可用）

**Phase 1 — 瘦索引导出（服务端 Python）**
- `src/indexer.py` 增加导出 `web/glyph_index.packbits` + `web/chars.json` + `web/fonts_meta.json`（复用现有 `_fonts_bin` 与 `font_ids/chars`，同源组 `DUP_GROUPS` 也导出）。
- 体积 28MB，gzip 后约 8–10MB（HTTP 可压缩）。

**Phase 2 — 前端比对模块**
- 新建 `web/match_client.js`：实现 `binarize64`、`packbits`、`popcount`、`matchChar(imageData, ch)`、`match(marks)`。
- `app.js` 的 `runMatch()` 改为优先调用本地 `match()`，仅当索引未加载时降级到 `/api/match`。

**Phase 3 — 同源归并 + 结果渲染**
- 把 `pipeline._group_of` + `META` 映射搬前端，结果卡片逻辑复用现有 `renderResult`。

**Phase 4 — 服务端瘦身（可选）**
- 部署时 `FONTOP_NO_OCR=1` + 不再加载 `glyph_index.npz`（只托管静态文件），服务端内存 → **<50MB**。
- 或直接把 `web/` 丢到任意静态托管（GitHub Pages / nginx / 对象存储），**完全无后端**。

## 5. 风险与已知天花板

- **精度天花板**：IoU 粗排对粘连/模糊字弱于 SDF 精排。若日后要精度，需在 WASM 里跑 SDF（成本陡增），或保留服务端精排作为"高精模式"。
- **首屏加载**：28MB 索引（gzip ~10MB）首次加载几秒，之后 `localStorage`/Cache 缓存。
- **同源字体**：Noto/思源字形相同的字体前端需归并展示，导出 `DUP_GROUPS` 即可。
- **字符集**：当前 3662 字，纯前端全扫 54930 次 popcount 没问题；若扩到 1 万字也仍是 ms 级。

## 6. 工作量估算

| 阶段 | 文件 | 估计 |
|---|---|---|
| P1 索引导出 | `src/indexer.py` | 0.5 天 |
| P2 前端比对 | `web/match_client.js`, `web/app.js` | 1 天 |
| P3 归并渲染 | `web/app.js` | 0.5 天 |
| P4 无后端部署 | `docs/DEPLOY.md` 补静态托管 | 0.5 天 |
| **合计** | | **~2.5 天** |

## 7. 决策点（待用户确认）

1. 接受"清晰度换零服务端内存"吗？（IoU 级精度）
2. 走路线 A（瘦索引 28MB）还是 B（字体渲染 4MB）？— 建议 A。
3. 自动识别（OCR）本期是否彻底不做前端、仅手动？— 建议仅手动。
4. P4 是否要"完全无后端"（纯静态托管），还是保留一个 <50MB 的轻服务端兜底？
