/* 管理台前端（I-008 上传 + 记录 + 待修重传；I-019 上传进度与目录回填；
 * I-018 拖文件夹与批量上传）。
 * 约定见 docs/FRONTEND.md：无框架、无构建；state 整体刷新；错误统一 toast。 */

const state = {
  status: null, options: null, picked: [], tasks: [], failures: [],
  busy: false, batch: null, batchTimer: null, lastResult: null,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

async function api(path, options) {
  let res;
  try {
    res = await fetch(path, options);
  } catch (e) {
    throw { code: "PUP-NET", msg: "无法连接本地服务",
            hint: "确认 python -m panup serve 正在运行" };
  }
  let body = null;
  try { body = await res.json(); } catch (e) { /* 非 JSON 视为空 */ }
  if (!res.ok) {
    const b = body || {};
    throw { code: b.code || `PUP-${res.status}`, msg: b.msg || res.statusText,
            hint: b.hint || "" };
  }
  return body;
}

function showToast(text, isError = true) {
  const t = $("#toast");
  t.textContent = text;
  t.classList.toggle("error", isError);
  t.classList.remove("hidden");
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => t.classList.add("hidden"), 8000);
}

function errText(code) {
  const c = String(code || "");
  if (!c) return "未知原因";
  if (c === "PUP-000") return "未分类失败（旧记录）";
  if (c.includes("noauth")) return "登录态失效（cookie 过期）";
  if (c.includes("nodir") || c.endsWith("-9")) return "远端目录不存在";
  if (c.includes("net") || c.includes("retry")) return "网络请求失败";
  if (c.includes("share")) return "创建分享链接失败";
  if (c.includes("quota") || c.includes("space")) return "网盘空间不足";
  return c;
}

function fmtSize(n) {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = Number(n), i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return `${v.toFixed(i ? 1 : 0)} ${units[i]}`;
}

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function baseName(path) {
  const s = String(path || "").replace(/\\/g, "/");
  return s.split("/").pop() || s;
}

/* ---------------- 状态灯 ---------------- */

function channels() {
  return $$("[data-kind='pan']").map((el) => ({
    name: el.dataset.light,
    label: el.textContent.trim(),
  }));
}

function panLabel(name) {
  const hit = channels().find((c) => c.name === name);
  return hit ? hit.label : name;
}

function writerLabel(name) {
  const el = document.querySelector(`[data-kind='writer'][data-light='${name}']`);
  return el ? el.textContent.trim() : name;
}

function renderStatus() {
  const lights = state.status || {};
  $$("[data-light]").forEach((el) => {
    const dot = el.querySelector(".dot");
    const info = lights[el.dataset.light];
    if (!info) {
      dot.className = "dot unknown";
      el.title = "该通道未注册（未接入或未启用）";
    } else if (info.ok) {
      dot.className = "dot ok";
      el.title = "登录态正常";
    } else {
      const e = info.error || {};
      dot.className = "dot bad";
      el.title = `${e.code || ""} ${e.msg || ""}\n${e.hint || ""}`.trim();
    }
  });
}

async function refreshStatus() {
  try {
    state.status = await api("/api/status");
    renderStatus();
  } catch (e) {
    showToast(`${e.msg}（${e.code}）${e.hint ? " 怎么办: " + e.hint : ""}`);
    renderStatus();
  }
}

/* ---------------- 上传页 ---------------- */

/* 网盘列表：目录由 /api/options 回填（不留空），下面一行写出「实际落点」。
 * 落点 = 基础目录 [+ 年/月/日] + 标题/，与管道 D-005 的规则一致。 */

function panOptions() {
  const list = (state.options && state.options.pans) || [];
  if (list.length) return list;
  return channels().map((c) => ({ name: c.name, default_dir: "" }));
}

function renderPanList() {
  const box = $("#pan-list");
  box.innerHTML = panOptions().map((p, i) => `
    <div class="pan-row">
      <label class="check">
        <input type="checkbox" class="pan-check" value="${esc(p.name)}" ${i === 0 ? "checked" : ""}>
        ${esc(panLabel(p.name))}
      </label>
      <div class="pan-dir-wrap">
        <input class="text pan-dir" data-pan="${esc(p.name)}"
               value="${esc(p.default_dir || "")}"
               placeholder="远端基础目录，例如 /来自电脑"
               ${i === 0 ? "" : "disabled"}>
        <p class="pan-note" data-note="${esc(p.name)}"></p>
      </div>
    </div>`).join("");
  updateLanding();
}

function dateSubdir() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getFullYear() % 100)}/${p(d.getMonth() + 1)}/${p(d.getDate())}`;
}

function tidyPath(path) {
  return String(path || "/").replace(/\/{2,}/g, "/");
}

/* 已选内容的「资源」视图：与后端 D-007 同一套分组规则——
 * 顶层目录各算一个资源，散文件合成一个（只有一个散文件时就是它自己）。
 * 只用于摘要与落点预览，真正的分组在后端做（这里算错也不会传错）。 */
function pickedGroups() {
  const dirs = new Map();
  const loose = [];
  for (const p of state.picked) {
    const parts = String(p.rel || p.file.name).split("/");
    if (parts.length > 1) {
      const top = parts[0];
      const g = dirs.get(top) || { name: top, kind: "folder", count: 0, size: 0 };
      g.count += 1;
      g.size += p.file.size;
      dirs.set(top, g);
    } else {
      loose.push(p);
    }
  }
  const out = [];
  for (const p of state.picked) {
    const top = String(p.rel || p.file.name).split("/")[0];
    if (dirs.has(top) && !out.some((g) => g.name === top)) out.push(dirs.get(top));
  }
  if (loose.length) {
    const typed = $("#title") && !$("#title").disabled
      ? $("#title").value.trim() : "";
    const first = loose[0].file.name.replace(/\.[^.]+$/, "") || loose[0].file.name;
    out.push({
      name: typed || (loose.length > 1 ? `${first} 等${loose.length}个` : first),
      kind: loose.length > 1 ? "folder" : "file",
      count: loose.length,
      size: loose.reduce((s, p) => s + p.file.size, 0),
    });
  }
  return out;
}

function titlePreview() {
  const typed = $("#title").value.trim();
  if (typed && !$("#title").disabled) return typed;
  const groups = pickedGroups();
  if (!groups.length) return "<标题>";
  if (groups.length === 1) return groups[0].name;
  return "<资源名>";
}

function landingOf(pan) {
  const input = document.querySelector(`.pan-dir[data-pan="${pan}"]`);
  const base = tidyPath((input && input.value.trim()) || "/").replace(/\/+$/, "") || "/";
  const dir = $("#date-dir").checked ? tidyPath(`${base}/${dateSubdir()}`) : base;
  return tidyPath(`${dir}/${titlePreview()}`);
}

function updateLanding() {
  $$(".pan-dir").forEach((input) => {
    const note = document.querySelector(`.pan-note[data-note="${input.dataset.pan}"]`);
    if (!note) return;
    note.classList.toggle("hidden", input.disabled);
    note.textContent = input.disabled ? "" : `实际落点 ${landingOf(input.dataset.pan)}/`;
  });
}

async function refreshOptions() {
  try {
    state.options = await api("/api/options");
  } catch (e) {
    state.options = null;      // 接口不通时退回「用状态灯顺序 + 目录留空」
  }
  renderPanList();
}

function setPicked(items) {
  state.picked = (items || []).filter((p) => p && p.file);
  const groups = pickedGroups();
  const files = state.picked.length;
  const size = state.picked.reduce((s, p) => s + p.file.size, 0);
  const drop = $("#drop");
  drop.classList.toggle("has-file", files > 0);
  if (!files) {
    $("#drop-title").textContent = "把文件或文件夹拖到这里";
    $("#drop-hint").textContent = "也可以点这里选文件，或用下面的「选择文件夹」";
  } else if (groups.length === 1) {
    const g = groups[0];
    $("#drop-title").textContent = g.name;
    $("#drop-hint").textContent = `${g.kind === "folder" ? "文件夹 · " : ""}`
      + `${g.count} 个文件 · ${fmtSize(g.size)} · 点这里重选`;
  } else {
    $("#drop-title").textContent = `${groups.length} 个资源 · ${files} 个文件`;
    $("#drop-hint").textContent = `${fmtSize(size)} · 点这里重选`;
  }
  renderPicked(groups);
  // 批量时各资源用自己的名字，表单标题只会误导 → 禁用
  const title = $("#title");
  const multi = groups.length > 1;
  title.disabled = multi;
  title.placeholder = multi
    ? "批量时各资源用各自的名字，这里不用填"
    : "写进飞书文档的标题；留空用文件名";
  updateLanding();
}

function renderPicked(groups) {
  const box = $("#pick-list");
  $("#pick-clear").classList.toggle("hidden", !groups.length);
  if (!groups.length) {
    box.innerHTML = "";
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");
  box.innerHTML = groups.map((g) => `
    <span class="pick-item">
      <b>${esc(g.name)}</b>
      <span class="pick-meta">${g.kind === "folder" ? `${g.count} 个文件 · ` : ""}${fmtSize(g.size)}</span>
    </span>`).join("");
}

function setBusy(busy, text) {
  state.busy = busy;
  const btn = $("#upload-btn");
  btn.disabled = busy;
  btn.textContent = busy ? (text || "上传中…") : "上传";
  // 上传途中不再换选择：FormData 已经装好了，让人以为换了实际没换最坑
  $("#drop").classList.toggle("busy", busy);
  $("#pick-dir").disabled = busy;
  $("#pick-clear").disabled = busy;
}

function selectedTargets() {
  return $$(".pan-check").filter((c) => c.checked).map((c) => {
    const dir = document.querySelector(`.pan-dir[data-pan="${c.value}"]`);
    return { pan: c.value, dir: dir ? dir.value.trim() : "" };
  });
}

function writerTags(writers) {
  return (writers || []).map((w) => w.ok
    ? `<span class="tag ok">已写入${esc(writerLabel(w.writer))}</span>`
    : `<span class="tag bad">${esc(writerLabel(w.writer))} 写入失败</span>`).join("");
}

function resRows(r) {
  const items = r.items || [];
  const fails = r.failed || [];
  return [
    ...items.map((i) => `
      <div class="res-row">
        <span class="res-pan">${esc(panLabel(i.pan))}</span>
        <a class="res-link" href="${esc(i.link)}" target="_blank" rel="noreferrer">${esc(i.link)}</a>
        ${i.pwd ? `<span class="res-pwd">提取码 ${esc(i.pwd)}</span>
                   <button class="btn tiny" type="button" data-copy="${esc(i.pwd)}">复制提取码</button>` : ""}
        ${i.dedup ? `<span class="tag">去重命中</span>` : ""}
      </div>`),
    ...fails.map((f) => `
      <div class="res-row bad">
        <span class="res-pan">${esc(panLabel(f.pan))}</span>
        <span class="res-err">${esc(f.msg)}${f.hint ? ` · 怎么办: ${esc(f.hint)}` : ""}</span>
      </div>`),
  ].join("");
}

function kindText(r) {
  if (r.kind === "folder") return `文件夹 · ${r.file_count || 0} 个文件`;
  return "单文件";
}

/* 一批结果：单资源沿用旧样式；多个资源按资源分组，每组自己的链接与飞书状态。 */
function renderResult(payload) {
  state.lastResult = payload;
  const list = payload.resources || [payload];
  const multi = list.length > 1;
  const okRes = list.filter((r) => (r.items || []).length).length;
  const fails = list.reduce((n, r) => n + (r.failed || []).length, 0);
  const head = multi
    ? `批量上传 · ${list.length} 个资源`
    : (list[0] && list[0].title) || "";

  const body = list.map((r) => (multi ? `
    <div class="res-group">
      <div class="res-ghead">
        <b>${esc(r.title || "")}</b>
        <span class="tag">${kindText(r)}</span>
        ${writerTags(r.writers)}
      </div>
      ${resRows(r)}
    </div>` : resRows(r))).join("");

  const box = $("#result");
  box.className = "result";
  box.innerHTML = `
    <div class="res-head">
      <h2 class="block-title">${esc(head)}</h2>
      <span class="block-hint">${okRes} 个资源成功${fails ? ` · ${fails} 处失败` : ""}</span>
      ${multi ? `<button class="btn tiny" type="button" data-copy-all="1">复制全部链接</button>` : ""}
      ${multi ? "" : writerTags(list[0] && list[0].writers)}
    </div>
    ${body}`;
}

/* 「复制全部链接」的文本：标题 + 每个盘一行（带提取码），方便直接发出去。 */
function allLinksText() {
  const payload = state.lastResult || {};
  const list = payload.resources || [payload];
  const lines = [];
  for (const r of list) {
    if (!(r.items || []).length) continue;
    lines.push(`【${r.title || ""}】`);
    for (const i of r.items) {
      lines.push(`${panLabel(i.pan)}：${i.link}${i.pwd ? ` 提取码 ${i.pwd}` : ""}`);
    }
  }
  return lines.join("\n");
}

/* ---------------- 上传进度（I-019）----------------
 * 两段：① 浏览器 → 本地服务（XHR 上传字节，本地也照实显示）；
 * ② 服务端任务（轮询 /api/jobs/{id}）：各盘传了多少、分享建好没、飞书写了没。 */

const PAN_STAGE_TEXT = {
  waiting: "等待", checking: "检查同名", mkdir: "建文件夹", uploading: "上传中",
  sharing: "创建分享链接", done: "完成", skipped: "已有记录", failed: "失败",
};

const WRITER_STAGE_TEXT = {
  pending: "等待写入", writing: "写入中", done: "已写入",
  failed: "写入失败", skipped: "未写入（无需写入）",
};

function pctOf(row) {
  const total = Number(row.bytes_total) || 0;
  const done = Number(row.bytes_done) || 0;
  if (total > 0) return Math.max(0, Math.min(100, Math.round((done / total) * 100)));
  const t = Number(row.total) || 0;
  const d = Number(row.done) || 0;
  return t > 0 ? Math.max(0, Math.min(100, Math.round((d / t) * 100))) : 0;
}

function rowClass(stage) {
  if (stage === "failed") return " bad";
  if (stage === "done" || stage === "skipped") return " ok";
  return "";
}

/* 单资源的一句话状态：给批量列表和单资源标题行共用。 */
function jobSummary(job) {
  const rows = Object.values(job.pans || {});
  if (job.status === "failed") return (job.error && job.error.msg) || "上传失败";
  if (job.status === "done") {
    const ok = rows.filter((r) => r.stage === "done" || r.stage === "skipped").length;
    const doc = job.writer
      ? ` · ${writerLabel(job.writer.name)}${job.writer.stage === "done" ? "已写入" : "未写入"}`
      : "";
    return `完成 · ${ok}/${rows.length} 个网盘${doc}`;
  }
  if (!job.scanned) return job.stage === "queued" ? "排队中" : "准备中";
  if (job.stage === "writing") {
    return `网盘已传完，正在写入${job.writer ? writerLabel(job.writer.name) : "文档"}…`;
  }
  if (job.stage === "finalizing") return "收尾中…";
  const cur = rows.find((r) => r.stage === "uploading");
  if (cur) {
    const done = rows.filter((r) => ["done", "skipped", "failed"].includes(r.stage)).length;
    return `上传中 · ${done}/${rows.length} 个盘 · ${pctOf(cur)}%`;
  }
  const settled = rows.filter((r) => ["done", "skipped", "failed"].includes(r.stage)).length;
  return `已完成 ${settled}/${rows.length} 个网盘`;
}

/* 一个资源的总进度：各盘串行跑，取跑得最远的那个盘。 */
function jobProgress(job) {
  if (job.status === "done" || job.status === "failed") return 100;
  const rows = Object.values(job.pans || {});
  return rows.length ? Math.round(rows.reduce((m, r) => Math.max(m, pctOf(r)), 0)) : 0;
}

function renderTransfer(loaded, total) {
  const p = total ? Math.round((loaded / total) * 100) : 0;
  const n = state.picked.length;
  $("#progress").classList.remove("hidden");
  $("#pg-title").textContent = n > 1 ? `正在交 ${n} 个文件` : "正在上传";
  $("#pg-stage").textContent = `把文件交给本地服务 · ${p}%`;
  $("#pg-rows").innerHTML = `
    <div class="pg-row">
      <span class="pg-pan">接收</span>
      <div class="pg-bar"><i style="width:${p}%"></i></div>
      <span class="pg-text">${fmtSize(loaded)} / ${fmtSize(total)}</span>
      <span class="pg-file"></span>
    </div>`;
  $("#pg-detail").innerHTML = "";
  $("#pg-steps").innerHTML = "";
}

function panRows(job) {
  const rows = Object.keys(job.pans || {}).map((name) => {
    const row = job.pans[name];
    const p = pctOf(row);
    const text = row.stage === "uploading"
      ? `第 ${row.file_index}/${row.total} 个 · ${p}%`
      : (PAN_STAGE_TEXT[row.stage] || row.stage);
    return `<div class="pg-row${rowClass(row.stage)}">
      <span class="pg-pan">${esc(panLabel(name))}</span>
      <div class="pg-bar"><i style="width:${p}%"></i></div>
      <span class="pg-text">${esc(text)}</span>
      <span class="pg-file" title="${esc(row.file || "")}">${esc(row.file || "")}</span>
    </div>`;
  });

  if (job.writer) {
    const w = job.writer;
    const text = (WRITER_STAGE_TEXT[w.stage] || w.stage)
      + (w.stage === "failed" && w.error ? ` · ${w.error}` : "");
    rows.push(`<div class="pg-row${rowClass(w.stage)}">
      <span class="pg-pan">${esc(writerLabel(w.name))}</span>
      <div class="pg-bar"><i style="width:${w.stage === "done" ? 100 : 0}%"></i></div>
      <span class="pg-text">${esc(text)}</span>
      <span class="pg-file"></span>
    </div>`);
  }
  return rows.join("");
}

function stepsHtml(job) {
  // 时间线「最新在上」：进度是看当下，不需要往下滚
  return ((job && job.steps) || []).slice().reverse().map((s) => {
    const who = s.pan ? panLabel(s.pan) : (s.writer ? writerLabel(s.writer) : "");
    return `<li><span class="pg-time">${esc(s.at)}</span>${who ? `<b>${esc(who)}</b> ` : ""}${esc(s.text)}</li>`;
  }).join("");
}

function batchLine(batch, list) {
  const running = list.find((j) => j.status === "running");
  const done = list.filter((j) => j.status !== "running").length;
  if (batch.status !== "running") {
    const failed = list.filter((j) => j.status === "failed").length;
    return `全部结束 · ${list.length} 个资源${failed ? ` · ${failed} 个失败` : ""}`;
  }
  const where = running
    ? `正在跑「${running.title || running.filename || ""}」`
    : "准备中";
  return `${done}/${list.length} 个资源已结束 · ${where}`;
}

/* 批量进度：资源清单（每行一条总进度）+ 当前资源的分盘细节 + 时间线。 */
function renderBatch(batch) {
  state.batch = batch;
  const list = batch.resources || [];
  const multi = list.length > 1;
  $("#progress").classList.remove("hidden");
  $("#pg-title").textContent = multi
    ? `批量上传 · ${list.length} 个资源`
    : (list[0] ? (list[0].title || list[0].filename) : "正在上传");
  $("#pg-stage").textContent = multi
    ? batchLine(batch, list)
    : jobSummary(list[0] || {});

  if (multi) {
    $("#pg-rows").innerHTML = list.map((j) => `
      <div class="pg-row pg-res-row${j.status === "failed" ? " bad" : (j.status === "done" ? " ok" : "")}">
        <span class="pg-res-name" title="${esc(j.title || j.filename)}">${esc(j.title || j.filename)}</span>
        <div class="pg-bar"><i style="width:${jobProgress(j)}%"></i></div>
        <span class="pg-text">${esc(jobSummary(j))}</span>
      </div>`).join("");
    const cur = list.find((j) => j.status === "running") || list[list.length - 1];
    $("#pg-detail").innerHTML = cur
      ? `<p class="pg-detail-head">当前「${esc(cur.title || cur.filename)}」</p>${panRows(cur)}`
      : "";
    $("#pg-steps").innerHTML = stepsHtml(cur);
  } else {
    const job = list[0] || {};
    $("#pg-rows").innerHTML = panRows(job);
    $("#pg-detail").innerHTML = "";
    $("#pg-steps").innerHTML = stepsHtml(job);
  }
}

function stopBatchPolling() {
  if (state.batchTimer) {
    clearInterval(state.batchTimer);
    state.batchTimer = null;
  }
}

function pollBatch(batchId) {
  stopBatchPolling();
  const tick = async () => {
    let batch;
    try {
      batch = await api(`/api/batches/${batchId}`);
    } catch (e) {
      stopBatchPolling();
      setBusy(false);
      showToast(`${e.msg}（${e.code}）${e.hint ? " 怎么办: " + e.hint : ""}`);
      return;
    }
    renderBatch(batch);
    if (batch.status === "running") return;

    stopBatchPolling();
    setBusy(false);
    const results = (batch.resources || [])
      .filter((j) => j.status === "done" && j.result)
      .map((j) => j.result);
    if (results.length) {
      renderResult(batch.resources.length > 1
        ? { count: results.length, resources: results }
        : results[0]);
    }
    finishUpload(batch);
  };
  state.batchTimer = setInterval(tick, 500);
  tick();
}

function finishUpload(batch) {
  const list = batch.resources || [];
  const fails = list.filter((j) => j.status === "failed");
  const pansFailed = list.reduce((n, j) => n + ((j.result && j.result.failed) || []).length, 0);
  const written = list.filter((j) => j.writer && j.writer.stage === "done").length;
  if (fails.length) {
    showToast(fails.map((j) => {
      const e = j.error || {};
      return `「${j.title || j.filename}」失败：${e.msg || "未知原因"}`
        + `${e.hint ? `（怎么办: ${e.hint}）` : ""}`;
    }).join("；"));
  } else if (pansFailed) {
    showToast(`${pansFailed} 个网盘没传成功，见结果里的红字；修好后到记录页重传`);
  } else if (written) {
    showToast(`上传完成 · ${list.length} 个资源，飞书已写入 ${written} 节`, false);
  } else {
    showToast(`上传完成 · ${list.length} 个资源`, false);
  }
  setPicked([]);
  refreshRecords();
}

/* 用 XHR 发 multipart：fetch 拿不到上传字节进度，本地写入也要让人看见。 */
function uploadWithProgress(fd, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded, e.total);
    };
    xhr.onload = () => {
      let body = null;
      try { body = JSON.parse(xhr.responseText || "null"); } catch (e) { /* 非 JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body || {});
        return;
      }
      const b = body || {};
      reject({ code: b.code || `PUP-${xhr.status}`, msg: b.msg || `HTTP ${xhr.status}`,
               hint: b.hint || "" });
    };
    xhr.onerror = () => reject({ code: "PUP-NET", msg: "无法连接本地服务",
                                 hint: "确认 python -m panup serve 正在运行" });
    xhr.send(fd);
  });
}

async function doUpload(ev) {
  ev.preventDefault();
  if (state.busy) return;
  if (!state.picked.length) { showToast("先选文件或文件夹，再点上传"); return; }
  const targets = selectedTargets();
  if (!targets.length) { showToast("至少勾选一个网盘"); return; }

  const size = state.picked.reduce((s, p) => s + p.file.size, 0);
  const fd = new FormData();
  for (const p of state.picked) fd.append("files", p.file, p.file.name);
  fd.append("paths", JSON.stringify(state.picked.map((p) => p.rel)));
  fd.append("pans", JSON.stringify(targets));
  fd.append("title", $("#title").disabled ? "" : $("#title").value.trim());
  fd.append("date_dir", $("#date-dir").checked ? "1" : "0");
  fd.append("doc", $("#write-doc").checked ? "feishu" : "");

  setBusy(true, "上传中…");
  $("#result").className = "result hidden";
  state.batch = null;
  renderTransfer(0, size);
  try {
    const r = await uploadWithProgress(fd, renderTransfer);
    if (r && r.batch_id) {        // 服务端交后台跑，进度靠轮询整批
      pollBatch(r.batch_id);
      return;
    }
    renderResult(r || {});        // 兼容同步返回（sync=1 / 旧服务）
    setBusy(false);
    if (r && r.resources) {
      finishUpload({ resources: r.resources.map((res) => (
        { status: "done", result: res, writer: null, title: res.title })) });
    }
  } catch (e) {
    setBusy(false);
    $("#progress").classList.add("hidden");
    showToast(`${e.msg}（${e.code}）${e.hint ? " 怎么办: " + e.hint : ""}`);
  }
}

/* 把拖进来的东西读成 [{file, rel}]：目录递归展开并保留相对路径。
 * `webkitGetAsEntry()` 是 Chrome/Edge 的能力；拿不到就退回平铺的 files。 */
function walkEntry(entry, prefix, out) {
  return new Promise((resolve) => {
    if (!entry) { resolve(); return; }
    if (entry.isFile) {
      entry.file((file) => {
        out.push({ file, rel: `${prefix}${file.name}` });
        resolve();
      }, resolve);
      return;
    }
    const reader = entry.createReader();
    const step = () => reader.readEntries(async (batch) => {
      if (!batch.length) { resolve(); return; }
      for (const child of batch) await walkEntry(child, `${prefix}${entry.name}/`, out);
      step();               // readEntries 每次最多给 100 条，读到空为止
    }, resolve);
    step();
  });
}

async function readDrop(dt) {
  const entries = Array.from(dt.items || [])
    .map((it) => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null))
    .filter(Boolean);
  if (!entries.length) {
    return Array.from(dt.files || []).map((f) => ({ file: f, rel: f.name }));
  }
  const out = [];
  for (const entry of entries) await walkEntry(entry, "", out);
  return out;
}

function initUpload() {
  const drop = $("#drop");
  const input = $("#file-input");
  const dirInput = $("#dir-input");
  const pick = (box) => Array.from(box.files || []).map((f) => ({
    file: f, rel: f.webkitRelativePath || f.name,
  }));

  drop.addEventListener("click", () => input.click());
  drop.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); input.click(); }
  });
  input.addEventListener("change", () => { setPicked(pick(input)); input.value = ""; });
  dirInput.addEventListener("change", () => {
    setPicked(pick(dirInput));
    dirInput.value = "";
  });
  $("#pick-dir").addEventListener("click", () => dirInput.click());
  $("#pick-clear").addEventListener("click", () => setPicked([]));

  ["dragenter", "dragover"].forEach((name) =>
    drop.addEventListener(name, (ev) => {
      ev.preventDefault();
      drop.classList.add("dragging");
    }));
  ["dragleave", "drop"].forEach((name) =>
    drop.addEventListener(name, (ev) => {
      ev.preventDefault();
      drop.classList.remove("dragging");
    }));
  drop.addEventListener("drop", async (ev) => {
    const items = await readDrop(ev.dataTransfer || {});
    setPicked(items);
    if (!items.length) showToast("文件夹里没有文件；放入文件后再上传");
  });

  // 拖歪了（落在拖拽区外）时别让浏览器把文件当页面打开——直接吞掉
  ["dragover", "drop"].forEach((name) =>
    document.addEventListener(name, (ev) => {
      if (!ev.target.closest || !ev.target.closest("#drop")) ev.preventDefault();
    }));

  $("#upload-form").addEventListener("submit", doUpload);

  // 目录与落点联动：改目录、改标题、切日期开关都刷新「实际落点」
  $("#pan-list").addEventListener("change", (ev) => {
    if (!ev.target.classList.contains("pan-check")) return;
    const dir = document.querySelector(`.pan-dir[data-pan="${ev.target.value}"]`);
    if (dir) dir.disabled = !ev.target.checked;
    updateLanding();
  });
  $("#pan-list").addEventListener("input", (ev) => {
    if (ev.target.classList.contains("pan-dir")) updateLanding();
  });
  $("#title").addEventListener("input", updateLanding);
  $("#date-dir").addEventListener("change", updateLanding);
}

/* ---------------- 记录页 ---------------- */

function statusBadge(status) {
  const map = {
    success: ["ok", "成功"], partial: ["warn", "部分成功"],
    failed: ["bad", "失败"], pending: ["muted", "进行中"],
  };
  const [cls, text] = map[status] || ["muted", status || "—"];
  return `<span class="badge ${cls}">${esc(text)}</span>`;
}

function itemCell(item) {
  const pan = `<span class="cell-pan">${esc(panLabel(item.pan))}</span>`;
  if (item.status === "success" && item.link) {
    return `<div class="cell-item">${pan}<a href="${esc(item.link)}" target="_blank"
      rel="noreferrer">${esc(item.link)}</a>${item.pwd
      ? `<button class="btn tiny" type="button" data-copy="${esc(item.pwd)}">复制码</button>` : ""}</div>`;
  }
  const reason = item.status === "failed" ? errText(item.error_code) : "传输中";
  return `<div class="cell-item bad">${pan}<span title="${esc(item.error_code || "")}">${esc(reason)}</span></div>`;
}

function renderRecords() {
  const tasks = state.tasks;
  $("#record-table").classList.toggle("hidden", !tasks.length);
  $("#record-empty").classList.toggle("hidden", !!tasks.length);
  $("#record-table tbody").innerHTML = tasks.map((t) => `
    <tr>
      <td class="nowrap">${esc(fmtTime(t.created_at))}</td>
      <td>
        <div class="cell-title">${esc(t.title)}</div>
        <div class="cell-sub">${esc(t.filename)} · ${esc(kindText(t))}${t.size ? ` · ${fmtSize(t.size)}` : ""}</div>
      </td>
      <td>${(t.items || []).map(itemCell).join("")}</td>
      <td>${statusBadge(t.status)}</td>
    </tr>`).join("");

  const fails = state.failures;
  $("#failure-count").textContent = String(fails.length);
  $("#failure-table").classList.toggle("hidden", !fails.length);
  $("#failure-empty").classList.toggle("hidden", !!fails.length);
  $("#failure-table tbody").innerHTML = fails.map((r) => `
    <tr>
      <td class="nowrap">${esc(fmtTime(r.updated_at))}</td>
      <td>${esc(baseName(r.local_path))}</td>
      <td>${esc(panLabel(r.pan))}</td>
      <td class="err" title="${esc(r.error_code || "")}">${esc(errText(r.error_code))}</td>
      <td><button class="btn tiny" type="button" data-retry="${r.id}">重传</button></td>
    </tr>`).join("");
}

async function refreshRecords() {
  try {
    const [tasks, fails] = await Promise.all([
      api("/api/uploads?limit=50"),
      api("/api/uploads?limit=50&status=failed"),
    ]);
    state.tasks = tasks.tasks || [];
    state.failures = fails.records || [];
    renderRecords();
  } catch (e) {
    showToast(`${e.msg}（${e.code}）${e.hint ? " 怎么办: " + e.hint : ""}`);
  }
}

async function retryRecord(id, btn) {
  btn.disabled = true;
  btn.textContent = "重传中…";
  try {
    const r = await api(`/api/uploads/${id}/retry`, { method: "POST" });
    if (r.ok) {
      showToast(r.message || "重传成功", false);
    } else {
      const f = (r.failed || [])[0] || {};
      showToast(`重传失败：${f.msg || "未知原因"}${f.hint ? " 怎么办: " + f.hint : ""}`);
    }
  } catch (e) {
    showToast(`${e.msg}（${e.code}）${e.hint ? " 怎么办: " + e.hint : ""}`);
  } finally {
    await refreshRecords();
  }
}

/* ---------------- 通用 ---------------- */

function switchTab(name) {
  $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.dataset.panel === name));
  if (name === "records") refreshRecords();
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    showToast("已复制", false);
  } catch (e) {
    showToast("复制失败，请手动选中复制");
  }
}

document.addEventListener("click", (ev) => {
  const copy = ev.target.closest("[data-copy]");
  if (copy) { copyText(copy.dataset.copy); return; }
  if (ev.target.closest("[data-copy-all]")) { copyText(allLinksText()); return; }
  const retry = ev.target.closest("[data-retry]");
  if (retry) retryRecord(retry.dataset.retry, retry);
});

document.addEventListener("DOMContentLoaded", () => {
  $$(".tab").forEach((b) =>
    b.addEventListener("click", () => switchTab(b.dataset.tab)));
  $("#refresh-status").addEventListener("click", refreshStatus);
  refreshOptions();
  initUpload();
  refreshStatus();
  refreshRecords();
});
