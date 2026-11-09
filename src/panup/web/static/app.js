/* 管理台前端（I-008：上传 + 记录 + 待修重传）。
 * 约定见 docs/FRONTEND.md：无框架、无构建；state 整体刷新；错误统一 toast。 */

const state = { status: null, file: null, tasks: [], failures: [], busy: false };

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

function renderPanList() {
  const box = $("#pan-list");
  box.innerHTML = channels().map((c, i) => `
    <div class="pan-row">
      <label class="check">
        <input type="checkbox" class="pan-check" value="${esc(c.name)}" ${i === 0 ? "checked" : ""}>
        ${esc(c.label)}
      </label>
      <input class="text pan-dir" data-pan="${esc(c.name)}"
             placeholder="远端目录（留空用配置默认）"
             ${i === 0 ? "" : "disabled"}>
    </div>`).join("");
  box.addEventListener("change", (ev) => {
    if (!ev.target.classList.contains("pan-check")) return;
    const dir = box.querySelector(`.pan-dir[data-pan="${ev.target.value}"]`);
    if (dir) dir.disabled = !ev.target.checked;
  });
}

function setFile(file) {
  state.file = file || null;
  const drop = $("#drop");
  drop.classList.toggle("has-file", !!state.file);
  $("#drop-title").textContent = state.file ? state.file.name : "把文件拖到这里";
  $("#drop-hint").textContent = state.file
    ? `${fmtSize(state.file.size)} · 点这里可重新选择`
    : "或点击选择文件 · 一次一个";
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
  try {
    const r = await api("/api/upload", { method: "POST", body: fd });
    renderResult(r);
    const fails = r.failed || [];
    if (fails.length) {
      showToast(fails.map((f) =>
        `${panLabel(f.pan)}失败：${f.msg}${f.hint ? `（怎么办: ${f.hint}）` : ""}`).join("；"));
    } else {
      showToast("上传完成", false);
    }
    setFile(null);
    refreshRecords();
  } catch (e) {
    showToast(`${e.msg}（${e.code}）${e.hint ? " 怎么办: " + e.hint : ""}`);
  } finally {
    setBusy(false);
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
  const retry = ev.target.closest("[data-retry]");
  if (retry) retryRecord(retry.dataset.retry, retry);
});

document.addEventListener("DOMContentLoaded", () => {
  $$(".tab").forEach((b) =>
    b.addEventListener("click", () => switchTab(b.dataset.tab)));
  $("#refresh-status").addEventListener("click", refreshStatus);
  renderPanList();
  initUpload();
  refreshStatus();
  refreshRecords();
});
