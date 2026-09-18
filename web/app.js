/* FontCop 前端逻辑：粘贴/拖拽/选文件 → canvas 框选字+输入该字 → 识别 → 结果卡片 */
(() => {
  const $ = (id) => document.getElementById(id);

  let img = null;            // 当前 Image 对象
  let marks = [];            // [{x1,y1,x2,y2,char}]
  let pendingBox = null;     // 正在框选的区域

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
    ctx.strokeStyle = "#165dff"; ctx.lineWidth = 2;
    for (const m of marks) {
      ctx.strokeRect(m.x1, m.y1, m.x2 - m.x1, m.y2 - m.y1);
      ctx.fillStyle = "#165dff";
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

  document.addEventListener("paste", (e) => {
    for (const item of e.clipboardData.items) {
      if (item.type.startsWith("image/")) {
        loadImageFile(item.getAsFile());
        break;
      }
    }
  });

  // 页面加载/聚焦时自动读取剪贴板截图（配合托盘"截图识别"流程）
  async function tryClipboardImage() {
    try {
      const items = await navigator.clipboard.read();
      for (const item of items) {
        const type = item.types.find((t) => t.startsWith("image/"));
        if (type) {
          const blob = await item.getType(type);
          if (img === null) loadImageFile(blob);  // 不覆盖已在编辑的图
          return;
        }
      }
    } catch { /* 无权限或剪贴板无图：静默忽略，用户可 ⌘V */ }
  }
  window.addEventListener("focus", tryClipboardImage);

  // ---------- 框选 ----------
  let dragStart = null;
  canvas.addEventListener("mousedown", (e) => {
    if (!img) return;
    const r = canvas.getBoundingClientRect();
    const sx = canvas.width / r.width, sy = canvas.height / r.height;
    dragStart = { x: (e.clientX - r.left) * sx, y: (e.clientY - r.top) * sy, sx, sy };
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

  $("btn-reset").onclick = () => { marks = []; redraw(); updateMarks(); };

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
      const resp = await fetch("/api/match", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ marks: payloadMarks }),
      });
      renderResult(await resp.json());
    } catch (err) {
      $("marks-info").textContent = "识别失败：" + err.message;
    }
    updateMarks();
  }
  $("btn-run").onclick = cropAndSend;

  // ---------- 自动识别（RapidOCR）----------
  $("btn-auto").onclick = async () => {
    if (!img) return;
    $("btn-auto").disabled = true;
    $("marks-info").textContent = "自动识别中…";
    const c = document.createElement("canvas");
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    c.getContext("2d").drawImage(img, 0, 0);
    const blob = await new Promise((res) => c.toBlob(res, "image/png"));
    const b64 = btoa(String.fromCharCode(...new Uint8Array(await blob.arrayBuffer())));
    try {
      const resp = await fetch("/api/auto", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image_b64: b64 }),
      });
      const r = await resp.json();
      if (r.chars_used) $("marks-info").textContent = "自动使用字符：" + r.chars_used.join(" ");
      renderResult(r);
    } catch (err) {
      $("marks-info").textContent = "自动识别失败：" + err.message + "（可回退手动框选）";
    }
    $("btn-auto").disabled = false;
  };

  // ---------- 结果渲染 ----------
  const VERDICTS = {
    free: ["✅ 免费字体", "命中开源白名单，可放心使用"],
    suspect: ["🤔 疑似免费", "与开源字体相似但非精确匹配"],
    risky: ["⚠️ 版权风险", "与白名单不匹配，大概率是商业版权字体"],
  };

  function renderResult(r) {
    $("result-empty").hidden = true;
    $("result").hidden = false;
    if (r.error) { $("verdict").textContent = "错误：" + r.error; return; }

    const [label, desc] = VERDICTS[r.verdict] || ["?", ""];
    const v = $("verdict");
    v.className = r.verdict;
    v.innerHTML = `${label} <span style="font-size:13px;font-weight:normal">相似度 ${Math.round(r.confidence * 100)}% · ${r.elapsed}s · ${desc}（字形级比对，仅供参考）</span>`;

    $("candidates").innerHTML = r.candidates.map((c, i) => {
      const pct = Math.round(c.score * 100);
      const sample = c.sample_png_b64 ? `<img src="data:image/png;base64,${c.sample_png_b64}" alt="">` : "";
      return `<div class="cand-card">${sample}
        <div class="info">
          <div class="name">${i + 1}. ${c.name}</div>
          <div class="meta">${c.license} · ${c.votes} 票 · <a href="${c.source_url}" target="_blank">来源</a></div>
          <div class="bar"><div style="width:${pct}%"></div></div>
        </div>
        <div class="score">${pct}%</div>
      </div>`;
    }).join("");
  }

  // ---------- 历史 / 白名单弹层 ----------
  $("modal-history").addEventListener("click", (e) => { if (e.target === e.currentTarget) $("modal-history").hidden = true; });
  $("modal-fonts").addEventListener("click", (e) => { if (e.target === e.currentTarget) $("modal-fonts").hidden = true; });
  $("history-close").onclick = () => $("modal-history").hidden = true;
  $("fonts-close").onclick = () => $("modal-fonts").hidden = true;

  $("btn-history").onclick = async () => {
    $("modal-history").hidden = false;
    $("history-list").innerHTML = "<span class='muted'>加载中…</span>";
    try {
      const r = await (await fetch("/api/history")).json();
      $("history-list").innerHTML = r.history.length
        ? r.history.map(h => `<div class="hist-row"><span>${h.ts} · 「${h.chars.join("")}」</span>
            <span class="v-${h.verdict}">${h.verdict === "free" ? "✅" : h.verdict === "suspect" ? "🤔" : "⚠️"} ${h.top} ${Math.round(h.score * 100)}%</span></div>`).join("")
        : "<span class='muted'>暂无记录</span>";
    } catch { $("history-list").innerHTML = "<span class='muted'>加载失败</span>"; }
  };

  $("btn-fonts").onclick = async () => {
    $("modal-fonts").hidden = false;
    $("fonts-list").innerHTML = "<span class='muted'>加载中…</span>";
    try {
      const r = await (await fetch("/api/fonts")).json();
      $("fonts-count").textContent = r.fonts.length;
      $("fonts-list").innerHTML = r.fonts.map(f =>
        `<div class="font-row"><span>${f.name} <span class="lic">${f.style}</span></span><span class="lic">${f.license}</span></div>`).join("");
    } catch { $("fonts-list").innerHTML = "<span class='muted'>加载失败</span>"; }
  };

  // ---------- ?selftest 自检钩子（供 headless 测试用，不影响正常使用）----------
  async function runSelfTest() {
    const t = (name, pass, detail) => ({ name, pass: !!pass, detail: detail || "" });
    const results = [];
    try {
      // 1. 弹层初始状态：hidden 属性存在且实际不可见
      const mh = $("modal-history"), mf = $("modal-fonts");
      results.push(t("history-modal hidden attr", mh.hidden));
      results.push(t("fonts-modal hidden attr", mf.hidden));
      results.push(t("history-modal invisible", getComputedStyle(mh).display === "none"));
      results.push(t("fonts-modal invisible", getComputedStyle(mf).display === "none"));
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
      // 5. dropzone 初始可见、canvas 初始隐藏
      results.push(t("dropzone visible", !$("dropzone").hidden));
      results.push(t("canvas-wrap hidden", $("canvas-wrap").hidden));
      // 6. API 连通性
      try {
        const fr = await fetch("/api/fonts"); const fj = await fr.json();
        results.push(t("api/fonts ok", fr.ok && fj.fonts.length > 0, `${fj.fonts.length} fonts`));
      } catch (e) { results.push(t("api/fonts ok", false, String(e))); }
      try {
        const hr = await fetch("/api/history"); const hj = await hr.json();
        results.push(t("api/history ok", hr.ok && Array.isArray(hj.history)));
      } catch (e) { results.push(t("api/history ok", false, String(e))); }
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
