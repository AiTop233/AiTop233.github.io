/* 管理台前端（I-007 页面壳 + 状态灯区；完整交互在 I-008 / I-009 / I-010 落地）。
 * 约定见 docs/FRONTEND.md：无框架、无构建；state 整体刷新；错误统一 toast。 */

const state = { status: null };

const $ = (sel) => document.querySelector(sel);

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
  showToast._timer = setTimeout(() => t.classList.add("hidden"), 6000);
}

function renderStatus() {
  const lights = state.status || {};
  document.querySelectorAll("[data-light]").forEach((el) => {
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

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) =>
    p.classList.toggle("active", p.dataset.panel === name));
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".tab").forEach((b) =>
    b.addEventListener("click", () => switchTab(b.dataset.tab)));
  $("#refresh-status").addEventListener("click", refreshStatus);
  refreshStatus();
});
