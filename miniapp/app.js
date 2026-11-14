/* TeleAutomator mini app : GUI over the same command engine as the control bot.
   Auth: Telegram initData header → /api/auth. Unauthorized → paywall (display-only).
   demo=1 query param renders local fixture data (no server calls) for previews. */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const DEMO = new URLSearchParams(location.search).has("demo");

  const SVGS = {
    check: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>',
    close: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
    alert: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    info: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    edit: '<svg class="btn-icon" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>',
    brain: '<svg class="btn-icon" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 4.44-2.04z"/><path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-4.44-2.04z"/></svg>',
    msg: '<svg class="btn-icon" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
    trash: '<svg class="btn-icon" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
    bolt: '<svg class="preset-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
    handshake: '<svg class="preset-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M11 17a2.5 2.5 0 0 0 4 0l4-4a2.5 2.5 0 0 0-3.5-3.5L14 11l-3-3-4 4a2.5 2.5 0 0 0 3.5 3.5Z"/><path d="m14 11 3.5-3.5a2.5 2.5 0 0 1 3.5 3.5l-4 4"/></svg>',
    rocket: '<svg class="preset-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4.5c1.62-1.63 5-2.5 5-2.5"/><path d="M12 15v5s3.03-.55 4.5-2c1.63-1.62 2.5-5 2.5-5"/></svg>',
    theater: '<svg class="preset-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M2 10s3-3 10-3 10 3 10 3-3 8-10 8-10-8-10-8Z"/><circle cx="8" cy="11" r="1.5"/><circle cx="16" cy="11" r="1.5"/></svg>',
    refresh: '<svg class="preset-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>',
    mic: '<svg class="voice-badge-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>',
    camera: '<svg class="media-badge-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>',
  };

  let cachedEndpointModels = [];

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
      chats_allowed: 6, pending_count: 2, replies_24h: 41, tokens_today: 18320, version: "3.0.2",
      auto_reactions: true, multibubble: true, typo: true, debounce: true, followup: false, mention_only: false,
      thinking: "default", temperature: "0.7", lang: "english", max_tokens: "512",
      quiet_hours_start: "02:00", quiet_hours_end: "08:00", quiet_hours_schedule: "02:00 AM – 08:00 AM IST",
      rules: ["pricing => We update our rates monthly, DM for catalog!", "help => How can I assist you today?"],
    },
    chats: [
      { id: 123456789, name: "Rohan Sharma", username: "@rohan_s", avatar_url: "https://t.me/i/userpic/320/rohan_s.jpg", initials: "RS", type: "Private", chatty: "", style: "", prompt: "", voice_profile: true, blocked: false },
      { id: -1001987654321, name: "Startup India Founders", username: "startupindia", avatar_url: "https://t.me/i/userpic/320/startupindia.jpg", initials: "SI", type: "Group", chatty: "0.4", style: "humorous", prompt: "You help founders swap tools. Keep it practical.", voice_profile: false, blocked: false },
      { id: -1001765432109, name: "Delhi Tech Meetup", username: "@delhitech", avatar_url: "https://t.me/i/userpic/320/delhitech.jpg", initials: "DT", type: "Group", chatty: "0", style: "", prompt: "", voice_profile: false, blocked: false },
      { id: 987654321, name: "Aarav", username: "@aaravv", avatar_url: "https://t.me/i/userpic/320/aaravv.jpg", initials: "AA", type: "Private", chatty: "0.6", style: "", prompt: "", voice_profile: false, blocked: false },
      { id: -1001654321098, name: "Crypto Signals Hub", username: "", avatar_url: "", initials: "CS", type: "Group", chatty: "", style: "concise", prompt: "", voice_profile: false, blocked: true },
      { id: 876543210, name: "Mom", username: "", avatar_url: "", initials: "MO", type: "Private", chatty: "0.25", style: "", prompt: "Never send links here.", voice_profile: false, blocked: false },
    ],
    pending: [
      { id: 41, chat_id: -1001987654321, chat_title: "Startup India Founders", username: "startupindia", avatar_url: "https://t.me/i/userpic/320/startupindia.jpg", initials: "SI", sender_id: 11223344, incoming_text: "btw are you joining the demo day on friday? wanted to show you the pitch deck before we send it out", text: "yeah definitely planning to join! send the deck over, will review it tonight.", created: "2026-11-13 14:22" },
      { id: 40, chat_id: 987654321, chat_title: "Aarav", username: "aaravv", avatar_url: "https://t.me/i/userpic/320/aaravv.jpg", initials: "AA", sender_id: 987654321, incoming_text: "Reached home! Call me when free, need to ask about the weekend plan.", text: "[Voice Note] Reached home! Call me when free, need to ask about the weekend plan.", created: "2026-11-13 13:05", is_voice: true, voice_dur: "0:21" },
    ],
    activity: [
      { chat: "Delhi Tech Meetup", chat_id: -1001765432109, sender: "TeleAutomator", text: "yeah the venue shifted to Hauz Khas this month, same 7pm slot", ts: "2026-11-13 14:18" },
      { chat: "Rohan Sharma", chat_id: 123456789, sender: "TeleAutomator", text: "[Voice Note] Haan bhai venue pahunch gaya, 2nd floor hall booked hai", ts: "2026-11-13 13:52", is_voice: true, voice_dur: "0:14" },
      { chat: "Startup India Founders", chat_id: -1001987654321, sender: "TeleAutomator", text: "pricing page looks solid, maybe add a monthly option", ts: "2026-11-13 12:30" },
      { chat: "Mom", chat_id: 876543210, sender: "TeleAutomator", text: "[Photo] Lunch pic sent, looks great!", ts: "2026-11-13 11:04", is_media: true },
    ],
    access: [
      { id: 555000111, name: "Kaif", username: "@mkr_infinity", avatar_url: "https://t.me/i/userpic/320/mkr_infinity.jpg", main: true, perms: "all" },
      { id: 777000222, name: "Manager", username: "@manager_h", avatar_url: "https://t.me/i/userpic/320/manager_h.jpg", main: false, perms: "all" },
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
    if (path === "/api/auth") return { authorized: true, is_main: true, version: "3.0.2", user: { id: 555000111, name: "Kaif" } };
    if (path === "/api/state") return DEMO_DATA.state;
    if (path === "/api/chats") return { chats: DEMO_DATA.chats, chatty_global: DEMO_DATA.state.chatty_global };
    if (path === "/api/pending") return { pending: DEMO_DATA.pending };
    if (path === "/api/activity") return { activity: DEMO_DATA.activity };
    if (path === "/api/access") return { users: DEMO_DATA.access };
    if (path === "/api/commands") return { commands: DEMO_DATA.commands };
    if (path === "/api/models" || path === "/api/fetch_models") {
      return {
        ok: true,
        models: [
          "gemini-2.5-flash-lite",
          "gemini-2.5-flash",
          "gemini-2.5-pro",
          "gpt-4o-mini",
          "llama-3.3-70b-instruct"
        ]
      };
    }
    if (path === "/api/test_model") {
      const model = (body && body.model) || "gemini-2.5-flash-lite";
      const userMsg = (body && body.message) || "hello";
      const candidates = model.split(/[,;]/).map((m) => m.trim()).filter(Boolean);
      const used = candidates[0] || "gemini-2.5-flash-lite";
      return {
        ok: true,
        model_used: used,
        reply: `TeleAutomator AI (${used}): Received "${userMsg}". AI pipeline responsive!`,
        results: candidates.map((m) => ({ model: m, ok: true, detail: "Working (118ms)" })),
        working_models: candidates,
        failed_models: [],
        active_model: model,
      };
    }
    if (path === "/api/cmd") {
      const cmd = (body && body.command) || "";
      if (cmd.includes("checkmodels")) {
        return {
          ok: true,
          response: "*Model Health Check*\n\n• `gemini-2.5-flash-lite`: Available (112ms)\n• `gemini-2.5-flash`: Available (148ms)\n• `gpt-4o-mini`: Available (195ms)\n\nAll candidate models healthy and rotating properly."
        };
      }
      return { ok: true, response: `*Demo* command \`${esc(cmd || "/demo")}\` ran against fixture data.\n\n• Changes persisted locally for preview.` };
    }
    if (path === "/api/action") {
      const a = body && body.action;
      const p = (body && body.params) || {};
      if (a === "approve" || a === "reject") {
        const i = DEMO_DATA.pending.findIndex((item) => String(item.id) === String(p.id));
        if (i >= 0) DEMO_DATA.pending.splice(i, 1);
        DEMO_DATA.state.pending_count = DEMO_DATA.pending.length;
        return { ok: true, response: a === "approve" ? "Draft approved and sent!" : "Draft rejected and discarded." };
      }
      if (a === "approve_all" || a === "reject_all") {
        const c = DEMO_DATA.pending.length;
        DEMO_DATA.pending = [];
        DEMO_DATA.state.pending_count = 0;
        return { ok: true, response: a === "approve_all" ? `All ${c} drafts approved and sent!` : `All ${c} drafts rejected.` };
      }
      if (a === "pause") {
        DEMO_DATA.state.state = "paused";
        DEMO_DATA.state.paused_remaining_sec = (p.minutes || 30) * 60;
        return { ok: true, response: `Paused for ${p.minutes || 30} minutes.` };
      }
      if (a === "resume") {
        DEMO_DATA.state.state = "active";
        DEMO_DATA.state.paused_remaining_sec = 0;
        return { ok: true, response: "Automation resumed." };
      }
      if (a === "stop") {
        DEMO_DATA.state.state = "stopped";
        DEMO_DATA.state.emergency = true;
        return { ok: true, response: "Emergency stop activated." };
      }
      if (a === "mode") {
        DEMO_DATA.state.mode = p.value;
        return { ok: true, response: `Mode changed to ${p.value}.` };
      }
      if (a === "style") {
        DEMO_DATA.state.style = p.value;
        return { ok: true, response: `Reply style changed to ${p.value}.` };
      }
      if (a === "prompt") {
        DEMO_DATA.state.prompt = p.value === "reset" ? "" : p.value;
        return { ok: true, response: p.value === "reset" ? "Prompt reset to built-in persona." : "Custom prompt saved." };
      }
      if (a === "name") {
        DEMO_DATA.state.owner_name = p.value;
        return { ok: true, response: `Owner name saved as ${p.value}.` };
      }
      if (a === "model") {
        DEMO_DATA.state.ai_model = p.value;
        return { ok: true, response: `Model updated to ${p.value}.` };
      }
      if (a === "baseurl") {
        DEMO_DATA.state.ai_base_url = p.value;
        return { ok: true, response: "Endpoint URL updated." };
      }
      if (a === "apikey") {
        return { ok: true, response: "API key updated." };
      }
      if (a === "allow") {
        const cid = parseInt(p.chat_id, 10) || Date.now();
        DEMO_DATA.chats.push({
          id: cid,
          name: `Chat ${cid}`,
          username: "",
          type: cid < 0 ? "Group" : "Private",
          chatty: "",
          style: "",
          prompt: "",
          voice_profile: false,
          blocked: false
        });
        DEMO_DATA.state.chats_allowed = DEMO_DATA.chats.length;
        return { ok: true, response: `Chat ${cid} added to allowlist.` };
      }
      if (a === "remove") {
        const i = DEMO_DATA.chats.findIndex((c) => String(c.id) === String(p.chat_id));
        if (i >= 0) DEMO_DATA.chats.splice(i, 1);
        DEMO_DATA.state.chats_allowed = DEMO_DATA.chats.length;
        return { ok: true, response: `Chat ${p.chat_id} removed from allowlist.` };
      }
      if (a === "chat_chatty") {
        const c = DEMO_DATA.chats.find((x) => String(x.id) === String(p.chat_id));
        if (c) c.chatty = p.value === "def" ? "" : String(parseFloat(p.value) / 100);
        return { ok: true, response: `Chatty updated for chat ${p.chat_id}.` };
      }
      if (a === "chatprompt") {
        const c = DEMO_DATA.chats.find((x) => String(x.id) === String(p.chat_id));
        if (c) c.prompt = p.value === "default" ? "" : p.value;
        return { ok: true, response: `Prompt updated for chat ${p.chat_id}.` };
      }
      if (a === "setcontext") {
        const c = DEMO_DATA.chats.find((x) => String(x.id) === String(p.chat_id));
        if (c) c.context = p.value;
        return { ok: true, response: `Context notes saved for chat ${p.chat_id}.` };
      }
      if (a === "delcontext") {
        const c = DEMO_DATA.chats.find((x) => String(x.id) === String(p.chat_id));
        if (c) delete c.context;
        return { ok: true, response: `Context notes cleared for chat ${p.chat_id}.` };
      }
      if (a === "syncpins") {
        return { ok: true, response: `Synced pinned message notes for chat ${p.chat_id}.` };
      }
      if (a === "addauth") {
        const uid = parseInt(p.user_id, 10) || 999999999;
        DEMO_DATA.access.push({ id: uid, name: `User ${uid}`, username: "", main: false, perms: "all" });
        return { ok: true, response: `User ${uid} added to authorized users.` };
      }
      if (a === "removeauth") {
        const i = DEMO_DATA.access.findIndex((u) => String(u.id) === String(p.user_id));
        if (i >= 0) DEMO_DATA.access.splice(i, 1);
        return { ok: true, response: `User ${p.user_id} removed from authorized users.` };
      }
      if (a === "quiethours") {
        DEMO_DATA.state.quiet_hours = p.value !== "off";
        DEMO_DATA.state.quiet_hours_schedule = p.value === "off" ? "Disabled" : p.value;
        return { ok: true, response: p.value === "off" ? "Quiet hours disabled." : `Quiet hours schedule set to ${p.value}.` };
      }
      if (a === "sleep") {
        DEMO_DATA.state.quiet_hours = true;
        return { ok: true, response: "Sleep mode engaged until morning IST. Good night!" };
      }
      if (a === "addrule") {
        if (!DEMO_DATA.state.rules) DEMO_DATA.state.rules = [];
        DEMO_DATA.state.rules.push(p.value);
        return { ok: true, response: `Keyword rule added: ${p.value}` };
      }
      if (a === "delrule") {
        if (DEMO_DATA.state.rules) {
          DEMO_DATA.state.rules = DEMO_DATA.state.rules.filter((r) => !r.startsWith(p.value) && r !== p.value);
        }
        return { ok: true, response: `Keyword rule deleted for "${p.value}".` };
      }
      if (a === "reaction" || a === "multibubble" || a === "typo" || a === "debounce" || a === "followup" || a === "mentiononly") {
        const mapKey = a === "reaction" ? "auto_reactions" : (a === "mentiononly" ? "mention_only" : a);
        DEMO_DATA.state[mapKey] = p.value === "on";
        return { ok: true, response: `${a} is now ${p.value.toUpperCase()}.` };
      }
      if (a === "thinking" || a === "temp" || a === "lang" || a === "maxtokens") {
        const stateKey = a === "temp" ? "temperature" : (a === "maxtokens" ? "max_tokens" : a);
        DEMO_DATA.state[stateKey] = p.value;
        return { ok: true, response: `${a} parameter set to ${p.value}.` };
      }
      if (a === "backup") {
        return { ok: true, response: "Snapshot backup created successfully at database/backups/teleautomator_snapshot.db" };
      }
      if (a === "clearcontext") {
        return { ok: true, response: "AI memory cache cleared across chats." };
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
    if (lines.length > 0) {
      const first = lines[0];
      const isErr = /^(\u274c|\[error\]|error|fail)/i.test(first);
      const isOk = /^(\u2705|\[ok\]|success)/i.test(first);
      const isWarning = /^(\u26a0|warning|alert)/i.test(first);
      const isInfo = /^(\u2139|\ud83d\udd0d|info)/i.test(first);
      if (isErr || isOk || isWarning || isInfo) {
        const title = first.replace(/^[^a-zA-Z0-9*_\s]+/, "").trim();
        const iconSvg = isErr ? SVGS.alert : (isOk ? SVGS.check : SVGS.info);
        elements.push(`<div class="app-callout">
          <span class="app-callout-icon">${iconSvg}</span>
          <div class="app-callout-body"><strong>${esc(plain(title))}</strong></div>
        </div>`);
        startIndex = 1;
      }
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
    if (iconEl) iconEl.innerHTML = statusKind === "ok" ? SVGS.check : (statusKind === "err" ? SVGS.alert : SVGS.info);
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
    updateTmaBackButton();
    haptic("light");
  }

  function closeSheet() {
    $("sheet-backdrop").classList.add("hidden");
    $("sheet").classList.add("hidden");
    updateTmaBackButton();
    haptic("light");
  }

  function updateTmaBackButton() {
    try {
      if (!tg || !tg.BackButton) return;
      const sheetOpen = $("sheet") && !$("sheet").classList.contains("hidden");
      if (sheetOpen) {
        tg.BackButton.show();
        tg.BackButton.offClick(backToOverview);
        tg.BackButton.offClick(closeSheet);
        tg.BackButton.onClick(closeSheet);
      } else if (currentView !== "overview") {
        tg.BackButton.show();
        tg.BackButton.offClick(closeSheet);
        tg.BackButton.offClick(backToOverview);
        tg.BackButton.onClick(backToOverview);
      } else {
        tg.BackButton.hide();
        tg.BackButton.offClick(closeSheet);
        tg.BackButton.offClick(backToOverview);
      }
    } catch (_) {}
  }

  function backToOverview() {
    showView("overview");
  }

  // -------------------------------------------------------------- views

  let currentView = "overview";

  function showView(name) {
    currentView = name;
    document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
    $(`view-${name}`).classList.remove("hidden");
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
    updateTmaBackButton();
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

    const svg = $("pulse-graph-svg");
    const areaPathEl = $("pulse-area-path");
    const linePathEl = $("pulse-line-path");
    const pointsGroup = $("pulse-points-group");
    const tooltip = $("pulse-graph-tooltip");

    if (svg && areaPathEl && linePathEl) {
      const padX = 16;
      const width = 500;
      const usableW = width - (padX * 2);
      const baselineY = 104;
      const maxH = 80;

      const pts = buckets.map((count, idx) => {
        const x = padX + idx * (usableW / 23);
        const y = count > 0 ? baselineY - ((count / maxVal) * maxH) : baselineY;
        return { x, y, count, idx };
      });

      // Smooth spline interpolation using cubic bezier
      let d = `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)}`;
      for (let i = 0; i < pts.length - 1; i++) {
        const p0 = pts[i === 0 ? 0 : i - 1];
        const p1 = pts[i];
        const p2 = pts[i + 1];
        const p3 = pts[i + 2 < pts.length ? i + 2 : i + 1];

        const cp1x = p1.x + (p2.x - p0.x) / 6;
        const cp1y = p1.y + (p2.y - p0.y) / 6;
        const cp2x = p2.x - (p3.x - p1.x) / 6;
        const cp2y = p2.y - (p3.y - p1.y) / 6;

        d += ` C ${cp1x.toFixed(1)} ${cp1y.toFixed(1)}, ${cp2x.toFixed(1)} ${cp2y.toFixed(1)}, ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;
      }

      linePathEl.setAttribute("d", d);
      const areaD = `${d} L ${pts[pts.length - 1].x.toFixed(1)} 116 L ${pts[0].x.toFixed(1)} 116 Z`;
      areaPathEl.setAttribute("d", areaD);

      if (pointsGroup) {
        let dotsHtml = "";
        pts.forEach((p) => {
          const isCurrent = p.idx === 23;
          const showDot = p.count > 0 || isCurrent;
          if (!showDot) return;
          const hourLabel = isCurrent ? "Current hour" : `${23 - p.idx}h ago`;
          const tip = `${p.count} ${p.count === 1 ? "reply" : "replies"} (${hourLabel})`;
          const r = isCurrent ? 4.5 : 3.5;
          const cls = isCurrent ? "pulse-dot current" : "pulse-dot";
          dotsHtml += `<circle class="${cls}" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${r}" data-tip="${esc(tip)}" tabindex="0" role="button" aria-label="${esc(tip)}"></circle>`;
        });
        pointsGroup.innerHTML = dotsHtml;

        pointsGroup.querySelectorAll(".pulse-dot").forEach((dot) => {
          const showTip = () => {
            haptic("light");
            if (tooltip) {
              tooltip.textContent = dot.dataset.tip;
              tooltip.classList.remove("hidden");
            }
          };
          dot.addEventListener("mouseenter", showTip);
          dot.addEventListener("click", showTip);
          dot.addEventListener("touchstart", showTip, { passive: true });
        });
      }
    }
  }

  function formatMode(m) {
    if (!m) return "Restricted Auto";
    if (m === "restricted_auto") return "Restricted Auto";
    if (m === "full_auto") return "Full Auto";
    if (m === "approval") return "Approval Required";
    if (m === "off") return "Automation Off";
    return String(m).replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase());
  }

  function renderState(s) {
    const pill = $("state-pill");
    if (s.state === "stopped") { pill.textContent = "Stopped"; pill.className = "pill pill-negative"; }
    else if (s.state === "paused") {
      const mins = Math.ceil((s.paused_remaining_sec || 0) / 60);
      pill.textContent = `Paused ${mins}m`;
      pill.className = "pill pill-warning";
    } else { pill.textContent = s.quiet_hours ? "Active · quiet hours" : "Active"; pill.className = "pill pill-positive"; }

    $("ov-mode").textContent = formatMode(s.mode);
    const bits = [];
    bits.push(`Style: ${(s.style || "casual").charAt(0).toUpperCase() + (s.style || "casual").slice(1)}`);
    if (s.safe_mode) bits.push("Safe Mode");
    if (s.emergency) bits.push("Emergency Stop");
    bits.push(`${s.ai_engine || "AI"} Engine`);
    bits.push(s.chats_allowed === 1 ? "1 chat" : `${s.chats_allowed} chats`);
    $("ov-sub").textContent = bits.join(" · ");

    $("kpi-chats").textContent = s.chats_allowed;
    $("kpi-pending").textContent = s.pending_count;
    $("kpi-replies").textContent = s.replies_24h;
    if ($("kpi-engine")) $("kpi-engine").textContent = s.ai_engine || "Local";

    if ($("ov-engine-badge")) {
      $("ov-engine-badge").textContent = `${s.ai_engine || "AI"}`;
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
      $("ov-req-count").textContent = (s.token_requests || s.tokens_today || 0).toLocaleString();
    }

    $("act-pause").classList.toggle("hidden", s.state !== "active");
    $("act-resume").classList.toggle("hidden", s.state === "active");
  }

  function feedRowHtml(a) {
    const isVoice = Boolean(a.is_voice || /\[voice|\[audio|\(voice\)/i.test(a.text || "") || a.voice_dur);
    const isMedia = Boolean(a.is_media || /\[photo|\[image|\[video|\[document|\(media\)/i.test(a.text || ""));
    const voiceBadge = isVoice
      ? `<div class="voice-badge">
          ${SVGS.mic}
          <span class="voice-wave"><span class="wave-bar"></span><span class="wave-bar"></span><span class="wave-bar"></span><span class="wave-bar"></span></span>
          <span>Voice Note ${esc(a.voice_dur ? `(${a.voice_dur})` : "")}</span>
        </div>`
      : "";
    const mediaBadge = isMedia && !isVoice
      ? `<div class="media-badge">${SVGS.camera} <span>Media Reply</span></div>`
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
    const cleanUser = c.username ? c.username.replace(/^@/, "").trim() : "";
    const userDisplay = cleanUser
      ? `<a href="https://t.me/${encodeURIComponent(cleanUser)}" target="_blank" rel="noopener noreferrer" class="pill pill-neutral chat-user chat-user-link" title="Open @${esc(cleanUser)} in Telegram">@${esc(cleanUser)} ↗</a>`
      : "";

    return `<div class="chat-capsule ${c.blocked ? "is-blocked" : ""}" data-cid="${c.id}">
      <div class="chat-capsule-head">
        <div class="chat-avatar-wrap">
          ${c.avatar_url ? `<img src="${esc(c.avatar_url)}" alt="${esc(c.name)}" class="chat-avatar-img" loading="lazy" onerror="this.style.display='none';if(this.nextElementSibling)this.nextElementSibling.style.display='flex';" />` : ""}
          <div class="chat-avatar fallback" style="background: ${avatarBg}; ${c.avatar_url ? 'display:none;' : ''}">${esc(initials)}</div>
        </div>
        <div class="chat-info">
          <div class="chat-title-row">
            <span class="chat-name">${esc(c.name)}</span>
            ${userDisplay}
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
      <div class="chat-actions chat-actions-grid">
        <button type="button" class="btn small action-btn-prompt" data-op="prompt">${SVGS.edit} Prompt</button>
        <button type="button" class="btn small action-btn-context" data-op="context">${SVGS.brain} Context</button>
        <button type="button" class="btn small action-btn-chatty" data-op="chatty">${SVGS.msg} Chatty</button>
        <button type="button" class="btn small danger action-btn-remove" data-op="remove">${SVGS.trash} Remove</button>
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
      icon: SVGS.msg,
      prompt: "Be casual, natural, concise, and friendly. Speak like a close peer on Telegram, avoid corporate jargon, and keep messages under 2-3 sentences."
    },
    {
      id: "exec",
      name: "Executive & Crisp",
      icon: SVGS.bolt,
      prompt: "Be extremely concise, professional, and high-signal. Answer directly in 1-2 clear sentences with crisp facts. No fluff or filler."
    },
    {
      id: "support",
      name: "Support Specialist",
      icon: SVGS.handshake,
      prompt: "Be warm, helpful, empathetic, and solution-oriented. Clarify issues politely, guide step-by-step, and provide reassuring, reliable answers."
    },
    {
      id: "tech",
      name: "Tech & Automation",
      icon: SVGS.rocket,
      prompt: "Speak in natural tech community tone. Sharp, knowledgeable about systems and automation, helpful without being overly formal."
    },
    {
      id: "witty",
      name: "Witty & Fun",
      icon: SVGS.theater,
      prompt: "Be playful, lightly humorous, cheerful, and witty. Keep it engaging, upbeat, and fun while still answering questions accurately."
    },
    {
      id: "reset",
      name: "Built-in Default",
      icon: SVGS.refresh,
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
    if ($("approval-batch-bar")) {
      $("approval-batch-bar").classList.toggle("hidden", count < 2);
    }
    $("approval-list").innerHTML = count
      ? rows.map(approvalCardHtml).join("")
      : `<div class="empty">Nothing waiting. In approval mode every draft shows up here.</div>`;
    $("approval-list").querySelectorAll("[data-ap]").forEach((btn) =>
      btn.addEventListener("click", () => runAction(btn.dataset.ap, { id: btn.dataset.id })));
    wireApprovalSwipes();
  }

  function approvalCardHtml(p) {
    const isVoice = Boolean(p.is_voice || /\[voice|\[audio|\(voice\)/i.test(p.text || "") || p.voice_dur);
    const isMedia = Boolean(p.is_media || /\[photo|\[image|\[video|\[document|\(media\)/i.test(p.text || ""));
    const voiceBadge = isVoice
      ? `<div class="voice-badge">
          ${SVGS.mic}
          <span class="voice-wave"><span class="wave-bar"></span><span class="wave-bar"></span><span class="wave-bar"></span><span class="wave-bar"></span></span>
          <span>Voice Note ${esc(p.voice_dur ? `(${p.voice_dur})` : "")}</span>
        </div>`
      : "";
    const mediaBadge = isMedia && !isVoice
      ? `<div class="media-badge">${SVGS.camera} <span>Media Draft</span></div>`
      : "";

    const cleanUser = p.username ? p.username.replace(/^@/, "").trim() : "";
    const initials = p.initials || "TG";

    return `<div class="approval-card-wrap" data-id="${p.id}">
      <div class="approval-swipe-underlay">
        <div class="swipe-hint swipe-hint-approve">
          <span class="swipe-icon">${SVGS.check}</span>
          <span>Approve</span>
        </div>
        <div class="swipe-hint swipe-hint-reject">
          <span>Reject</span>
          <span class="swipe-icon">${SVGS.close}</span>
        </div>
      </div>
      <div class="approval-card-content">
        <div class="approval-card-header">
          <div class="approval-avatar-wrap">
            ${p.avatar_url ? `<img src="${esc(p.avatar_url)}" alt="${esc(p.chat_title || '')}" class="approval-avatar-img" loading="lazy" onerror="this.style.display='none';if(this.nextElementSibling)this.nextElementSibling.style.display='flex';" />` : ""}
            <div class="chat-avatar fallback-avatar" style="${p.avatar_url ? 'display:none;' : ''}">${esc(initials)}</div>
          </div>
          <div class="approval-user-meta">
            <div class="approval-name-row">
              <span class="approval-user-name">${esc(p.chat_title || `Chat ${p.chat_id}`)}</span>
              ${cleanUser ? `<a href="https://t.me/${encodeURIComponent(cleanUser)}" target="_blank" rel="noopener noreferrer" class="pill pill-neutral chat-user-link" title="Open @${esc(cleanUser)} in Telegram">@${esc(cleanUser)} ↗</a>` : ""}
            </div>
            <div class="approval-sub-row">
              <span class="pill pill-neutral num">ID: ${esc(String(p.sender_id || p.chat_id))}</span>
              <span class="pill pill-warning">Draft #${p.id}</span>
              <span class="feed-ts num">${esc(formatIST(p.created))}</span>
            </div>
          </div>
        </div>

        ${voiceBadge}${mediaBadge}

        ${p.incoming_text ? `
          <div class="approval-msg-section">
            <span class="approval-section-tag">Incoming Message</span>
            <div class="approval-incoming-bubble">${esc(p.incoming_text)}</div>
          </div>
        ` : ""}

        <div class="approval-msg-section">
          <span class="approval-section-tag">Draft AI Reply</span>
          <div class="approval-draft-bubble">${esc(p.text)}</div>
        </div>

        <div class="approval-actions">
          <button class="btn small primary" data-ap="approve" data-id="${p.id}">${SVGS.check} Approve</button>
          <button class="btn small danger" data-ap="reject" data-id="${p.id}">${SVGS.close} Reject</button>
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
          const cleanUser = u.username ? u.username.replace(/^@/, "").trim() : "";
          const userLink = cleanUser
            ? `<a href="https://t.me/${encodeURIComponent(cleanUser)}" target="_blank" rel="noopener noreferrer" class="pill pill-neutral chat-user-link" title="Open in Telegram">@${esc(cleanUser)} ↗</a>`
            : "";
          return `<div class="user-capsule">
            <div class="user-avatar-wrap">
              ${u.avatar_url ? `<img src="${esc(u.avatar_url)}" alt="${esc(u.name)}" class="user-avatar-img" loading="lazy" onerror="this.style.display='none';if(this.nextElementSibling)this.nextElementSibling.style.display='flex';" />` : ""}
              <div class="user-avatar-circle" style="${u.avatar_url ? 'display:none;' : ''}">${esc(initials)}</div>
            </div>
            <div class="capsule-main">
              <div class="capsule-head">
                <span class="capsule-title">${esc(u.name)}</span>
                ${userLink}
                ${u.main ? '<span class="pill pill-positive">Owner</span>' : '<span class="pill pill-neutral">Authorized</span>'}
              </div>
              <p class="capsule-sub num">ID: ${esc(String(u.id))}</p>
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
      if (s.quiet_hours_enabled === false) {
        qhStatus.textContent = "Inactive";
        qhStatus.className = "pill pill-inactive";
      } else if (s.quiet_hours) {
        qhStatus.textContent = "Sleeping";
        qhStatus.className = "pill pill-warning";
      } else {
        qhStatus.textContent = "Active";
        qhStatus.className = "pill pill-positive";
      }
    }
    const qhStart = $("qh-start-input");
    const qhEnd = $("qh-end-input");
    if (qhStart && document.activeElement !== qhStart && s.quiet_hours_start) qhStart.value = s.quiet_hours_start;
    if (qhEnd && document.activeElement !== qhEnd && s.quiet_hours_end) qhEnd.value = s.quiet_hours_end;

    const isQhEnabled = s.quiet_hours_enabled !== false;
    const curWindow = `${s.quiet_hours_start || "02:00"} ${s.quiet_hours_end || "08:00"}`;
    document.querySelectorAll("#qh-preset-carousel button").forEach((chip) => {
      const qhVal = chip.dataset.qh;
      if (qhVal === "off") {
        chip.classList.toggle("active", !isQhEnabled);
      } else {
        chip.classList.toggle("active", isQhEnabled && qhVal === curWindow);
      }
    });

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
    setSegActive("seg-lang", s.lang || "english");
    setSegActive("seg-maxtokens", s.max_tokens || "512");

    if (!cachedEndpointModels.length && s.ai_model) {
      const curModels = s.ai_model.split(/[,;]/).map((x) => x.trim().replace(/^models\//, "")).filter(Boolean);
      if (curModels.length > 0) {
        renderModelChips(curModels);
      }
    } else if (cachedEndpointModels.length > 0) {
      renderModelChips(cachedEndpointModels);
    }

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
      toast(`Synced ${synced} offline action${synced > 1 ? "s" : ""}`, "ok");
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
      toast("Action queued offline. Will auto-sync when connected", "info");
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
    const uName = auth.user && auth.user.name ? auth.user.name : "";
    if (uName) {
      const uIcon = '<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.5" style="display:inline-block;vertical-align:-1px;margin-right:3px;flex-shrink:0"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';
      $("whoami").innerHTML = `${uIcon}${esc(uName)}`;
    } else {
      $("whoami").innerHTML = "";
    }
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
        toast(count ? `${count} action(s) pending sync. Reconnecting will auto-sync.` : "Offline queue empty", "info");
        flushOfflineQueue();
      });
    }

    // Interactive Dashboard KPIs and Usage Grid Shortcut Navigation
    document.querySelectorAll(".kpi[data-goto], .usage-cell[data-goto]").forEach((el) => {
      el.addEventListener("click", () => {
        haptic("light");
        const target = el.dataset.goto;
        if (target === "activity") {
          $("goto-activity").click();
        } else {
          showView(target);
        }
      });
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          el.click();
        }
      });
    });

    // Close open sheet or popup with Escape key
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        closeSheet();
      }
    });

    // Instant Tactile Haptic on buttons
    document.addEventListener("pointerdown", (e) => {
      const target = e.target.closest(".btn, .pay-btn, .pay-check-btn, .chip, .seg, .model-chip, .preset-chip, .clay-switch, .m3-nav-item, .sheet-close-btn, .linklike, .kpi[data-goto], .usage-cell[data-goto]");
      if (!target) return;
      haptic("light");
    }, { passive: true });

    // Native Telegram link navigation bridge
    document.addEventListener("click", (e) => {
      const link = e.target.closest(".chat-user-link");
      if (!link) return;
      const href = link.getAttribute("href");
      if (href && href.startsWith("https://t.me/") && window.Telegram && window.Telegram.WebApp && typeof window.Telegram.WebApp.openTelegramLink === "function") {
        e.preventDefault();
        window.Telegram.WebApp.openTelegramLink(href);
      }
    });

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

    const btnApproveAll = $("btn-approve-all");
    if (btnApproveAll) {
      btnApproveAll.addEventListener("click", () => {
        const count = document.querySelectorAll(".approval-card-wrap").length;
        if (!count) return;
        openSheet("Approve all drafts",
          `<p>Send all <strong>${count} pending drafts</strong> to their chats now?</p>`,
          [
            { label: `Approve all (${count})`, kind: "primary", onClick: () => runAction("approve_all") },
            { label: "Cancel" }
          ]);
      });
    }

    const btnRejectAll = $("btn-reject-all");
    if (btnRejectAll) {
      btnRejectAll.addEventListener("click", () => {
        const count = document.querySelectorAll(".approval-card-wrap").length;
        if (!count) return;
        openSheet("Reject all drafts",
          `<p>Discard all <strong>${count} pending drafts</strong>?</p>`,
          [
            { label: `Discard all (${count})`, kind: "danger", onClick: () => runAction("reject_all") },
            { label: "Cancel" }
          ]);
      });
    }

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
    // Model Fallback Multi-Select Chips
    function renderModelChips(modelsList, selectedOverride) {
      const container = $("ai-model-chips");
      if (!container) return;
      if (!modelsList || !modelsList.length) {
        container.innerHTML = '<div class="empty sm">No models found. Tap &ldquo;Fetch models&rdquo; or type manually.</div>';
        return;
      }

      let selectedList;
      if (Array.isArray(selectedOverride)) {
        selectedList = selectedOverride.map((s) => String(s).trim().replace(/^models\//, "")).filter(Boolean);
      } else {
        selectedList = ($("ai-model").value || "")
          .split(/[,;]/)
          .map((s) => s.trim().replace(/^models\//, ""))
          .filter(Boolean);
      }

      container.innerHTML = modelsList.map((m) => {
        const cleanM = String(m).replace(/^models\//, "").trim();
        const idx = selectedList.indexOf(cleanM);
        const isActive = idx !== -1;
        const badgeHtml = isActive ? `<span class="chip-order-badge">${idx + 1}</span>` : "";
        return `<button class="model-chip ${isActive ? "active" : ""}" data-model="${esc(cleanM)}" type="button">${badgeHtml}${esc(cleanM)}</button>`;
      }).join("");

      container.querySelectorAll(".model-chip").forEach((chip) => {
        chip.addEventListener("click", () => {
          haptic("light");
          const modelName = chip.dataset.model;
          let currentSelected = ($("ai-model").value || "")
            .split(/[,;]/)
            .map((s) => s.trim().replace(/^models\//, ""))
            .filter(Boolean);

          const existingIdx = currentSelected.indexOf(modelName);
          if (existingIdx !== -1) {
            currentSelected.splice(existingIdx, 1);
            toast(`Removed ${modelName} from fallback chain (${currentSelected.length} active)`);
          } else {
            currentSelected.push(modelName);
            toast(`Added ${modelName} as fallback #${currentSelected.length}`);
          }

          const newChain = currentSelected.join(",");
          $("ai-model").value = newChain;
          runAction("model", { value: newChain });
          renderModelChips(modelsList, currentSelected);
        });
      });
    }

    // Health check candidate models and auto-add healthy models
    async function checkModelsHealth() {
      const btn = $("ai-check");
      const baseurl = $("ai-baseurl").value.trim();
      const apikey = $("ai-key").value.trim();
      const prompt = ($("test-prompt").value || "").trim() || "hi";
      const candidateModels = cachedEndpointModels.length
        ? cachedEndpointModels.join(",")
        : ($("ai-model").value.trim() || "gemini-2.5-flash-lite,gemini-2.5-flash");

      btn.disabled = true;
      btn.textContent = "Checking...";
      toast("Pinging candidate models for live health...");

      const box = $("test-results-box");
      const badge = $("test-badge");
      const modelEl = $("test-model-name");
      const replyEl = $("test-reply-content");
      const summaryEl = $("test-models-summary");

      box.classList.remove("hidden");
      badge.className = "pill pill-warning";
      badge.textContent = "Testing...";
      modelEl.textContent = "Verifying live endpoint health...";
      replyEl.textContent = "Running health verification...";

      try {
        const res = await api("/api/test_model", {
          message: prompt,
          model: candidateModels,
          base_url: baseurl,
          api_key: apikey,
        });

        if (res && res.ok && res.working_models && res.working_models.length > 0) {
          badge.className = "pill pill-positive";
          badge.textContent = `${res.working_models.length} Healthy`;
          modelEl.textContent = `Active rotation: ${res.active_model}`;
          replyEl.textContent = `"${res.reply}"`;

          $("ai-model").value = res.active_model;
          if (!cachedEndpointModels.length && res.results) {
            cachedEndpointModels = res.results.map((r) => r.model);
            $("models-fetched-count").textContent = `(${cachedEndpointModels.length})`;
          }
          renderModelChips(cachedEndpointModels.length ? cachedEndpointModels : res.working_models, res.working_models);

          const pills = (res.results || []).map((r) => {
            const cls = r.ok ? "test-pill ok" : "test-pill fail";
            const iconSvg = r.ok
              ? '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" style="display:inline-block;vertical-align:-1px;margin-right:4px;"><polyline points="3 8 7 12 13 4"/></svg>'
              : '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" style="display:inline-block;vertical-align:-1px;margin-right:4px;"><line x1="4" y1="4" x2="12" y2="12"/><line x1="12" y1="4" x2="4" y2="12"/></svg>';
            return `<span class="${cls}">${iconSvg}${esc(r.model)}: ${esc(r.detail)}</span>`;
          });
          summaryEl.innerHTML = pills.join("");

          toast(`Auto-configured ${res.working_models.length} healthy model(s): ${res.active_model}`);
        } else {
          badge.className = "pill pill-negative";
          badge.textContent = "Failed";
          modelEl.textContent = "Candidate models unavailable";
          replyEl.textContent = (res && res.error) || "Health check failed. Check your API key, endpoint URL, or quota.";

          const failSvg = '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" style="display:inline-block;vertical-align:-1px;margin-right:4px;"><line x1="4" y1="4" x2="12" y2="12"/><line x1="12" y1="4" x2="4" y2="12"/></svg>';
          const pills = (res && res.results ? res.results : []).map((r) => {
            return `<span class="test-pill fail">${failSvg}${esc(r.model)}: ${esc(r.detail)}</span>`;
          });
          summaryEl.innerHTML = pills.join("");
          toast("Health check found 0 working models");
        }
      } catch (e) {
        badge.className = "pill pill-negative";
        badge.textContent = "Error";
        replyEl.textContent = "Health check request failed: " + e.message;
        toast("Health check error: " + e.message);
      } finally {
        btn.disabled = false;
        btn.textContent = "Check health";
      }
    }
    $("ai-check").addEventListener("click", checkModelsHealth);

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
        cachedEndpointModels = models;
        $("models-fetched-count").textContent = `(${models.length})`;
        if (!models.length) {
          $("ai-model-chips").innerHTML = `<div class="empty sm">Endpoint returned 0 models.</div>`;
          return;
        }

        renderModelChips(cachedEndpointModels);
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
            const workingArr = res.working_models || res.active_model.split(",");
            if (cachedEndpointModels.length) {
              renderModelChips(cachedEndpointModels, workingArr);
            } else {
              renderModelChips(workingArr, workingArr);
            }
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
        if ($("qh-status-pill")) {
          $("qh-status-pill").textContent = "Active";
          $("qh-status-pill").className = "pill pill-positive";
        }
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
          if ($("qh-status-pill")) {
            $("qh-status-pill").textContent = "Inactive";
            $("qh-status-pill").className = "pill pill-inactive";
          }
          runAction("quiethours", { value: "off" });
        } else {
          const parts = qh.split(" ");
          if ($("qh-start-input")) $("qh-start-input").value = parts[0];
          if ($("qh-end-input")) $("qh-end-input").value = parts[1];
          if ($("qh-status-pill")) {
            $("qh-status-pill").textContent = "Active";
            $("qh-status-pill").className = "pill pill-positive";
          }
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
