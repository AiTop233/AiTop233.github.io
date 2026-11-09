/* 管理台前端（I-008 上传 + 记录 + 待修重传；I-019 上传进度与目录回填）。
 * 约定见 docs/FRONTEND.md：无框架、无构建；state 整体刷新；错误统一 toast。 */

const state = {
  status: null, options: null, file: null, tasks: [], failures: [],
  busy: false, job: null, jobTimer: null,
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

/* 错误码 → 「发生了什么 + 怎么办」。
 * 台账只存 error_code（不存 msg / hint），所以人话只能在前端还原；
 * 表里没有的走模式匹配，仍不认识的显示成「上传失败（码）」，不把原始码当原因。 */
const ERR_INFO = {
  "PUP-000": ["未分类失败（旧记录）", "点「重传」再跑一次；仍失败就看 logs/ 里同一时间的日志"],
  "PUP-NET": ["连不上本地服务", "确认 python -m panup serve 还在跑"],
  "PAN-name-conflict": ["同名资源已存在", "换个标题再传（同名不合并）；要补传已有资源用「重传」"],
};

function errInfo(code) {
  const c = String(code || "");
  if (!c) return { reason: "未知原因", hint: "" };
  const hit = ERR_INFO[c];
  if (hit) return { reason: hit[0], hint: hit[1] };
  if (c.includes("noauth") || c.endsWith("-31001")) {
    return { reason: "登录态失效（cookie 过期）", hint: "重新导出 cookie 放进 secrets/，再点「重传」" };
  }
  if (c.includes("token")) {
    return { reason: "登录态不完整", hint: "重新导出一份完整 cookie（含 bdstoken 等字段）" };
  }
  if (c.includes("nodir") || c.endsWith("-9")) {
    return { reason: "远端目录不存在", hint: "目录可能被删或改名，换一个目录再传" };
  }
  if (c.endsWith("-31002")) {
    return { reason: "同名文件已存在", hint: "换标题，或先在网盘里删掉旧文件" };
  }
  if (c.includes("html")) {
    return { reason: "网盘返回了异常页面", hint: "多半是登录态失效或被风控，重新登录后再试" };
  }
  if (c.includes("net")) {
    return { reason: "网络请求失败", hint: "检查网络后点「重传」" };
  }
  if (c.includes("retry")) {
    return { reason: "重试次数用尽", hint: "稍等一会儿点「重传」；反复失败先查登录态" };
  }
  if (c.includes("share")) {
    return { reason: "创建分享链接失败", hint: "点「重传」再建一次；多次失败查登录态或限频" };
  }
  if (c.includes("quota") || c.includes("space")) {
    return { reason: "网盘空间不足", hint: "清一下盘或换一个盘" };
  }
  if (c.includes("exists")) {
    return { reason: "远端已有同名文件", hint: "换标题，或先删旧文件" };
  }
  if (c.includes("part")) {
    return { reason: "分片上传失败", hint: "点「重传」，已传完的文件会跳过" };
  }
  if (c.includes("oss")) {
    return { reason: "直传通道失败", hint: "点「重传」；连续失败可能是被限频，隔几分钟再试" };
  }
  if (c.includes("pre")) {
    return { reason: "预上传失败", hint: "点「重传」；反复失败先查登录态" };
  }
  if (c.includes("nofile")) {
    return { reason: "远端找不到这个文件", hint: "可能已被删除，重新上传一次" };
  }
  return { reason: `上传失败（${c}）`, hint: "点「重传」再试；仍失败就把这个码和当时的日志一起看" };
}

/* 待修/记录里的失败原因：一行人话 + 一行怎么办；原始码只留在 title 里备查 */
function failCell(code) {
  const info = errInfo(code);
  return `<div>${esc(info.reason)}</div>${info.hint
    ? `<div class="cell-sub">怎么办：${esc(info.hint)}</div>` : ""}`;
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

function titlePreview() {
  const typed = $("#title").value.trim();
  if (typed) return typed;
  if (state.file) {
    const name = baseName(state.file.name);
    return name.replace(/\.[^.]+$/, "") || name;
  }
  return "<标题>";
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

function setFile(file) {
  state.file = file || null;
  const drop = $("#drop");
  drop.classList.toggle("has-file", !!state.file);
  $("#drop-title").textContent = state.file ? state.file.name : "把文件拖到这里";
  $("#drop-hint").textContent = state.file
    ? `${fmtSize(state.file.size)} · 点这里可重新选择`
    : "或点击选择文件 · 一次一个";
  updateLanding();
}

function setBusy(busy, text) {
  state.busy = busy;
  const btn = $("#upload-btn");
  btn.disabled = busy;
  btn.textContent = busy ? (text || "上传中…") : "上传";
}

function selectedTargets() {
  return $$(".pan-check").filter((c) => c.checked).map((c) => {
    const dir = document.querySelector(`.pan-dir[data-pan="${c.value}"]`);
    return { pan: c.value, dir: dir ? dir.value.trim() : "" };
  });
}

function renderResult(r) {
  const items = r.items || [];
  const fails = r.failed || [];
  const rows = [
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
  ];
  const writers = (r.writers || []).map((w) =>
    w.ok ? `<span class="tag ok">已写入${esc(writerLabel(w.writer))}</span>`
         : `<span class="tag bad">${esc(writerLabel(w.writer))} 写入失败</span>`).join("");

  const box = $("#result");
  box.className = "result";
  box.innerHTML = `
    <div class="res-head">
      <h2 class="block-title">${esc(r.title || "")}</h2>
      <span class="block-hint">${items.length} 个网盘成功${fails.length ? ` · ${fails.length} 个失败` : ""}</span>
      ${writers}
    </div>
    ${rows.join("")}`;
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

function stageLine(job) {
  const rows = Object.values(job.pans || {});
  const total = rows.length;
  if (job.status === "failed") return (job.error && job.error.msg) || "上传失败";
  if (job.status === "done") {
    const ok = rows.filter((r) => r.stage === "done" || r.stage === "skipped").length;
    const doc = job.writer
      ? ` · ${writerLabel(job.writer.name)}${job.writer.stage === "done" ? "已写入" : "未写入"}`
      : "";
    return `已完成 · ${ok}/${total} 个网盘${doc}`;
  }
  if (job.stage === "writing") {
    return `网盘已传完，正在写入${job.writer ? writerLabel(job.writer.name) : "文档"}…`;
  }
  if (job.stage === "finalizing") return "收尾中…";
  if (job.stage === "queued") return "准备中…";
  const settled = rows.filter((r) => ["done", "skipped", "failed"].includes(r.stage)).length;
  return `上传到网盘 · 已完成 ${settled}/${total} 个网盘`;
}

function renderTransfer(loaded, total) {
  const p = total ? Math.round((loaded / total) * 100) : 0;
  $("#progress").classList.remove("hidden");
  $("#pg-title").textContent = state.file ? state.file.name : "正在上传";
  $("#pg-stage").textContent = `把文件交给本地服务 · ${p}%`;
  $("#pg-rows").innerHTML = `
    <div class="pg-row">
      <span class="pg-pan">接收</span>
      <div class="pg-bar"><i style="width:${p}%"></i></div>
      <span class="pg-text">${fmtSize(loaded)} / ${fmtSize(total)}</span>
      <span class="pg-file"></span>
    </div>`;
  $("#pg-steps").innerHTML = "";
}

function renderProgress(job) {
  state.job = job;
  const box = $("#progress");
  box.classList.remove("hidden");
  $("#pg-title").textContent = job.title || job.filename || "正在上传";
  $("#pg-stage").textContent = stageLine(job);

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

  $("#pg-rows").innerHTML = rows.join("");
  // 时间线「最新在上」：进度是看当下，不需要往下滚
  $("#pg-steps").innerHTML = (job.steps || []).slice().reverse().map((s) => {
    const who = s.pan ? panLabel(s.pan) : (s.writer ? writerLabel(s.writer) : "");
    return `<li><span class="pg-time">${esc(s.at)}</span>${who ? `<b>${esc(who)}</b> ` : ""}${esc(s.text)}</li>`;
  }).join("");
}

function stopJobPolling() {
  if (state.jobTimer) {
    clearInterval(state.jobTimer);
    state.jobTimer = null;
  }
}

function pollJob(jobId) {
  stopJobPolling();
  const tick = async () => {
    let job;
    try {
      job = await api(`/api/jobs/${jobId}`);
    } catch (e) {
      stopJobPolling();
      setBusy(false);
      showToast(`${e.msg}（${e.code}）${e.hint ? " 怎么办: " + e.hint : ""}`);
      return;
    }
    renderProgress(job);
    if (job.status === "running") return;

    stopJobPolling();
    setBusy(false);
    if (job.status === "done") {
      renderResult(job.result || {});
      finishUpload(job.result || {});
    } else {
      refreshRecords();
      const err = job.error || {};
      showToast(`${err.msg || "上传失败"}${err.code ? `（${err.code}）` : ""}${err.hint ? " 怎么办: " + err.hint : ""}`);
    }
  };
  state.jobTimer = setInterval(tick, 500);
  tick();
}

function finishUpload(r) {
  const fails = r.failed || [];
  if (fails.length) {
    showToast(fails.map((f) =>
      `${panLabel(f.pan)}失败：${f.msg}${f.hint ? `（怎么办: ${f.hint}）` : ""}`).join("；"));
  } else if (state.job && state.job.writer && state.job.writer.stage === "done") {
    showToast("上传完成，飞书文档已写入", false);
  } else {
    showToast("上传完成", false);
  }
  setFile(null);
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
  if (!state.file) { showToast("先选一个文件，再点上传"); return; }
  const targets = selectedTargets();
  if (!targets.length) { showToast("至少勾选一个网盘"); return; }

  const fd = new FormData();
  fd.append("file", state.file);
  fd.append("pans", JSON.stringify(targets));
  fd.append("title", $("#title").value.trim());
  fd.append("date_dir", $("#date-dir").checked ? "1" : "0");
  fd.append("doc", $("#write-doc").checked ? "feishu" : "");

  setBusy(true, "上传中…");
  $("#result").className = "result hidden";
  state.job = null;
  renderTransfer(0, state.file.size);
  try {
    const r = await uploadWithProgress(fd, renderTransfer);
    if (r && r.job_id) {          // 服务端交后台跑，进度靠轮询
      pollJob(r.job_id);
      return;
    }
    renderResult(r || {});        // 兼容同步返回（旧服务 / sync=1）
    setBusy(false);
    finishUpload(r || {});
  } catch (e) {
    setBusy(false);
    $("#progress").classList.add("hidden");
    showToast(`${e.msg}（${e.code}）${e.hint ? " 怎么办: " + e.hint : ""}`);
  }
}

function initUpload() {
  const drop = $("#drop");
  const input = $("#file-input");

  drop.addEventListener("click", () => input.click());
  drop.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); input.click(); }
  });
  input.addEventListener("change", () => setFile(input.files[0]));

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
  drop.addEventListener("drop", (ev) => {
    const f = ev.dataTransfer && ev.dataTransfer.files[0];
    if (f) setFile(f);
  });

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
  const info = item.status === "failed" ? errInfo(item.error_code) : null;
  const reason = info ? info.reason : "传输中";
  const tip = info
    ? (info.hint ? `${info.reason} · 怎么办：${info.hint}` : info.reason)
    : (item.error_code || "");
  return `<div class="cell-item bad">${pan}<span title="${esc(tip)}">${esc(reason)}</span></div>`;
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
        <div class="cell-sub">${esc(t.filename)}${t.size ? ` · ${fmtSize(t.size)}` : ""}</div>
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
      <td class="err" title="${esc(r.error_code || "")}">${failCell(r.error_code)}</td>
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
