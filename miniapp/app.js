/* TeleAutomator mini app : GUI over the same command engine as the control bot.
   Auth: Telegram initData header → /api/auth. Unauthorized → paywall (display-only).
   demo=1 query param renders local fixture data (no server calls) for previews. */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const DEMO = new URLSearchParams(location.search).has("demo");
  let canGiveFeedback = false;
  let activeUserId = null;
  const FEEDBACK_LABELS = { helpful: "Helpful", unnecessary: "Unneeded", off_topic: "Off-topic", style: "Style mismatch" };

  const SVGS = {
    check: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>',
    close: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
    alert: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    info: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    edit: '<svg class="btn-icon" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>',
    brain: '<svg class="btn-icon" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 4.44-2.04z"/><path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-4.44-2.04z"/></svg>',
    msg: '<svg class="btn-icon" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
    trash: '<svg class="btn-icon" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
    clock: '<svg class="btn-icon" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
    chevronRight: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg>',
    copy: '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>',
    externalLink: '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>',
    bolt: '<svg class="preset-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
    handshake: '<svg class="preset-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M11 17a2.5 2.5 0 0 0 4 0l4-4a2.5 2.5 0 0 0-3.5-3.5L14 11l-3-3-4 4a2.5 2.5 0 0 0 3.5 3.5Z"/><path d="m14 11 3.5-3.5a2.5 2.5 0 0 1 3.5 3.5l-4 4"/></svg>',
    rocket: '<svg class="preset-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4.5c1.62-1.63 5-2.5 5-2.5"/><path d="M12 15v5s3.03-.55 4.5-2c1.63-1.62 2.5-5 2.5-5"/></svg>',
    theater: '<svg class="preset-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M2 10s3-3 10-3 10 3 10 3-3 8-10 8-10-8-10-8Z"/><circle cx="8" cy="11" r="1.5"/><circle cx="16" cy="11" r="1.5"/></svg>',
    refresh: '<svg class="preset-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>',
    mic: '<svg class="voice-badge-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>',
    camera: '<svg class="media-badge-icon" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>',
  };

  let cachedEndpointModels = [];

  const BEHAVIOR_HELP = {
    reaction: {
      title: "Auto-Reactions",
      desc: "Automatically reacts to incoming messages with native Telegram emoji reactions, just like an active human reading their chats.",
      onText: "The bot analyzes message sentiment and naturally places an appropriate emoji reaction (such as thumbs-up, heart, or fire) before or alongside replying.",
      offText: "Emoji reactions are disabled. All responses from the account will be text-only.",
    },
    ownreact: {
      title: "React on Own Messages",
      desc: "Occasionally reacts to your own sent replies with an emoji reaction, just like real people do when joking or emphasizing a message.",
      onText: "Around 20% of newly sent replies will naturally receive an emoji reaction from your account.",
      offText: "Your account will never react to its own messages and only react to incoming messages from peers.",
    },
    multibubble: {
      title: "Multi-Bubble Splitting",
      desc: "Breaks longer replies into 2–3 natural consecutive message bubbles with realistic typing pauses between them.",
      onText: "Sends natural multi-part messages simulating mobile phone texting cadence instead of one robotic wall of text.",
      offText: "Replies are always sent in a single message bubble all at once.",
    },
    typo: {
      title: "Typo & Self-Correction",
      desc: "Simulates accidental human thumb slips on mobile keyboards and auto-corrects them moments later.",
      onText: "Occasionally sends a minor realistic typo and edits the message or sends an asterisk (*fix) seconds later.",
      offText: "Every reply is sent cleanly with zero simulated typos or post-edits.",
    },
    debounce: {
      title: "Message Burst Debounce",
      desc: "Waits for rapid consecutive incoming messages to finish before generating one cohesive response.",
      onText: "Stitches multiple quick fragments (e.g. 'hey', 'you free?', 'look at this') into one context before replying once.",
      offText: "Replies immediately to every single incoming message independently, risking spammy fragmented replies.",
    },
    followup: {
      title: "Spontaneous Follow-ups",
      desc: "Simulates natural human texting habits by occasionally sending an extra thought after a short answer.",
      onText: "After short replies, the bot may spontaneously send a follow-up bubble 10–30s later (e.g. 'btw let me know').",
      offText: "Strictly sends one reply per incoming turn and never initiates spontaneous follow-ups.",
    },
    mentiononly: {
      title: "Mention-Only in Groups",
      desc: "Limits automated replies in group chats exclusively to direct replies or @mentions.",
      onText: "In group chats, the bot stays silent unless someone explicitly quotes its message or mentions its @handle.",
      offText: "The bot participates in open group conversations based on its configured Chatty probability percentage.",
    },
    quiethours: {
      title: "Daily Quiet Window (Sleep Schedule)",
      desc: "Pauses automated replies during sleep or off-hours in Indian Standard Time (IST).",
      onText: "Replies are suspended during the configured sleep hours so your Telegram activity matches a realistic diurnal human rhythm.",
      offText: "The bot replies around the clock 24/7 without observing sleep or quiet windows.",
    },
    thinking: {
      title: "Reasoning Effort (Thinking)",
      desc: "Sets how extensively reasoning models think before answering.",
      onText: "Medium/High effort allows models to generate thorough, step-by-step reasoning for nuanced questions.",
      offText: "Off or Low responds with minimal latency and minimal token usage for quick chatting.",
    },
    modelrotation: {
      title: "Smart Model Rotation",
      desc: "Automatic failover chain across multiple candidate models if rate limits or downtime occur.",
      onText: "If the primary endpoint model hits 429 rate limit or 503 error, traffic instantly falls back to secondary models.",
      offText: "Only the single active model is used, returning an error immediately if unavailable.",
    },
    cooldown: {
      title: "Per-Chat Cooldown",
      desc: "Controls the minimum and maximum seconds the bot waits before replying in a specific chat.",
      onText: "Replies are delayed naturally between Min and Max seconds to simulate realistic reading and typing time.",
      offText: "When Min and Max are set to 0, replies are sent without waiting (instant reply, strictly within anti-spam rate limits).",
    },
  };

  function openHelpSheet(key) {
    const item = BEHAVIOR_HELP[key];
    if (!item) return;

    const sw = $(`sw-${key}`);
    const currentState = sw ? (sw.dataset.state || "off") : null;

    let stateBanner = "";
    if (currentState) {
      const isCurrentlyOn = currentState === "on";
      stateBanner = `
        <div class="help-current-status">
          <span>Current status:</span>
          <span class="pill pill-compact ${isCurrentlyOn ? "pill-positive" : "pill-neutral"}">
            ${isCurrentlyOn ? "ACTIVE (ON)" : "INACTIVE (OFF)"}
          </span>
        </div>
      `;
    }

    const bodyHtml = `
      <div class="help-popup-content">
        <p class="help-popup-desc">${esc(item.desc)}</p>
        ${stateBanner}
        <div class="help-states-grid">
          <div class="help-state-card on">
            <div class="help-state-header">
              <span class="help-state-badge on">WHEN ON</span>
            </div>
            <div class="help-state-body">${esc(item.onText)}</div>
          </div>
          <div class="help-state-card off">
            <div class="help-state-header">
              <span class="help-state-badge off">WHEN OFF</span>
            </div>
            <div class="help-state-body">${esc(item.offText)}</div>
          </div>
        </div>
      </div>
    `;

    const buttons = [];
    if (sw) {
      const isCurrentlyOn = (sw.dataset.state || "off") === "on";
      buttons.push({
        label: isCurrentlyOn ? "Turn OFF" : "Turn ON",
        kind: isCurrentlyOn ? "danger" : "primary",
        onClick: () => {
          if (sw) sw.click();
        },
      });
    }
    buttons.push({ label: "Got it", kind: "" });

    openSheet(item.title, bodyHtml, buttons);
  }

  function openAllBehaviorGuideSheet() {
    const keys = ["reaction", "ownreact", "multibubble", "typo", "debounce", "followup", "mentiononly"];
    const bodyHtml = `
      <div class="help-popup-content">
        <p class="help-popup-desc">The bot includes natural human simulation engines to mimic realistic messaging cadence, avoid robotic patterns, and keep conversations engaging.</p>
        <div class="help-guide-list">
          ${keys.map((k) => {
            const it = BEHAVIOR_HELP[k];
            if (!it) return "";
            const sw = $(`sw-${k}`);
            const state = sw ? (sw.dataset.state || "off") : "";
            const statePill = state ? `<span class="pill pill-compact ${state === "on" ? "pill-positive" : "pill-neutral"}" style="margin-left:8px;">${state.toUpperCase()}</span>` : "";
            return `
              <div class="help-guide-item">
                <div class="help-guide-title"><strong>${esc(it.title)}</strong> ${statePill}</div>
                <div class="help-popup-desc" style="font-size:12.5px;margin-bottom:8px;">${esc(it.desc)}</div>
                <div class="help-states-grid">
                  <div class="help-state-card on">
                    <div class="help-state-header"><span class="help-state-badge on">WHEN ON</span></div>
                    <div class="help-state-body" style="font-size:12px;">${esc(it.onText)}</div>
                  </div>
                  <div class="help-state-card off">
                    <div class="help-state-header"><span class="help-state-badge off">WHEN OFF</span></div>
                    <div class="help-state-body" style="font-size:12px;">${esc(it.offText)}</div>
                  </div>
                </div>
              </div>
            `;
          }).join("")}
        </div>
      </div>
    `;
    openSheet("Behavior & Human Simulation Guide", bodyHtml, [{ label: "Close Guide", kind: "primary" }]);
  }

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

  const readsInFlight = new Map();

  async function api(path, body) {
    if (DEMO) return demoApi(path, body);
    if (!body && readsInFlight.has(path)) return readsInFlight.get(path);
    const opts = { method: body ? "POST" : "GET", headers: { "X-Telegram-Init-Data": initDataHeader() } };
    if (body) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    const controller = new AbortController();
    opts.signal = controller.signal;
    const timeout = setTimeout(() => controller.abort(), body ? 120000 : 20000);
    const request = (async () => {
      const res = await fetch(path, opts);
      const data = await res.json();
      if (res.status === 401) return { authorized: false, paywall: data.paywall, version: data.version };
      if (res.status >= 400) return { ...data, ok: false, response: data.response || data.error || `Server returned ${res.status}. Try again.` };
      return data;
    })();
    if (!body) readsInFlight.set(path, request);
    try { return await request; }
    catch (error) {
      if (error.name === "AbortError") throw new Error("The request timed out. Refresh to check the result before trying again.");
      if (error.name === "SyntaxError") throw new Error("The server sent an invalid response. Try again.");
      throw error;
    } finally {
      clearTimeout(timeout);
      if (!body) readsInFlight.delete(path);
    }
  }

  const renderedHtml = new WeakMap();
  function updateHtml(id, html) {
    const element = $(id);
    if (renderedHtml.get(element) === html) return false;
    element.innerHTML = html;
    renderedHtml.set(element, html);
    return true;
  }

  function syncField(id, value) {
    const field = $(id);
    if (!field) return;
    const next = String(value ?? "");
    if ((field.dataset.syncedValue === undefined && field.dataset.dirty !== "true") || field.value === field.dataset.syncedValue) field.value = next;
    field.dataset.syncedValue = next;
    field.dataset.dirty = String(field.value !== next);
  }

  // ------------------------------------------------------------ demo data
  // Real-shaped fixture data for the authorized screens (inspector previews).

  const DEMO_DATA = {
    state: {
      authorized: true, is_main: true, mode: "restricted_auto", state: "active", paused_remaining_sec: 0,
      emergency: false, quiet_hours: false, safe_mode: false, chatty_global: 0.15, style: "casual",
      prompt: "Reply like a 22-year-old Delhi guy, short, lowercase, Hinglish words when natural.",
      owner_name: "Kaif", ai_engine: "Gemini", ai_model: "gemini-2.5-flash-lite", ai_base_url: "",
      available_models: ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro"],
      models_manually_set: false,
      chats_allowed: 6, pending_count: 2, replies_24h: 41, tokens_today: 18320, version: "3.0.8",
      auto_reactions: true, ownreact: true, multibubble: true, typo: true, debounce: true, followup: false, mention_only: false,
      thinking: "default", temperature: "0.7", lang: "english", max_tokens: "512",
      quiet_hours_start: "02:00", quiet_hours_end: "08:00", quiet_hours_schedule: "02:00 AM – 08:00 AM IST",
      rules: ["pricing => We update our rates monthly, DM for catalog!", "help => How can I assist you today?"],
    },
    chats: [
      { id: 123456789, name: "Rohan Sharma", username: "@rohan_s", avatar_url: "https://t.me/i/userpic/320/rohan_s.jpg", initials: "RS", type: "Private", chatty: "", style: "", prompt: "", cooldown_min: 10, cooldown_max: 30, cooldown_str: "10s - 30s", voice_profile: true, blocked: false },
      { id: -1001987654321, name: "Startup India Founders", username: "startupindia", avatar_url: "https://t.me/i/userpic/320/startupindia.jpg", initials: "SI", type: "Group", chatty: "0.4", style: "humorous", prompt: "You help founders swap tools. Keep it practical.", cooldown_min: 15, cooldown_max: 45, cooldown_str: "15s - 45s", voice_profile: false, blocked: false },
      { id: -1001765432109, name: "Delhi Tech Meetup", username: "@delhitech", avatar_url: "https://t.me/i/userpic/320/delhitech.jpg", initials: "DT", type: "Group", chatty: "0", style: "", prompt: "", cooldown_min: null, cooldown_max: null, cooldown_str: "", voice_profile: false, blocked: false },
      { id: 987654321, name: "Aarav", username: "@aaravv", avatar_url: "https://t.me/i/userpic/320/aaravv.jpg", initials: "AA", type: "Private", chatty: "0.6", style: "", prompt: "", cooldown_min: 5, cooldown_max: 20, cooldown_str: "5s - 20s", voice_profile: false, blocked: false },
      { id: -1001654321098, name: "Crypto Signals Hub", username: "", avatar_url: "", initials: "CS", type: "Group", chatty: "", style: "concise", prompt: "", cooldown_min: null, cooldown_max: null, cooldown_str: "", voice_profile: false, blocked: true },
      { id: 876543210, name: "Mom", username: "", avatar_url: "", initials: "MO", type: "Private", chatty: "0.25", style: "", prompt: "Never send links here.", cooldown_min: 30, cooldown_max: 90, cooldown_str: "30s - 90s", voice_profile: false, blocked: false },
    ],
    pending: [
      { id: 41, chat_id: -1001987654321, chat_title: "Startup India Founders", username: "startupindia", avatar_url: "https://t.me/i/userpic/320/startupindia.jpg", initials: "SI", sender_id: 11223344, incoming_text: "btw are you joining the demo day on friday? wanted to show you the pitch deck before we send it out", text: "yeah definitely planning to join! send the deck over, will review it tonight.", created: "2026-11-13 14:22" },
      { id: 40, chat_id: 987654321, chat_title: "Aarav", username: "aaravv", avatar_url: "https://t.me/i/userpic/320/aaravv.jpg", initials: "AA", sender_id: 987654321, incoming_text: "Reached home! Call me when free, need to ask about the weekend plan.", text: "[Voice Note] Reached home! Call me when free, need to ask about the weekend plan.", created: "2026-11-13 13:05", is_voice: true, voice_dur: "0:21" },
    ],
    activity: [
      { chat: "Delhi Tech Meetup", chat_id: -1001765432109, message_id: 1042, msg_url: "https://t.me/delhitech/1042", sender: "TeleAutomator", text: "yeah the venue shifted to Hauz Khas this month, same 7pm slot", ts: "2026-11-13 14:18" },
      { chat: "Rohan Sharma", chat_id: 123456789, message_id: 588, msg_url: "https://t.me/rohan_s/588", sender: "TeleAutomator", text: "[Voice Note] Haan bhai venue pahunch gaya, 2nd floor hall booked hai", ts: "2026-11-13 13:52", is_voice: true, voice_dur: "0:14" },
      { chat: "Startup India Founders", chat_id: -1001987654321, message_id: 912, msg_url: "https://t.me/startupindia/912", sender: "TeleAutomator", text: "pricing page looks solid, maybe add a monthly option", ts: "2026-11-13 12:30" },
      { chat: "Mom", chat_id: 876543210, message_id: 341, msg_url: "https://t.me/c/876543210/341", sender: "TeleAutomator", text: "[Photo] Lunch pic sent, looks great!", ts: "2026-11-13 11:04", is_media: true },
    ],
    access: [
      { id: 555000111, name: "Kaif", username: "mkr_infinity", avatar_url: "https://t.me/i/userpic/320/mkr_infinity.jpg", avatar_bg: "linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%)", initials: "KR", main: true, perms: "all" },
      { id: 777000222, name: "Manager", username: "manager_h", avatar_url: "https://t.me/i/userpic/320/manager_h.jpg", avatar_bg: "linear-gradient(135deg, #065f46 0%, #10b981 100%)", initials: "MH", main: false, perms: "all" },
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
    if (path === "/api/auth") return { authorized: true, is_main: true, version: "3.0.8", user: { id: 555000111, name: "Kaif" } };
    if (path === "/api/state") return DEMO_DATA.state;
    if (path === "/api/chats") return { chats: DEMO_DATA.chats, chatty_global: DEMO_DATA.state.chatty_global };
    if (path === "/api/pending") return { pending: DEMO_DATA.pending };
    if (path === "/api/activity") return { activity: DEMO_DATA.activity };
    if (path.startsWith("/api/feedback")) {
      const rows = DEMO_DATA.activity.filter(row => row.feedback).map(row => ({ ...row, reply_text: row.text, chat_title: row.chat, rating: row.feedback, updated_at: row.ts }));
      const rating = new URLSearchParams(path.split("?")[1]).get("rating");
      return { ok: true, feedback: rows.filter(row => !rating || row.rating === rating), counts: Object.fromEntries(Object.keys(FEEDBACK_LABELS).map(key => [key, rows.filter(row => row.rating === key).length])) };
    }
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
      if (a === "feedback") {
        const params = body.params || {};
        const row = DEMO_DATA.activity.find(row => String(row.chat_id) === String(params.chat_id) && String(row.message_id) === String(params.id));
        if (!row) return { ok: false, response: "Choose a recent automated reply." };
        row.feedback = params.value === "clear" ? "" : params.value;
        return { ok: true, response: "Reply feedback saved for this chat." };
      }
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
      if (a === "chat_cooldown") {
        const c = DEMO_DATA.chats.find((x) => String(x.id) === String(p.chat_id));
        if (c) {
          if (p.reset) {
            c.cooldown_min = null;
            c.cooldown_max = null;
            c.cooldown_str = "";
          } else {
            c.cooldown_min = parseFloat(p.min) || 5;
            c.cooldown_max = parseFloat(p.max) || 60;
            c.cooldown_str = `${Math.round(c.cooldown_min)}s - ${Math.round(c.cooldown_max)}s`;
          }
        }
        return { ok: true, response: p.reset ? `Cooldown for chat ${p.chat_id} reset to global default.` : `Cooldown for chat ${p.chat_id} set to ${p.min}s - ${p.max}s.` };
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
        const raw = String(p.user_id || "").trim();
        const clean = raw.replace(/^@/, "");
        const uid = parseInt(clean, 10) || Math.floor(100000000 + Math.random() * 900000000);
        const name = raw.startsWith("@") ? `@${clean}` : `User ${uid}`;
        const username = raw.startsWith("@") ? clean : "";
        DEMO_DATA.access.push({
          id: uid,
          name: name,
          username: username,
          avatar_url: username ? `https://t.me/i/userpic/320/${username}.jpg` : "",
          avatar_bg: "linear-gradient(135deg, #701a75 0%, #d946ef 100%)",
          initials: (raw.startsWith("@") ? clean : `U${uid}`).slice(0, 2).toUpperCase(),
          main: false,
          perms: "all",
        });
        return { ok: true, response: `Owner ${name} (${uid}) added to authorized users.` };
      }
      if (a === "save_available_models") {
        DEMO_DATA.state.available_models = p.models || [];
        return { ok: true, response: `Saved ${(p.models || []).length} available model(s).` };
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
      if (a === "reaction" || a === "ownreact" || a === "multibubble" || a === "typo" || a === "debounce" || a === "followup" || a === "mentiononly") {
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
    const closeBtn = $("toast-close");
    if (iconEl) iconEl.innerHTML = statusKind === "ok" ? SVGS.check : (statusKind === "err" ? SVGS.alert : SVGS.info);
    if (msgEl) msgEl.textContent = plainText;
    else el.textContent = plainText;

    el.classList.remove("hidden");
    if (el.showPopover && !el.matches(":popover-open")) el.showPopover();
    const dismiss = hideToast;
    el.onclick = dismiss;
    if (closeBtn) closeBtn.onclick = (e) => { e.stopPropagation(); dismiss(); };
    haptic(statusKind === "err" ? "err" : (statusKind === "ok" ? "ok" : "light"));
    clearTimeout(toastTimer);
    const duration = statusKind === "err"
      ? Math.min(9000, 4500 + plainText.length * 40)
      : Math.min(7000, 3600 + plainText.length * 30);
    toastTimer = setTimeout(hideToast, duration);
  }

  function hideToast() {
    if ($("toast").hidePopover && $("toast").matches(":popover-open")) $("toast").hidePopover();
    $("toast").classList.add("hidden");
    clearTimeout(toastTimer);
  }

  function haptic(kind) {
    try {
      if (!tg) return;
      if (kind === "ok" || kind === "err") tg.HapticFeedback && tg.HapticFeedback.notificationOccurred(kind);
      else tg.HapticFeedback && tg.HapticFeedback.impactOccurred("light");
    } catch { /* haptics are best-effort */ }
  }

  function toggleSheetExpanded() {
    const sheet = $("sheet");
    if (!sheet) return;
    const isExp = sheet.classList.toggle("is-expanded");
    const expBtn = $("sheet-expand");
    if (expBtn) expBtn.setAttribute("aria-expanded", isExp ? "true" : "false");
    haptic("light");
  }

  let sheetVersion = 0;
  let sheetBusy = false;

  function openSheet(title, bodyHtml, buttons) {
    const sheet = $("sheet");
    hideToast();
    sheet.appendChild($("toast"));
    const version = ++sheetVersion;
    sheetBusy = false;
    $("sheet-close").disabled = false;
    sheet.removeAttribute("aria-busy");
    $("sheet-error").classList.add("hidden");
    if (sheet) sheet.classList.remove("is-expanded");
    const expBtn = $("sheet-expand");
    if (expBtn) expBtn.setAttribute("aria-expanded", "false");
    $("sheet-title").textContent = title;
    const bodyEl = $("sheet-body");
    if (bodyEl) {
      bodyEl.innerHTML = bodyHtml;
      bodyEl.scrollTop = 0;
    }
    const actions = $("sheet-actions");
    actions.innerHTML = "";
    (buttons || []).forEach((b) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `btn ${b.kind || ""}`.trim();
      btn.textContent = b.label;
      btn.addEventListener("click", async () => {
        if (sheetBusy) return;
        if (!b.onClick) return closeSheet();
        const fields = [...bodyEl.querySelectorAll("input, textarea, select")];
        if (b.kind === "primary" && fields.some((field) => !field.reportValidity())) return;
        sheetBusy = true;
        $("sheet-close").disabled = true;
        sheet.setAttribute("aria-busy", "true");
        btn.textContent = "Working…";
        actions.querySelectorAll("button").forEach((button) => { button.disabled = true; });
        try {
          const result = await b.onClick();
          if (version !== sheetVersion) return;
          if (result === false || (result && (result.ok === false || result.queued))) {
            $("sheet-error").textContent = result.response || "Your changes have not been saved. Review the values and try again.";
            $("sheet-error").classList.remove("hidden");
          } else closeSheet(true);
        } catch (error) {
          if (version === sheetVersion) {
            $("sheet-error").textContent = error.message || "Could not save. Try again.";
            $("sheet-error").classList.remove("hidden");
          }
        } finally {
          if (version === sheetVersion) {
            sheetBusy = false;
            $("sheet-close").disabled = false;
            sheet.removeAttribute("aria-busy");
            actions.querySelectorAll("button").forEach((button) => { button.disabled = false; });
            btn.textContent = b.label;
          }
        }
      });
      actions.appendChild(btn);
    });
    const inputs = [...bodyEl.querySelectorAll('input:not([type="checkbox"]), textarea, select')];
    inputs.forEach((field, index) => {
      field.enterKeyHint = index < inputs.length - 1 ? "next" : "done";
      field.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" || (field.tagName === "TEXTAREA" && !event.ctrlKey && !event.metaKey)) return;
        event.preventDefault();
        if (index < inputs.length - 1) inputs[index + 1].focus();
        else (actions.querySelector(".btn.primary") || actions.querySelector(".btn"))?.click();
      });
    });
    sheet.classList.remove("hidden");
    if (!sheet.open) sheet.showModal();
    document.body.classList.add("sheet-open");
    $("sheet-title").focus({ preventScroll: true });
    updateTmaBackButton();
    haptic("light");
  }

  function closeSheet(saved = false) {
    const sheet = $("sheet");
    if (sheetBusy && saved !== true) return;
    if (saved !== true && sheet.querySelector('[data-dirty="true"]') && !window.confirm("Discard the unsaved changes in this popup?")) return;
    if (sheet) sheet.classList.remove("is-expanded");
    const expBtn = $("sheet-expand");
    if (expBtn) expBtn.setAttribute("aria-expanded", "false");
    sheet.close();
    document.body.appendChild($("toast"));
    if (!$("toast").classList.contains("hidden") && $("toast").showPopover && !$("toast").matches(":popover-open")) $("toast").showPopover();
    sheet.classList.add("hidden");
    document.body.classList.remove("sheet-open");
    updateTmaBackButton();
    updateClosingConfirmation();
    if (refreshAfterSheet) { refreshAfterSheet = false; loadView(currentView); }
    haptic("light");
  }

  function updateTmaBackButton() {
    try {
      if (!tg || !tg.BackButton) return;
      const sheetOpen = $("sheet") && $("sheet").open;
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
  let latestState = null;
  const viewLoads = new Map();
  const viewScroll = new Map();
  let refreshAfterSheet = false;

  function showView(name) {
    if (!$(`view-${name}`)) return;
    viewScroll.set(currentView, window.scrollY);
    currentView = name;
    document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
    $(`view-${name}`).classList.remove("hidden");
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
    document.querySelectorAll(".tab").forEach((t) => {
      if (t.dataset.view === name) t.setAttribute("aria-current", "page");
      else t.removeAttribute("aria-current");
    });
    window.scrollTo({ top: viewScroll.get(name) || 0, behavior: "instant" });
    updateTmaBackButton();
    haptic();
    loadView(name);
  }

  function loadView(name) {
    if ($("sheet").open) { refreshAfterSheet = true; return Promise.resolve(); }
    if (viewLoads.has(name)) return viewLoads.get(name);
    const refresh = { overview: refreshOverview, chats: refreshChats, persona: refreshPersona, approvals: refreshApprovals, more: refreshMore }[name];
    if (!refresh) return Promise.resolve();
    const view = $(`view-${name}`);
    view.setAttribute("aria-busy", "true");
    $("view-error").classList.add("hidden");
    const request = refresh().catch((error) => {
      if (currentView === name) {
        $("view-error-message").textContent = error.message || "Could not refresh. Your current view is still available.";
        $("view-error").classList.remove("hidden");
      }
    }).finally(() => { view.removeAttribute("aria-busy"); viewLoads.delete(name); });
    viewLoads.set(name, request);
    return request;
  }

  // ------------------------------------------------------------ overview

  async function refreshOverview() {
    const [s, acts] = await Promise.all([latestState || api("/api/state"), api("/api/activity")]);
    if (!s || s.authorized === false) return maybePaywall(s);
    if (s.ok === false) throw new Error(s.response);
    renderState(s);
    if (acts.authorized === false) return maybePaywall(acts);
    renderSparkline(acts && acts.activity ? acts.activity : [], s.replies_24h || 0);
    const rows = (acts.activity || []).slice(0, 4);
    updateHtml("ov-activity", rows.length
      ? rows.map(feedRowHtml).join("")
      : `<div class="empty">No replies yet, the account stays quiet until a chat talks.</div>`);
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

    const hasLink = Boolean(a.msg_url);
    const linkIcon = hasLink
      ? `<span class="feed-link-icon" title="Jump to message in Telegram">${SVGS.externalLink}</span>`
      : "";

    return `<article class="rated-reply"><div class="feed-row ${hasLink ? "feed-clickable" : ""}" ${hasLink ? `data-msg-url="${esc(a.msg_url)}"` : ""} role="${hasLink ? "button" : "article"}" tabindex="${hasLink ? "0" : "-1"}">
      <div class="feed-top">
        <span class="feed-chat">${esc(a.chat)}</span>
        <div class="feed-meta">
          <span class="feed-ts num">${esc(formatIST(a.ts))}</span>
          ${linkIcon}
        </div>
      </div>
      ${voiceBadge}${mediaBadge}
      <span class="feed-text">${esc(a.text)}</span>
    </div>${(a.is_automated || DEMO) && canGiveFeedback && a.message_id > 0 ? `<button type="button" class="btn small feedback-button" data-feedback-chat="${esc(a.chat_id)}" data-feedback-message="${esc(a.message_id)}" data-feedback-rating="${esc(a.feedback || "")}">${esc(FEEDBACK_LABELS[a.feedback] || "Rate reply")}</button>` : ""}</article>`;
  }

  // --------------------------------------------------------------- chats

  let chatCache = [];

  async function refreshChats() {
    const data = await api("/api/chats");
    if (!data || data.authorized === false) return maybePaywall(data);
    if (data.ok === false) throw new Error(data.response);
    chatCache = data.chats || [];
    const changed = updateHtml("chat-list", chatCache.length
      ? chatCache.map(chatRowHtml).join("")
      : `<div class="empty">No chats allowed yet. Add a chat ID above.</div>`);
    if (changed) wireChatRows();
  }

  function chatRowHtml(c) {
    const initials = c.initials || (c.type === "Group" ? "GP" : "DM");
    const avatarBg = c.avatar_bg || "linear-gradient(135deg, #153421 0%, #1E3F2A 100%)";
    const cleanUser = c.username ? c.username.replace(/^@/, "").trim() : "";
    const usernameText = cleanUser ? `@${cleanUser}` : `ID: ${c.id}`;

    return `<div class="chat-capsule-card ${c.blocked ? "is-blocked" : ""}" data-cid="${c.id}" role="button" tabindex="0" aria-label="${esc(c.name)} details">
      <div class="chat-capsule-left">
        <div class="chat-avatar-wrap">
          ${c.avatar_url ? `<img src="${esc(c.avatar_url)}" alt="${esc(c.name)}" class="chat-avatar-img" loading="lazy" onerror="this.style.display='none';if(this.nextElementSibling)this.nextElementSibling.style.display='flex';" />` : ""}
          <div class="chat-avatar fallback" style="background: ${avatarBg}; ${c.avatar_url ? 'display:none;' : ''}">${esc(initials)}</div>
        </div>
        <div class="chat-capsule-info">
          <div class="chat-capsule-name">${esc(c.name)}</div>
          <div class="chat-capsule-username">${esc(usernameText)}</div>
        </div>
      </div>
      <div class="chat-capsule-right">
        ${c.blocked ? `<span class="pill pill-compact pill-negative">Blocked</span>` : ""}
        <span class="pill pill-compact ${c.type === "Group" ? "pill-positive" : "pill-neutral"}">${esc(c.type)}</span>
        <span class="chat-capsule-arrow" aria-hidden="true">${SVGS.chevronRight}</span>
      </div>
    </div>`;
  }

  function wireChatRows() {
    document.querySelectorAll("#chat-list .chat-capsule-card").forEach((card) => {
      const cid = card.dataset.cid;
      const openHandler = () => {
        const c = chatCache.find((x) => String(x.id) === String(cid));
        if (c) openChatDetailSheet(c);
      };
      card.addEventListener("click", openHandler);
      card.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openHandler();
        }
      });
    });
  }

  function openChatDetailSheet(c) {
    const initials = c.initials || (c.type === "Group" ? "GP" : "DM");
    const avatarBg = c.avatar_bg || "linear-gradient(135deg, #153421 0%, #1E3F2A 100%)";
    const cleanUser = c.username ? c.username.replace(/^@/, "").trim() : "";
    const userDisplay = cleanUser
      ? `<a href="https://t.me/${encodeURIComponent(cleanUser)}" target="_blank" rel="noopener noreferrer" class="pill pill-neutral chat-user chat-user-link" title="Open @${esc(cleanUser)} in Telegram">@${esc(cleanUser)} ${SVGS.externalLink}</a>`
      : "";

    const chattyDisplay = c.chatty !== "" && c.chatty !== null && c.chatty !== undefined ? `${Math.round(parseFloat(c.chatty) * 100)}%` : "Global default";
    const cooldownDisplay = c.cooldown_str || `Global Default (${c.cooldown_default_min ?? 5}s – ${c.cooldown_default_max ?? 60}s)`;

    const bodyHtml = `
      <div class="chat-detail-wrap">
        <div class="chat-detail-header">
          <div class="chat-avatar-wrap large">
            ${c.avatar_url ? `<img src="${esc(c.avatar_url)}" alt="${esc(c.name)}" class="chat-avatar-img" loading="lazy" onerror="this.style.display='none';if(this.nextElementSibling)this.nextElementSibling.style.display='flex';" />` : ""}
            <div class="chat-avatar fallback" style="background: ${avatarBg}; ${c.avatar_url ? 'display:none;' : ''}">${esc(initials)}</div>
          </div>
          <div class="chat-detail-title-col">
            <h4 class="chat-detail-name">${esc(c.name)}</h4>
            <div class="chat-detail-sub-row">
              ${userDisplay}
              <div class="chat-id-badge-wrap">
                <span class="pill pill-neutral num">ID: ${esc(String(c.id))}</span>
                <button type="button" class="copy-id-btn" data-copy="${esc(String(c.id))}" aria-label="Copy Chat ID" title="Copy Chat ID">${SVGS.copy}</button>
              </div>
            </div>
          </div>
        </div>

        <div class="chat-detail-tags">
          <span class="pill ${c.type === "Group" ? "pill-positive" : "pill-neutral"}">${esc(c.type)}</span>
          ${c.voice_profile ? `<span class="pill pill-neutral">Voice Profile Active</span>` : ""}
          ${c.blocked ? `<span class="pill pill-negative">Blocked</span>` : ""}
          ${c.prompt ? `<span class="pill pill-warning">Custom Prompt</span>` : ""}
          ${c.context ? `<span class="pill pill-positive">Has Context</span>` : ""}
        </div>

        <div class="chat-detail-summary-card">
          <div class="summary-item">
            <span class="summary-label">Chatty Frequency</span>
            <span class="summary-val">${esc(chattyDisplay)}</span>
          </div>
          <div class="summary-item">
            <span class="summary-label">Reply Cooldown</span>
            <span class="summary-val">${esc(cooldownDisplay)}</span>
          </div>
          ${c.prompt ? `
            <div class="summary-item full">
              <span class="summary-label">Custom Persona</span>
              <div class="summary-quote">${esc(c.prompt)}</div>
            </div>` : ""}
          ${c.context ? `
            <div class="summary-item full">
              <span class="summary-label">Permanent Memory</span>
              <div class="summary-quote">${esc(c.context)}</div>
            </div>` : ""}
        </div>

        <div class="chat-actions-heading">Chat Actions</div>
        <div class="chat-actions-5grid">
          <button type="button" class="clay-action-btn action-theme-prompt" data-action="prompt">
            <div class="action-btn-icon-wrap">${SVGS.edit}</div>
            <div class="action-btn-text">
              <span class="action-btn-title">Prompt</span>
              <span class="action-btn-sub">AI Persona</span>
            </div>
          </button>
          <button type="button" class="clay-action-btn action-theme-context" data-action="context">
            <div class="action-btn-icon-wrap">${SVGS.brain}</div>
            <div class="action-btn-text">
              <span class="action-btn-title">Context</span>
              <span class="action-btn-sub">Chat Memory</span>
            </div>
          </button>
          <button type="button" class="clay-action-btn action-theme-chatty" data-action="chatty">
            <div class="action-btn-icon-wrap">${SVGS.msg}</div>
            <div class="action-btn-text">
              <span class="action-btn-title">Chatty</span>
              <span class="action-btn-sub">${esc(fmtPct(c.chatty))} Chance</span>
            </div>
          </button>
          <button type="button" class="clay-action-btn action-theme-cooldown" data-action="cooldown">
            <div class="action-btn-icon-wrap">${SVGS.clock}</div>
            <div class="action-btn-text">
              <span class="action-btn-title">Cooldown</span>
              <span class="action-btn-sub">${esc(c.cooldown_str || "Default")}</span>
            </div>
          </button>
          <button type="button" class="clay-action-btn action-theme-remove" data-action="remove">
            <div class="action-btn-icon-wrap">${SVGS.trash}</div>
            <div class="action-btn-text">
              <span class="action-btn-title">Remove</span>
              <span class="action-btn-sub">Delete / Block</span>
            </div>
          </button>
        </div>
      </div>
    `;

    openSheet(c.name, bodyHtml, [{ label: "Close", kind: "" }]);

    {
      const sheetBody = $("sheet-body");
      if (!sheetBody) return;

      sheetBody.querySelector(".copy-id-btn")?.addEventListener("click", (e) => {
        e.stopPropagation();
        const copyText = e.currentTarget.dataset.copy;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(copyText).then(() => toast("Chat ID copied!")).catch(() => toast(`ID: ${copyText}`));
        } else {
          toast(`ID: ${copyText}`);
        }
      });

      sheetBody.querySelectorAll(".clay-action-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          const act = btn.dataset.action;
          if (act === "prompt") promptSheet(c);
          else if (act === "context") contextSheet(c);
          else if (act === "chatty") chattySheet(c);
          else if (act === "cooldown") chatCooldownSheet(c);
          else if (act === "remove") removeSheet(c, "remove");
        });
      });
    }
  }

  function chatCooldownSheet(c) {
    const curMin = c.cooldown_min ?? c.cooldown_default_min ?? 5;
    const curMax = c.cooldown_max ?? c.cooldown_default_max ?? 60;
    const isCustom = c.cooldown_min != null && c.cooldown_max != null;

    const bodyHtml = `
      <div class="cooldown-sheet-content">
        <p class="field-hint" style="margin-top:0;margin-bottom:12px">
          Set custom random reply cooldown range for <strong>${esc(c.name)}</strong>. The bot waits a random duration between Min and Max seconds between automated replies in this chat.
        </p>
        <div class="cooldown-inputs-grid">
          <div class="field-group">
            <label for="cd-min-input" class="field-label">Min Cooldown (sec)</label>
            <input type="number" id="cd-min-input" class="clay-input" min="0" value="${curMin}" step="0.1" required>
          </div>
          <div class="field-group">
            <label for="cd-max-input" class="field-label">Max Cooldown (sec)</label>
            <input type="number" id="cd-max-input" class="clay-input" min="0" value="${curMax}" step="0.1" required>
          </div>
        </div>
        <div class="cooldown-presets-section">
          <span class="field-label" style="display:block;margin-bottom:6px">Quick Presets</span>
          <div class="cooldown-preset-chips">
            <button type="button" class="preset-chip" data-min="5" data-max="15">5s - 15s (Active)</button>
            <button type="button" class="preset-chip" data-min="15" data-max="45">15s - 45s (Natural)</button>
            <button type="button" class="preset-chip" data-min="30" data-max="90">30s - 90s (Casual)</button>
            <button type="button" class="preset-chip" data-min="60" data-max="180">60s - 180s (Slow)</button>
          </div>
        </div>
        <div class="current-cd-status" style="margin-top:12px;font-size:12px;color:var(--faint);">
          Status: ${isCustom ? `<span style="color:var(--accent-bright);font-weight:600">Custom (${curMin}s - ${curMax}s)</span>` : `<span>Default (${curMin}s - ${curMax}s)</span>`}
        </div>
      </div>
    `;

    openSheet(
      `Cooldown · ${c.name}`,
      bodyHtml,
      [
        {
          label: "Save Cooldown",
          kind: "primary",
          onClick: () => {
            const minVal = parseFloat($("cd-min-input")?.value || "5");
            const maxVal = parseFloat($("cd-max-input")?.value || "60");
            if (maxVal < minVal) return { ok: false, response: "Maximum cooldown must be at least the minimum." };
            return runAction("chat_cooldown", { chat_id: c.id, min: minVal, max: maxVal });
          },
        },
        {
          label: "Reset to Global",
          onClick: () => {
            return runAction("chat_cooldown", { chat_id: c.id, reset: true });
          },
        },
      ]
    );

    {
      document.querySelectorAll(".cooldown-preset-chips .preset-chip").forEach((btn) => {
        btn.addEventListener("click", () => {
          const minInp = $("cd-min-input");
          const maxInp = $("cd-max-input");
          if (minInp) minInp.value = btn.dataset.min;
          if (maxInp) maxInp.value = btn.dataset.max;
          minInp?.dispatchEvent(new Event("input", { bubbles: true }));
          maxInp?.dispatchEvent(new Event("input", { bubbles: true }));
          haptic("light");
        });
      });
    }
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
    openSheet(`Chatty · ${c.name}`, `<p>Chance of occasionally joining a relevant conversation. Default follows the global setting. Messages addressed to other people are ignored.</p>`, buttons);
  }

  function promptSheet(c) {
    openSheet(`Per-chat prompt · ${c.name}`,
      `<p class="field-hint" style="margin-top:0;margin-bottom:8px">Custom AI persona for this chat only (slang, attitude, constraints).</p>` +
      `<textarea id="sheet-input" rows="4" placeholder="Empty = global prompt">${esc(c.prompt)}</textarea>`,
      [
        { label: "Save", kind: "primary", onClick: () => runAction("chatprompt", { chat_id: c.id, value: $("sheet-input").value.trim() }) },
        { label: "Clear", onClick: () => runAction("chatprompt", { chat_id: c.id, value: "default" }) },
      ]);
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

    const changed = updateHtml("preset-carousel", PROMPT_PRESETS.map((p) => {
      const isActive = p.prompt ? currentPrompt === p.prompt : !currentPrompt;
      return `<button type="button" class="preset-chip ${isActive ? "active" : ""}" data-preset="${p.id}">
        <span class="preset-icon">${p.icon}</span>
        <span>${esc(p.name)}</span>
      </button>`;
    }).join(""));
    if (!changed) return;
    el.querySelectorAll(".preset-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        haptic("light");
        const found = PROMPT_PRESETS.find((x) => x.id === chip.dataset.preset);
        if (!found) return;
        $("pf-prompt").value = found.prompt;
        $("pf-prompt").dispatchEvent(new Event("input", { bubbles: true }));
        el.querySelectorAll(".preset-chip").forEach((c) => c.classList.remove("active"));
        chip.classList.add("active");
        toast(found.prompt ? `Loaded "${found.name}". Tap Save prompt to apply.` : "Reset to built-in persona. Tap Save prompt to apply.", "info");
      });
    });
  }

  async function refreshPersona() {
    const [s, data] = await Promise.all([api("/api/state"), api("/api/chats")]);
    if (!s || s.authorized === false) return maybePaywall(s);
    if (s.ok === false) throw new Error(s.response);
    if (data.authorized === false) return maybePaywall(data);
    if (data.ok === false) throw new Error(data.response);
    syncField("pf-prompt", s.prompt || "");
    syncField("pf-name", s.owner_name || "");
    renderPromptPresets();
    const styles = ["casual", "concise", "formal", "humorous"];
    const styleChanged = updateHtml("pf-style", styles.map((st) =>
      `<button class="seg ${st === s.style ? "active" : ""}" data-style="${st}">${st}</button>`).join(""));
    if (styleChanged) $("pf-style").querySelectorAll(".seg").forEach((b) =>
      b.addEventListener("click", () => runAction("style", { value: b.dataset.style })));
    const chats = (data.chats || []).filter((c) => c.prompt || c.context);
    const changed = updateHtml("pf-chats", chats.length
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
      : `<div class="empty">No per-chat prompts or context notes yet. Set them from the Chats tab.</div>`);
    if (!changed) return;
    $("pf-chats").querySelectorAll("[data-op]").forEach((btn) =>
      btn.addEventListener("click", () => {
        const c = (data.chats || []).find((x) => String(x.id) === btn.dataset.cid);
        if (!c) return;
        if (btn.dataset.op === "edit-prompt") promptSheet(c);
        else if (btn.dataset.op === "edit-context") contextSheet(c);
      }));
  }

  // ------------------------------------------------------------ approvals (Phase 2: Swipe Actions)

  let approvalTotal = 0;
  async function refreshApprovals() {
    const data = await api("/api/pending");
    if (!data || data.authorized === false) return maybePaywall(data);
    if (data.ok === false) throw new Error(data.response);
    const rows = data.pending || [];
    const count = rows.length;
    approvalTotal = data.total ?? count;
    $("tab-approvals").textContent = String(approvalTotal);
    $("tab-approvals").classList.toggle("hidden", !approvalTotal);
    $("approval-summary").textContent = count < approvalTotal ? `Showing ${count} of ${approvalTotal} drafts. Approve this batch to see the next drafts.` : `${count} pending draft(s).`;
    if ($("approval-batch-bar")) {
      $("approval-batch-bar").classList.toggle("hidden", count < 2);
    }
    const changed = updateHtml("approval-list", count
      ? rows.map(approvalCardHtml).join("")
      : `<div class="empty">Nothing waiting. In approval mode every draft shows up here.</div>`);
    if (!changed) return;
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
              ${cleanUser ? `<a href="https://t.me/${encodeURIComponent(cleanUser)}" target="_blank" rel="noopener noreferrer" class="pill pill-neutral chat-user-link" title="Open @${esc(cleanUser)} in Telegram">@${esc(cleanUser)} ${SVGS.externalLink}</a>` : ""}
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

  function renderModelChips(modelsList, selectedOverride) {
    const container = $("ai-model-chips");
    if (!container) return;
    if (!modelsList || !modelsList.length) {
      container.innerHTML = '<div class="empty sm">No models loaded. Tap &ldquo;Fetch models&rdquo; to query your endpoint.</div>';
      return;
    }
    const selectedList = (Array.isArray(selectedOverride) ? selectedOverride : ($("ai-model").value || "").split(/[,;]/))
      .map((s) => String(s).trim().replace(/^models\//, "")).filter(Boolean);
    const changed = updateHtml("ai-model-chips", modelsList.map((m) => {
      const cleanM = String(m).replace(/^models\//, "").trim();
      const idx = selectedList.indexOf(cleanM);
      const badge = idx === -1 ? "" : `<span class="chip-order-badge">${idx + 1}</span>`;
      return `<button class="model-chip ${idx === -1 ? "" : "active"}" data-model="${esc(cleanM)}" type="button">${badge}${esc(cleanM)}</button>`;
    }).join(""));
    if (!changed) return;
    container.querySelectorAll(".model-chip").forEach((chip) => {
      chip.addEventListener("click", async () => {
        const selected = [...selectedList];
        const idx = selected.indexOf(chip.dataset.model);
        if (idx === -1) selected.push(chip.dataset.model);
        else selected.splice(idx, 1);
        if (!selected.length) return toast("Keep at least one active model", "err");
        const res = await runAction("model", { value: selected.join(",") });
        if (res && res.ok) {
          $("ai-model").value = selected.join(",");
          renderModelChips(modelsList, selected);
        }
      });
    });
  }

  async function refreshMore() {
    const [data, s] = await Promise.all([api("/api/access"), api("/api/state")]);
    if (!data || data.authorized === false) return maybePaywall(data);
    if (!s || s.authorized === false) return maybePaywall(s);
    if (s.ok === false) throw new Error(s.response);
    renderMoreControls(s);
    if ($("settings-history").open) await refreshHistory();
    if ($("settings-feedback").open) await refreshFeedback();
    const changed = updateHtml("access-list", data.ok === false ? `<p class="empty">${esc(data.response)}</p>` : (data.users || []).length
      ? data.users.map((u) => {
          const initials = u.initials || (u.name || "U").slice(0, 2).toUpperCase();
          const cleanUser = u.username ? u.username.replace(/^@/, "").trim() : "";
          const userLink = cleanUser
            ? `<a href="https://t.me/${encodeURIComponent(cleanUser)}" target="_blank" rel="noopener noreferrer" class="pill pill-compact pill-neutral chat-user-link" title="Open @${esc(cleanUser)} in Telegram">@${esc(cleanUser)} ${SVGS.externalLink}</a>`
            : "";
          const avatarBg = u.avatar_bg || "linear-gradient(135deg, #1E293B 0%, #334155 100%)";
          return `<div class="owner-capsule-card">
            <div class="owner-capsule-left">
              <div class="chat-avatar-wrap">
                ${u.avatar_url ? `<img src="${esc(u.avatar_url)}" alt="${esc(u.name)}" class="chat-avatar-img" loading="lazy" onerror="this.style.display='none';if(this.nextElementSibling)this.nextElementSibling.style.display='flex';" />` : ""}
                <div class="chat-avatar fallback" style="background:${avatarBg}; ${u.avatar_url ? 'display:none;' : ''}">${esc(initials)}</div>
              </div>
              <div class="owner-capsule-info">
                <div class="owner-capsule-name-row">
                  <span class="owner-capsule-name">${esc(u.name)}</span>
                  ${userLink}
                  ${u.main ? '<span class="pill pill-compact pill-positive">Owner</span>' : '<span class="pill pill-compact pill-neutral">Authorized</span>'}
                </div>
                <div class="owner-capsule-sub-row">
                  <span class="num">ID: ${esc(String(u.id))}</span>
                </div>
              </div>
            </div>
            <div class="capsule-side">
              ${u.main ? "" : `<button type="button" class="btn small danger" data-unauth="${u.id}">Remove</button>`}
            </div>
          </div>`;
        }).join("")
      : `<div class="empty">No authorized owners. Add an owner by ID or @username above.</div>`);
    if (!changed) return;
    $("access-list").querySelectorAll("[data-unauth]").forEach((btn) =>
      btn.addEventListener("click", () => openSheet("Remove owner", `<p>Revoke panel access for owner <span class="num">${esc(btn.dataset.unauth)}</span>?</p>`,
        [{ label: "Remove", kind: "danger", onClick: () => runAction("removeauth", { user_id: btn.dataset.unauth }) }, { label: "Cancel" }])));

  }

  function openFeedbackSheet(chatId, messageId, current) {
    const buttons = Object.entries(FEEDBACK_LABELS).map(([rating, label]) => ({ label, kind: rating === current ? "primary" : "",
      onClick: () => runAction("feedback", { chat_id: chatId, id: messageId, value: rating }) }));
    if (current) buttons.push({ label: "Clear rating", onClick: () => runAction("feedback", { chat_id: chatId, id: messageId, value: "clear" }) });
    buttons.push({ label: "Cancel" });
    openSheet("Rate this reply", `<p>Your rating guides future replies in this chat.</p><p class="helper">Chat ${esc(chatId)} · Message ${esc(messageId)}</p>`, buttons);
  }

  let feedbackRequest = 0;
  async function refreshFeedback() {
    const request = ++feedbackRequest;
    $("feedback-refresh").disabled = true;
    $("feedback-error").classList.add("hidden");
    try {
      const result = await api(`/api/feedback?rating=${encodeURIComponent($("feedback-filter").value)}`);
      if (request !== feedbackRequest) return;
      if (result.authorized === false) return maybePaywall(result);
      if (!result.ok) throw new Error(result.response || "Could not load feedback.");
      $("feedback-counts").textContent = Object.entries(FEEDBACK_LABELS).map(([key, label]) => `${label}: ${result.counts?.[key] || 0}`).join(" · ");
      updateHtml("feedback-list", result.feedback.length ? result.feedback.map(row => `<article class="history-row">
        <div class="history-heading"><strong>${esc(row.chat_title || `Chat ${row.chat_id}`)}</strong><span class="pill">${esc(FEEDBACK_LABELS[row.rating] || row.rating)}</span></div>
        <p>${esc(row.reply_text)}</p><small>${esc(formatIST(row.updated_at))}</small>
        <button type="button" class="btn small feedback-button" data-feedback-chat="${esc(row.chat_id)}" data-feedback-message="${esc(row.message_id)}" data-feedback-rating="${esc(row.rating)}">Change rating</button>
      </article>`).join("") : '<p class="empty">No matching ratings. Start from Recent replies on Overview.</p>');
    } catch (error) {
      if (request === feedbackRequest) { $("feedback-error").textContent = error.message || "Could not load feedback. Try Refresh."; $("feedback-error").classList.remove("hidden"); }
    } finally { if (request === feedbackRequest) $("feedback-refresh").disabled = false; }
  }

  let historyRows = [];
  let historyBefore = null;
  let historyRequest = 0;

  async function refreshHistory(reset = true) {
    const request = ++historyRequest;
    const button = $(reset ? "history-refresh" : "history-more");
    button.disabled = true;
    $("history-error").classList.add("hidden");
    try {
      const query = new URLSearchParams({ status: $("history-status").value, limit: "40" });
      if (!reset && historyBefore) query.set("before", historyBefore);
      const result = DEMO ? { ok: true, events: [], diagnostics: DEMO_DATA.state } : await api(`/api/history?${query}`);
      if (request !== historyRequest) return;
      if (result.authorized === false) return maybePaywall(result);
      if (!result.ok) throw new Error(result.response || "Could not load action history.");
      historyRows = reset ? result.events : [...historyRows, ...result.events];
      historyBefore = result.next_before;
      const d = result.diagnostics || {};
      updateHtml("history-diagnostics", [
        ["Engine", d.state || "Unknown"], ["Mode", formatMode(d.mode || "")],
        ["Provider", d.ai_engine || "Unknown"], ["Model", d.ai_model || "Default"],
        ["Safe mode", d.safe_mode ? "Active" : "Clear"], ["Quiet hours", d.quiet_hours ? "Active" : "Off"],
      ].map(([label, value]) => `<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join(""));
      updateHtml("history-list", historyRows.length ? historyRows.map(event => `<article class="history-row">
        <div class="history-heading"><strong>${esc(String(event.action).replaceAll("_", " "))}</strong><span class="pill">${esc(event.status)}</span></div>
        <p>${esc(event.detail || "")}</p><small>${esc(formatIST(event.created_at))} · ${esc(event.source)}${event.chat_id ? ` · Chat ${esc(event.chat_id)}` : ""}</small>
      </article>`).join("") : '<p class="empty">No matching actions yet.</p>');
      $("history-more").classList.toggle("hidden", !historyBefore);
    } catch (error) {
      if (request === historyRequest) {
        $("history-error").textContent = error.message || "Could not load history. Tap Refresh to retry.";
        $("history-error").classList.remove("hidden");
      }
    } finally { button.disabled = false; }
  }

  async function exportSettings() {
    const button = $("settings-export");
    button.disabled = true;
    try {
      if (DEMO) throw new Error("Connect to your engine to export preferences.");
      const result = await api("/api/settings/export");
      if (result.authorized === false) return maybePaywall(result);
      if (!result.ok) throw new Error(result.response || "Could not prepare the backup.");
      const url = new URL(result.download_url, location.origin);
      if (url.origin !== location.origin) throw new Error("Invalid download address.");
      if (url.protocol === "https:" && telegramCall("downloadFile", "8.0", { url: url.href, file_name: result.file_name }, accepted => toast(accepted ? "Download requested" : "Download cancelled", "info"))) return;
      const link = document.createElement("a");
      link.href = url.href;
      link.download = result.file_name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      toast("Download requested", "info");
    } catch (error) { toast(error.message || "Could not export preferences.", "err"); }
    finally { button.disabled = false; }
  }

  async function previewSettingsFile() {
    const input = $("settings-file");
    const file = input.files?.[0];
    if (!file) return;
    input.disabled = true;
    try {
      if (DEMO) throw new Error("Connect to your engine to import preferences.");
      if (file.size > 1000000) throw new Error("Choose a backup smaller than 1 MB.");
      let backup;
      try { backup = JSON.parse(await file.text()); }
      catch (_) { throw new Error("The file is not valid JSON. Choose a TeleAutomator backup."); }
      const preview = await api("/api/settings/preview", { backup });
      if (preview.authorized === false) return maybePaywall(preview);
      if (!preview.ok) throw new Error(preview.response || "This backup is invalid.");
      const summary = preview.summary;
      openSheet("Review preference import", `<p>Merge <strong>${esc(summary.settings)} settings</strong>, <strong>${esc(summary.chats)} chat profiles</strong>, and <strong>${esc(summary.rules)} keyword rules</strong>.</p>
        <p>Access permissions and conversation memory are preserved. Existing preferences listed in this backup will be replaced.</p>
        <p class="helper">Settings: ${esc((preview.setting_keys || []).join(", ") || "None")}</p>
        <p class="helper">Chat IDs: ${esc((preview.chat_ids || []).join(", ") || "None")}</p>`, [
        { label: "Apply preferences", kind: "primary", onClick: async () => {
          const result = await api("/api/settings/import", { backup });
          if (result.authorized === false) { maybePaywall(result); return false; }
          if (result.ok) { latestState = null; refreshAfterSheet = true; toast("Preferences restored", "ok"); }
          return result;
        } }, { label: "Cancel" },
      ]);
    } catch (error) { toast(error.message || "Could not read the backup.", "err"); }
    finally { input.disabled = false; input.value = ""; input.dataset.dirty = "false"; updateClosingConfirmation(); }
  }

  function renderMoreControls(s) {
    if (!s) return;
    const pipeline = s.pipeline || { context: "Per-chat files and batched summaries", writer: "Selected model", humanizer: "Local checks; no extra model call" };
    updateHtml("pipeline-status", [["Context stage", pipeline.context], ["Writer stage", pipeline.writer], ["Final style check", pipeline.humanizer]].map(([label, value]) => `<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join(""));
    if (s.ai_model !== undefined) syncField("ai-model", s.ai_model);
    if (s.ai_base_url !== undefined) syncField("ai-baseurl", s.ai_base_url);
    if (Array.isArray(s.available_models)) {
      cachedEndpointModels = s.available_models;
      $("models-fetched-count").textContent = `(${cachedEndpointModels.length})`;
    }

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
    if (qhStart && s.quiet_hours_start) syncField("qh-start-input", s.quiet_hours_start);
    if (qhEnd && s.quiet_hours_end) syncField("qh-end-input", s.quiet_hours_end);

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
      "ownreact": s.ownreact,
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
      btn.setAttribute("role", "switch");
      btn.setAttribute("aria-checked", String(on));
      btn.setAttribute("aria-label", btn.closest(".setting-toggle-row")?.querySelector(".toggle-title")?.textContent.trim() || action);
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
    setSegActive("seg-maxtokens", s.max_tokens || "default");

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
      const changed = updateHtml("rules-list", rules.length
        ? rules.map((r) => `<div class="rule-row">
            <div class="rule-info">
              <span class="rule-trigger">Trigger: &ldquo;${esc(r.keyword)}&rdquo;</span>
              <span class="rule-response">${esc(r.reply)}</span>
            </div>
            <button class="btn small danger" data-delrule="${esc(r.keyword)}">Delete</button>
          </div>`).join("")
        : `<div class="empty">No keyword auto-replies configured. Tap &ldquo;+ Add Rule&rdquo; above.</div>`);

      if (changed) rulesList.querySelectorAll("[data-delrule]").forEach((b) => {
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
    const resetSafemodeBtn = $("btn-reset-safemode");
    if (safemodeBadge) {
      const isTripped = s.safe_mode_active || s.safe_mode;
      safemodeBadge.textContent = isTripped ? "Safe Mode Triggered" : "Protected";
      safemodeBadge.className = `pill ${isTripped ? "pill-warning" : "pill-positive"}`;
      if (resetSafemodeBtn) {
        resetSafemodeBtn.style.display = isTripped ? "inline-block" : "none";
      }
    }

    const emergBtn = $("btn-emergency-toggle");
    if (emergBtn) {
      const isStopped = s.emergency || s.state === "stopped";
      emergBtn.textContent = isStopped ? "Resume Engine" : "Halt Engine";
      emergBtn.className = `btn small ${isStopped ? "primary" : "danger"}`;
    }
  }

  // Queue only bounded, non-secret preferences for the authenticated account.
  const OFFLINE_QUEUE_PREFIX = "teleautomator_offline_queue_v2:";
  const QUEUED_PREFERENCES = new Set(["style", "chatstyle", "lang", "temp", "maxtokens", "thinking", "chat_chatty"]);

  function safeQueuedAction(item) {
    if (!item || !QUEUED_PREFERENCES.has(item.action) || !item.params || typeof item.params !== "object") return false;
    if (Object.keys(item.params).some(key => !["value", "chat_id"].includes(key))) return false;
    const value = item.params.value;
    if (typeof value !== "string" || !value || value.length > 40) return false;
    if (["chatstyle", "chat_chatty"].includes(item.action) && !/^-?\d+$/.test(String(item.params.chat_id || ""))) return false;
    if (["style", "chatstyle"].includes(item.action)) return ["casual", "concise", "formal", "humorous"].includes(value);
    if (item.action === "lang") return /^[a-zA-Z][a-zA-Z -]{0,39}$/.test(value);
    if (item.action === "thinking") return ["default", "off", "none", "low", "medium", "high"].includes(value);
    if (item.action === "maxtokens" && value === "default") return true;
    if (item.action === "chat_chatty" && ["def", "default"].includes(value)) return true;
    const number = Number(value);
    return Number.isFinite(number) && number >= 0 && (item.action === "temp" ? number <= 2 : item.action === "chat_chatty" ? number <= 100 : Number.isInteger(number) && number > 0 && number <= 1000000);
  }

  function loadOfflineQueue(userId = activeUserId) {
    try {
      localStorage.removeItem("teleautomator_offline_queue_v1");
      if (!userId) return [];
      const parsed = JSON.parse(localStorage.getItem(OFFLINE_QUEUE_PREFIX + userId) || "[]");
      if (!Array.isArray(parsed)) return [];
      return parsed.filter(item => safeQueuedAction(item) && item.id && Number.isFinite(Date.parse(item.time)) && Math.abs(Date.now() - Date.parse(item.time)) < 3600000).slice(-50);
    } catch { return []; }
  }

  function saveOfflineQueue(queue, userId = activeUserId) {
    if (!userId) return false;
    try {
      localStorage.setItem(OFFLINE_QUEUE_PREFIX + userId, JSON.stringify(queue.filter(safeQueuedAction).slice(-50)));
      return true;
    } catch { return false; }
  }

  function updateSyncBadge() {
    const badge = $("offline-sync-badge");
    const countEl = $("offline-sync-count");
    if (!badge) return;
    const count = loadOfflineQueue().length;
    if (countEl) countEl.textContent = String(count);
    badge.classList.toggle("hidden", count === 0);
    badge.title = `${count} preference change(s) queued for this account`;
  }

  function enqueueAction(action, params) {
    if (!activeUserId || !safeQueuedAction({ action, params })) return false;
    const queue = loadOfflineQueue();
    if (queue.some(item => item.action === action && JSON.stringify(item.params) === JSON.stringify(params))) return true;
    queue.push({ id: Date.now() + "_" + Math.random().toString(36).slice(2, 6), action, params, time: new Date().toISOString() });
    const saved = saveOfflineQueue(queue);
    updateSyncBadge();
    return saved;
  }

  let isFlushingQueue = false;
  async function flushOfflineQueue() {
    if (isFlushingQueue || !activeUserId) return;
    const userId = activeUserId;
    const queue = loadOfflineQueue(userId);
    if (!queue.length) { updateSyncBadge(); return; }
    isFlushingQueue = true;
    const remaining = [];
    let synced = 0;
    try {
      for (let index = 0; index < queue.length; index++) {
        if (activeUserId !== userId) { remaining.push(...queue.slice(index)); break; }
        const item = queue[index];
        try {
          const result = await api("/api/action", { action: item.action, params: item.params });
          if (result?.authorized === false) { remaining.push(...queue.slice(index)); break; }
          if (result?.ok) synced++;
          else remaining.push(item);
        } catch { remaining.push(...queue.slice(index)); break; }
      }
      const ids = new Set(queue.map(item => item.id));
      saveOfflineQueue([...remaining, ...loadOfflineQueue(userId).filter(item => !ids.has(item.id))], userId);
      if (activeUserId === userId) {
        updateSyncBadge();
        if (synced) { toast(`Synced ${synced} preference change(s)`, "ok"); loadView(currentView); }
      }
    } finally { isFlushingQueue = false; }
  }

  // --------------------------------------------------------- run + notify

  const actionsInFlight = new Map();
  async function runAction(action, params = {}) {
    const key = JSON.stringify([action, params]);
    if (actionsInFlight.has(key)) return actionsInFlight.get(key);
    const request = performAction(action, params);
    actionsInFlight.set(key, request);
    try { return await request; } finally { actionsInFlight.delete(key); }
  }

  async function performAction(action, params) {
    haptic();
    const card = ["approve", "reject"].includes(action) && params.id ? document.querySelector(`.approval-card-wrap[data-id="${params.id}"]`) : null;
    const buttons = card ? [...card.querySelectorAll("button")] : [...document.querySelectorAll(`[data-action="${action}"]`)];
    buttons.forEach((button) => { button.disabled = true; });
    card?.setAttribute("aria-busy", "true");
    try {
      const res = await api("/api/action", { action, params });
      if (res && res.authorized === false) {
        maybePaywall(res);
        return { ok: false, response: "Your access has changed. Reopen the app after the owner restores it." };
      }
      haptic(res && res.ok ? "ok" : "err");
      latestState = null;
      toast(res?.response || (res?.ok ? "Done" : "Failed"), res?.ok ? "ok" : "err");
      await loadView(currentView);
      updateClosingConfirmation();
      return res;
    } catch (error) {
      if (navigator.onLine === false) {
        const queued = enqueueAction(action, params);
        const response = queued ? "Preference queued for this account. Reconnect to sync it." : "Offline: this action is not queued. Reconnect and check its result before trying again.";
        toast(response, queued ? "info" : "err");
        updateClosingConfirmation();
        return { ok: false, queued, response };
      }
      const response = error.message || "The request failed. Refresh to check its result before trying again.";
      toast(response, "err");
      return { ok: false, response };
    } finally {
      buttons.forEach((button) => { button.disabled = false; });
      card?.removeAttribute("aria-busy");
      const content = card?.querySelector(".approval-card-content");
      if (content) content.style.transform = "translateX(0)";
    }
  }

  async function runCmd(command) {
    haptic();
    let res;
    try { res = await api("/api/cmd", { command }); }
    catch (error) { res = { ok: false, response: error.message || "Could not run the command. Try again." }; }
    latestState = null;
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
    if (!res) { showConnectionError("The server could not be reached. Check your connection and try again."); return true; }
    if (res.authorized === false) {
      stopUpdates();
      closeSheet(true);
      $("connection-error").classList.add("hidden");
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
    const nextUserId = auth.user?.id || null;
    if (activeUserId !== nextUserId) { stopUpdates(); activeUserId = nextUserId; }
    updateSyncBadge();
    if (paywallPoll) { clearInterval(paywallPoll); paywallPoll = null; }
    hideLoading();
    $("paywall").classList.add("hidden");
    $("connection-error").classList.add("hidden");
    $("app").classList.remove("hidden");
    const uName = auth.user && auth.user.name ? auth.user.name : "";
    if (uName) {
      const uIcon = '<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.5" style="display:inline-block;vertical-align:-1px;margin-right:3px;flex-shrink:0"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';
      $("whoami").innerHTML = `${uIcon}${esc(uName)}`;
    } else {
      $("whoami").innerHTML = "";
    }
    $("app-version").textContent = auth.version ? `v${auth.version}` : "";
    $("settings-backup").classList.toggle("hidden", auth.is_main !== true);
    canGiveFeedback = auth.can_feedback ?? auth.is_main === true;
    $("settings-feedback").classList.toggle("hidden", !canGiveFeedback);
    if (!wired) {
      wired = true;
      wire();
      const params = new URLSearchParams(location.search);
      showView(["overview", "chats", "persona", "approvals", "more"].includes(params.get("view")) ? params.get("view") : "overview");
    } else {
      loadView(currentView);
    }
    startUpdates();
  }

  function initSheetControls() {
    const sheet = $("sheet");
    if (!sheet) return;

    const expandBtn = $("sheet-expand");

    if (expandBtn) {
      expandBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleSheetExpanded();
      });
    }

    sheet.addEventListener("cancel", (event) => { event.preventDefault(); closeSheet(); });
    let pointerStart = null;
    sheet.addEventListener("pointerdown", (event) => { pointerStart = { x: event.clientX, y: event.clientY }; });
    sheet.addEventListener("pointercancel", () => { pointerStart = null; });
    sheet.addEventListener("click", (event) => {
      if (event.target !== sheet || !pointerStart) return;
      const rect = sheet.getBoundingClientRect();
      const outside = event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom;
      if (outside && Math.hypot(event.clientX - pointerStart.x, event.clientY - pointerStart.y) < 8) closeSheet();
      pointerStart = null;
    });
  }

  // ---------------------------------------------------------------- init

  function wire() {
    $("retry-view").addEventListener("click", () => loadView(currentView));
    $("settings-history").addEventListener("toggle", () => { if ($("settings-history").open) refreshHistory(); });
    $("settings-feedback").addEventListener("toggle", () => { if ($("settings-feedback").open) refreshFeedback(); });
    $("feedback-filter").addEventListener("change", refreshFeedback);
    $("feedback-refresh").addEventListener("click", refreshFeedback);
    $("history-status").addEventListener("change", () => refreshHistory());
    $("history-refresh").addEventListener("click", () => refreshHistory());
    $("history-more").addEventListener("click", () => refreshHistory(false));
    $("settings-export").addEventListener("click", exportSettings);
    $("settings-file").addEventListener("change", previewSettingsFile);
    document.addEventListener("input", (event) => {
      const field = event.target;
      if (!field.matches("input, textarea, select")) return;
      field.dataset.dirty = String(field.value !== (field.dataset.syncedValue ?? field.defaultValue));
      updateClosingConfirmation();
    });
    document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showView(t.dataset.view)));
    const sheetCloseBtn = $("sheet-close");
    if (sheetCloseBtn) sheetCloseBtn.addEventListener("click", closeSheet);

    initSheetControls();

    const toastEl = $("toast");
    if (toastEl) toastEl.addEventListener("click", hideToast);

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

    // Global click delegation for links, cards, help buttons & feeds
    document.addEventListener("click", (e) => {
      const ratingButton = e.target.closest("[data-feedback-message]");
      if (ratingButton) {
        e.preventDefault();
        e.stopPropagation();
        openFeedbackSheet(ratingButton.dataset.feedbackChat, ratingButton.dataset.feedbackMessage, ratingButton.dataset.feedbackRating);
        return;
      }
      const guideBtn = e.target.closest("#btn-all-behavior-help");
      if (guideBtn) {
        e.preventDefault();
        e.stopPropagation();
        haptic("light");
        openAllBehaviorGuideSheet();
        return;
      }

      const helpBtn = e.target.closest(".help-btn, [data-help]");
      if (helpBtn) {
        e.preventDefault();
        e.stopPropagation();
        haptic("light");
        const key = helpBtn.dataset.help;
        if (key) openHelpSheet(key);
        return;
      }

      const feedRow = e.target.closest(".feed-clickable");
      if (feedRow) {
        const url = feedRow.dataset.msgUrl;
        if (url) {
          haptic("light");
          if (window.Telegram?.WebApp?.openTelegramLink && url.startsWith("https://t.me/")) {
            try {
              window.Telegram.WebApp.openTelegramLink(url);
              return;
            } catch (_) {}
          }
          window.open(url, "_blank", "noopener,noreferrer");
          return;
        }
      }
      const link = e.target.closest(".chat-user-link");
      if (!link) return;
      const href = link.getAttribute("href");
      if (href && href.startsWith("https://t.me/") && window.Telegram && window.Telegram.WebApp && typeof window.Telegram.WebApp.openTelegramLink === "function") {
        e.preventDefault();
        window.Telegram.WebApp.openTelegramLink(href);
      }
    });

    // Keyboard navigation support for clickable feed items
    document.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        const feedRow = e.target.closest(".feed-clickable");
        if (feedRow && document.activeElement === feedRow) {
          e.preventDefault();
          feedRow.click();
        }
      }
    });

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
        openSheet("Approve pending batch",
          `<p>Send these <strong>${count} pending drafts</strong> in the background? ${approvalTotal > count ? `${approvalTotal - count} more drafts will remain for review.` : ""}</p>`,
          [
            { label: `Approve batch (${count})`, kind: "primary", onClick: () => runAction("approve_all") },
            { label: "Cancel" }
          ]);
      });
    }

    const btnRejectAll = $("btn-reject-all");
    if (btnRejectAll) {
      btnRejectAll.addEventListener("click", () => {
        const count = approvalTotal || document.querySelectorAll(".approval-card-wrap").length;
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
      const button = $("goto-activity");
      if (button.disabled) return;
      button.disabled = true;
      try {
        const acts = await api("/api/activity");
        if (acts.authorized === false) return maybePaywall(acts);
        if (acts.ok === false) throw new Error(acts.response);
        const rows = acts.activity || [];
        openSheet("Recent replies", rows.length ? rows.map(feedRowHtml).join("") : "<p>Nothing yet.</p>", [{ label: "Close" }]);
      } catch (error) { toast(error.message || "Could not load recent replies. Try again.", "err"); }
      finally { button.disabled = false; }
    });

    $("allow-btn").addEventListener("click", async () => {
      const v = $("allow-id").value.trim();
      if (!v) return toast("Enter a chat ID");
      const res = await runAction("allow", { chat_id: v });
      if (res && res.ok) {
        $("allow-id").value = "";
        $("allow-id").dataset.dirty = "false";
        updateClosingConfirmation();
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

    $("auth-add").addEventListener("click", async () => {
      const v = $("auth-id").value.trim();
      if (!v) return toast("Enter a Telegram user ID or @username");
      const res = await runAction("addauth", { user_id: v });
      if (res?.ok) {
        $("auth-id").value = "";
        $("auth-id").dataset.dirty = "false";
        updateClosingConfirmation();
      }
    });
    $("auth-id").addEventListener("keydown", (e) => { if (e.key === "Enter") $("auth-add").click(); });

    $("ai-model-save").addEventListener("click", () => {
      const v = $("ai-model").value.trim();
      if (!v) return toast("Enter a model name");
      runAction("model", { value: v });
    });
    $("ai-model").addEventListener("keydown", (e) => { if (e.key === "Enter") $("ai-model-save").click(); });

    // Modal popup: Select which fetched models to add to available models
    function showFetchModelsPopup(models) {
      if (!models || !models.length) {
        toast("Endpoint returned 0 models.");
        return;
      }
      const currentActive = ($("ai-model").value || "")
        .split(/[,;]/)
        .map((s) => s.trim().replace(/^models\//, ""))
        .filter(Boolean);

      const html = `
        <div class="model-popup-toolbar">
          <span class="faint">${models.length} model(s) retrieved from endpoint</span>
          <div class="model-popup-btns">
            <button type="button" class="btn small" id="popup-select-all">Select all</button>
            <button type="button" class="btn small" id="popup-deselect-all">Deselect all</button>
          </div>
        </div>
        <div class="model-popup-list" id="popup-models-list">
          ${models.map((m) => {
            const cleanM = String(m).replace(/^models\//, "").trim();
            const isChecked = cachedEndpointModels.length
              ? cachedEndpointModels.includes(cleanM)
              : (currentActive.includes(cleanM) || cleanM.includes("mercury-3") || cleanM.includes("flash"));
            return `<label class="model-check-row">
              <input type="checkbox" class="model-popup-cb" value="${esc(cleanM)}" ${isChecked ? "checked" : ""}>
              <span class="model-row-name num">${esc(cleanM)}</span>
            </label>`;
          }).join("")}
        </div>
      `;

      openSheet(
        "Available Models from Endpoint",
        html,
        [
          {
            label: "Confirm Selection",
            kind: "primary",
            onClick: async () => {
              const cbs = Array.from(document.querySelectorAll(".model-popup-cb:checked"));
              const selected = cbs.map((cb) => cb.value.trim()).filter(Boolean);
              if (!selected.length) {
                toast("Please select at least 1 model.");
                return false;
              }
              const result = await runAction("save_available_models", { models: selected });
              if (!result?.ok) return result;
              cachedEndpointModels = selected;
              $("models-fetched-count").textContent = `(${cachedEndpointModels.length})`;
              renderModelChips(cachedEndpointModels);
              toast(`Loaded ${selected.length} model(s) into available models`);
              return result;
            },
          },
          { label: "Cancel" },
        ]
      );

      const selAll = $("popup-select-all");
      const deselAll = $("popup-deselect-all");
      if (selAll) {
        selAll.addEventListener("click", () => {
          document.querySelectorAll(".model-popup-cb").forEach((cb) => (cb.checked = true));
        });
      }
      if (deselAll) {
        deselAll.addEventListener("click", () => {
          document.querySelectorAll(".model-popup-cb").forEach((cb) => (cb.checked = false));
        });
      }
    }

    // Modal popup: Health check results and manual rotation confirmation
    function showHealthResultsPopup(res) {
      if (!res || !res.results) return;
      const okCount = res.working_models ? res.working_models.length : 0;
      const totalCount = res.results.length;

      const replyHtml = res.reply
        ? `<p class="faint sm" style="margin-top:6px;word-break:break-word;">Live reply: &ldquo;${esc(res.reply)}&rdquo;</p>`
        : "";

      const bannerHtml = `
        <div class="health-summary-banner ${okCount > 0 ? "positive" : "negative"}">
          <span class="pill ${okCount > 0 ? "pill-positive" : "pill-negative"}">${okCount} Healthy / ${totalCount} Tested</span>
          ${replyHtml}
        </div>
      `;

      const listHtml = `
        <div class="health-model-list">
          ${res.results.map((r) => {
            const isOk = !!r.ok;
            return `<div class="health-model-row ${isOk ? "is-ok" : "is-fail"}">
              <div class="health-model-left">
                <input type="checkbox" class="health-result-cb" value="${esc(r.model)}" ${isOk ? "checked" : "disabled"}>
                <span class="health-model-name num">${esc(r.model)}</span>
              </div>
              <div class="health-model-right">
                <span class="pill ${isOk ? "pill-positive" : "pill-negative"}">${isOk ? "Healthy" : "Failed"}</span>
                <span class="faint sm detail" title="${esc(r.detail || "")}">${esc(r.detail || "")}</span>
              </div>
            </div>`;
          }).join("")}
        </div>
      `;

      const bodyHtml = bannerHtml + `<p class="field-hint" style="margin-bottom:8px;">Choose which healthy models to activate in your fallback rotation:</p>` + listHtml;

      openSheet(
        "Health Check Results",
        bodyHtml,
        [
          {
            label: "Apply Selected to Rotation",
            kind: "primary",
            onClick: async () => {
              const cbs = Array.from(document.querySelectorAll(".health-result-cb:checked"));
              const selected = cbs.map((cb) => cb.value.trim()).filter(Boolean);
              if (!selected.length) {
                toast("Select at least 1 healthy model.");
                return false;
              }
              const newChain = selected.join(",");
              const result = await runAction("model", { value: newChain });
              if (!result?.ok) return result;
              $("ai-model").value = newChain;
              renderModelChips(cachedEndpointModels.length ? cachedEndpointModels : selected, selected);
              toast(`Set active rotation (${selected.length} model(s)): ${newChain}`);
              return result;
            },
          },
          { label: "Close" },
        ]
      );
    }

    // Health check candidate models
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
      toast("Pinging models for live endpoint health...");

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

          if (res.auto_applied) {
            $("ai-model").value = res.active_model;
          }
          if (!cachedEndpointModels.length && res.results) {
            cachedEndpointModels = res.results.map((r) => r.model);
            $("models-fetched-count").textContent = `(${cachedEndpointModels.length})`;
          }
          renderModelChips(cachedEndpointModels.length ? cachedEndpointModels : res.working_models);

          const pills = (res.results || []).map((r) => {
            const cls = r.ok ? "test-pill ok" : "test-pill fail";
            const iconSvg = r.ok
              ? '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" style="display:inline-block;vertical-align:-1px;margin-right:4px;"><polyline points="3 8 7 12 13 4"/></svg>'
              : '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" style="display:inline-block;vertical-align:-1px;margin-right:4px;"><line x1="4" y1="4" x2="12" y2="12"/><line x1="12" y1="4" x2="4" y2="12"/></svg>';
            return `<span class="${cls}">${iconSvg}${esc(r.model)}: ${esc(r.detail)}</span>`;
          });
          summaryEl.innerHTML = pills.join("");

          showHealthResultsPopup(res);
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
          if (res && res.results) {
            showHealthResultsPopup(res);
          } else {
            const errMsg = (res && res.error) || "Health check found 0 working models";
            openSheet(
              "Health Check Failed",
              `<div class="health-summary-banner negative">
                <span class="pill pill-negative">0 Working Models</span>
                <p style="margin-top:8px;font-size:13px;line-height:1.45;word-break:break-word;">${esc(errMsg)}</p>
              </div>
              <p class="field-hint">Check your API key, endpoint URL, or quota, then try again.</p>`,
              [{ label: "Retry", kind: "primary", onClick: () => checkModelsHealth() }, { label: "Close" }]
            );
            toast(errMsg, "err");
          }
        }
      } catch (e) {
        badge.className = "pill pill-negative";
        badge.textContent = "Error";
        replyEl.textContent = "Health check request failed: " + e.message;
        openSheet(
          "Health Check Request Error",
          `<div class="health-summary-banner negative">
            <span class="pill pill-negative">Connection Error</span>
            <p style="margin-top:8px;font-size:13px;line-height:1.45;">${esc(e.message)}</p>
          </div>`,
          [{ label: "Close" }]
        );
        toast("Health check error: " + e.message, "err");
      } finally {
        btn.disabled = false;
        btn.textContent = "Check health";
      }
    }
    $("ai-check").addEventListener("click", checkModelsHealth);

    // Fetch models from endpoint with interactive selection popup
    async function fetchModels() {
      const btn = $("ai-fetch-models");
      const baseurl = $("ai-baseurl").value.trim();
      const apikey = $("ai-key").value.trim();
      btn.disabled = true;
      btn.textContent = "Fetching...";
      try {
        const res = await api("/api/fetch_models", { base_url: baseurl, api_key: apikey });
        if (!res || !res.ok) {
          const errDetail = (res && res.error) || "Failed to load models from endpoint";
          const errUrl = (res && res.url) || baseurl || "https://generativelanguage.googleapis.com/v1beta/models";
          openSheet(
            "Fetch Models Failed",
            `<div class="health-summary-banner negative">
              <span class="pill pill-negative">Endpoint Error</span>
              <p style="margin-top:8px;font-size:13px;line-height:1.45;word-break:break-word;">${esc(errDetail)}</p>
              <p class="faint sm" style="margin-top:6px;word-break:break-all;">Target URL: ${esc(errUrl)}</p>
            </div>
            <p class="field-hint">Verify your Base URL, API key, and network connectivity, then try again.</p>`,
            [
              { label: "Retry", kind: "primary", onClick: () => fetchModels() },
              { label: "Close" }
            ]
          );
          toast(errDetail, "err");
          return;
        }
        const models = res.models || [];
        if (!models.length) {
          openSheet(
            "Fetch Models",
            `<div class="health-summary-banner negative">
              <span class="pill pill-negative">0 Models Returned</span>
              <p style="margin-top:8px;font-size:13px;line-height:1.45;">The endpoint answered successfully but reported 0 generative text models.</p>
            </div>`,
            [{ label: "Close" }]
          );
          toast("Endpoint returned 0 models.", "info");
          return;
        }
        showFetchModelsPopup(models);
      } catch (e) {
        openSheet(
          "Fetch Models Error",
          `<div class="health-summary-banner negative">
            <span class="pill pill-negative">Network Error</span>
            <p style="margin-top:8px;font-size:13px;line-height:1.45;">${esc(e.message)}</p>
          </div>`,
          [{ label: "Close" }]
        );
        toast("Error fetching models: " + e.message, "err");
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

          if (res.auto_applied && res.active_model) {
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

          if (res.auto_applied && res.failed_models && res.failed_models.length > 0) {
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
        runAction("quiethours", { value: qh === "off" ? "off" : `on ${qh}` });
      });
    });

    // Behavior Simulation Clay Switches
    document.querySelectorAll("#behavior-toggles .clay-switch").forEach((sw) => {
      sw.addEventListener("click", () => {
        haptic("light");
        const cur = sw.dataset.state || "off";
        const next = cur === "on" ? "off" : "on";
        runAction(sw.dataset.action, { value: next });
      });
    });

    // Behavior Simulation Help Popup Buttons (?)
    document.querySelectorAll("#behavior-toggles .help-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        haptic("light");
        openHelpSheet(btn.dataset.help);
      });
    });

    // AI Tuning Segmented Controls
    document.querySelectorAll("#seg-thinking .seg, #seg-temp .seg, #seg-lang .seg, #seg-maxtokens .seg").forEach((b) => {
      b.addEventListener("click", () => {
        haptic("light");
        const param = b.dataset.param;
        const val = b.dataset.val;
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
              if (!kw || !rep) return { ok: false, response: "Enter both a keyword and a reply." };
              return runAction("addrule", { value: `${kw} => ${rep}` });
            }
          },
          { label: "Cancel" }
        ]);
      });
    }

    // System Maintenance & Safety Buttons
    const resetSafemodeBtn = $("btn-reset-safemode");
    if (resetSafemodeBtn) {
      resetSafemodeBtn.addEventListener("click", () => {
        runAction("safemode_reset", {});
      });
    }

    const emergToggleBtn = $("btn-emergency-toggle");
    if (emergToggleBtn) {
      emergToggleBtn.addEventListener("click", () => {
        const isStopped = emergToggleBtn.textContent.includes("Resume");
        if (isStopped) {
          runAction("resume", {});
        } else {
          openSheet("Emergency Kill-Switch", "<p>Immediately halt all automated replies, reactions, and background tasks?</p>", [
            { label: "Halt Engine Immediately", kind: "danger", onClick: () => runAction("stop", {}) },
            { label: "Cancel" }
          ]);
        }
      });
    }

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
        openSheet("Clear AI Memory", "<p>Reset cached conversation memory across all chats? Permanent notes, styles, and allowlists are strictly preserved.</p>", [
          { label: "Clear Memory", kind: "danger", onClick: () => runAction("clearcontext", { chat_id: "all" }) },
          { label: "Cancel" }
        ]);
      });
    }
  }

  function syncTelegramTheme() {
    if (!tg) return;
    const background = getComputedStyle(document.documentElement).getPropertyValue("--ground").trim();
    telegramCall("setHeaderColor", "6.1", background);
    telegramCall("setBackgroundColor", "6.1", background);
    telegramCall("setBottomBarColor", "7.10", background);
  }

  function telegramCall(method, version, ...args) {
    if (!tg || typeof tg[method] !== "function" || (version && !tg.isVersionAtLeast?.(version))) return false;
    try { tg[method](...args); return true; } catch { return false; }
  }

  function updateClosingConfirmation() {
    const dirty = document.querySelector('.canvas [data-dirty="true"], #sheet[open] [data-dirty="true"]');
    telegramCall(dirty || loadOfflineQueue().length ? "enableClosingConfirmation" : "disableClosingConfirmation", "6.2");
  }

  let viewportFrame = null;
  let viewportBaseline = window.innerHeight;
  function syncViewport() {
    if (viewportFrame !== null) return;
    viewportFrame = requestAnimationFrame(() => {
      viewportFrame = null;
      const root = document.documentElement;
      const viewport = window.visualViewport;
      const stable = tg?.viewportStableHeight || window.innerHeight;
      const visible = Math.min(viewport?.height || window.innerHeight, stable);
      const editing = document.activeElement?.matches("input, textarea, select");
      if (!editing) viewportBaseline = visible;
      root.style.setProperty("--app-height", `${stable}px`);
      root.style.setProperty("--visual-height", `${visible}px`);
      root.style.setProperty("--keyboard-inset", `${Math.max(0, window.innerHeight - visible - (viewport?.offsetTop || 0))}px`);
      root.classList.toggle("keyboard-open", Boolean(editing && viewportBaseline - visible > 100));
      for (const edge of ["top", "right", "bottom", "left"]) {
        root.style.setProperty(`--tg-safe-area-inset-${edge}`, `${tg?.safeAreaInset?.[edge] || 0}px`);
        root.style.setProperty(`--tg-content-safe-area-inset-${edge}`, `${tg?.contentSafeAreaInset?.[edge] || 0}px`);
      }
      $("fullscreen-button").classList.toggle("hidden", !tg?.isVersionAtLeast?.("8.0") || Boolean(tg.isFullscreen));
    });
  }

  function showConnectionError(message) {
    stopUpdates();
    hideLoading();
    $("connection-error-message").textContent = message;
    $("connection-error").classList.remove("hidden");
    $("paywall").classList.add("hidden");
    $("app").classList.add("hidden");
  }

  async function authenticate() {
    const retry = $("retry-connection");
    retry.disabled = true;
    try {
      const auth = await api("/api/auth");
      if (auth.ok === false) throw new Error(auth.response);
      if (auth.authorized !== true) return maybePaywall(auth);
      unlockApp(auth);
      flushOfflineQueue();
    } catch (error) { showConnectionError(error.message || "Check your connection and try again."); }
    finally { retry.disabled = false; }
  }

  async function init() {
    updateSyncBadge();
    $("retry-connection").addEventListener("click", authenticate);
    $("fullscreen-button").addEventListener("click", () => telegramCall("requestFullscreen", "8.0"));
    window.addEventListener("online", () => {
      if (!$("connection-error").classList.contains("hidden")) authenticate();
      else { flushOfflineQueue(); startUpdates(); }
    });
    window.addEventListener("resize", syncViewport);
    window.visualViewport?.addEventListener("resize", syncViewport);
    document.addEventListener("focusin", syncViewport);
    document.addEventListener("focusout", syncViewport);
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) stopUpdates();
      else if (!$("app").classList.contains("hidden")) { startUpdates(); loadView(currentView); }
    });
    if (tg) {
      telegramCall("ready");
      telegramCall("expand");
      telegramCall("disableVerticalSwipes", "7.7");
      telegramCall("requestFullscreen", "8.0");
      syncTelegramTheme();
      for (const event of ["viewportChanged", "safeAreaChanged", "contentSafeAreaChanged", "fullscreenChanged"]) tg.onEvent(event, syncViewport);
      tg.onEvent("fullscreenFailed", () => { telegramCall("expand"); syncViewport(); });
      tg.onEvent("themeChanged", syncTelegramTheme);
    }
    syncViewport();
    await authenticate();
  }

  function setConnectionStatus(status) {
    const beacon = $("live-beacon");
    if (!beacon) return;
    const wasLive = beacon.classList.contains("live");
    beacon.className = `live-beacon ${status}`;
    beacon.title = status === "live"
      ? "Real-time engine connected"
      : (status === "connecting" ? "Connecting to engine…" : "Engine offline");
    if (status === "live" && !wasLive) {
      flushOfflineQueue();
    }
  }

  function initEventSource() {
    if (DEMO) { setConnectionStatus("live"); return; }
    if (eventSource) return;
    if (!window.EventSource) {
      setConnectionStatus("offline");
      return;
    }
    try {
      const raw = initDataHeader();
      const q = raw ? `?initData=${encodeURIComponent(raw)}` : "";
      const es = new EventSource(`/api/events${q}`);
      eventSource = es;
      let lastRevision;
      let lastHistoryRevision;
      es.onopen = () => {
        setConnectionStatus("live");
      };
      es.addEventListener("state", (e) => {
        setConnectionStatus("live");
        try {
          const s = JSON.parse(e.data);
          latestState = s;
          if (s && s.state) renderState(s);
          if (s && currentView === "more" && !$("sheet").open) renderMoreControls(s);
          if (s && s.history_revision !== lastHistoryRevision) {
            lastHistoryRevision = s.history_revision;
            if (currentView === "more" && $("settings-history").open) refreshHistory();
          }
          if (s && s.revision !== lastRevision) {
            lastRevision = s.revision;
            if (currentView !== "overview") loadView(currentView);
          }
        } catch (_) {}
      });
      es.onerror = () => {
        setConnectionStatus("connecting");
        api("/api/auth").then((auth) => { if (auth && auth.authorized === false) maybePaywall(auth); }).catch(() => {});
        // SSE reconnects automatically by browser spec
      };
    } catch (_) {
      setConnectionStatus("offline");
    }
  }

  let eventSource = null;
  let refreshTimer = null;
  function startUpdates() {
    if (document.hidden || $("app").classList.contains("hidden")) return;
    initEventSource();
    if (refreshTimer !== null) return;
    refreshTimer = setInterval(() => {
      if (!$("sheet").open && (!eventSource || eventSource.readyState !== 1 || currentView === "overview")) loadView(currentView);
    }, 15000);
  }

  function stopUpdates() {
    eventSource?.close();
    eventSource = null;
    latestState = null;
    clearInterval(refreshTimer);
    refreshTimer = null;
  }

  // Register Service Worker for Instant PWA Offline Loading
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("./sw.js").catch(() => {});
    });
  }

  init().catch((error) => showConnectionError(error.message));
})();
