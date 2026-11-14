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
      { id: 41, chat_id: -1001987654321, chat_title: "Startup India Founders", text: "btw are you joining the demo day on friday? wanted to show you the pitch deck before we send it out", created: "2026-11-13 14:22" },
      { id: 40, chat_id: 987654321, chat_title: "Aarav", text: "🎙️ Reached home! Call me when free, need to ask about the weekend plan.", created: "2026-11-13 13:05", is_voice: true, voice_dur: "0:21" },
    ],
    activity: [
      { chat: "Delhi Tech Meetup", chat_id: -1001765432109, sender: "TeleAutomator", text: "yeah the venue shifted to Hauz Khas this month, same 7pm slot", ts: "2026-11-13 14:18" },
      { chat: "Rohan Sharma", chat_id: 123456789, sender: "TeleAutomator", text: "🎙️ Haan bhai venue pahunch gaya, 2nd floor hall booked hai", ts: "2026-11-13 13:52", is_voice: true, voice_dur: "0:14" },
      { chat: "Startup India Founders", chat_id: -1001987654321, sender: "TeleAutomator", text: "pricing page looks solid, maybe add a monthly option", ts: "2026-11-13 12:30" },
      { chat: "Mom", chat_id: 876543210, sender: "TeleAutomator", text: "📷 [photo] Lunch pic sent, looks great!", ts: "2026-11-13 11:04", is_media: true },
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

  // ------------------------------------------------------------ IST & AM/PM Dates
  function formatIST(raw, showDate = true) {
    if (!raw) return "—";
    let str = String(raw).trim();
    if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(str) && !str.endsWith("Z") && !str.includes("+")) {
      str = str.replace(" ", "T") + "Z";
    }
    const date = new Date(str);
    if (isNaN(date.getTime())) return String(raw);
    try {
      const formatter = new Intl.DateTimeFormat("en-US", {
        timeZone: "Asia/Kolkata",
        month: showDate ? "short" : undefined,
        day: showDate ? "numeric" : undefined,
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
      });
      return `${formatter.format(date)} IST`;
    } catch (_) {
      const utc = date.getTime() + (date.getTimezoneOffset() * 60000);
      const ist = new Date(utc + (3600000 * 5.5));
      let hours = ist.getHours();
      const minutes = String(ist.getMinutes()).padStart(2, "0");
      const ampm = hours >= 12 ? "PM" : "AM";
      hours = hours % 12 || 12;
      const timeStr = `${hours}:${minutes} ${ampm} IST`;
      if (!showDate) return timeStr;
      const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
      return `${months[ist.getMonth()]} ${ist.getDate()}, ${timeStr}`;
    }
  }

  function formatTime12h(timeStr) {
    if (!timeStr) return "";
    const match = String(timeStr).trim().match(/^(\d{1,2}):(\d{2})$/);
    if (!match) return timeStr;
    let h = parseInt(match[1], 10);
    const m = match[2];
    const ampm = h >= 12 ? "PM" : "AM";
    h = h % 12 || 12;
    return `${String(h).padStart(2, "0")}:${m} ${ampm}`;
  }

  function formatQuietSchedule(raw) {
    if (!raw) return "02:00 AM – 08:00 AM IST";
    const cleaned = String(raw).replace(/\s*IST\s*$/i, "").trim();
    const parts = cleaned.split(/\s*[-–—]\s*/);
    if (parts.length === 2) {
      return `${formatTime12h(parts[0])} – ${formatTime12h(parts[1])} IST`;
    }
    return raw;
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
      $("ov-qh-sched").textContent = formatQuietSchedule(s.quiet_hours_schedule);
      $("ov-req-count").textContent = (s.token_requests || 0).toLocaleString();
    }

    $("act-pause").classList.toggle("hidden", s.state !== "active");
    $("act-resume").classList.toggle("hidden", s.state === "active");
  }

  function feedRowHtml(a) {
    const isVoice = Boolean(a.is_voice || /\[voice|\[audio|🎤|🎙️|\(voice\)/i.test(a.text || "") || a.voice_dur);
    const isMedia = Boolean(a.is_media || /\[photo|\[image|\[video|\[document|📷|📹|📎|\(media\)/i.test(a.text || ""));
    const voiceBadge = isVoice
      ? `<div class="voice-badge">
          <span class="voice-wave"><span class="wave-bar"></span><span class="wave-bar"></span><span class="wave-bar"></span><span class="wave-bar"></span></span>
          <span>Voice Note ${esc(a.voice_dur ? `(${a.voice_dur})` : "")}</span>
        </div>`
      : "";
    const mediaBadge = isMedia && !isVoice
      ? `<div class="media-badge"><span>📷 Media Reply</span></div>`
      : "";

    return `<div class="feed-row">
      <div class="feed-top"><span class="feed-chat">${esc(a.chat)}</span><span class="feed-ts num">${esc(formatIST(a.ts))}</span></div>
      ${voiceBadge}${mediaBadge}
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
    const isVoice = Boolean(p.is_voice || /\[voice|\[audio|🎤|🎙️|\(voice\)/i.test(p.text || "") || p.voice_dur);
    const isMedia = Boolean(p.is_media || /\[photo|\[image|\[video|\[document|📷|📹|📎|\(media\)/i.test(p.text || ""));
    const voiceBadge = isVoice
      ? `<div class="voice-badge">
          <span class="voice-wave"><span class="wave-bar"></span><span class="wave-bar"></span><span class="wave-bar"></span><span class="wave-bar"></span></span>
          <span>Voice Note ${esc(p.voice_dur ? `(${p.voice_dur})` : "")}</span>
        </div>`
      : "";
    const mediaBadge = isMedia && !isVoice
      ? `<div class="media-badge"><span>📷 Media Draft</span></div>`
      : "";

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
          <span class="feed-ts num">${esc(formatIST(p.created))}</span>
        </div>
        <p class="approval-chat-title">${esc(p.chat_title || String(p.chat_id))}</p>
        ${voiceBadge}${mediaBadge}
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
      renderMoreControls(s);
    }
  }

  function renderMoreControls(s) {
    if (!s) return;

    // 1. Quiet Hours & Sleep (Phase 7)
    const qhStatus = $("qh-status-pill");
    if (qhStatus) {
      qhStatus.textContent = s.quiet_hours ? "Sleeping" : "Scheduled";
      qhStatus.className = `pill ${s.quiet_hours ? "pill-warning" : "pill-positive"}`;
    }
    const qhStart = $("qh-start-input");
    const qhEnd = $("qh-end-input");
    if (qhStart && document.activeElement !== qhStart && s.quiet_hours_start) qhStart.value = s.quiet_hours_start;
    if (qhEnd && document.activeElement !== qhEnd && s.quiet_hours_end) qhEnd.value = s.quiet_hours_end;

    // 2. Behavior Toggles
    const toggleMap = {
      "reaction": s.auto_reactions,
      "multibubble": s.multibubble,
      "typo": s.typo,
      "debounce": s.debounce,
      "followup": s.followup,
      "mentiononly": s.mention_only,
    };
    Object.entries(toggleMap).forEach(([action, isEnabled]) => {
      const btn = $(`sw-${action}`);
      if (!btn) return;
      const on = Boolean(isEnabled);
      btn.dataset.state = on ? "on" : "off";
      btn.className = `clay-switch ${on ? "on" : "off"}`;
      btn.textContent = on ? "ON" : "OFF";
    });

    // 3. AI Tuning Chips
    const setSegActive = (containerId, activeVal) => {
      const container = $(containerId);
      if (!container) return;
      container.querySelectorAll(".seg").forEach((b) => {
        b.classList.toggle("active", String(b.dataset.val).toLowerCase() === String(activeVal).toLowerCase());
      });
    };
    setSegActive("seg-thinking", s.thinking || "default");
    setSegActive("seg-temp", s.temperature || "0.7");
    setSegActive("seg-lang", s.lang || "dynamic");
    setSegActive("seg-maxtokens", s.max_tokens || "512");

    // 4. Keyword Rules
    const rulesList = $("rules-list");
    if (rulesList) {
      const rules = s.rules || [];
      rulesList.innerHTML = rules.length
        ? rules.map((r) => `<div class="rule-row">
            <div class="rule-info">
              <span class="rule-trigger">Trigger: &ldquo;${esc(r.keyword)}&rdquo;</span>
              <span class="rule-response">${esc(r.reply)}</span>
            </div>
            <button class="btn small danger" data-delrule="${esc(r.keyword)}">Delete</button>
          </div>`).join("")
        : `<div class="empty">No keyword auto-replies configured. Tap &ldquo;+ Add Rule&rdquo; above.</div>`;

      rulesList.querySelectorAll("[data-delrule]").forEach((b) => {
        b.addEventListener("click", () => {
          openSheet("Delete trigger", `<p>Remove keyword auto-reply for <strong>&ldquo;${esc(b.dataset.delrule)}&rdquo;</strong>?</p>`, [
            { label: "Delete", kind: "danger", onClick: () => runAction("delrule", { value: b.dataset.delrule }) },
            { label: "Cancel" }
          ]);
        });
      });
    }

    // 5. System Safety & Maintenance
    const safemodeBadge = $("safemode-badge");
    if (safemodeBadge) {
      safemodeBadge.textContent = s.safe_mode ? "Safe Mode Triggered" : "Protected";
      safemodeBadge.className = `pill ${s.safe_mode ? "pill-warning" : "pill-positive"}`;
    }
  }

  // ------------------------------------------------ Offline Optimistic Action Queue (Phase 8)
  const OFFLINE_QUEUE_KEY = "teleautomator_offline_queue_v1";

  function loadOfflineQueue() {
    try {
      const raw = localStorage.getItem(OFFLINE_QUEUE_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch { return []; }
  }

  function saveOfflineQueue(q) {
    try {
      localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(q));
    } catch {}
  }

  function updateSyncBadge() {
    const badge = $("offline-sync-badge");
    const countEl = $("offline-sync-count");
    if (!badge) return;
    const q = loadOfflineQueue();
    if (q.length > 0) {
      if (countEl) countEl.textContent = String(q.length);
      badge.classList.remove("hidden");
      badge.title = `${q.length} action(s) queued for sync`;
    } else {
      badge.classList.add("hidden");
    }
  }

  function enqueueAction(action, params) {
    const q = loadOfflineQueue();
    q.push({
      id: Date.now() + "_" + Math.random().toString(36).slice(2, 6),
      action,
      params,
      time: new Date().toISOString()
    });
    saveOfflineQueue(q);
    updateSyncBadge();
  }

  let isFlushingQueue = false;
  async function flushOfflineQueue() {
    if (isFlushingQueue) return;
    const q = loadOfflineQueue();
    if (!q.length) {
      updateSyncBadge();
      return;
    }
    isFlushingQueue = true;
    const remaining = [];
    let synced = 0;
    for (const item of q) {
      try {
        const res = await api("/api/action", { action: item.action, params: item.params });
        if (res && res.authorized === false) {
          remaining.push(item);
          break;
        }
        if (res && res.ok) {
          synced++;
        } else {
          remaining.push(item);
        }
      } catch {
        remaining.push(item);
        break; // Network dropped or still offline
      }
    }
    saveOfflineQueue(remaining);
    updateSyncBadge();
    isFlushingQueue = false;
    if (synced > 0) {
      haptic("ok");
      toast(`Synced ${synced} offline action${synced > 1 ? "s" : ""} ⚡`, "ok");
      loadView(currentView);
    }
  }

  // --------------------------------------------------------- run + notify

  async function runAction(action, params) {
    haptic();

    // Optimistic UI for pending draft approvals
    if (params && params.id && (action === "approve" || action === "reject")) {
      const card = document.querySelector(`.approval-card-wrap[data-id="${params.id}"]`);
      if (card) {
        card.style.transition = "transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.22s ease";
        card.style.transform = action === "approve" ? "translateX(120%)" : "translateX(-120%)";
        card.style.opacity = "0";
        setTimeout(() => {
          card.remove();
          const badge = $("tab-approvals");
          if (badge) {
            const count = Math.max(0, (parseInt(badge.textContent, 10) || 1) - 1);
            badge.textContent = String(count);
            badge.classList.toggle("hidden", !count);
          }
        }, 250);
      }
    }

    let res = null;
    try {
      res = await api("/api/action", { action, params });
    } catch {
      // Offline fallback: queue action for automatic sync upon reconnection
      enqueueAction(action, params);
      haptic("light");
      toast("Action queued offline ⚡ Will auto-sync when connected", "info");
      return { ok: true, queued: true };
    }

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

    const syncBadge = $("offline-sync-badge");
    if (syncBadge) {
      syncBadge.addEventListener("click", () => {
        const count = loadOfflineQueue().length;
        toast(count ? `${count} action(s) pending sync ⚡ Reconnecting will auto-sync.` : "Offline queue empty ⚡", "info");
        flushOfflineQueue();
      });
    }

    // Android Material 3 Expressive Fluid Wave Touch Ripple + Instant Tactile Haptic
    document.addEventListener("pointerdown", (e) => {
      const target = e.target.closest(".btn, .pay-btn, .pay-check-btn, .chip, .seg, .model-chip, .preset-chip, .clay-switch, .m3-nav-item, .sheet-close-btn, .linklike");
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

    // Phase 7: Quiet Hours & Sleep Wiring
    const qhSave = $("qh-save-btn");
    if (qhSave) {
      qhSave.addEventListener("click", () => {
        const start = ($("qh-start-input").value || "02:00").trim();
        const end = ($("qh-end-input").value || "08:00").trim();
        runAction("quiethours", { value: `on ${start} ${end}` });
      });
    }

    const qhSleep = $("btn-quick-sleep");
    if (qhSleep) {
      qhSleep.addEventListener("click", () => {
        openSheet("Sleep Until Morning", "<p>Pause automated replies overnight until morning IST? Automation resumes automatically.</p>", [
          { label: "Sleep Now", kind: "primary", onClick: () => runAction("sleep", {}) },
          { label: "Cancel" }
        ]);
      });
    }

    document.querySelectorAll("#qh-preset-carousel button").forEach((chip) => {
      chip.addEventListener("click", () => {
        haptic("light");
        const qh = chip.dataset.qh;
        if (qh === "off") {
          runAction("quiethours", { value: "off" });
        } else {
          const parts = qh.split(" ");
          if ($("qh-start-input")) $("qh-start-input").value = parts[0];
          if ($("qh-end-input")) $("qh-end-input").value = parts[1];
          runAction("quiethours", { value: `on ${qh}` });
        }
        document.querySelectorAll("#qh-preset-carousel button").forEach((c) => c.classList.remove("active"));
        chip.classList.add("active");
      });
    });

    // Behavior Simulation Clay Switches
    document.querySelectorAll("#behavior-toggles .clay-switch").forEach((sw) => {
      sw.addEventListener("click", () => {
        haptic("light");
        const cur = sw.dataset.state || "off";
        const next = cur === "on" ? "off" : "on";
        sw.dataset.state = next;
        sw.className = `clay-switch ${next}`;
        sw.textContent = next.toUpperCase();
        runAction(sw.dataset.action, { value: next });
      });
    });

    // AI Tuning Segmented Controls
    document.querySelectorAll("#seg-thinking .seg, #seg-temp .seg, #seg-lang .seg, #seg-maxtokens .seg").forEach((b) => {
      b.addEventListener("click", () => {
        haptic("light");
        const param = b.dataset.param;
        const val = b.dataset.val;
        b.parentElement.querySelectorAll(".seg").forEach((s) => s.classList.remove("active"));
        b.classList.add("active");
        runAction(param, { value: val });
      });
    });

    // Keyword Auto-Reply Rules Add
    const addRuleBtn = $("btn-add-rule");
    if (addRuleBtn) {
      addRuleBtn.addEventListener("click", () => {
        openSheet("New Keyword Auto-Reply", `
          <p class="field-hint" style="margin-top:0">When incoming message contains this keyword, reply instantly:</p>
          <label for="rule-kw-input" style="font-weight:600;font-size:13px;display:block;margin-top:8px">Keyword trigger</label>
          <input id="rule-kw-input" placeholder="e.g. pricing, help, contact">
          <label for="rule-reply-input" style="font-weight:600;font-size:13px;display:block;margin-top:12px">Auto-reply message</label>
          <textarea id="rule-reply-input" rows="3" placeholder="e.g. We are updating packages! DM @admin for urgent queries."></textarea>
        `, [
          {
            label: "Add Rule",
            kind: "primary",
            onClick: () => {
              const kw = ($("rule-kw-input").value || "").trim();
              const rep = ($("rule-reply-input").value || "").trim();
              if (!kw || !rep) return toast("Keyword and reply text cannot be empty", "err");
              runAction("addrule", { value: `${kw} => ${rep}` });
            }
          },
          { label: "Cancel" }
        ]);
      });
    }

    // System Maintenance Buttons
    const backupBtn = $("btn-backup-db");
    if (backupBtn) {
      backupBtn.addEventListener("click", () => {
        openSheet("Backup Database", "<p>Create a point-in-time snapshot backup of the database and settings?</p>", [
          { label: "Create Backup", kind: "primary", onClick: () => runAction("backup", {}) },
          { label: "Cancel" }
        ]);
      });
    }

    const clearCtxBtn = $("btn-clear-context");
    if (clearCtxBtn) {
      clearCtxBtn.addEventListener("click", () => {
        openSheet("Clear AI Context", "<p>Reset cached conversation memory across chats? Permanent notes and allowlists are preserved.</p>", [
          { label: "Clear Memory", kind: "danger", onClick: () => runAction("clearcontext", { chat_id: "all" }) },
          { label: "Cancel" }
        ]);
      });
    }
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
    updateSyncBadge();
    window.addEventListener("online", () => {
      flushOfflineQueue();
    });

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
    flushOfflineQueue();
  }

  function setConnectionStatus(status) {
    const beacon = $("live-beacon");
    if (!beacon) return;
    beacon.className = `live-beacon ${status}`;
    beacon.title = status === "live"
      ? "Real-time engine connected"
      : (status === "connecting" ? "Connecting to engine…" : "Engine offline");
    if (status === "live") {
      flushOfflineQueue();
    }
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
