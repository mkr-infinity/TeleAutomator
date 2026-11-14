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
    try {
      if (tg && tg.initData) return tg.initData;
      if (location.hash && location.hash.includes("tgWebAppData=")) {
        const hashParams = new URLSearchParams(location.hash.slice(1));
        const raw = hashParams.get("tgWebAppData");
        if (raw) return raw;
      }
      return "";
    } catch { return ""; }
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

  function formatStructuredAppResponse(raw) {
    if (!raw) return '<div class="empty">No response received.</div>';
    const lines = String(raw).split("\n").map((l) => l.trim()).filter(Boolean);
    const elements = [];

    let startIndex = 0;
    if (lines.length > 0 && /^[✅❌⚠️❓🚀⚡⏸️▶️🛑🤖]/.test(lines[0])) {
      const icon = lines[0].slice(0, 2);
      const title = lines[0].slice(2).trim();
      elements.push(`<div class="app-callout">
        <span class="app-callout-icon">${esc(icon)}</span>
        <div class="app-callout-body"><strong>${esc(plain(title))}</strong></div>
      </div>`);
      startIndex = 1;
    }

    for (let i = startIndex; i < lines.length; i++) {
      const line = lines[i];
      if (/^[•\-\*]\s/.test(line)) {
        const content = line.replace(/^[•\-\*]\s/, "");
        const cmdMatch = content.match(/^`?(\/[a-zA-Z0-9_]+)`?\s*[-–—:]?\s*(.*)$/);
        if (cmdMatch) {
          elements.push(`<div class="app-response-item">
            <span class="cmd-pill">${esc(cmdMatch[1])}</span>
            <span>${esc(plain(cmdMatch[2]))}</span>
          </div>`);
        } else {
          elements.push(`<div class="app-response-item">
            <span class="app-item-bullet">•</span>
            <span>${esc(plain(content))}</span>
          </div>`);
        }
      } else if (/^(\*|\*\*)[^*]+(\*|\*\*):?$/.test(line)) {
        elements.push(`<div class="app-response-header">${esc(plain(line))}</div>`);
      } else {
        elements.push(`<p class="app-response-text">${esc(plain(line))}</p>`);
      }
    }

    return `<div class="app-response-card">${elements.join("")}</div>`;
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
  function toast(text, kind = "info") {
    const el = $("toast");
    if (!el) return;
    const plainText = plain(text) || "Done";

    let statusKind = kind;
    if (kind === "info") {
      const lower = plainText.toLowerCase();
      if (lower.includes("fail") || lower.includes("error") || lower.includes("halt") || lower.includes("stop")) {
        statusKind = "err";
      } else if (lower.includes("ok") || lower.includes("saved") || lower.includes("verified") || lower.includes("resumed") || lower.includes("allowed") || lower.includes("done")) {
        statusKind = "ok";
      }
    }

    el.className = `toast toast-${statusKind}`;
    const iconEl = $("toast-icon");
    const msgEl = $("toast-msg");
    if (iconEl) iconEl.textContent = statusKind === "ok" ? "✓" : (statusKind === "err" ? "!" : "ℹ");
    if (msgEl) msgEl.textContent = plainText;
    else el.textContent = plainText;

    el.classList.remove("hidden");
    haptic(statusKind === "err" ? "err" : (statusKind === "ok" ? "ok" : "light"));
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

    // Telegram TMA native BackButton support
    try {
      if (tg && tg.BackButton) {
        tg.BackButton.show();
        tg.BackButton.onClick(closeSheet);
      }
    } catch (_) {}
    haptic("light");
  }

  function closeSheet() {
    $("sheet-backdrop").classList.add("hidden");
    $("sheet").classList.add("hidden");

    // Revert Telegram TMA native BackButton
    try {
      if (tg && tg.BackButton) {
        tg.BackButton.hide();
        tg.BackButton.offClick(closeSheet);
      }
    } catch (_) {}
    haptic("light");
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
    renderSparkline(acts && acts.activity ? acts.activity : [], s.replies_24h || 0);
    const rows = (acts.activity || []).slice(0, 4);
    $("ov-activity").innerHTML = rows.length
      ? rows.map(feedRowHtml).join("")
      : `<div class="empty">No replies yet, the account stays quiet until a chat talks.</div>`;
    $("tab-approvals").textContent = String(s.pending_count || 0);
    $("tab-approvals").classList.toggle("hidden", !s.pending_count);
  }

  function renderSparkline(activityList, replies24h) {
    const container = $("sparkline-bars");
    if (!container) return;

    const totalBadge = $("activity-total-badge");
    if (totalBadge) {
      totalBadge.textContent = `${replies24h || 0} in 24h`;
    }

    const buckets = new Array(24).fill(0);
    const now = Date.now();

    (activityList || []).forEach((item) => {
      if (!item.ts) return;
      const itemDate = new Date(item.ts.includes("T") ? item.ts : item.ts.replace(" ", "T"));
      const diffHours = Math.floor((now - itemDate.getTime()) / (1000 * 60 * 60));
      if (diffHours >= 0 && diffHours < 24) {
        buckets[23 - diffHours]++;
      }
    });

    const bucketSum = buckets.reduce((a, b) => a + b, 0);
    if (replies24h > 0 && bucketSum === 0) {
      buckets[23] = Math.max(1, Math.round(replies24h * 0.35));
      buckets[22] = Math.max(0, Math.round(replies24h * 0.25));
      buckets[21] = Math.max(0, Math.round(replies24h * 0.20));
      buckets[20] = Math.max(0, Math.round(replies24h * 0.20));
    }

    const maxVal = Math.max(1, ...buckets);

    container.innerHTML = buckets.map((count, idx) => {
      const isCurrent = idx === 23;
      const heightPx = count > 0 ? Math.round(6 + (count / maxVal) * 44) : 6;
      const cls = ["spark-bar"];
      if (count > 0) cls.push("active");
      if (isCurrent) cls.push("current");
      const hourLabel = idx === 23 ? "Current hour" : `${23 - idx}h ago`;
      const tip = `${count} ${count === 1 ? "reply" : "replies"} (${hourLabel})`;

      return `<div class="${cls.join(" ")}" style="height: ${heightPx}px" title="${tip}" data-tip="${tip}"></div>`;
    }).join("");

    container.querySelectorAll(".spark-bar").forEach((bar) => {
      bar.addEventListener("click", () => {
        haptic("light");
        toast(bar.dataset.tip, "info");
      });
    });
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
    if ($("kpi-engine")) $("kpi-engine").textContent = s.ai_engine || "Local";

    if ($("ov-engine-badge")) {
      $("ov-engine-badge").textContent = `${s.ai_engine || "AI"} Engine`;
      if ($("ov-status-pill")) {
        const statusText = s.emergency ? "Stopped" : (s.safe_mode ? "Safe Mode" : (s.state === "paused" ? "Paused" : "Active"));
        $("ov-status-pill").textContent = statusText;
        $("ov-status-pill").className = `pill ${s.emergency ? "pill-negative" : (s.state === "paused" ? "pill-warning" : "pill-positive")}`;
      }
      $("ov-model-val").textContent = s.ai_model || (s.ai_engine === "Local" ? "Local Rule Base" : "Default");
      if ($("ov-persona-val")) {
        $("ov-persona-val").textContent = (s.style || "casual").charAt(0).toUpperCase() + (s.style || "casual").slice(1);
      }
      $("ov-qh-sched").textContent = s.quiet_hours_schedule || "02:00 – 08:00 IST";
      $("ov-req-count").textContent = (s.token_requests || 0).toLocaleString();
    }

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
    const initials = c.initials || (c.type === "Group" ? "GP" : "DM");
    const avatarBg = c.avatar_bg || "linear-gradient(135deg, #153421 0%, #1E3F2A 100%)";
    const userDisplay = c.username ? (c.username.startsWith("@") ? c.username : "@" + c.username) : "";

    return `<div class="chat-capsule ${c.blocked ? "is-blocked" : ""}" data-cid="${c.id}">
      <div class="chat-capsule-head">
        <div class="chat-avatar" style="background: ${avatarBg}">${esc(initials)}</div>
        <div class="chat-info">
          <div class="chat-title-row">
            <span class="chat-name">${esc(c.name)}</span>
            ${userDisplay ? `<span class="pill pill-neutral chat-user">${esc(userDisplay)}</span>` : ""}
            <span class="pill pill-neutral num chat-id">${esc(String(c.id))}</span>
          </div>
          <div class="chat-badges">
            <span class="pill ${c.type === "Group" ? "pill-positive" : "pill-neutral"}">${esc(c.type)}</span>
            ${c.blocked ? `<span class="pill pill-negative">Blocked</span>` : ""}
            ${c.prompt ? `<span class="pill pill-warning">Custom Prompt</span>` : ""}
            ${c.context ? `<span class="pill pill-positive">Has Context</span>` : ""}
            ${c.voice_profile ? `<span class="pill pill-neutral">Voice Profile</span>` : ""}
            <span class="pill pill-neutral">Chatty ${esc(fmtPct(c.chatty))}</span>
            ${c.style ? `<span class="pill pill-neutral">${esc(c.style)}</span>` : ""}
          </div>
        </div>
      </div>
      <div class="chat-actions">
        <button class="btn small" data-op="prompt">Prompt</button>
        <button class="btn small" data-op="context">Context</button>
        <button class="btn small" data-op="chatty">Chatty</button>
        <button class="btn small danger" data-op="remove">Remove</button>
      </div>
    </div>`;
  }

  function wireChatRows() {
    document.querySelectorAll("#chat-list .chat-capsule, #chat-list .row").forEach((row) => {
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

  // -------------------------------------------------------------- persona (Phase 5: Presets)

  const PROMPT_PRESETS = [
    {
      id: "casual",
      name: "Casual Friend",
      icon: "💬",
      prompt: "Be casual, natural, concise, and friendly. Speak like a close peer on Telegram, avoid corporate jargon, and keep messages under 2-3 sentences."
    },
    {
      id: "exec",
      name: "Executive & Crisp",
      icon: "⚡",
      prompt: "Be extremely concise, professional, and high-signal. Answer directly in 1-2 clear sentences with crisp facts. No fluff or filler."
    },
    {
      id: "support",
      name: "Support Specialist",
      icon: "🤝",
      prompt: "Be warm, helpful, empathetic, and solution-oriented. Clarify issues politely, guide step-by-step, and provide reassuring, reliable answers."
    },
    {
      id: "tech",
      name: "Tech & Automation",
      icon: "🚀",
      prompt: "Speak in natural tech community tone. Sharp, knowledgeable about systems and automation, helpful without being overly formal."
    },
    {
      id: "witty",
      name: "Witty & Fun",
      icon: "🎭",
      prompt: "Be playful, lightly humorous, cheerful, and witty. Keep it engaging, upbeat, and fun while still answering questions accurately."
    },
    {
      id: "reset",
      name: "Built-in Default",
      icon: "🔄",
      prompt: ""
    }
  ];

  function renderPromptPresets() {
    const el = $("preset-carousel");
    if (!el) return;
    const currentPrompt = ($("pf-prompt").value || "").trim();

    el.innerHTML = PROMPT_PRESETS.map((p) => {
      const isActive = p.prompt ? currentPrompt === p.prompt : !currentPrompt;
      return `<button type="button" class="preset-chip ${isActive ? "active" : ""}" data-preset="${p.id}">
        <span class="preset-icon">${p.icon}</span>
        <span>${esc(p.name)}</span>
      </button>`;
    }).join("");

    el.querySelectorAll(".preset-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        haptic("light");
        const found = PROMPT_PRESETS.find((x) => x.id === chip.dataset.preset);
        if (!found) return;
        $("pf-prompt").value = found.prompt;
        el.querySelectorAll(".preset-chip").forEach((c) => c.classList.remove("active"));
        chip.classList.add("active");
        toast(found.prompt ? `Loaded "${found.name}". Tap Save prompt to apply.` : "Reset to built-in persona. Tap Save prompt to apply.", "info");
      });
    });
  }

  async function refreshPersona() {
    const s = await api("/api/state");
    if (!s || s.authorized === false) return maybePaywall(s);
    if (document.activeElement !== $("pf-prompt")) $("pf-prompt").value = s.prompt || "";
    if (document.activeElement !== $("pf-name")) $("pf-name").value = s.owner_name || "";
    renderPromptPresets();
    const styles = ["casual", "concise", "formal", "humorous"];
    $("pf-style").innerHTML = styles.map((st) =>
      `<button class="seg ${st === s.style ? "active" : ""}" data-style="${st}">${st}</button>`).join("");
    $("pf-style").querySelectorAll(".seg").forEach((b) =>
      b.addEventListener("click", () => runAction("style", { value: b.dataset.style })));
    const data = await api("/api/chats");
    const chats = (data.chats || []).filter((c) => c.prompt || c.context);
    $("pf-chats").innerHTML = chats.length
      ? chats.map((c) => {
          return `<div class="persona-chat-card">
            <div class="capsule-main">
              <div class="capsule-head">
                <span class="capsule-title">${esc(c.name)}</span>
                <span class="pill pill-neutral num">${esc(String(c.id))}</span>
                ${c.prompt ? `<span class="pill pill-warning">Custom Prompt</span>` : ""}
                ${c.context ? `<span class="pill pill-positive">Has Context</span>` : ""}
              </div>
              <p class="capsule-sub">${c.prompt ? `Prompt: ${esc(c.prompt)}` : ""}${c.prompt && c.context ? " · " : ""}${c.context ? `Context: ${esc(c.context)}` : ""}</p>
            </div>
            <div class="capsule-side">
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

  // ------------------------------------------------------------ approvals (Phase 2: Swipe Actions)

  async function refreshApprovals() {
    const data = await api("/api/pending");
    if (!data || data.authorized === false) return maybePaywall(data);
    const rows = data.pending || [];
    const count = rows.length;
    $("tab-approvals").textContent = String(count);
    $("tab-approvals").classList.toggle("hidden", !count);
    $("approval-list").innerHTML = count
      ? rows.map(approvalCardHtml).join("")
      : `<div class="empty">Nothing waiting. In approval mode every draft shows up here.</div>`;
    $("approval-list").querySelectorAll("[data-ap]").forEach((btn) =>
      btn.addEventListener("click", () => runAction(btn.dataset.ap, { id: btn.dataset.id })));
    wireApprovalSwipes();
  }

  function approvalCardHtml(p) {
    return `<div class="approval-card-wrap" data-id="${p.id}">
      <div class="approval-swipe-underlay">
        <div class="swipe-hint swipe-hint-approve">
          <span class="swipe-icon">✓</span>
          <span>Approve</span>
        </div>
        <div class="swipe-hint swipe-hint-reject">
          <span>Reject</span>
          <span class="swipe-icon">✕</span>
        </div>
      </div>
      <div class="approval-card-content">
        <div class="approval-head">
          <span class="pill pill-warning">Draft #${p.id}</span>
          <span class="feed-ts num">${esc(String(p.created || "").slice(0, 16))}</span>
        </div>
        <p class="approval-chat-title">${esc(p.chat_title || String(p.chat_id))}</p>
        <div class="approval-draft-bubble">${esc(p.text)}</div>
        <div class="approval-actions">
          <button class="btn small primary" data-ap="approve" data-id="${p.id}">✓ Approve</button>
          <button class="btn small danger" data-ap="reject" data-id="${p.id}">✕ Reject</button>
          <span class="swipe-hint-pill">Swipe right to approve · left to reject</span>
        </div>
      </div>
    </div>`;
  }

  function wireApprovalSwipes() {
    document.querySelectorAll(".approval-card-wrap").forEach((wrap) => {
      const content = wrap.querySelector(".approval-card-content");
      const approveHint = wrap.querySelector(".swipe-hint-approve");
      const rejectHint = wrap.querySelector(".swipe-hint-reject");
      const draftId = wrap.dataset.id;
      if (!content) return;

      let startX = 0;
      let startY = 0;
      let currentX = 0;
      let isSwiping = false;

      wrap.addEventListener("touchstart", (e) => {
        if (!e.touches || !e.touches[0]) return;
        startX = e.touches[0].clientX;
        startY = e.touches[0].clientY;
        currentX = 0;
        isSwiping = false;
        content.style.transition = "none";
      }, { passive: true });

      wrap.addEventListener("touchmove", (e) => {
        if (!e.touches || !e.touches[0]) return;
        const dx = e.touches[0].clientX - startX;
        const dy = e.touches[0].clientY - startY;

        if (!isSwiping) {
          if (Math.abs(dx) > 12 && Math.abs(dx) > Math.abs(dy)) {
            isSwiping = true;
          } else if (Math.abs(dy) > 12) {
            return;
          }
        }

        if (isSwiping) {
          currentX = dx;
          content.style.transform = `translateX(${dx}px)`;
          if (dx > 0) {
            if (approveHint) approveHint.style.opacity = String(Math.min(dx / 70, 1));
            if (rejectHint) rejectHint.style.opacity = "0";
          } else {
            if (rejectHint) rejectHint.style.opacity = String(Math.min(-dx / 70, 1));
            if (approveHint) approveHint.style.opacity = "0";
          }
        }
      }, { passive: true });

      wrap.addEventListener("touchend", () => {
        if (!isSwiping) return;
        content.style.transition = "transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1)";
        if (currentX > 80) {
          content.style.transform = "translateX(120%)";
          haptic("ok");
          runAction("approve", { id: draftId });
        } else if (currentX < -80) {
          content.style.transform = "translateX(-120%)";
          haptic("err");
          runAction("reject", { id: draftId });
        } else {
          content.style.transform = "translateX(0px)";
          if (approveHint) approveHint.style.opacity = "0";
          if (rejectHint) rejectHint.style.opacity = "0";
        }
      }, { passive: true });
    });
  }

  // ----------------------------------------------------------------- more

  let commandCache = [];

  async function refreshMore() {
    const data = await api("/api/access");
    if (!data || data.authorized === false) return maybePaywall(data);
    $("access-list").innerHTML = (data.users || []).length
      ? data.users.map((u) => {
          const initials = (u.name || "U").slice(0, 2).toUpperCase();
          return `<div class="user-capsule">
            <div class="user-avatar-circle">${esc(initials)}</div>
            <div class="capsule-main">
              <div class="capsule-head">
                <span class="capsule-title">${esc(u.name)}</span>
                ${u.main ? '<span class="pill pill-positive">Owner</span>' : '<span class="pill pill-neutral">Authorized</span>'}
              </div>
              <p class="capsule-sub num">${esc(String(u.id))}${u.username ? " · @" + esc(u.username) : ""}</p>
            </div>
            <div class="capsule-side">
              ${u.main ? "" : `<button class="btn small danger" data-unauth="${u.id}">Remove</button>`}
            </div>
          </div>`;
        }).join("")
      : `<div class="empty">No authorized users.</div>`;
    $("access-list").querySelectorAll("[data-unauth]").forEach((btn) =>
      btn.addEventListener("click", () => openSheet("Remove user", `<p>Revoke panel access for user <span class="num">${esc(btn.dataset.unauth)}</span>?</p>`,
        [{ label: "Remove", kind: "danger", onClick: () => runAction("removeauth", { user_id: btn.dataset.unauth }) }, { label: "Cancel" }])));

    const s = await api("/api/state");
    if (s && s.authorized !== false) {
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
        const target = src.find((x) => x.command === cmd);
        const desc = target ? plain(target.description) : "";
        openSheet(`/${cmd}`, `${desc ? `<p class="field-hint" style="margin-top:0;margin-bottom:10px">${esc(desc)}</p>` : ""}<input id="sheet-input" placeholder="Arguments (leave empty to run bare)">`,
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
    return res;
  }

  async function runCmd(command) {
    haptic();
    const res = await api("/api/cmd", { command });
    if (res && res.authorized === false) return maybePaywall(res);
    haptic(res && res.ok ? "ok" : "err");
    openSheet(`/${command.split(" ")[0].slice(1)}`, formatStructuredAppResponse(res && res.response ? res.response : "No response."), [{ label: "Close" }]);
    loadView(currentView);
    return res;
  }

  // -------------------------------------------------------------- paywall & loader

  let paywallPoll = null;
  let wired = false;

  function hideLoading() {
    const loader = $("loading-screen");
    if (loader && !loader.classList.contains("hidden")) {
      loader.classList.add("fade-out");
      setTimeout(() => loader.classList.add("hidden"), 300);
    }
  }

  function wirePaywall() {
    const btn = $("pay-check-btn");
    if (!btn || btn.dataset.wired) return;
    btn.dataset.wired = "1";
    btn.addEventListener("click", async () => {
      haptic();
      btn.textContent = "Checking…";
      btn.disabled = true;
      try {
        const fresh = await api("/api/auth");
        if (fresh && fresh.authorized === true) {
          unlockApp(fresh);
          toast("Access granted! Welcome.");
          return;
        }
        haptic("err");
        toast("Account not authorized yet.");
      } catch {
        toast("Could not connect to server.");
      } finally {
        btn.textContent = "Check access";
        btn.disabled = false;
      }
    });
  }

  function maybePaywall(res) {
    hideLoading();
    if (!res || res.authorized === false) {
      $("app").classList.add("hidden");
      $("paywall").classList.remove("hidden");
      if (res && res.version) $("pay-version").textContent = `v${res.version}`;
      wirePaywall();
      if (!paywallPoll) {
        paywallPoll = setInterval(async () => {
          try {
            const fresh = await api("/api/auth");
            if (fresh && fresh.authorized === true) {
              clearInterval(paywallPoll);
              paywallPoll = null;
              unlockApp(fresh);
              toast("Access granted! Welcome.");
            }
          } catch (_) {}
        }, 8000);
      }
      return true;
    }
    if (paywallPoll) { clearInterval(paywallPoll); paywallPoll = null; }
    return false;
  }

  function unlockApp(auth) {
    if (paywallPoll) { clearInterval(paywallPoll); paywallPoll = null; }
    hideLoading();
    $("paywall").classList.add("hidden");
    $("app").classList.remove("hidden");
    $("whoami").textContent = auth.user && auth.user.name ? auth.user.name : "";
    $("app-version").textContent = auth.version ? `v${auth.version}` : "";
    if (!wired) {
      wired = true;
      wire();
      initEventSource();
      const params = new URLSearchParams(location.search);
      showView(["overview", "chats", "persona", "approvals", "more"].includes(params.get("view")) ? params.get("view") : "overview");
      setInterval(() => { if (currentView === "overview") refreshOverview(); }, 12000);
    }
  }

  // ---------------------------------------------------------------- init

  function wire() {
    document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showView(t.dataset.view)));
    $("sheet-backdrop").addEventListener("click", closeSheet);

    const sheetCloseBtn = $("sheet-close");
    if (sheetCloseBtn) sheetCloseBtn.addEventListener("click", closeSheet);

    const toastEl = $("toast");
    if (toastEl) toastEl.addEventListener("click", () => toastEl.classList.add("hidden"));

    const beacon = $("live-beacon");
    if (beacon) {
      beacon.addEventListener("click", () => {
        const isLive = beacon.classList.contains("live");
        toast(isLive ? "Engine: Real-time Live Sync active" : "Engine: Connecting to control engine…", isLive ? "ok" : "info");
      });
    }

    // Android Material 3 Expressive Fluid Wave Touch Ripple + Instant Tactile Haptic
    document.addEventListener("pointerdown", (e) => {
      const target = e.target.closest(".btn, .pay-btn, .pay-check-btn, .chip, .seg, .model-chip, .preset-chip, .m3-nav-item, .sheet-close-btn, .linklike");
      if (!target) return;
      haptic("light");
      const rect = target.getBoundingClientRect();
      const size = Math.max(rect.width, rect.height) * 2;
      const x = e.clientX - rect.left - size / 2;
      const y = e.clientY - rect.top - size / 2;
      const ripple = document.createElement("span");
      ripple.className = "m3-wave-ripple";
      ripple.style.width = `${size}px`;
      ripple.style.height = `${size}px`;
      ripple.style.left = `${x}px`;
      ripple.style.top = `${y}px`;
      target.appendChild(ripple);
      setTimeout(() => ripple.remove(), 550);
    }, { passive: true });

    // Swipe down on bottom sheet to dismiss
    const sheetEl = $("sheet");
    if (sheetEl) {
      let touchStartY = 0;
      sheetEl.addEventListener("touchstart", (e) => {
        if (e.touches && e.touches[0]) touchStartY = e.touches[0].clientY;
      }, { passive: true });
      sheetEl.addEventListener("touchmove", (e) => {
        if (e.touches && e.touches[0]) {
          const currentY = e.touches[0].clientY;
          if (currentY - touchStartY > 60 && sheetEl.scrollTop <= 0) {
            closeSheet();
          }
        }
      }, { passive: true });
    }

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

    $("allow-btn").addEventListener("click", async () => {
      const v = $("allow-id").value.trim();
      if (!v) return toast("Enter a chat ID");
      $("allow-id").value = "";
      const res = await runAction("allow", { chat_id: v });
      if (res && res.ok) {
        refreshChats();
      }
    });
    $("allow-id").addEventListener("keydown", (e) => { if (e.key === "Enter") $("allow-btn").click(); });

    $("pf-save").addEventListener("click", () => {
      const v = $("pf-prompt").value.trim();
      if (!v) return runAction("prompt", { value: "reset" });
      runAction("prompt", { value: v });
    });
    $("pf-prompt").addEventListener("input", () => {
      const v = ($("pf-prompt").value || "").trim();
      document.querySelectorAll("#preset-carousel .preset-chip").forEach((chip) => {
        const found = PROMPT_PRESETS.find((x) => x.id === chip.dataset.preset);
        chip.classList.toggle("active", Boolean(found && found.prompt && found.prompt === v));
      });
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
            const iconSvg = r.ok
              ? '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" style="display:inline-block;vertical-align:-1px;margin-right:4px;"><polyline points="3 8 7 12 13 4"/></svg>'
              : '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" style="display:inline-block;vertical-align:-1px;margin-right:4px;"><line x1="4" y1="4" x2="12" y2="12"/><line x1="12" y1="4" x2="4" y2="12"/></svg>';
            return `<span class="${cls}">${iconSvg}${esc(r.model)}: ${esc(r.detail)}</span>`;
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

          const failSvg = '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" style="display:inline-block;vertical-align:-1px;margin-right:4px;"><line x1="4" y1="4" x2="12" y2="12"/><line x1="12" y1="4" x2="4" y2="12"/></svg>';
          const pills = (res && res.results ? res.results : []).map((r) => {
            return `<span class="test-pill fail">${failSvg}${esc(r.model)}: ${esc(r.detail)}</span>`;
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

  function syncTelegramTheme() {
    if (!tg) return;
    try {
      const darkBg = (tg.themeParams && tg.themeParams.bg_color) || "#0B0E14";
      if (tg.setHeaderColor) tg.setHeaderColor(darkBg);
      if (tg.setBackgroundColor) tg.setBackgroundColor(darkBg);
    } catch (_) {}
  }

  async function init() {
    if (tg) {
      try {
        tg.ready();
        tg.expand();
        syncTelegramTheme();
        tg.onEvent("themeChanged", syncTelegramTheme);
      } catch { /* older clients */ }
    }

    let auth = null;
    try { auth = await api("/api/auth"); } catch { /* no server (plain browser / file) → paywall */ }
    if (!auth || auth.authorized !== true) { maybePaywall(auth); return; }

    unlockApp(auth);
  }

  function setConnectionStatus(status) {
    const beacon = $("live-beacon");
    if (!beacon) return;
    beacon.className = `live-beacon ${status}`;
    beacon.title = status === "live"
      ? "Real-time engine connected"
      : (status === "connecting" ? "Connecting to engine…" : "Engine offline");
  }

  function initEventSource() {
    if (!window.EventSource) {
      setConnectionStatus("offline");
      return;
    }
    try {
      const raw = initDataHeader();
      const q = raw ? `?initData=${encodeURIComponent(raw)}` : "";
      const es = new EventSource(`/api/events${q}`);
      es.onopen = () => {
        setConnectionStatus("live");
      };
      es.addEventListener("state", (e) => {
        setConnectionStatus("live");
        try {
          const s = JSON.parse(e.data);
          if (s && s.state) renderState(s);
        } catch (_) {}
      });
      es.onerror = () => {
        setConnectionStatus("connecting");
        // SSE reconnects automatically by browser spec
      };
    } catch (_) {
      setConnectionStatus("offline");
    }
  }

  init();
})();
