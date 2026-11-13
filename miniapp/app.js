/* TeleAutomator mini app : GUI over the same command engine as the control bot.
   Auth: Telegram initData header → /api/auth. Unauthorized → paywall (display-only).
   demo=1 query param renders local fixture data (no server calls) for previews. */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const DEMO = new URLSearchParams(location.search).has("demo");

  // ------------------------------------------------------------ api layer

  function initDataHeader() {
    try { return tg && tg.initData ? tg.initData : ""; } catch { return ""; }
  }

  async function api(path, body) {
    if (DEMO) return demoApi(path, body);
    const opts = { method: body ? "POST" : "GET", headers: { "X-Telegram-Init-Data": initDataHeader() } };
    if (body) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) return { authorized: false, paywall: data.paywall, version: data.version };
    return data;
  }

  // ------------------------------------------------------------ demo data
  // Real-shaped fixture data for the authorized screens (inspector previews).

  const DEMO_DATA = {
    state: {
      authorized: true, is_main: true, mode: "restricted_auto", state: "active", paused_remaining_sec: 0,
      emergency: false, quiet_hours: false, safe_mode: false, chatty_global: 0.15, style: "casual",
      prompt: "Reply like a 22-year-old Delhi guy, short, lowercase, Hinglish words when natural.",
      owner_name: "Kaif", ai_engine: "Gemini", ai_model: "gemini-2.5-flash-lite", ai_base_url: "",
      chats_allowed: 6, pending_count: 2, replies_24h: 41, tokens_today: 18320, version: "2.9.0",
    },
    chats: [
      { id: 123456789, name: "Rohan Sharma", username: "@rohan_s", type: "Private", chatty: "", style: "", prompt: "", voice_profile: true, blocked: false },
      { id: -1001987654321, name: "Startup India Founders", username: "", type: "Group", chatty: "0.4", style: "humorous", prompt: "You help founders swap tools. Keep it practical.", voice_profile: false, blocked: false },
      { id: -1001765432109, name: "Delhi Tech Meetup", username: "@delhitech", type: "Group", chatty: "0", style: "", prompt: "", voice_profile: false, blocked: false },
      { id: 987654321, name: "Aarav", username: "@aaravv", type: "Private", chatty: "0.6", style: "", prompt: "", voice_profile: false, blocked: false },
      { id: -1001654321098, name: "Crypto Signals Hub", username: "", type: "Group", chatty: "", style: "concise", prompt: "", voice_profile: false, blocked: true },
      { id: 876543210, name: "Mom", username: "", type: "Private", chatty: "0.25", style: "", prompt: "Never send links here.", voice_profile: false, blocked: false },
    ],
    pending: [
      { id: 41, chat_id: -1001987654321, text: "btw are you joining the demo day on friday? wanted to show you the pitch deck before we send it out", created: "2026-11-13 14:22" },
      { id: 40, chat_id: 987654321, text: "reached home? call me when you're free, need to ask about the weekend plan", created: "2026-11-13 13:05" },
    ],
    activity: [
      { chat: "Delhi Tech Meetup", chat_id: -1001765432109, sender: "TeleAutomator", text: "yeah the venue shifted to Hauz Khas this month, same 7pm slot", ts: "2026-11-13 14:18" },
      { chat: "Rohan Sharma", chat_id: 123456789, sender: "TeleAutomator", text: "sent you the file, check when free", ts: "2026-11-13 13:52" },
      { chat: "Startup India Founders", chat_id: -1001987654321, sender: "TeleAutomator", text: "pricing page looks solid, maybe add a monthly option", ts: "2026-11-13 12:30" },
      { chat: "Mom", chat_id: 876543210, sender: "TeleAutomator", text: "yes mom, ate already", ts: "2026-11-13 11:04" },
    ],
    access: [
      { id: 555000111, name: "Kaif", username: "@mkr_infinity", main: true, perms: "all" },
      { id: 777000222, name: "Manager", username: "@manager_h", main: false, perms: "all" },
    ],
    commands: [
      { command: "status", description: "Live status: mode, AI engine, chat rules" },
      { command: "prompt", description: "AI persona: /prompt <text> to set, bare to view" },
      { command: "style", description: "AI style: casual|concise|formal|humorous" },
      { command: "pause", description: "Pause automation: /pause <minutes>" },
      { command: "reaction", description: "Auto-reactions: /reaction on|off" },
      { command: "chatty", description: "Per-group banter picker" },
      { command: "model", description: "Set model or fallback chain" },
      { command: "checkmodels", description: "Ping candidate models live" },
      { command: "safemode", description: "Crash-loop guard status" },
      { command: "help", description: "Full command reference" },
    ],
  };

  async function demoApi(path, body) {
    if (path === "/api/auth") return { authorized: true, is_main: true, version: "2.9.0", user: { id: 555000111, name: "Kaif" } };
    if (path === "/api/state") return DEMO_DATA.state;
    if (path === "/api/chats") return { chats: DEMO_DATA.chats, chatty_global: DEMO_DATA.state.chatty_global };
    if (path === "/api/pending") return { pending: DEMO_DATA.pending };
    if (path === "/api/activity") return { activity: DEMO_DATA.activity };
    if (path === "/api/access") return { users: DEMO_DATA.access };
    if (path === "/api/commands") return { commands: DEMO_DATA.commands };
    if (path === "/api/cmd") return { ok: true, response: "*Demo* command `/demo` ran against fixture data.\n\n• Nothing changed, this screen is a preview." };
    if (path === "/api/action") {
      const a = body && body.action;
      if (a === "approve" || a === "reject") {
        const i = DEMO_DATA.pending.findIndex((p) => String(p.id) === String(body.params.id));
        if (i >= 0) DEMO_DATA.pending.splice(i, 1);
        DEMO_DATA.state.pending_count = DEMO_DATA.pending.length;
      }
      return { ok: true, response: "*Demo* action applied to fixture data." };
    }
    return { ok: false, response: "Unknown demo endpoint." };
  }

  // ------------------------------------------------------- markdown light
  // Engine responses are Telegram-ish: *bold* _italic_ `code`. Escape first.

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function md(s) {
    let h = esc(s);
    h = h.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    h = h.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    h = h.replace(/\*([^*\n]+)\*/g, "<strong>$1</strong>");
    h = h.replace(/_([^_\n]+)_/g, "<em>$1</em>");
    h = h.replace(/\n/g, "<br>");
    return `<span class="md">${h}</span>`;
  }

  function plain(s) {
    return String(s ?? "").replace(/[*_`]/g, "");
  }

  function fmtPct(v) {
    if (v === "" || v === null || v === undefined) return "Default";
    const f = Math.round(parseFloat(v) * 100);
    return `${f}%`;
  }

  // ------------------------------------------------------------ chrome ui

  let toastTimer = null;
  function toast(text) {
    const el = $("toast");
    el.textContent = plain(text) || "Done";
    el.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("hidden"), 3200);
  }

  function haptic(kind) {
    try {
      if (!tg) return;
      if (kind === "ok" || kind === "err") tg.HapticFeedback && tg.HapticFeedback.notificationOccurred(kind);
      else tg.HapticFeedback && tg.HapticFeedback.impactOccurred("light");
    } catch { /* haptics are best-effort */ }
  }

  function openSheet(title, bodyHtml, buttons) {
    $("sheet-title").textContent = title;
    $("sheet-body").innerHTML = bodyHtml;
    const actions = $("sheet-actions");
    actions.innerHTML = "";
    (buttons || []).forEach((b) => {
      const btn = document.createElement("button");
      btn.className = `btn ${b.kind || ""}`.trim();
      btn.textContent = b.label;
      btn.addEventListener("click", () => { closeSheet(); b.onClick && b.onClick(); });
      actions.appendChild(btn);
    });
    const inp = $("sheet-body").querySelector("input");
    if (inp) {
      inp.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          const primaryBtn = actions.querySelector(".btn.primary") || actions.querySelector(".btn");
          if (primaryBtn) primaryBtn.click();
        }
      });
      setTimeout(() => inp.focus(), 60);
    }
    const ta = $("sheet-body").querySelector("textarea");
    if (ta) {
      ta.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
          e.preventDefault();
          const primaryBtn = actions.querySelector(".btn.primary") || actions.querySelector(".btn");
          if (primaryBtn) primaryBtn.click();
        }
      });
      setTimeout(() => ta.focus(), 60);
    }
    $("sheet-backdrop").classList.remove("hidden");
    $("sheet").classList.remove("hidden");
  }

  function closeSheet() {
    $("sheet-backdrop").classList.add("hidden");
    $("sheet").classList.add("hidden");
  }

  // -------------------------------------------------------------- views

  let currentView = "overview";

  function showView(name) {
    currentView = name;
    document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
    $(`view-${name}`).classList.remove("hidden");
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
    haptic();
    loadView(name);
  }

  function loadView(name) {
    if (name === "overview") refreshOverview();
    else if (name === "chats") refreshChats();
    else if (name === "persona") refreshPersona();
    else if (name === "approvals") refreshApprovals();
    else if (name === "more") refreshMore();
  }

  // ------------------------------------------------------------ overview

  async function refreshOverview() {
    const s = await api("/api/state");
    if (!s || s.authorized === false) return maybePaywall(s);
    renderState(s);
    const acts = await api("/api/activity");
    const rows = (acts.activity || []).slice(0, 4);
    $("ov-activity").innerHTML = rows.length
      ? rows.map(feedRowHtml).join("")
      : `<div class="empty">No replies yet, the account stays quiet until a chat talks.</div>`;
    $("tab-approvals").textContent = String(s.pending_count || 0);
    $("tab-approvals").classList.toggle("hidden", !s.pending_count);
  }

  function renderState(s) {
    const pill = $("state-pill");
    if (s.state === "stopped") { pill.textContent = "Stopped"; pill.className = "pill pill-negative"; }
    else if (s.state === "paused") {
      const mins = Math.ceil((s.paused_remaining_sec || 0) / 60);
      pill.textContent = `Paused ${mins}m`;
      pill.className = "pill pill-warning";
    } else { pill.textContent = s.quiet_hours ? "Active · quiet hours" : "Active"; pill.className = "pill pill-positive"; }

    $("ov-mode").textContent = `Mode: ${s.mode} · style ${s.style}`;
    const bits = [];
    if (s.safe_mode) bits.push("safe mode");
    if (s.emergency) bits.push("emergency stop");
    bits.push(`${s.ai_engine} engine`);
    bits.push(s.chats_allowed === 1 ? "1 chat" : `${s.chats_allowed} chats`);
    $("ov-sub").textContent = bits.join(" · ");

    $("kpi-chats").textContent = s.chats_allowed;
    $("kpi-pending").textContent = s.pending_count;
    $("kpi-replies").textContent = s.replies_24h;
    $("kpi-tokens").textContent = s.tokens_today >= 1000 ? `${(s.tokens_today / 1000).toFixed(1)}k` : s.tokens_today;

    $("act-pause").classList.toggle("hidden", s.state !== "active");
    $("act-resume").classList.toggle("hidden", s.state === "active");
  }

  function feedRowHtml(a) {
    return `<div class="feed-row">
      <div class="feed-top"><span class="feed-chat">${esc(a.chat)}</span><span class="feed-ts num">${esc(String(a.ts || "").slice(5, 16))}</span></div>
      <span class="feed-text">${esc(a.text)}</span>
    </div>`;
  }

  // --------------------------------------------------------------- chats

  let chatCache = [];

  async function refreshChats() {
    const data = await api("/api/chats");
    if (!data || data.authorized === false) return maybePaywall(data);
    chatCache = data.chats || [];
    $("chat-list").innerHTML = chatCache.length
      ? chatCache.map(chatRowHtml).join("")
      : `<div class="empty">No chats allowed yet. Add a chat ID above.</div>`;
    wireChatRows();
  }

  function chatRowHtml(c) {
    const sub = [c.type, c.blocked ? "blocked" : "", c.prompt ? "custom prompt" : "", c.context ? "has context" : "", c.style ? c.style : "", c.voice_profile ? "voice profile" : ""]
      .filter(Boolean).join(" · ");
    return `<div class="row" data-cid="${c.id}">
      <div class="row-main">
        <p class="row-title">${esc(c.name)}</p>
        <p class="row-sub">chatty ${esc(fmtPct(c.chatty))}${sub ? " · " + esc(sub) : ""}</p>
      </div>
      <div class="row-side">
        <button class="btn small" data-op="prompt">Prompt</button>
        <button class="btn small" data-op="context">Context</button>
        <button class="btn small" data-op="chatty">Chatty</button>
        <button class="btn small" data-op="remove">Remove</button>
      </div>
    </div>`;
  }

  function wireChatRows() {
    document.querySelectorAll("#chat-list .row").forEach((row) => {
      const cid = row.dataset.cid;
      row.querySelectorAll("[data-op]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const c = chatCache.find((x) => String(x.id) === String(cid));
          if (!c) return;
          if (btn.dataset.op === "chatty") chattySheet(c);
          else if (btn.dataset.op === "prompt") promptSheet(c);
          else if (btn.dataset.op === "context") contextSheet(c);
          else removeSheet(c, btn.dataset.op);
        });
      });
    });
  }

  function chattySheet(c) {
    const opts = [0, 10, 25, 40, 60, 80, 100];
    const curVal = c.chatty !== "" && c.chatty !== null && c.chatty !== undefined ? Math.round(parseFloat(c.chatty) * 100) : null;
    const buttons = opts.map((p) => ({
      label: `${p}%`,
      kind: curVal !== null && curVal === p ? "primary" : "",
      onClick: () => runAction("chat_chatty", { chat_id: c.id, value: String(p) }),
    }));
    buttons.push({ label: "Default", onClick: () => runAction("chat_chatty", { chat_id: c.id, value: "def" }) });
    openSheet(`Chatty · ${c.name}`, `<p>Chance the account joins the chat on its own. Default follows the global 30–60% band.</p>`, buttons);
  }

  function promptSheet(c) {
    openSheet(`Per-chat prompt · ${c.name}`,
      `<p class="field-hint" style="margin-top:0;margin-bottom:8px">Custom AI persona for this chat only (slang, attitude, constraints).</p>` +
      `<textarea id="sheet-input" rows="4" placeholder="Empty = global prompt">${esc(c.prompt)}</textarea>`,
      [
        { label: "Save", kind: "primary", onClick: () => runAction("chatprompt", { chat_id: c.id, value: $("sheet-input").value.trim() }) },
        { label: "Clear", onClick: () => runAction("chatprompt", { chat_id: c.id, value: "default" }) },
      ]);
    const ta = $("sheet-input");
    if (ta) ta.focus();
  }

  function contextSheet(c) {
    openSheet(`Group context · ${c.name}`,
      `<p class="field-hint" style="margin-top:0;margin-bottom:8px">Permanent background notes &amp; rules remembered across all conversations in this chat.</p>` +
      `<textarea id="sheet-input" rows="5" placeholder="e.g. Solana meme coins, keep replies brief, focus on technical analysis">${esc(c.context || "")}</textarea>`,
      [
        { label: "Save notes", kind: "primary", onClick: () => runAction("setcontext", { chat_id: c.id, value: $("sheet-input").value.trim() }) },
        { label: "Clear notes", onClick: () => runAction("delcontext", { chat_id: c.id }) },
        { label: "Sync pins", onClick: () => runAction("syncpins", { chat_id: c.id }) },
      ]);
    const ta = $("sheet-input");
    if (ta) ta.focus();
  }

  function removeSheet(c, op) {
    openSheet("Remove chat",
      `<p>Stop automation for <strong>${esc(c.name)}</strong>? The chat leaves the allowlist until you allow it again.</p>`,
      [
        { label: "Remove", kind: "danger", onClick: () => runAction("remove", { chat_id: c.id }) },
        { label: "Cancel" },
      ]);
  }

  // -------------------------------------------------------------- persona

  async function refreshPersona() {
    const s = await api("/api/state");
    if (!s || s.authorized === false) return maybePaywall(s);
    if (document.activeElement !== $("pf-prompt")) $("pf-prompt").value = s.prompt || "";
    if (document.activeElement !== $("pf-name")) $("pf-name").value = s.owner_name || "";
    const styles = ["casual", "concise", "formal", "humorous"];
    $("pf-style").innerHTML = styles.map((st) =>
      `<button class="seg ${st === s.style ? "active" : ""}" data-style="${st}">${st}</button>`).join("");
    $("pf-style").querySelectorAll(".seg").forEach((b) =>
      b.addEventListener("click", () => runAction("style", { value: b.dataset.style })));
    const data = await api("/api/chats");
    const chats = (data.chats || []).filter((c) => c.prompt || c.context);
    $("pf-chats").innerHTML = chats.length
      ? chats.map((c) => {
          const parts = [];
          if (c.prompt) parts.push(`Persona: ${c.prompt}`);
          if (c.context) parts.push(`Context: ${c.context}`);
          return `<div class="row">
            <div class="row-main"><p class="row-title">${esc(c.name)}</p><p class="row-sub">${esc(parts.join(" · "))}</p></div>
            <div class="row-side">
              <button class="btn small" data-cid="${c.id}" data-op="edit-prompt">Prompt</button>
              <button class="btn small" data-cid="${c.id}" data-op="edit-context">Context</button>
            </div>
          </div>`;
        }).join("")
      : `<div class="empty">No per-chat prompts or context notes yet. Set them from the Chats tab.</div>`;
    $("pf-chats").querySelectorAll("[data-op]").forEach((btn) =>
      btn.addEventListener("click", () => {
        const c = (data.chats || []).find((x) => String(x.id) === btn.dataset.cid);
        if (!c) return;
        if (btn.dataset.op === "edit-prompt") promptSheet(c);
        else if (btn.dataset.op === "edit-context") contextSheet(c);
      }));
  }

  // ------------------------------------------------------------ approvals

  async function refreshApprovals() {
    const data = await api("/api/pending");
    if (!data || data.authorized === false) return maybePaywall(data);
    const rows = data.pending || [];
    const count = rows.length;
    $("tab-approvals").textContent = String(count);
    $("tab-approvals").classList.toggle("hidden", !count);
    $("approval-list").innerHTML = count
      ? rows.map((p) => `<div class="row" style="min-height:0;align-items:flex-start;flex-direction:column;gap:10px;">
          <div class="row-main" style="width:100%">
            <p class="row-sub">${esc(p.chat_title || String(p.chat_id))} · ${esc(String(p.created || "").slice(0, 16))}</p>
            <p class="row-title" style="white-space:normal">${esc(p.text)}</p>
          </div>
          <div class="row-side"><button class="btn small primary" data-ap="approve" data-id="${p.id}">Approve</button>
          <button class="btn small danger" data-ap="reject" data-id="${p.id}">Reject</button></div>
        </div>`).join("")
      : `<div class="empty">Nothing waiting. In approval mode every draft shows up here.</div>`;
    $("approval-list").querySelectorAll("[data-ap]").forEach((btn) =>
      btn.addEventListener("click", () => runAction(btn.dataset.ap, { id: btn.dataset.id })));
  }

  // ----------------------------------------------------------------- more

  let commandCache = [];

  async function refreshMore() {
    const data = await api("/api/access");
    if (!data || data.authorized === false) return maybePaywall(data);
    $("access-list").innerHTML = (data.users || []).length
      ? data.users.map((u) => `<div class="row">
          <div class="row-main"><p class="row-title">${esc(u.name)}${u.main ? " · owner" : ""}</p><p class="row-sub num">${u.id}${u.username ? " · " + esc(u.username) : ""}</p></div>
          <div class="row-side">${u.main ? "" : `<button class="btn small" data-unauth="${u.id}">Remove</button>`}</div>
        </div>`).join("")
      : `<div class="empty">No authorized users.</div>`;
    $("access-list").querySelectorAll("[data-unauth]").forEach((btn) =>
      btn.addEventListener("click", () => openSheet("Remove user", `<p>Revoke panel access for user <span class="num">${esc(btn.dataset.unauth)}</span>?</p>`,
        [{ label: "Remove", kind: "danger", onClick: () => runAction("removeauth", { user_id: btn.dataset.unauth }) }, { label: "Cancel" }])));

    const s = await api("/api/state");
    if (s && !s.authorized === false) {
      if (document.activeElement !== $("ai-model") && s.ai_model) $("ai-model").value = s.ai_model;
      if (document.activeElement !== $("ai-baseurl") && s.ai_base_url) $("ai-baseurl").value = s.ai_base_url;
    }

    if (!commandCache.length) {
      const cmds = await api("/api/commands");
      commandCache = cmds.commands || [];
    }
    renderCommandChips(commandCache);
  }

  function renderCommandChips(commands) {
    const src = commands && commands.length ? commands : commandCache;
    const q = ($("cmd-search").value || "").toLowerCase();
    const list = src.filter((c) => !q || c.command.includes(q) || c.description.toLowerCase().includes(q));
    const countEl = $("cmd-count");
    if (countEl) countEl.textContent = `(${list.length})`;
    $("cmd-chips").innerHTML = list.map((c) =>
      `<button class="chip" data-cmd="${esc(c.command)}"><strong>/${esc(c.command)}</strong>${esc(plain(c.description))}</button>`).join("")
      || `<div class="empty">No matching command.</div>`;
    $("cmd-chips").querySelectorAll(".chip").forEach((chip) =>
      chip.addEventListener("click", () => {
        const cmd = chip.dataset.cmd;
        openSheet(`/${cmd}`, `<input id="sheet-input" placeholder="Arguments (leave empty to run bare)">`,
          [{ label: "Run", kind: "primary", onClick: () => runCmd(`/${cmd} ${$("sheet-input").value.trim()}`.trim()), keepOpen: false }, { label: "Cancel" }]);
      }));
  }

  // --------------------------------------------------------- run + notify

  async function runAction(action, params) {
    haptic();
    const res = await api("/api/action", { action, params });
    if (res && res.authorized === false) return maybePaywall(res);
    haptic(res && res.ok ? "ok" : "err");
    toast(res && res.response ? res.response : (res && res.ok ? "Done" : "Failed"));
    loadView(currentView);
  }

  async function runCmd(command) {
    haptic();
    const res = await api("/api/cmd", { command });
    if (res && res.authorized === false) return maybePaywall(res);
    haptic(res && res.ok ? "ok" : "err");
    openSheet(`/${command.split(" ")[0].slice(1)}`, md(res && res.response ? res.response : "No response."), [{ label: "Close" }]);
    loadView(currentView);
  }

  // -------------------------------------------------------------- paywall

  function maybePaywall(res) {
    if (!res || res.authorized === false) {
      $("app").classList.add("hidden");
      $("paywall").classList.remove("hidden");
      if (res && res.version) $("pay-version").textContent = `v${res.version}`;
      return true;
    }
    return false;
  }

  // ---------------------------------------------------------------- init

  function wire() {
    document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showView(t.dataset.view)));
    $("sheet-backdrop").addEventListener("click", closeSheet);

    $("act-pause").addEventListener("click", () => runAction("pause", { minutes: 30 }));
    $("act-resume").addEventListener("click", () => runAction("resume", {}));
    $("act-stop").addEventListener("click", () => openSheet("Stop everything", "<p>Halts all replies and reactions until you resume.</p>",
      [{ label: "Stop", kind: "danger", onClick: () => runAction("stop", {}) }, { label: "Cancel" }]));
    $("act-mode").addEventListener("click", () => openSheet("Switch mode",
      "<p><strong>restricted_auto</strong> replies on its own inside guardrails · <strong>approval</strong> drafts wait here · <strong>draft</strong> only drafts, never sends.</p>",
      [
        { label: "restricted_auto", kind: "primary", onClick: () => runAction("mode", { value: "restricted_auto" }) },
        { label: "approval", onClick: () => runAction("mode", { value: "approval" }) },
        { label: "draft", onClick: () => runAction("mode", { value: "draft" }) },
      ]));

    $("goto-activity").addEventListener("click", async () => {
      const acts = await api("/api/activity");
      const rows = acts.activity || [];
      openSheet("Recent replies", rows.length ? rows.map(feedRowHtml).join("") : "<p>Nothing yet.</p>", [{ label: "Close" }]);
    });

    $("allow-btn").addEventListener("click", () => {
      const v = $("allow-id").value.trim();
      if (!v) return toast("Enter a chat ID");
      $("allow-id").value = "";
      runAction("allow", { chat_id: v });
    });
    $("allow-id").addEventListener("keydown", (e) => { if (e.key === "Enter") $("allow-btn").click(); });

    $("pf-save").addEventListener("click", () => {
      const v = $("pf-prompt").value.trim();
      if (!v) return runAction("prompt", { value: "reset" });
      runAction("prompt", { value: v });
    });
    $("pf-name-save").addEventListener("click", () => {
      const v = $("pf-name").value.trim();
      if (!v) return toast("Enter a name");
      runAction("name", { value: v });
    });
    $("pf-name").addEventListener("keydown", (e) => { if (e.key === "Enter") $("pf-name-save").click(); });

    $("auth-add").addEventListener("click", () => {
      const v = $("auth-id").value.trim();
      if (!v) return toast("Enter a Telegram user ID");
      $("auth-id").value = "";
      runAction("addauth", { user_id: v });
    });
    $("auth-id").addEventListener("keydown", (e) => { if (e.key === "Enter") $("auth-add").click(); });

    $("ai-model-save").addEventListener("click", () => {
      const v = $("ai-model").value.trim();
      if (!v) return toast("Enter a model name");
      runAction("model", { value: v });
    });
    $("ai-model").addEventListener("keydown", (e) => { if (e.key === "Enter") $("ai-model-save").click(); });
    $("ai-check").addEventListener("click", () => runCmd("/checkmodels"));
    $("ai-key-save").addEventListener("click", () => {
      const v = $("ai-key").value.trim();
      if (!v) return toast("Paste a key first");
      $("ai-key").value = "";
      runAction("apikey", { value: v });
    });
    $("ai-key").addEventListener("keydown", (e) => { if (e.key === "Enter") $("ai-key-save").click(); });
    $("ai-baseurl-save").addEventListener("click", () => {
      const v = $("ai-baseurl").value.trim();
      if (!v) return toast("Enter an endpoint URL");
      runAction("baseurl", { value: v });
    });
    $("ai-baseurl").addEventListener("keydown", (e) => { if (e.key === "Enter") $("ai-baseurl-save").click(); });

    // Fetch models from endpoint
    async function fetchModels() {
      const btn = $("ai-fetch-models");
      const baseurl = $("ai-baseurl").value.trim();
      const apikey = $("ai-key").value.trim();
      btn.disabled = true;
      btn.textContent = "Fetching...";
      try {
        const res = await api("/api/fetch_models", { base_url: baseurl, api_key: apikey });
        if (!res || !res.ok) {
          toast(res && res.error ? res.error : "Failed to load models from endpoint");
          return;
        }
        const models = res.models || [];
        $("models-fetched-count").textContent = `(${models.length})`;
        if (!models.length) {
          $("ai-model-chips").innerHTML = `<div class="empty sm">Endpoint returned 0 models.</div>`;
          return;
        }

        const curActive = new Set(($("ai-model").value || "").split(/[,;]/).map((s) => s.trim()).filter(Boolean));
        $("ai-model-chips").innerHTML = models.map((m) => {
          const isAct = curActive.has(m);
          return `<button class="model-chip ${isAct ? "active" : ""}" data-model="${esc(m)}">${esc(m)}</button>`;
        }).join("");

        $("ai-model-chips").querySelectorAll(".model-chip").forEach((chip) => {
          chip.addEventListener("click", () => {
            chip.classList.toggle("active");
            const activeChips = Array.from($("ai-model-chips").querySelectorAll(".model-chip.active"));
            const selectedModels = activeChips.map((c) => c.dataset.model);
            $("ai-model").value = selectedModels.join(",");
            if (selectedModels.length > 1) {
              toast(`Multi-rotation active (${selectedModels.length} models selected)`);
            } else if (selectedModels.length === 1) {
              toast(`Selected: ${selectedModels[0]}`);
            } else {
              toast("No models selected");
            }
          });
        });
        toast(`Loaded ${models.length} models from endpoint`);
      } catch (e) {
        toast("Error fetching models: " + e.message);
      } finally {
        btn.disabled = false;
        btn.textContent = "Fetch models";
      }
    }
    $("ai-fetch-models").addEventListener("click", fetchModels);

    // Live test playground
    async function testModelPlayground() {
      const btn = $("btn-test-model");
      const prompt = $("test-prompt").value.trim() || "hello";
      const model = $("ai-model").value.trim();
      const baseurl = $("ai-baseurl").value.trim();
      const apikey = $("ai-key").value.trim();

      const box = $("test-results-box");
      const badge = $("test-badge");
      const modelEl = $("test-model-name");
      const replyEl = $("test-reply-content");
      const summaryEl = $("test-models-summary");

      box.classList.remove("hidden");
      badge.className = "pill pill-warning";
      badge.textContent = "Testing...";
      modelEl.textContent = "Pinging candidate model(s)...";
      replyEl.textContent = "Sending test request...";
      summaryEl.innerHTML = "";

      btn.disabled = true;
      btn.textContent = "Testing...";

      try {
        const res = await api("/api/test_model", {
          message: prompt,
          model,
          base_url: baseurl,
          api_key: apikey,
        });

        if (res && res.ok) {
          badge.className = "pill pill-positive";
          badge.textContent = "Working";
          modelEl.textContent = `Replied: ${res.model_used || "OK"}`;
          replyEl.textContent = `"${res.reply}"`;

          if (res.active_model) {
            $("ai-model").value = res.active_model;
            const activeSet = new Set(res.active_model.split(","));
            document.querySelectorAll("#ai-model-chips .model-chip").forEach((c) => {
              c.classList.toggle("active", activeSet.has(c.dataset.model));
            });
          }

          const pills = (res.results || []).map((r) => {
            const cls = r.ok ? "test-pill ok" : "test-pill fail";
            const icon = r.ok ? "✓" : "✗";
            return `<span class="${cls}">${icon} ${esc(r.model)}: ${esc(r.detail)}</span>`;
          });
          summaryEl.innerHTML = pills.join("");

          if (res.failed_models && res.failed_models.length > 0) {
            toast(`Auto-pruned ${res.failed_models.length} failing model(s). Working: ${res.active_model}`);
          } else {
            toast(`Working model verified: ${res.active_model}`);
          }
        } else {
          badge.className = "pill pill-negative";
          badge.textContent = "Failed";
          modelEl.textContent = "All candidate models failed";
          replyEl.textContent = (res && res.error) || "No valid response received. Check your endpoint URL, model name, and API key.";

          const pills = (res && res.results ? res.results : []).map((r) => {
            return `<span class="test-pill fail">✗ ${esc(r.model)}: ${esc(r.detail)}</span>`;
          });
          summaryEl.innerHTML = pills.join("");
          toast("Model test failed");
        }
      } catch (e) {
        badge.className = "pill pill-negative";
        badge.textContent = "Error";
        replyEl.textContent = "Request error: " + e.message;
        toast("Error during test: " + e.message);
      } finally {
        btn.disabled = false;
        btn.textContent = "Send test";
      }
    }
    $("btn-test-model").addEventListener("click", testModelPlayground);
    $("test-prompt").addEventListener("keydown", (e) => { if (e.key === "Enter") $("btn-test-model").click(); });

    $("cmd-search").addEventListener("input", () => {
      renderCommandChips(commandCache);
    });
  }

  async function init() {
    if (tg) { try { tg.ready(); tg.expand(); tg.setHeaderColor("#07150C"); tg.setBackgroundColor("#07150C"); } catch { /* older clients */ } }

    let auth = null;
    try { auth = await api("/api/auth"); } catch { /* no server (plain browser / file) → paywall */ }
    if (!auth || auth.authorized !== true) { maybePaywall(auth); return; }

    $("paywall").classList.add("hidden");
    $("app").classList.remove("hidden");
    $("whoami").textContent = auth.user && auth.user.name ? auth.user.name : "";
    $("app-version").textContent = auth.version ? `v${auth.version}` : "";
    wire();
    const params = new URLSearchParams(location.search);
    showView(["overview", "chats", "persona", "approvals", "more"].includes(params.get("view")) ? params.get("view") : "overview");
    // Light refresh so the panel follows the bot if both are open.
    setInterval(() => { if (currentView === "overview") refreshOverview(); }, 10000);
  }

  init();
})();
