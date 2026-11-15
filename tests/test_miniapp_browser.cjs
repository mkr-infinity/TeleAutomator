/* Real Chromium checks. All Telegram/AI responses are local fixtures. */
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const http = require("node:http");
const path = require("node:path");
const vm = require("node:vm");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const root = path.join(__dirname, "../miniapp");

function telegramMock({ version }) {
  const handlers = {};
  window.telegramCalls = [];
  window.sources = [];
  Object.defineProperty(navigator, "clipboard", { value: { async writeText() {} }, configurable: true });
  const app = {
    version, platform: "android", initData: "local-test-fixture", isFullscreen: false,
    viewportStableHeight: innerHeight, safeAreaInset: { top: 24, bottom: 24 }, contentSafeAreaInset: { top: 52, bottom: 0 },
    isVersionAtLeast: value => Number(version) >= Number(value),
    onEvent: (event, callback) => (handlers[event] ||= []).push(callback),
    BackButton: { show() {}, hide() {}, onClick(callback) { window.telegramBack = callback; }, offClick() {} },
    HapticFeedback: { impactOccurred() {}, notificationOccurred() {} },
  };
  for (const method of ["ready", "expand", "disableVerticalSwipes", "setHeaderColor", "setBackgroundColor", "setBottomBarColor", "enableClosingConfirmation", "disableClosingConfirmation"]) {
    app[method] = () => window.telegramCalls.push(method);
  }
  app.requestFullscreen = () => { window.telegramCalls.push("requestFullscreen"); app.isFullscreen = true; };
  window.Telegram = { WebApp: app };
  window.addEventListener("resize", () => {
    if (!window.lockStableHeight) app.viewportStableHeight = innerHeight;
    (handlers.viewportChanged || []).forEach(callback => callback({ isStateStable: true }));
  });
  window.EventSource = class {
    constructor() { this.readyState = 1; this.handlers = {}; window.sources.push(this); queueMicrotask(() => this.onopen?.()); }
    addEventListener(event, callback) { this.handlers[event] = callback; }
    emit(state) { this.handlers.state?.({ data: JSON.stringify(state) }); }
    close() { this.readyState = 2; }
  };
}

(async () => {
  const projectVersion = (await fs.readFile(path.join(root, "../app/__init__.py"), "utf8")).match(/__version__\s*=\s*"([^"]+)"/)[1];
  const source = await fs.readFile(path.join(root, "app.js"), "utf8");
  const fixture = source.match(/const DEMO_DATA = (\{[\s\S]*?\n  \});/);
  assert(fixture, "dashboard fixtures must be available");
  const data = JSON.parse(JSON.stringify(vm.runInNewContext(`(${fixture[1]})`)));
  data.state.ai_model = "first,second";
  data.state.available_models = ["first", "second"];
  data.state.rules = [{ keyword: "help", reply: "Send a message" }];
  data.chats.forEach(chat => { chat.cooldown_default_min = 3; chat.cooldown_default_max = 8; });
  data.activity.forEach((row, index) => { row.is_automated = index < 3; });
  const requests = [];
  let rejectAction = null;
  let authFailure = false;
  let historyFailure = false;
  let importFailure = false;
  let isMainUser = true;
  let feedbackFailure = false;
  let activityFailure = false;
  const history = Array.from({ length: 45 }, (_, index) => ({ id: 45 - index, source: "automation", action: "reply", status: (45 - index) % 10 === 0 ? "failed" : "sent", detail: index ? "Message delivered" : "<script>window.historyXSS = true</script>", created_at: "2026-11-15 12:00:00", chat_id: -222 }));
  const preferences = { format: "teleautomator-preferences", version: 1, settings: { reply_style: "formal", owner_name: "Owner" }, chats: [{ id: -222, notes: "Test notes" }], keyword_rules: [] };
  const server = http.createServer(async (req, res) => {
    const pathname = new URL(req.url, "http://local").pathname;
    if (process.env.BROWSER_TRACE) console.log("server", pathname);
    if (pathname.startsWith("/api/")) {
      let raw = "";
      for await (const part of req) raw += part;
      const body = raw ? JSON.parse(raw) : {};
      requests.push({ path: pathname, body });
      let result = {};
      if (pathname === "/api/auth") {
        if (authFailure) { res.statusCode = 503; result = { ok: false, response: "The engine is starting. Try again." }; }
        else result = { authorized: true, is_main: isMainUser, can_feedback: isMainUser, version: projectVersion, user: { id: 555000111, name: "Test owner" } };
      } else if (pathname === "/api/state") result = data.state;
      else if (pathname === "/api/history") {
        if (historyFailure) { historyFailure = false; res.statusCode = 503; result = { ok: false, response: "History unavailable. Retry." }; }
        else {
          const query = new URL(req.url, "http://local").searchParams;
          const rows = history.filter(row => (!query.get("status") || row.status === query.get("status")) && (!query.get("before") || row.id < Number(query.get("before")))).slice(0, 40);
          result = { ok: true, events: rows, next_before: rows.length === 40 ? rows.at(-1).id : null, diagnostics: data.state };
        }
      }
      else if (pathname === "/api/settings/export") result = { ok: true, download_url: "/api/settings/download?token=local-fixture", file_name: "teleautomator-preferences.json" };
      else if (pathname === "/api/settings/download") { res.setHeader("Content-Disposition", 'attachment; filename="teleautomator-preferences.json"'); result = preferences; }
      else if (pathname === "/api/settings/preview") {
        result = body.backup?.version === 1 ? { ok: true, summary: { settings: 2, chats: 1, rules: 0 }, setting_keys: ["owner_name", "reply_style"], chat_ids: [-222] } : { ok: false, response: "Choose a version 1 backup" };
      }
      else if (pathname === "/api/settings/import") {
        if (importFailure) { importFailure = false; result = { ok: false, response: "Import failed. Please retry." }; }
        else result = { ok: true, response: "Preferences restored" };
      }
      else if (pathname === "/api/chats") result = { chats: data.chats };
      else if (pathname === "/api/access") result = { users: data.access };
      else if (pathname === "/api/pending") result = { pending: data.pending };
      else if (pathname === "/api/activity") {
        if (activityFailure) { activityFailure = false; res.statusCode = 503; result = { ok: false, response: "Activity unavailable. Retry." }; }
        else result = { activity: data.activity };
      }
      else if (pathname === "/api/feedback") {
        if (feedbackFailure) { feedbackFailure = false; res.statusCode = 503; result = { ok: false, response: "Feedback unavailable. Retry." }; }
        else {
          const rows = data.activity.filter(row => row.feedback).map(row => ({ ...row, rating: row.feedback, reply_text: row.text, chat_title: row.chat, updated_at: row.ts }));
          const rating = new URL(req.url, "http://local").searchParams.get("rating");
          result = { ok: true, feedback: rows.filter(row => !rating || row.rating === rating), counts: Object.fromEntries(["helpful", "unnecessary", "off_topic", "style"].map(key => [key, rows.filter(row => row.rating === key).length])) };
        }
      }
      else if (pathname === "/api/commands") result = { commands: data.commands };
      else if (pathname === "/api/fetch_models") result = { ok: true, models: ["first", "second", "third"] };
      else if (pathname === "/api/test_model") result = { ok: true, reply: "hello", active_model: "first,second", model_used: "first", working_models: ["first", "second"], failed_models: ["third"], results: [{ model: "first", ok: true, detail: "Working" }, { model: "second", ok: true, detail: "Working" }, { model: "third", ok: false, detail: "Unavailable" }] };
      else if (pathname === "/api/cmd") result = { ok: true, response: "Status: active\nMode: restricted_auto" };
      else if (pathname === "/api/action") {
        await new Promise(resolve => setTimeout(resolve, 40));
        if (rejectAction === body.action) { rejectAction = null; result = { ok: false, response: "Save failed. Please retry." }; }
        else {
          result = { ok: true, response: "Saved" };
          if (body.action === "reaction") data.state.auto_reactions = body.params.value === "on";
          if (body.action === "temp") data.state.temperature = body.params.value;
          if (body.action === "quiethours") {
            const [enabled, start, end] = body.params.value.split(" ");
            data.state.quiet_hours_enabled = enabled !== "off";
            if (start && end) { data.state.quiet_hours_start = start; data.state.quiet_hours_end = end; }
          }
          if (body.action === "feedback") {
            const row = data.activity.find(row => String(row.chat_id) === String(body.params.chat_id) && String(row.message_id) === String(body.params.id));
            assert(row, "feedback must reference a displayed reply");
            row.feedback = body.params.value === "clear" ? "" : body.params.value;
          }
          if (body.action === "chat_cooldown") {
            const chat = data.chats.find(chat => String(chat.id) === String(body.params.chat_id));
            chat.cooldown_min = body.params.reset ? null : body.params.min;
            chat.cooldown_max = body.params.reset ? null : body.params.max;
          }
          if (body.action === "approve" || body.action === "reject") data.pending = data.pending.filter(draft => String(draft.id) !== String(body.params.id));
        }
      }
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify(result));
      return;
    }
    const files = { "/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css", "/sw.js": "sw.js", "/logo.svg": "logo.svg" };
    const file = files[pathname];
    if (!file) { res.writeHead(404).end(); return; }
    res.setHeader("Content-Type", ({ ".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".svg": "image/svg+xml" })[path.extname(file)]);
    res.end(await fs.readFile(path.join(root, file)));
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  let browser;
  let popups = 0;
  const errors = [];
  const base = `http://127.0.0.1:${server.address().port}`;
  const { expect } = require(path.join(path.dirname(require.resolve(process.env.PLAYWRIGHT_MODULE || "playwright")), "test"));
  async function makePage(version = "8.0", width = 390, height = 844, serviceWorkers = "block") {
    const context = await browser.newContext({ viewport: { width, height }, isMobile: true, hasTouch: true, reducedMotion: "reduce", serviceWorkers });
    await context.route(/^https:\/\//, route => route.fulfill({
      contentType: "application/javascript",
      body: route.request().url().includes("telegram-web-app.js") ? `(${telegramMock.toString()})(${JSON.stringify({ version })});` : "/* external requests disabled */",
    }));
    const page = await context.newPage();
    page.on("pageerror", error => errors.push(error.message));
    if (process.env.BROWSER_TRACE) {
      page.on("request", request => console.log("request", new URL(request.url()).pathname));
      page.on("requestfailed", request => console.log("failed", new URL(request.url()).pathname, request.failure()?.errorText));
      page.on("pageerror", error => console.log("pageerror", error.message));
    }
    await page.goto(base, { waitUntil: "domcontentloaded", timeout: 45000 });
    return page;
  }
  async function navigate(page, view, group) {
    await page.locator(`.tab[data-view="${view}"]`).click();
    if (group) await page.locator(`#settings-${group}`).evaluate(element => { element.open = true; });
    await checkControls(page);
  }
  async function checkControls(page) {
    const problems = await page.evaluate(() => {
      const problems = [], ids = new Set();
      for (const element of document.querySelectorAll("[id]")) {
        if (ids.has(element.id)) problems.push(`Duplicate ID: ${element.id}`);
        ids.add(element.id);
      }
      for (const label of document.querySelectorAll("label[for]")) {
        if (!document.getElementById(label.htmlFor)) problems.push(`Missing label target: ${label.htmlFor}`);
      }
      const parents = new Map();
      for (const button of document.querySelectorAll("button")) {
        if (!button.getClientRects().length) continue;
        const label = button.getAttribute("aria-label") || button.textContent.trim() || button.title;
        if (!label) problems.push("Unnamed visible button");
        const labels = parents.get(button.parentElement) || new Set();
        if (labels.has(label)) problems.push(`Duplicate sibling button: ${label}`);
        labels.add(label); parents.set(button.parentElement, labels);
      }
      return problems;
    });
    assert.deepEqual(problems, []);
  }
  async function checkSheet(page, title) {
    const sheet = page.locator("#sheet");
    await expect(sheet).toBeVisible();
    await checkControls(page);
    if (title) await expect(page.locator("#sheet-title")).toContainText(new RegExp(title, "i"));
    assert(await sheet.evaluate(element => element.open && element.matches(":modal")));
    const bounds = await sheet.boundingBox();
    const size = page.viewportSize();
    assert(bounds.x >= -1 && bounds.x + bounds.width <= size.width + 1, "popup must fit horizontally");
    assert(bounds.y >= 75 && bounds.y + bounds.height <= size.height + 1, "popup must respect Android safe areas");
    const close = await page.locator("#sheet-close").boundingBox();
    assert(close.width >= 48 && close.height >= 48);
    await page.locator(".sheet-head").evaluate(element => {
      for (const [type, y] of [["touchstart", 200], ["touchmove", 265], ["touchend", 265]]) {
        element.dispatchEvent(new TouchEvent(type, { bubbles: true, touches: type === "touchend" ? [] : [new Touch({ identifier: 1, target: element, clientX: 100, clientY: y })] }));
      }
    });
    assert(await sheet.evaluate(element => element.open), "small swipes must not dismiss popups");
    popups++;
  }
  async function close(page) { await page.locator("#sheet-close").click(); await expect(page.locator("#sheet")).not.toBeVisible(); }
  try {
    try { browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }); }
    catch (error) {
      if (error.message.includes("Executable doesn't exist")) { console.log("Browser checks need Playwright Chromium installed"); process.exitCode = 77; return; }
      throw error;
    }
    const page = await makePage();
    await expect(page.locator("#app")).toBeVisible();
    await checkControls(page);
    activityFailure = true;
    await page.locator("#goto-activity").click();
    await expect(page.locator("#toast-msg")).toContainText("Activity unavailable");
    await expect(page.locator("#sheet")).not.toBeVisible();
    await expect(page.locator("#goto-activity")).toBeEnabled();
    const calls = await page.evaluate(() => window.telegramCalls);
    assert(calls.includes("requestFullscreen") && calls.includes("disableVerticalSwipes"), JSON.stringify({ calls, sdk: await page.evaluate(() => ({ version: window.Telegram?.WebApp?.version, supported: window.Telegram?.WebApp?.isVersionAtLeast?.("8.0") })) }));
    for (const [selector, title] of [["#act-mode", "mode"], ["#act-stop", "Stop"], ["#goto-activity", "Recent"]]) {
      await page.locator(selector).click(); await checkSheet(page, title); await close(page);
    }
    const stopsBefore = requests.filter(request => request.body.action === "stop").length;
    await page.locator("#act-stop").click();
    await page.context().setOffline(true);
    await page.locator("#sheet-actions .danger").click();
    await expect(page.locator("#sheet-error")).toContainText("not queued");
    assert(await page.evaluate(() => !Object.keys(localStorage).some(key => (localStorage.getItem(key) || "").includes('"action":"stop"'))));
    await close(page);
    await page.context().setOffline(false);
    assert.equal(requests.filter(request => request.body.action === "stop").length, stopsBefore, "offline stop must not replay later");
    await page.locator("#goto-activity").click();
    await expect(page.locator("#sheet .feedback-button")).toHaveCount(3);
    await page.locator("#sheet .feedback-button").first().click();
    await checkSheet(page, "Rate this reply");
    rejectAction = "feedback";
    await page.locator("#sheet-actions button", { hasText: "Off-topic" }).click();
    await expect(page.locator("#sheet-error")).toContainText("Save failed");
    await page.locator("#sheet-actions button", { hasText: "Off-topic" }).click();
    await expect(page.locator("#sheet")).not.toBeVisible();
    await expect(page.locator("#ov-activity .feedback-button").first()).toHaveText("Off-topic");
    await navigate(page, "more", "feedback");
    await expect(page.locator("#pipeline-status")).toContainText("no extra model call");
    await expect(page.locator("#feedback-list .history-row")).toHaveCount(1);
    assert((await page.locator("#feedback-list .feedback-button").boundingBox()).height >= 48, "feedback buttons need mobile touch targets");
    await expect(page.locator("#feedback-counts")).toContainText("Off-topic: 1");
    await page.locator("#feedback-filter").selectOption("helpful");
    await expect(page.locator("#feedback-list .history-row")).toHaveCount(0);
    await page.locator("#feedback-filter").selectOption("off_topic");
    await expect(page.locator("#feedback-list .history-row")).toHaveCount(1);
    feedbackFailure = true;
    await page.locator("#feedback-refresh").click();
    await expect(page.locator("#feedback-error")).toContainText("Retry");
    await page.locator("#feedback-refresh").click();
    await expect(page.locator("#feedback-error")).not.toBeVisible();
    if (process.env.TELEAUTOMATOR_UI_ARTIFACTS) {
      await fs.mkdir(process.env.TELEAUTOMATOR_UI_ARTIFACTS, { recursive: true });
      await page.screenshot({ path: path.join(process.env.TELEAUTOMATOR_UI_ARTIFACTS, "reply-feedback.png") });
    }
    await page.locator("#feedback-list .feedback-button").click();
    await checkSheet(page, "Rate this reply");
    await page.locator("#sheet-actions button", { hasText: "Helpful" }).click();
    await expect(page.locator("#sheet")).not.toBeVisible();
    await page.locator("#feedback-filter").selectOption("helpful");
    await expect(page.locator("#feedback-list .history-row")).toHaveCount(1);
    await page.locator("#feedback-list .feedback-button").click();
    await checkSheet(page, "Rate this reply");
    await page.locator("#sheet-actions button", { hasText: "Clear rating" }).click();
    await expect(page.locator("#sheet")).not.toBeVisible();
    await expect(page.locator("#feedback-list .history-row")).toHaveCount(0);
    for (const [action, title] of [[null, "Rohan"], ["prompt", "Prompt"], ["context", "Context"], ["chatty", "Chatty"], ["cooldown", "Cooldown"], ["remove", "Remove"]]) {
      await navigate(page, "chats");
      await page.evaluate(() => {
        window.sheetChanges = 0;
        window.sheetObserver?.disconnect();
        window.sheetObserver = new MutationObserver(records => { window.sheetChanges += records.filter(record => record.type === "childList").length; });
        window.sheetObserver.observe(document.getElementById("sheet-body"), { childList: true });
      });
      await page.locator(".chat-capsule-card").first().click();
      assert.equal(await page.evaluate(() => window.sheetChanges), 1, "one chat-card tap must open the popup once");
      if (action) await page.locator(`.clay-action-btn[data-action="${action}"]`).click();
      await checkSheet(page, title);
      if (!action) {
        await page.locator(".copy-id-btn").click();
        await expect(page.locator("#toast")).toBeVisible();
        await expect(page.locator("#toast-msg")).toContainText("copied");
        assert(await page.locator("#toast").evaluate(element => element.matches(":popover-open")));
        await page.locator("#toast-close").click();
        await page.evaluate(() => {
          window.originalClipboardWrite = navigator.clipboard.writeText;
          navigator.clipboard.writeText = () => Promise.reject(new Error("Clipboard denied"));
        });
        await page.locator(".copy-id-btn").click();
        await expect(page.locator("#toast-msg")).toContainText("ID:");
        await page.evaluate(() => { navigator.clipboard.writeText = window.originalClipboardWrite; });
        await page.locator("#toast-close").click();
        assert(await page.locator("#sheet").evaluate(element => element.open));
      }
      await close(page);
    }
    await page.evaluate(() => { window.sheetChanges = 0; });
    await page.locator(".chat-capsule-card").nth(2).press("Enter");
    await checkSheet(page, "Delhi Tech");
    assert.equal(await page.evaluate(() => window.sheetChanges), 1, "keyboard activation must open the popup once");
    await expect(page.locator("#sheet-body")).toContainText("Global Default (3s – 8s)");
    await close(page);
    await page.locator(".chat-capsule-card").first().click();
    await page.locator('.clay-action-btn[data-action="cooldown"]').click();
    await page.locator("#cd-min-input").fill("8");
    await page.locator("#cd-min-input").press("Enter");
    await expect(page.locator("#cd-max-input")).toBeFocused();
    await page.locator("#cd-max-input").fill("2");
    await page.locator("#sheet-actions .primary").click();
    await expect(page.locator("#sheet-error")).toContainText("Maximum cooldown");
    await expect(page.locator("#cd-min-input")).toHaveValue("8");
    await page.locator("#cd-min-input").fill("3");
    await page.locator("#cd-max-input").fill("7");
    rejectAction = "chat_cooldown";
    await page.locator("#sheet-actions .primary").click();
    await expect(page.locator("#sheet-error")).toContainText("Save failed");
    const before = requests.filter(request => request.body.action === "chat_cooldown").length;
    assert(await page.locator("#sheet-actions .primary").evaluate(button => { button.click(); button.click(); return document.getElementById("sheet-close").disabled; }));
    await expect(page.locator("#sheet")).not.toBeVisible();
    assert.equal(requests.filter(request => request.body.action === "chat_cooldown").length, before + 1);
    await page.locator("#allow-id").fill("@new_chat");
    rejectAction = "allow";
    await page.locator("#allow-btn").click();
    await expect(page.locator("#toast-msg")).toContainText("Save failed");
    await expect(page.locator("#allow-id")).toHaveValue("@new_chat");
    await page.locator("#allow-btn").click();
    await expect(page.locator("#allow-id")).toHaveValue("");
    await navigate(page, "more", "ai");
    await expect(page.locator("#ai-model")).toHaveValue("first,second");
    await page.locator("#ai-baseurl").fill("https://unsaved.test/v1");
    await page.locator("#ai-baseurl").blur();
    await page.evaluate(() => {
      window.savedChip = document.querySelector(".model-chip");
      const state = { mode: "restricted_auto", state: "active", ai_model: "first,second", ai_base_url: "https://remote.test/v1", available_models: ["first", "second"], revision: "new-revision" };
      window.sources.at(-1).emit(state);
    });
    await expect(page.locator("#ai-baseurl")).toHaveValue("https://unsaved.test/v1");
    assert(await page.evaluate(() => window.savedChip.isConnected), "unchanged live model chips should keep their DOM nodes");
    await page.locator("#ai-fetch-models").click();
    await checkSheet(page, "Available Models");
    await page.locator("#popup-deselect-all").click();
    await expect(page.locator(".model-popup-cb:checked")).toHaveCount(0);
    await page.locator("#sheet-actions .primary").click();
    await expect(page.locator("#sheet-error")).toBeVisible();
    await page.locator("#popup-select-all").click();
    await expect(page.locator(".model-popup-cb:checked")).toHaveCount(3);
    const selectionsBefore = requests.filter(request => request.body.action === "save_available_models").length;
    await page.locator("#sheet-actions .primary").click();
    await expect(page.locator("#sheet")).not.toBeVisible();
    assert.equal(requests.filter(request => request.body.action === "save_available_models").length, selectionsBefore + 1);
    await page.locator("#ai-check").click();
    await checkSheet(page, "Health Check Results");
    await expect(page.locator('.health-result-cb[value="third"]')).toBeDisabled();
    await close(page);
    await navigate(page, "more", "behavior");
    await page.context().setOffline(true);
    await page.locator("#sw-reaction").click();
    await expect(page.locator("#toast-msg")).toContainText("not queued");
    await expect(page.locator("#sw-reaction")).toHaveAttribute("aria-checked", "true");
    await page.locator('[data-qh="off"]').click();
    await expect(page.locator('[data-qh="02:00 08:00"]')).toHaveClass(/active/);
    await expect(page.locator("#qh-status-pill")).toHaveText("Active");
    await page.context().setOffline(false);
    const reactionBefore = requests.filter(request => request.body.action === "reaction").length;
    await page.locator("#sw-reaction").click();
    await expect(page.locator("#sw-reaction")).toHaveAttribute("aria-checked", "false");
    await navigate(page, "more", "preferences");
    await page.context().setOffline(true);
    await page.locator('#seg-temp [data-val="0.2"]').click();
    await expect(page.locator("#toast-msg")).toContainText("queued");
    await expect(page.locator('#seg-temp [data-val="0.7"]')).toHaveClass(/active/);
    await expect(page.locator('#seg-temp [data-val="0.2"]')).not.toHaveClass(/active/);
    await page.context().setOffline(false);
    await expect(page.locator('#seg-temp [data-val="0.2"]')).toHaveClass(/active/);
    await navigate(page, "more", "behavior");
    assert.equal(requests.filter(request => request.body.action === "reaction").length, reactionBefore + 1);
    rejectAction = "reaction";
    await page.locator("#sw-reaction").click();
    await expect(page.locator("#toast-msg")).toContainText("Save failed");
    await expect(page.locator("#sw-reaction")).toHaveAttribute("aria-checked", "false");
    for (const help of ["reaction", "ownreact", "multibubble", "typo", "debounce", "followup", "mentiononly"]) {
      await page.locator(`[data-help="${help}"]`).click(); await checkSheet(page, ""); await close(page);
    }
    await page.locator("#btn-all-behavior-help").click(); await checkSheet(page, "Guide"); await close(page);
    await page.locator("#btn-quick-sleep").click(); await checkSheet(page, "Sleep"); await close(page);
    await navigate(page, "more", "rules");
    await page.locator("#btn-add-rule").click(); await checkSheet(page, "Keyword");
    await page.locator("#rule-kw-input").fill("test");
    page.once("dialog", dialog => dialog.dismiss());
    await page.locator("#sheet-close").click();
    await expect(page.locator("#rule-kw-input")).toHaveValue("test");
    await page.evaluate(() => { window.lockStableHeight = true; });
    await page.locator("#rule-reply-input").focus();
    await page.setViewportSize({ width: 390, height: 460 });
    await checkSheet(page, "Keyword");
    page.once("dialog", dialog => dialog.accept()); await close(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => { window.lockStableHeight = false; });
    await navigate(page, "more", "safety");
    for (const [selector, title] of [["#btn-backup-db", "Backup"], ["#btn-clear-context", "Memory"], ["#btn-emergency-toggle", "Kill-Switch"], ["[data-unauth]", "Remove owner"]]) {
      await page.locator(selector).first().click(); await checkSheet(page, title); await close(page);
    }
    await navigate(page, "more", "history");
    await expect(page.locator(".history-row")).toHaveCount(40);
    await expect(page.locator("#history-list")).toContainText("<script>");
    assert(!(await page.evaluate(() => window.historyXSS)), "history text must be escaped");
    await page.locator("#history-more").click();
    await expect(page.locator(".history-row")).toHaveCount(45);
    await page.locator("#history-status").selectOption("failed");
    await expect(page.locator(".history-row")).toHaveCount(4);
    await expect(page.locator("#history-more")).not.toBeVisible();
    historyFailure = true;
    await page.locator("#history-refresh").click();
    await expect(page.locator("#history-error")).toContainText("Retry");
    await page.locator("#history-refresh").click();
    await expect(page.locator("#history-error")).not.toBeVisible();
    await page.locator("#history-status").selectOption("skipped");
    await expect(page.locator(".history-row")).toHaveCount(0);
    history.unshift({ ...history[0], id: 46, status: "skipped", detail: "Conversation already ended" });
    await page.evaluate(state => window.sources.at(-1).emit({ ...state, history_revision: 46 }), data.state);
    await expect(page.locator("#history-list")).toContainText("Conversation already ended");
    await navigate(page, "more", "backup");
    const downloadEvent = page.waitForEvent("download");
    await page.locator("#settings-export").click();
    const download = await downloadEvent;
    assert.equal(download.suggestedFilename(), "teleautomator-preferences.json");
    assert.equal(JSON.parse(await fs.readFile(await download.path(), "utf8")).format, preferences.format);
    await page.locator("#settings-file").setInputFiles({ name: "bad.json", mimeType: "application/json", buffer: Buffer.from("not json") });
    await expect(page.locator("#toast-msg")).toContainText("not valid JSON");
    await page.locator("#settings-file").setInputFiles({ name: "old.json", mimeType: "application/json", buffer: Buffer.from('{"version":0}') });
    await expect(page.locator("#toast-msg")).toContainText("version 1");
    const importsBefore = requests.filter(request => request.path === "/api/settings/import").length;
    await page.locator("#settings-file").setInputFiles({ name: "settings.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(preferences)) });
    await checkSheet(page, "Review preference import");
    await expect(page.locator("#sheet-body")).toContainText("2 settings");
    assert.equal(requests.filter(request => request.path === "/api/settings/import").length, importsBefore, "preview must not apply anything");
    importFailure = true;
    await page.locator("#sheet-actions .primary").click();
    await expect(page.locator("#sheet-error")).toContainText("Import failed");
    await page.locator("#sheet-actions .primary").click();
    await expect(page.locator("#sheet")).not.toBeVisible();
    await expect(page.locator("#toast-msg")).toContainText("Preferences restored");
    await navigate(page, "approvals");
    for (const [selector, title] of [["#btn-approve-all", "Approve"], ["#btn-reject-all", "Reject"]]) {
      await page.locator(selector).click(); await checkSheet(page, title); await close(page);
    }
    for (const [width, height] of [[320, 568], [412, 915], [800, 360], [840, 900], [1280, 800]]) {
      await page.setViewportSize({ width, height });
      for (const view of ["overview", "chats", "persona", "approvals", "more"]) {
        await navigate(page, view);
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${view} layout must fit ${width}px`);
      }
      for (const group of ["ai", "test", "behavior", "preferences", "rules", "safety", "feedback", "history", "backup"]) {
        await navigate(page, "more", group);
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${group} layout must fit ${width}px`);
      }
      await navigate(page, "chats");
      await page.locator(".chat-capsule-card").first().click(); await checkSheet(page, "Rohan"); await close(page);
    }
    if (process.env.TELEAUTOMATOR_UI_ARTIFACTS) {
      await fs.mkdir(process.env.TELEAUTOMATOR_UI_ARTIFACTS, { recursive: true });
      await page.setViewportSize({ width: 390, height: 844 });
      await navigate(page, "more");
      await page.evaluate(() => { document.querySelectorAll(".settings-group").forEach(group => { group.open = false; }); window.scrollTo(0, 0); });
      await page.screenshot({ path: path.join(process.env.TELEAUTOMATOR_UI_ARTIFACTS, "settings.png") });
      await navigate(page, "chats");
      await page.locator(".chat-capsule-card").first().click();
      await page.screenshot({ path: path.join(process.env.TELEAUTOMATOR_UI_ARTIFACTS, "chat-popup.png") });
    }
    const old = await makePage("7.6");
    await expect(old.locator("#app")).toBeVisible();
    assert(!(await old.evaluate(() => window.telegramCalls)).includes("requestFullscreen"));
    isMainUser = false;
    const limited = await makePage();
    await navigate(limited, "more");
    await expect(limited.locator("#settings-backup")).not.toBeVisible();
    await expect(limited.locator("#settings-feedback")).not.toBeVisible();
    isMainUser = true;
    authFailure = true;
    const retry = await makePage();
    await expect(retry.locator("#connection-error")).toBeVisible();
    await expect(retry.locator("#paywall")).not.toBeVisible();
    authFailure = false;
    await retry.locator("#retry-connection").click();
    await expect(retry.locator("#app")).toBeVisible();
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ popupChecks: popups, viewportSizes: 6, tabs: 5, settingsGroups: 9, duplicateControls: "IDs, labels, sibling buttons, single popup per tap", fullscreen: "supported and older clients", formRecovery: "passed", duplicateSaves: "blocked", offlineControls: "confirmed state preserved until server saves", liveUpdates: "preserve drafts and DOM", history: "filter, pages, retry, safe rendering, live updates", preferences: "download, preview, failed import recovery, owner visibility", replyFeedback: "rate, failed save recovery, filter, edit, clear, permissions, local stages", connectionRetry: "passed", pageErrors: errors.length }));
  } finally {
    await browser?.close();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
