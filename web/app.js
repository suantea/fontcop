/* FontCop 前端逻辑：粘贴/拖拽/选文件 → canvas 框选字+输入该字 → 识别 → 结果卡片 */
(() => {
  const $ = (id) => document.getElementById(id);

  // HTML 转义：所有拼进 innerHTML 的用户/外部数据都必须过 esc()，防自 XSS/破版
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  let img = null;            // 当前 Image 对象
  let marks = [];            // [{x1,y1,x2,y2,char}]
  let pendingBox = null;     // 正在框选的区域
  let inFlight = null;       // 进行中的 fetch AbortController（重置/超时时可中断）
  let suppressErr = false;   // 重置主动中止时不弹错误提示

  // 带超时的 fetch：避免「卡在自动识别中」——超时/服务无响应时一定给出提示并恢复按钮
  function fetchTimeout(url, init, ms) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(new DOMException("timeout", "TimeoutError")), ms);
    inFlight = ctrl;
    return fetch(url, { ...init, signal: ctrl.signal }).finally(() => {
      clearTimeout(t);
      if (inFlight === ctrl) inFlight = null;
    });
  }

  function errText(err) {
    if (suppressErr || err && err.name === "AbortError") return null;
    if (err && err.name === "TimeoutError") return "识别超时（服务忙或无响应），请重试";
    const m = err && err.message;
    if (m && /load failed|failed to fetch|networkerror/i.test(m)) return "网络错误：服务无响应（请确认服务在运行后重试）";
    return m || String(err);
  }

  function resetAll() {
    suppressErr = true;
    if (inFlight) { try { inFlight.abort(); } catch { /* ignore */ } inFlight = null; }
    img = null; marks = []; pendingBox = null; dragStart = null;
    $("dropzone").hidden = false;
    $("canvas-wrap").hidden = true;
    $("result").hidden = true;
    $("result-empty").hidden = false;
    $("btn-auto").disabled = false;
    $("btn-run").disabled = true;
    updateMarks();
    suppressErr = false;
  }

  // ---------- 图片载入 ----------
  function loadImageFile(file) {
    const url = URL.createObjectURL(file);
    const im = new Image();
    im.onload = () => { img = im; marks = []; showCanvas(); };
    im.src = url;
  }

  function showCanvas() {
    $("dropzone").hidden = true;
    $("canvas-wrap").hidden = false;
    $("result").hidden = true;
    $("result-empty").hidden = false;
    redraw();
    updateMarks();
  }

  const canvas = $("canvas");
  const ctx = canvas.getContext("2d");

  function redraw(previewBox) {
    if (!img) return;
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    ctx.drawImage(img, 0, 0);
    // 已标注框
    ctx.strokeStyle = "#3b6ef5"; ctx.lineWidth = 2;
    for (const m of marks) {
      ctx.strokeRect(m.x1, m.y1, m.x2 - m.x1, m.y2 - m.y1);
      ctx.fillStyle = "#3b6ef5";
      ctx.font = "16px sans-serif";
      ctx.fillText(m.char, m.x1 + 2, m.y1 - 4 < 16 ? m.y1 + 18 : m.y1 - 4);
    }
    if (previewBox) {
      ctx.strokeStyle = "#ff7d00";
      ctx.strokeRect(previewBox.x1, previewBox.y1, previewBox.x2 - previewBox.x1, previewBox.y2 - previewBox.y1);
    }
  }

  function updateMarks() {
    $("marks-info").textContent = marks.length
      ? "已标注：" + marks.map(m => m.char).join(" ")
      : "已标注：无（在图上拖框选字）";
    $("btn-run").disabled = marks.length === 0;
  }

  // ---------- 交互入口 ----------
  $("dropzone").onclick = () => $("file-input").click();
  $("btn-file").onclick = (e) => { e.stopPropagation(); $("file-input").click(); };
  $("file-input").onchange = (e) => e.target.files[0] && loadImageFile(e.target.files[0]);

  const dz = $("dropzone");
  dz.ondragover = (e) => { e.preventDefault(); dz.classList.add("dragover"); };
  dz.ondragleave = () => dz.classList.remove("dragover");
  dz.ondrop = (e) => {
    e.preventDefault(); dz.classList.remove("dragover");
    if (e.dataTransfer.files[0]) loadImageFile(e.dataTransfer.files[0]);
  };

  // 页面级粘贴（Ctrl+V）：加载图片后自动识别，实现连续使用
  document.addEventListener("paste", (e) => {
    for (const item of e.clipboardData.items) {
      if (item.type.startsWith("image/")) {
        const blob = item.getAsFile();
        const im = new Image();
        im.onload = async () => {
          img = im; marks = []; showCanvas();
          await doAutoRecognize(await autoImageB64(img));
        };
        im.src = URL.createObjectURL(blob);
        e.preventDefault();
        return;
      }
    }
  });

  // ---------- 框选 ----------
  let dragStart = null;
  canvas.addEventListener("mousedown", (e) => {
    if (!img) return;
    const r = canvas.getBoundingClientRect();
    const sx = canvas.width / r.width, sy = canvas.height / r.height;
    const px = (e.clientX - r.left) * sx, py = (e.clientY - r.top) * sy;
    // 点中已有标注框 → 删除该框
    const hit = marks.findIndex((m) => px >= m.x1 && px <= m.x2 && py >= m.y1 && py <= m.y2);
    if (hit >= 0) {
      marks.splice(hit, 1);
      redraw(); updateMarks();
      dragStart = null;
      return;
    }
    dragStart = { x: px, y: py, sx, sy };
  });
  canvas.addEventListener("mousemove", (e) => {
    if (!dragStart) return;
    const r = canvas.getBoundingClientRect();
    const x2 = (e.clientX - r.left) * dragStart.sx, y2 = (e.clientY - r.top) * dragStart.sy;
    pendingBox = norm({
      x1: dragStart.x, y1: dragStart.y, x2, y2,
    });
    redraw(pendingBox);
  });
  canvas.addEventListener("mouseup", () => {
    if (!pendingBox || pendingBox.x2 - pendingBox.x1 < 8 || pendingBox.y2 - pendingBox.y1 < 8) {
      pendingBox = null; redraw(); return;
    }
    openCharDialog(pendingBox);
    dragStart = null;
  });

  function norm(b) {
    return { x1: Math.min(b.x1, b.x2), y1: Math.min(b.y1, b.y2), x2: Math.max(b.x1, b.x2), y2: Math.max(b.y1, b.y2) };
  }

  // ---------- 字符输入浮层 ----------
  function openCharDialog(box) {
    const r = canvas.getBoundingClientRect();
    const d = $("char-dialog");
    d.style.left = Math.min(window.innerWidth - 240, r.left + box.x2 * (r.width / canvas.width) + 10) + "px";
    d.style.top = Math.max(10, r.top + box.y1 * (r.height / canvas.height)) + "px";
    d.hidden = false;
    $("char-input").value = "";
    $("char-input").focus();
  }
  function closeCharDialog() { $("char-dialog").hidden = true; pendingBox = null; redraw(); }

  function confirmChar() {
    const ch = $("char-input").value.trim()[0];
    if (!ch) return;
    // 同一字符只保留一个标注：已有该字时替换为新框
    const dup = marks.findIndex((m) => m.char === ch);
    if (dup >= 0) marks.splice(dup, 1);
    marks.push({ ...pendingBox, char: ch });
    closeCharDialog();
    updateMarks();
  }
  $("char-ok").onclick = confirmChar;
  $("char-cancel").onclick = closeCharDialog;
  $("char-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") confirmChar();
    if (e.key === "Escape") closeCharDialog();
  });

  $("btn-reset").onclick = resetAll;

  // ---------- 识别 ----------
  async function cropAndSend() {
    $("btn-run").disabled = true;
    $("marks-info").textContent = "识别中…";
    const payloadMarks = [];
    for (const m of marks) {
      const c = document.createElement("canvas");
      c.width = Math.round(m.x2 - m.x1);
      c.height = Math.round(m.y2 - m.y1);
      c.getContext("2d").drawImage(img, m.x1, m.y1, c.width, c.height, 0, 0, c.width, c.height);
      const blob = await new Promise((res) => c.toBlob(res, "image/png"));
      const b64 = btoa(String.fromCharCode(...new Uint8Array(await blob.arrayBuffer())));
      payloadMarks.push({ image_b64: b64, char: m.char });
    }
    try {
      const resp = await fetchTimeout("/api/match", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ marks: payloadMarks }),
      }, 20000);
      renderResult(await resp.json());
    } catch (err) {
      const m = errText(err);
      if (m) $("marks-info").textContent = "识别失败：" + m;
    } finally {
      $("btn-run").disabled = marks.length === 0;
    }
  }
  $("btn-run").onclick = cropAndSend;

   // ---------- 自动识别（RapidOCR）----------
   // 复用：把“编码→POST→渲染”抽成函数，避免按钮和粘贴重复代码
   const MAX_AUTO_EDGE = 1600;  // 发送前把整图缩到该边长：4K 截图原图 base64 可 >16MB 击穿请求体上限，且 OCR 对超大图反而检出更差
   async function autoImageB64(inIm) {
     const w = inIm.naturalWidth, h = inIm.naturalHeight;
     const scale = Math.min(1, MAX_AUTO_EDGE / Math.max(w, h));
     const c = document.createElement("canvas");
     c.width = Math.max(1, Math.round(w * scale));
     c.height = Math.max(1, Math.round(h * scale));
     c.getContext("2d").drawImage(inIm, 0, 0, c.width, c.height);
     const blob = await new Promise((res) => c.toBlob(res, "image/png"));
     return btoa(String.fromCharCode(...new Uint8Array(await blob.arrayBuffer())));
   }
async function doAutoRecognize(b64) {
     const btn = $("btn-auto");
     btn.disabled = true;
     $("marks-info").textContent = "自动识别中…";
     try {
       const resp = await fetchTimeout("/api/auto", {
         method: "POST",
         headers: { "Content-Type": "application/json" },
         body: JSON.stringify({ image_b64: b64 }),
       }, 60000);
       const r = await resp.json();
       if (r.error) {
         $("marks-info").textContent = "自动识别失败：" + r.error;
         renderResult(r);  // 上屏中性失败态，避免残留上一条判定
         return;
       }
       if (r.chars_used) $("marks-info").textContent = "自动使用字符：" + r.chars_used.join(" ");
       renderResult(r);
     } catch (err) {
       const m = errText(err);
       if (m) $("marks-info").textContent = "自动识别失败：" + m + "（可回退手动框选）";
     } finally {
       btn.disabled = false;
     }
   }
   $("btn-auto").onclick = async () => {
     if (!img) return;
     await doAutoRecognize(await autoImageB64(img));
   };

  // ---------- 结果渲染 ----------
  const VERDICTS = {
    free: ["✅ 免费字体", "命中开源白名单，可放心使用"],
    suspect: ["🤔 疑似免费", "与开源字体相似但非精确匹配"],
    risky: ["⚠️ 版权风险", "与白名单不匹配，大概率是商业版权字体"],
    unknown: ["❓ 无法判断", "未识别到可比的字，需手动框选或更换截图"],
  };

  function renderResult(r) {
    $("result-empty").hidden = true;
    $("result").hidden = false;
    const v = $("verdict");
    if (r.error) {
      // 失败：上屏中性态，不残留上一条的判定颜色/内容（README：失败不残留）
      v.className = "unknown";
      v.innerHTML = `<span class="v-sub">❓ 识别失败：${esc(r.error)}</span>`;
      $("candidates").innerHTML = "";
      return;
    }

    // 字体名映射 font_id→名称：从响应自带候选+逐字 top 构建（避免图表渲染时 nameById 未定义导致误报“识别失败”且残留虚假判定）
    const nameById = {};
    (r.candidates || []).forEach((c) => { if (c && c.font_id && (c.name || c.font_id)) nameById[c.font_id] = c.name || c.font_id; });
    (r.per_char || []).forEach((row) => (row.top || []).forEach((t) => { if (t && t.font_id && !nameById[t.font_id]) nameById[t.font_id] = t.name || t.font_id; }));

    const [label, desc] = VERDICTS[r.verdict] || ["?", ""];
    v.className = r.verdict;
    v.innerHTML = `${label} <span class="v-sub">相似度 ${Math.round(r.confidence * 100)}% · ${r.elapsed}s · ${desc}（字形级比对，仅供参考）</span>`;

    // ---------- 逐字比对：堆叠横条图（每个字一段，段内按候选字体得分比例着色）----------
    const cnvColors = ["#3b6ef5", "#f7ba1e", "#7b61ff", "#10b981", "#ff7d00", "#ef4444", "#0fc6c2", "#fd18a8", "#98a2b8", "#722ed1"];
    const cnvColorOf = (fid) => {
      let h = 0;
      for (let i = 0; i < fid.length; i++) h = ((h << 5) - h + fid.charCodeAt(i)) | 0;
      return cnvColors[Math.abs(h) % cnvColors.length];
    };
    const pcAll = (r.per_char || []);
    const concl = (r.candidates || [])[0];
    const conclFid = concl ? concl.font_id : null;
    const conclName = concl ? concl.name : "";
    // 图例：颜色 → 字体名（按出现顺序去重）
    const legend = [];
    pcAll.forEach((row) => {
      (row.top || []).forEach((t) => { if (t && !legend.some((l) => l.fid === t.font_id)) legend.push({ fid: t.font_id, name: nameById[t.font_id] || t.font_id }); });
    });
    const legendHtml = legend.map((l) => `<span class="pc-lg" title="${esc(l.name)}"><i style="background:${cnvColorOf(l.fid)}"></i>${esc(l.name)}</span>`).join("");
    // 每个字一行：字符 + 堆叠条 + 顶选
    const chartRows = pcAll.map((row) => {
      const tops = (row.top || []).slice(0, 3).filter((t) => t);
      if (!tops.length) return "";
      const sum = tops.reduce((a, t) => a + Math.max(0, t.score), 0) || 1;
      const segs = tops.map((t) => {
        const w = Math.max(0, t.score) / sum * 100;
        const nm = nameById[t.font_id] || t.font_id;
        return `<span class="pc-seg" style="width:${w}%;background:${cnvColorOf(t.font_id)}" title="${esc(row.char)} → ${esc(nm)} ${Math.round(t.score * 100)}%"></span>`;
      }).join("");
      const t0 = tops[0];
      const nm0 = nameById[t0.font_id] || t0.font_id;
      const sameFont = t0.font_id === conclFid;
      return `<div class="pc-row">
          <span class="pc-char">${esc(row.char)}</span>
          <span class="pc-bar">${segs}</span>
          <span class="pc-top ${sameFont ? "pc-top-same" : "pc-top-diff"}" title="${sameFont ? "与汇总结论一致" : "与汇总结论不同"}">${esc(nm0)} ${Math.round(t0.score * 100)}%</span>
        </div>`;
    }).join("");
    const diffs = pcAll.filter((row) => { const t = (row.top || [])[0]; return t && t.font_id !== conclFid; });
    const pcHtml = (concl && pcAll.length) ? `<div class="pc-box">
        <button type="button" class="pc-toggle" aria-expanded="false">
          <span class="pc-arrow">▸</span>
          ${VERDICTS[r.verdict]?.[0] || "汇总"} → <b>${esc(conclName)}</b>
          <span class="pc-votes">${pcAll.length} 字投票</span>
        </button>
        <div class="pc-body" hidden>
        ${pcAll.length <= 18 ? `<div class="pc-chart">${chartRows}</div>` : chartRows}
        ${legendHtml ? `<div class="pc-legend">${legendHtml}</div>` : ""}
        ${diffs.length ? `<div class="pc-detail">不同于汇总结论的字：${diffs.map((row) => {
          const t = (row.top || [])[0];
          if (!t) return "";
          const nm = nameById[t.font_id] || t.font_id;
          return `<span class="chip chip-diff">${esc(row.char)}→${esc(nm)}</span>`;
        }).join(" ")}</div>` : ""}
        </div>
      </div>` : "";

    // 按相似度降序展示（后端已排序，这里保险再排一次）
    const sortedCands = [...(r.candidates || [])].sort((a, b) => b.score - a.score);
    $("candidates").innerHTML = pcHtml + sortedCands.map((c, i) => {
      const pct = Math.round(c.score * 100);
      const sample = c.sample_png_b64 ? `<img src="data:image/png;base64,${esc(c.sample_png_b64)}" alt="">` : "";
      return `<div class="cand-card">${sample}
        <div class="info">
          <div class="name">${i + 1}. ${esc(c.name)}</div>
          <div class="meta" title="${esc(c.name)} · ${esc(c.license)} 许可证 · ${c.votes} 票（识别到的字投给该字体的数量）"><a href="#" class="lic-link" data-lic="${esc(c.license)}">${esc(c.license)}</a> · <span title="${c.votes} 票 = 本次识别到的字中投给该字体的数量">${c.votes} 票</span> · <a href="${esc(c.source_url)}" target="_blank">来源</a></div>
          <div class="bar"><div style="width:${pct}%"></div></div>
        </div>
        <div class="score">${pct}%</div>
      </div>`;
    }).join("");

    // 逐字汇总折叠条：点击展开/收起
    document.querySelectorAll(".pc-toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        const body = btn.parentElement.querySelector(".pc-body");
        const open = body.hidden;
        body.hidden = !open;
        btn.setAttribute("aria-expanded", String(open));
        btn.querySelector(".pc-arrow").textContent = open ? "▾" : "▸";
      });
    });
  }

  // ---------- 白名单 / 关于弹层 ----------
  $("modal-fonts").addEventListener("click", (e) => { if (e.target === e.currentTarget) $("modal-fonts").hidden = true; });
  $("modal-about").addEventListener("click", (e) => { if (e.target === e.currentTarget) $("modal-about").hidden = true; });
  $("fonts-close").onclick = () => $("modal-fonts").hidden = true;
  $("about-close").onclick = () => $("modal-about").hidden = true;
  $("btn-about").onclick = () => { $("modal-about").hidden = false; };

  // ---------- 开源协议说明弹层（点候选卡片里的协议名触发）----------
  const LICENSE_INFO = {
    "SIL-OFL": {
      title: "SIL Open Font License 1.1",
      html: `<p class="modal-note"><b>最常用的开源字体协议。</b>可以：</p>
      <p class="modal-note">✅ 个人及商业免费使用 · ✅ 嵌入文档/网页/App · ✅ 自行修改（需改名）</p>
      <p class="modal-note"><b>要求：</b>单独出售字体文件本身是被禁止的；修改版必须换名并以同协议发布。字体随软件打包分发时需附带许可证文本。</p>`,
    },
    "free-commercial": {
      title: "免费商用授权",
      html: `<p class="modal-note"><b>厂商自行声明的免费商用授权</b>（如站酷系列）。</p>
      <p class="modal-note">✅ 个人及商业免费使用</p>
      <p class="modal-note"><b>注意：</b>协议内容以官网声明为准，通常禁止单独出售字体文件、禁止包含在收费字体包里转售。</p>`,
    },
    "free": {
      title: "自由字体许可",
      html: `<p class="modal-note"><b>允许自由使用与分发的字体许可</b>（如 DejaVu Fonts License，类 BSD）。</p>
      <p class="modal-note">✅ 个人及商业免费使用 · ✅ 修改与再分发</p>
      <p class="modal-note"><b>要求：</b>保留版权与许可声明。</p>`,
    },
  };
  $("license-close").onclick = () => $("modal-license").hidden = true;
  $("modal-license").addEventListener("click", (e) => { if (e.target === e.currentTarget) $("modal-license").hidden = true; });
  document.addEventListener("click", (e) => {
    const link = e.target.closest(".lic-link");
    if (!link) return;
    e.preventDefault();
    const info = LICENSE_INFO[link.dataset.lic] || {
      title: link.dataset.lic,
      html: `<p class="modal-note">该字体使用自定义许可（${link.dataset.lic}），请点「来源」查看字体官方页面的授权说明。</p>`,
    };
    $("license-title").childNodes[0].textContent = info.title + " ";
    $("license-body").innerHTML = info.html;
    $("modal-license").hidden = false;
  });

  $("btn-fonts").onclick = async () => {
    $("modal-fonts").hidden = false;
    $("fonts-list").innerHTML = "<span class='muted'>加载中…</span>";
    try {
      const r = await (await fetch("/api/fonts")).json();
      $("fonts-count").textContent = r.fonts.length;
      $("fonts-list").innerHTML = r.fonts.map(f =>
        `<div class="font-row"><span>${esc(f.name)} <span class="lic">${esc(f.style)}</span></span><span class="lic">${esc(f.license)}</span></div>`).join("");
    } catch { $("fonts-list").innerHTML = "<span class='muted'>加载失败</span>"; }
  };

  // ---------- ?selftest 自检钩子（供 headless 测试用，不影响正常使用）----------
  async function runSelfTest() {
    const t = (name, pass, detail) => ({ name, pass: !!pass, detail: detail || "" });
    const results = [];
    try {
      // 1. 弹层初始状态：hidden 属性存在且实际不可见
      const mf = $("modal-fonts"), ma = $("modal-about");
      results.push(t("fonts-modal hidden attr", mf.hidden));
      results.push(t("about-modal hidden attr", ma.hidden));
      results.push(t("fonts-modal invisible", getComputedStyle(mf).display === "none"));
      results.push(t("about-modal invisible", getComputedStyle(ma).display === "none"));
      // 2. 打开白名单弹层
      mf.hidden = false;
      results.push(t("fonts-modal opens", !mf.hidden && getComputedStyle(mf).display !== "none"));
      // 3. 点关闭按钮 → 弹层关闭（核心回归点）
      $("fonts-close").click();
      results.push(t("fonts-modal closes via button", mf.hidden && getComputedStyle(mf).display === "none"));
      // 4. 点遮罩关闭
      mf.hidden = false;
      mf.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      results.push(t("fonts-modal closes via backdrop", mf.hidden));
      // 5. 关于弹层：按钮打开、标题含许可证声明
      $("btn-about").click();
      results.push(t("about-modal opens", !ma.hidden && /MIT License/.test(ma.innerHTML)));
      $("about-close").click();
      results.push(t("about-modal closes via button", ma.hidden));
      // 5. dropzone 初始可见、canvas 初始隐藏
      results.push(t("dropzone visible", !$("dropzone").hidden));
      results.push(t("canvas-wrap hidden", $("canvas-wrap").hidden));
      // 6. API 连通性
      try {
        const fr = await fetch("/api/fonts"); const fj = await fr.json();
        results.push(t("api/fonts ok", fr.ok && fj.fonts.length > 0, `${fj.fonts.length} fonts`));
      } catch (e) { results.push(t("api/fonts ok", false, String(e))); }
    } catch (e) {
      results.push(t("selftest crashed", false, String(e)));
    }
    document.title = "SELFTEST:" + JSON.stringify(results);
    return results;
  }
  if (new URLSearchParams(location.search).has("selftest")) {
    window.__fontcopSelfTest = runSelfTest;
    runSelfTest();
  }
  // ?demo：复现"识别后带错误提示 + 大图载入"的布局状态（供截图诊断）
  if (new URLSearchParams(location.search).has("demo")) {
    const c = document.createElement("canvas");
    c.width = 1400; c.height = 900;
    const g = c.getContext("2d");
    g.fillStyle = "#fff"; g.fillRect(0, 0, 1400, 900);
    g.fillStyle = "#000"; g.font = "120px sans-serif"; g.fillText("清深度锋说", 60, 300);
    c.toBlob((blob) => {
      loadImageFile(new File([blob], "demo.png", { type: "image/png" }));
      setTimeout(() => {
        $("marks-info").textContent = "自动识别失败：…config.yaml does not exist!（可回退手动框选）";
        renderResult({ error: "/private/var/folders/.../rapidocr_onnxruntime/config.yaml does not exist!" });
        // 布局探测：检查大图是否撑爆布局
        setTimeout(() => {
          const cw = $("canvas-wrap").getBoundingClientRect().width;
          const right = document.getElementById("right").getBoundingClientRect().width;
          document.title = "LAYOUT:" + JSON.stringify({
            winW: window.innerWidth,
            canvasAttrW: canvas.width,
            canvasCssW: Math.round(canvas.getBoundingClientRect().width),
            canvasWrapW: Math.round(cw),
            rightW: Math.round(right),
            bodyScrollW: document.body.scrollWidth,
          });
        }, 200);
      }, 300);
    });
  }
})();
