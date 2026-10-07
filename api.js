async function api(url, options = {}) {
  const opts = { credentials: "same-origin", ...options };
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers = { "Content-Type": "application/json", ...opts.headers };
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(url, opts);
  let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) {
    const msg = (data && (data.detail || data.message)) || res.statusText || "Request failed";
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

async function postForm(url, fields) {
  const fd = new FormData();
  Object.entries(fields).forEach(([k, v]) => fd.append(k, v));
  return api(url, { method: "POST", body: fd });
}

function showErr(el, msg) {
  if (!el) return alert(msg);
  el.textContent = msg;
  el.classList.remove("hidden");
}

/* Toast notifications (replaces alert) */
function toast(msg, type) {
  let box = document.getElementById("toasts");
  if (!box) { box = document.createElement("div"); box.id = "toasts"; document.body.appendChild(box); }
  const el = document.createElement("div");
  el.className = "toast " + (type || "ok");
  el.textContent = (window.__t ? window.__t(String(msg)) : msg);
  box.appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 250); }, 3000);
}

/* Button loading state: await withLoading(btn, () => api(...)) */
async function withLoading(btn, fn) {
  if (btn) { btn.disabled = true; btn.dataset.t = btn.textContent; btn.textContent = "…"; }
  try { return await fn(); }
  finally { if (btn) { btn.disabled = false; btn.textContent = btn.dataset.t; } }
}


/* HTML escape for any value inserted through innerHTML */
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const T = s => (window.__t ? window.__t(s) : s);

/* ---------- Modal dialogs (replace prompt()/confirm()) ---------- */
const ui = (function () {
  let stack = [];
  function mk(tag, cls, html) { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }

  function open({ title, body, actions, wide, onClose }) {
    const bg = mk("div", "modal-bg");
    const box = mk("div", "modal" + (wide ? " modal-wide" : ""));
    box.setAttribute("role", "dialog"); box.setAttribute("aria-modal", "true");
    const head = mk("div", "modal-head");
    const h = mk("h3"); h.textContent = T(title || ""); head.appendChild(h);
    const x = mk("button", "modal-x", "&times;"); x.type = "button"; x.setAttribute("aria-label", "Close");
    head.appendChild(x);
    const main = mk("div", "modal-body");
    if (typeof body === "string") main.innerHTML = body; else if (body) main.appendChild(body);
    const foot = mk("div", "modal-foot");
    box.append(head, main, foot); bg.appendChild(box); document.body.appendChild(bg);
    document.body.classList.add("modal-open");
    const api_ = { el: box, body: main, foot,
      close(val) { if (!bg.isConnected) return; bg.remove(); stack = stack.filter(m => m !== api_);
        if (!stack.length) document.body.classList.remove("modal-open"); if (onClose) onClose(val); } };
    (actions || []).forEach(a => {
      const b = mk("button", "btn-soft " + (a.cls || "")); b.type = "button"; b.textContent = T(a.label);
      b.onclick = () => a.run(api_); foot.appendChild(b); a.el = b;
    });
    x.onclick = () => api_.cancel ? api_.cancel() : api_.close(null);
    bg.addEventListener("mousedown", e => { if (e.target === bg) x.onclick(); });
    stack.push(api_);
    requestAnimationFrame(() => bg.classList.add("in"));
    return api_;
  }

  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && stack.length) { const m = stack[stack.length - 1]; if (m.cancel) m.cancel(); else m.close(null); }
  });

  function confirmBox(message, opts = {}) {
    return new Promise(res => {
      const m = open({
        title: opts.title || "Confirm", body: "<p class='modal-msg'></p>",
        actions: [
          { label: "Cancel", run: d => d.close(false) },
          { label: opts.ok || "OK", cls: opts.danger ? "btn-red" : "btn-green", run: d => d.close(true) },
        ],
        onClose: v => res(v === true),
      });
      m.body.querySelector(".modal-msg").textContent = T(message);
      setTimeout(() => m.foot.lastChild.focus(), 30);
    });
  }

  function promptBox(title, value, opts = {}) {
    return new Promise(res => {
      const wrap = mk("div");
      if (opts.label) { const l = mk("label", "modal-label"); l.textContent = T(opts.label); wrap.appendChild(l); }
      const inp = mk("input", "modal-input"); inp.type = "text"; inp.value = value || ""; inp.autocomplete = "off"; inp.spellcheck = false;
      if (opts.placeholder) inp.placeholder = opts.placeholder;
      wrap.appendChild(inp);
      const submit = d => { const v = inp.value.trim(); if (!v && !opts.allowEmpty) { inp.focus(); return; } d.close(v); };
      const m = open({
        title, body: wrap,
        actions: [{ label: "Cancel", run: d => d.close(null) }, { label: opts.ok || "OK", cls: "btn-green", run: submit }],
        onClose: v => res(v),
      });
      inp.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); submit(m); } });
      setTimeout(() => { inp.focus(); inp.select(); }, 30);
    });
  }

  /* Real text editor modal: Ctrl/Cmd+S saves, Tab indents, warns on unsaved changes */
  function editor(name, content, onSave) {
    const wrap = mk("div", "ed");
    const ta = mk("textarea", "ed-area"); ta.value = content || ""; ta.spellcheck = false; ta.wrap = "off";
    ta.setAttribute("autocapitalize", "off"); ta.setAttribute("autocorrect", "off");
    const bar = mk("div", "ed-bar");
    const pos = mk("span", "ed-pos", "Ln 1, Col 1"); const state = mk("span", "ed-state", "");
    bar.append(pos, state); wrap.append(ta, bar);
    let saved = ta.value, saving = false;
    const dirty = () => ta.value !== saved;
    const refresh = () => {
      const before = ta.value.slice(0, ta.selectionStart).split("\n");
      pos.textContent = "Ln " + before.length + ", Col " + (before[before.length - 1].length + 1);
      state.textContent = dirty() ? T("Unsaved changes") : T("Saved");
      state.className = "ed-state" + (dirty() ? " dirty" : "");
    };
    const save = async d => {
      if (saving) return; saving = true; d.saveBtn.disabled = true;
      try { await onSave(ta.value); saved = ta.value; refresh(); toast("Saved"); }
      catch (e) { toast(e.message, "err"); }
      saving = false; d.saveBtn.disabled = false;
    };
    const m = open({
      title: name, body: wrap, wide: true,
      actions: [{ label: "Close", run: d => d.cancel() }, { label: "Save", cls: "btn-green", run: d => save(d) }],
    });
    m.saveBtn = m.foot.lastChild;
    m.cancel = async () => { if (dirty() && !(await confirmBox("Discard unsaved changes?", { danger: true, ok: "Discard" }))) return; m.close(null); };
    ta.addEventListener("input", refresh);
    ta.addEventListener("keyup", refresh); ta.addEventListener("click", refresh);
    ta.addEventListener("keydown", e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(m); }
      if (e.key === "Tab") { e.preventDefault(); const a = ta.selectionStart, b = ta.selectionEnd;
        ta.setRangeText("  ", a, b, "end"); refresh(); }
    });
    refresh(); setTimeout(() => ta.focus(), 30);
    return m;
  }

  return { open, confirm: confirmBox, prompt: promptBox, editor };
})();

/* ---------- Telegram login (popup, custom button) ---------- */
function loadTelegramScript() {
  return new Promise((resolve, reject) => {
    if (window.Telegram && window.Telegram.Login) return resolve();
    const s = document.createElement("script");
    s.src = "https://telegram.org/js/telegram-widget.js?22";
    s.onload = () => (window.Telegram && window.Telegram.Login) ? resolve() : reject(new Error("Telegram script not ready"));
    s.onerror = () => reject(new Error("Cannot load Telegram (blocked by network or adblock?)"));
    document.head.appendChild(s);
  });
}
/* Opens the Telegram popup, sends the signed result to our server. Resolves with {redirect}. */
async function telegramAuth(botId, mode) {
  await loadTelegramScript();
  const data = await new Promise((resolve) => {
    window.Telegram.Login.auth({ bot_id: botId, request_access: "write" }, resolve);
  });
  if (!data) throw new Error("Telegram login cancelled");
  return api("/auth/telegram/verify" + (mode === "link" ? "?mode=link" : ""), { method: "POST", body: data });
}
