# 字体版权快查工具（FontCop）开发说明与计划 v2

> 本版基于对成熟方案（mixfont/lens、YuzuMarker.FontDetection、Fontke 识字体、WhatTheFont）与字形比对算法（SDF、RaySpace、Hausdorff、SSIM）的调研，将 v1 计划细化为可执行任务。

## 1. 项目目标

本地运行的截图小工具：**粘贴/拖入/截图 → 自动给出字体版权结论**。

三档输出：

| 结论 | 含义 | 附加信息 |
|---|---|---|
| ✅ 免费 | 命中开源字体白名单（高置信） | 字体名、许可证、来源链接 |
| 🤔 疑似 | 与某开源字体相似但不精确 | Top-3 开源候选 + 相似度 |
| ⚠️ 版权风险 | 与白名单全部不匹配 | 大概率商业字体 + 最接近的开源平替 |

## 2. 参照系统分析（调研结论）

### 2.1 mixfont/lens —— 推理管线参照
GitHub: mixfont/lens（2026-03，开源模型）。其 pipeline 结构直接可借鉴：

```
run_inference.py (CLI 入口)
  → lens_inference.py (OCR 找最大单词 + 预处理 + 模型推理)
  → ocr_word_detection.py (OCR 框检测)
  → font_metadata_mapper.py (标签 → 字体元数据映射)
  → 输出 JSON (top-k + 字体元数据)
```

**可借鉴点**：
1. **取"最大的词"识别**而非全文——显著文字块就是用户想识别的，天然规避混排问题
2. **元数据与模型解耦**（metadata mapper 单独一个文件），我们的 `fonts.json` 同理
3. **debug 模式输出中间产物**（预处理后图、OCR 框）——调试必备，第一版就做
4. OCR 失败时 fallback 到整图推理——我们也应 fallback 到让用户手动框选

### 2.2 Fontke（识字体网）—— 人工辅助交互参照
Fontke 的四步流程（纯人工切字，和我们第一版路线几乎一致）：

1. 上传图片（文件或 URL）
2. **预处理调节**：文字反白时点"反相"；整体过暗/过亮拖"阈值"滑块 → 二值化
3. **文字拼合**：汉字不相连笔画会被拆成多个部件，用户拖动拼合成完整单字；每个字下方输入"这是什么字"
4. 开始识别 → 按相似度倒序列出候选

**关键洞察**：Fontke 让用户输入"每个部件是什么字"——**这解决了我们的核心难题**！用户框选一个字并打出这个字（如"锋"），系统只需拿"锋"去和几百款字体的"锋"渲染比对，不需要 OCR 识别文字内容，也不需要猜字符。**第一版照抄此交互**。

### 2.3 WhatTheFont —— 全自动交互参照（第二版目标）
- 上传 → 自动检测文字区域 → 用户点击想识别的文字位置 → 出结果（<1 秒）
- 支持手动框选裁剪区域兜底
- UI 三步：上传（拖入虚框）→ 预览+旋转/裁切 → 右侧结果列表

**借鉴点**：拖入虚框上传区 + 左图右结果的布局 + 结果卡片带"相似度 + 字体预览样张"。

### 2.4 算法参照：RaySpace 博文（paultendo.github.io）
对比字形相似度的算法谱系：

| 算法 | 精度 | 成本 | 结论 |
|---|---|---|---|
| 像素 IoU（二值图交并比） | 低-中 | 极低 | 基线，对错位敏感 |
| SSIM | 中 | 低 | 对缩放/平移不鲁棒 |
| **SDF + NCC**（128×128 有符号距离场 + 归一化互相关） | **高**（实测同形异脚本字 NCC=1.0） | 中（可用 scipy 距离变换） | **主算法** |
| RaySpace 射线指纹 | 高 | 中 | 备选，需字体矢量解析 |
| Hausdorff（部分匹配版） | 中-高 | 中 | 备选 |

**决策：主算法用 SDF+NCC**。渲染单字 → 128×128 二值图 → `scipy.ndimage.distance_transform_edt` 算距离场 → 与索引中的 SDF 算 NCC。比 IoU 鲁棒得多（对笔画粗细、轻微错位不敏感），仍是纯 numpy/scipy 轻依赖。IoU 作为粗排（便宜），SDF+NCC 做精排（级联，参考 RaySpace 的 cascade 思路）。

### 2.5 字体库来源（白名单数据）
- **github.com/momofeng/chinese-fonts**：已整理的中文开源字体大合集（含 OSFCC、wumanzoo 免费字体索引合并），直接拿清单+下载链接
- **猫啃网 maoken.com/freefonts**：免费商用字体榜单（阿里普惠体、思源黑/宋、霞鹜文楷、得意黑、MiSans、OPPO Sans、荣耀 HONOR Sans、HarmonyOS Sans 等），按下载量排序优先收录
- **Google Fonts**：西文开源字体全量（构建脚本可批量拉取）
- 元数据每款记录：`名称 / 英文名 / 许可证(SIL-OFL/Apache/MIT/免费商用) / 来源URL / 风格标签(黑体/宋体/楷体/圆体/手写)`

### 2.6 数据集参照（测试用）
- gaborcselle/font-examples：字体截图样本集，可改造为我们测试图的生成基础
- 测试图自造更实际：**用每款白名单字体渲染汉字 + 加噪声/背景/缩放/低分辨率**，程序化生成回归测试集（lens 的做法相同）

## 3. 系统架构与运行逻辑

```
┌────────────────────────────────────────────────────────┐
│ UI（本地 Web，参照 WhatTheFont 布局）                      │
│  入口区：虚线拖拽框 + "⌘V 粘贴截图" + 截图按钮              │
│  标注区：图片上拖框选单字 + 键盘输入该字（参照 Fontke）       │
│  结果区：结论徽章(✅/🤔/⚠️) + 候选卡片(样张/相似度/许可证)   │
├────────────────────────────────────────────────────────┤
│ HTTP API（src/server.py，标准库 http.server）             │
│  POST /api/match      {image_b64, glyph, bbox[]} → 结论  │
│  GET  /api/fonts      白名单列表                          │
│  GET  /api/history    识别历史                            │
├────────────────────────────────────────────────────────┤
│ 识别管线 src/pipeline.py                                 │
│  1. 裁剪 bbox → 灰度 → 自适应二值化（参照 Fontke 反相/阈值）│
│  2. 外接框裁紧 + 等比缩放至 128×128（保持宽高比，居中留白）  │
│  3. 粗排：索引内 IoU 距离取前 50 款                        │
│  4. 精排：SDF→NCC 得最终相似度                             │
│  5. 多字投票：各字 Top-K 按 font 聚合，加权平均相似度        │
│  6. 三档判定：max_sim≥0.90→✅；≥0.75→🤔；否则→⚠️          │
├────────────────────────────────────────────────────────┤
│ 建库 src/indexer.py（一次性，产出 data/glyph_index.npz）   │
│  每款字体 × 500 常用字 → 渲染 128×128 → 存 SDF+二值图      │
├────────────────────────────────────────────────────────┤
│ 字体库 fonts/ + fonts.json（名称/许可证/来源/风格标签）     │
└────────────────────────────────────────────────────────┘
```

**运行逻辑（一次完整识别）**：
1. 用户 Cmd+Shift+4 截图 → `⌘V` 粘贴到网页（或拖入文件）
2. 网页 canvas 上拖框选一个字 → 弹出输入框，用户打出这个字（如"霁"）
3. 可继续框选更多字（2-5 个效果最好），点"开始识别"
4. 前端把原图 bbox 坐标 + 字符列表 POST `/api/match`
5. 服务端逐字走管线 → 投票 → 返回三档结论 + Top-5 候选（含该字在候选字体下的渲染样张供人眼复核）
6. 界面并排显示：用户原图的字 vs 各候选字体渲染的同一字——**人眼终审**（参照 Fontke 结果页）

**性能预算**：500 款字体索引常驻内存（npz 约 500×500×128×128×1B≈4GB 二值 + SDF float16 减半 → 实际存 SDF 即可 ≈4GB 偏大；**改为存 SDF 下采样 64×64 + 二值 64×64，≈1GB，可接受**；精排时对 Top-50 再算 128×128 SDF 实时比对）。单字粗排用 numpy 矩阵乘，<200ms；总响应 <3s。

## 4. 目录结构

```
font/
├── PLAN.md
├── README.md
├── fonts/                      # ttf/otf 文件
│   ├── fonts.json              # 白名单元数据（schema 见 §6.1）
│   └── download_list.json      # 来源清单（momofeng/chinese-fonts 等）
├── src/
│   ├── indexer.py              # 建库：渲染→SDF→npz
│   ├── pipeline.py             # 粗排+精排+投票+三档判定
│   ├── features.py             # 预处理/IoU/SDF/NCC
│   ├── render.py               # Pillow ImageFont 渲染封装
│   ├── server.py               # http.server + API + 静态托管
│   └── tray.py                 # (M3) 托盘+快捷键，pystray
├── web/
│   ├── index.html              # 单页应用，原生 JS，无框架
│   ├── app.js
│   └── style.css
├── tools/
│   ├── fetch_fonts.py          # 从下载清单批量拉字体
│   └── gen_testset.py          # 程序化生成测试图（噪声/背景/缩放）
├── data/
│   ├── glyph_index.npz         # 建好的索引
│   └── history.jsonl           # 识别历史
└── tests/
    ├── test_features.py        # SDF/NCC 数学正确性
    ├── test_pipeline_clean.py  # 干净渲染字 → Top1 命中率 >95%
    └── test_pipeline_noisy.py  # 截图模拟（噪声+背景+缩放）>75%
```

## 5. UI 参照与线框

参照 WhatTheFont 三步布局 + Fontke 标注步骤，单页从左到右：

```
┌──────────────────────────────────────────────────────────────┐
│  FontCop — 字体版权快查                [历史] [白名单]          │
├──────────────────────────────────────────────────────────────┤
│  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐      ┌──────────────────────┐ │
│  │   拖入图片 / ⌘V 粘贴截图    │      │ 结论：⚠️ 版权风险      │ │
│  │   [选择文件]  [截图]        │  →   │ ────────────────────  │ │
│  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘      │ 1. 思源黑体  NCC 0.62 │ │
│                                      │    [锋样张对比图]      │ │
│  （图片载入后变为 canvas 标注区）       │    SIL-OFL · Google   │ │
│  ┌────────────────────────────┐      │ 2. 阿里普惠体 0.58    │ │
│  │ canvas：拖框选字 → 输入该字  │      │ 3. MiSans    0.51    │ │
│  │ 已标注：锋✓ 霁✓             │      │ ────────────────────  │ │
│  │ [开始识别] [重置]           │      │ 💡 最接近的开源平替：   │ │
│  └────────────────────────────┘      │    思源黑体 (0.62)    │ │
└──────────────────────────────────────────────────────────────┘
```

- 拖框选字后弹出小输入框（参照 Fontke"文字拼合"步），回车确认
- 结果卡片：字体样张（用被识别的字渲染）、NCC 相似度条、许可证徽章、来源链接
- 顶部 [截图] 按钮调 macOS `screencapture -c`（截图进剪贴板，网页自动读取）——M3 前先靠系统快捷键+⌘V

## 6. 数据与接口定义

### 6.1 fonts.json schema
```json
{
  "id": "source-han-sans",
  "name": "思源黑体",
  "en_name": "Source Han Sans",
  "license": "SIL-OFL",
  "commercial_free": true,
  "style": "sans",
  "source_url": "https://github.com/adobe-fonts/source-han-sans",
  "file": "SourceHanSansSC-Regular.otf",
  "weights": ["Regular", "Bold"]
}
```

### 6.2 POST /api/match
```json
// 请求
{ "image_b64": "...",
  "marks": [ {"bbox": [x1,y1,x2,y2], "char": "锋"}, ... ] }
// 响应
{ "verdict": "free|suspect|risky",
  "confidence": 0.93,
  "candidates": [
    {"font_id": "...", "name": "思源黑体", "license": "SIL-OFL",
     "score": 0.93, "votes": 3,
     "sample_png_b64": "..."} ],
  "per_char": [ {"char": "锋", "top": [...] } ] }
```

## 7. 里程碑与任务拆解

### M0：环境与字体库（0.5 天）
- [ ] `tools/fetch_fonts.py`：按 `download_list.json` 批量下载（先手工精选 20 款：思源黑/宋、霞鹜文楷、得意黑、阿里普惠体、MiSans、HONOR Sans、OPPO Sans、HarmonyOS Sans、猫啃系 5 款、西文 Inter/Roboto/Noto Sans）
- [ ] `fonts/fonts.json` 逐款填元数据（许可证、来源）
- [ ] 校验每个 ttf 能被 Pillow 渲染、含 500 常用字 cmap（fontTools 检查，缺失字记入 fonts.json 的 coverage 字段）
- **验收**：`python tools/fetch_fonts.py` 一键可重建；20+ 款字体全部可渲染

### M1：比对引擎（1.5 天）
- [ ] `render.py`：渲染任意字→128×128 二值图（紧裁+居中留白）；64×64 SDF 计算（scipy distance_transform_edt）
- [ ] `features.py`：IoU、NCC（含 SDF 归一化）、三档阈值常量
- [ ] `indexer.py`：每款字体渲染 500 字 → 存 `glyph_index.npz`（二值 64×64 uint8 + SDF 64×64 float16）
- [ ] `pipeline.py`：粗排(IoU, top50) → 精排(SDF+NCC, top5)；单字 + 多字投票
- [ ] `tools/gen_testset.py`：程序化生成测试图（纯渲染 / +高斯噪声 / +纯色背景 / +缩放0.5-2x / +JPEG压缩）
- [ ] `tests/` 三组回归测试
- **验收**：干净图 Top-1 命中率 ≥95%；噪声图 Top-5 命中率 ≥80%；单字比对 <300ms
- **降级预案**：若 NCC 在噪声图不达标 → 引入Raycast笔画方向特征或换 CLIP-ViT embedding（接口预留 `features.py:embed()`）

### M2：Web 界面（1.5 天）
- [ ] `server.py`：`python -m src.server` 启动，托管 web/ + API；剪贴板图片上传接口
- [ ] `index.html/app.js`：粘贴(⌘V)/拖拽/选文件 三入口 → canvas 标注区（框选+输入字）→ 结果区（三档徽章+候选卡片+样张对比）
- [ ] 样张对比：服务端返回候选字体渲染同字的 PNG，原图字与候选字并排
- [ ] `data/history.jsonl` 识别历史 + [历史] 弹层
- **验收**：截图→⌘V→框两个字→出结论，全程 <5s；无控制台操作

### M3：截图工具化（1 天）
- [ ] `tray.py`：pystray 托盘图标，菜单[截图识别/打开界面/退出]
- [ ] 全局快捷键（如 ⌥F）→ 调系统 `screencapture -i -c`（交互截图进剪贴板）→ 自动打开/聚焦网页并触发粘贴识别
- [ ] 启动脚本 `start.sh`：起 server + tray，登录自启（launchd plist，可选）
- **验收**：快捷键→截图→弹窗出结论，全程 <8s，无终端窗口

### M4：增强（按需，每个独立小项）
- [ ] 全自动模式：RapidOCR(onnxruntime) 检测文字行，免手动框选（照抄 lens 的"取最大文字块"策略）；保留手动模式兜底
- [ ] 白名单扩至 1000+：Google Fonts 批量 + momofeng/chinese-fonts 全量；索引分片加载
- [ ] 整行多字自动切分投票（横向投影切字）
- [ ] PyInstaller 打包单可执行（可选，indexer/字体资源打入）

## 8. 依赖清单（最终确认）

| 阶段 | 依赖 | 用途 |
|---|---|---|
| 全部 | pillow | 字体渲染 |
| 全部 | numpy | 特征计算 |
| M1 | scipy | 距离变换（SDF） |
| 建库 | fontTools | cmap 覆盖检查 |
| M3 可选 | pystray | 托盘 |
| M4 可选 | rapidocr-onnxruntime | 全自动切字 |

无 PyTorch、无 Paddle、无云 API。核心识别 = pillow+numpy+scipy 三个轻依赖。

## 9. 已知局限与标注

1. "不匹配=版权字体"是推断：冷门免费字体可能误报 ⚠️——界面固定文案"字形级比对结果，仅供参考，不构成法律意见"
2. 同源双版本（免费商用版 vs 收费版）字形极近，结论标 🤔 而非 ✅
3. 书法/手写/变形艺术字置信度下降——per_char 中单独降权
4. 第一版需手动框选+输入字（Fontke 同款交互），全自动属 M4

## 10. 立即开始

按 M0 → M1 顺序执行：先拉 20 款字体建元数据，再实现 render/features/indexer/pipeline + 回归测试，用数据验证比对算法达标后进入界面开发。
