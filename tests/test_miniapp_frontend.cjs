const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const path = require("node:path");
const projectVersion = fs.readFileSync(path.join(__dirname, "../app/__init__.py"), "utf8").match(/__version__\s*=\s*"([^"]+)"/)[1];

const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    textContent: "", innerHTML: "", value: "", style: {}, dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    querySelectorAll() { return []; }, addEventListener() {}, setAttribute() {}, closest() { return null; },
  });
  return elements.get(id);
}
const storage = new Map();
const queueKey = userId => `teleautomator_offline_queue_v2:${userId}`;
const queued = (userId = 111) => JSON.parse(storage.get(queueKey(userId)) || "[]");
const item = (id, action = "style", params = { value: "casual" }) => ({ id, action, params, time: new Date().toISOString() });
let duringRequest = () => {};
const context = {
  console, URLSearchParams, AbortController, setTimeout() {}, clearTimeout() {}, navigator: {},
  location: { search: "" }, window: { addEventListener() {} },
  document: { activeElement: null, getElementById: element, querySelectorAll() { return []; } },
  localStorage: {
    getItem(key) { return storage.get(key) || null; },
    setItem(key, value) { storage.set(key, value); },
    removeItem(key) { storage.delete(key); },
  },
  fetch: async (url) => {
    if (url === "/api/action") { duringRequest(); throw new Error("offline"); }
    const body = url === "/api/access" ? { users: [] } : {
      mode: "restricted_auto", state: "stopped", emergency: true,
      available_models: ["first", "second"], ai_model: "first,second",
    };
    return { status: 200, json: async () => body };
  },
};
vm.createContext(context);
const file = path.join(__dirname, "../miniapp/app.js");
const source = fs.readFileSync(file, "utf8").replace(
  /\n  init\(\)\.catch\([^\n]+\);\n/, "\n  globalThis.testAPI = { api, syncField, refreshMore, renderMoreControls, flushOfflineQueue, enqueueAction, loadOfflineQueue, setUser(id) { activeUserId = id; } };\n"
);
assert.match(source, /globalThis.testAPI/);
vm.runInContext(source, context, { filename: file });

(async () => {
  await context.testAPI.refreshMore();
  assert.match(element("ai-model-chips").innerHTML, /first/);
  assert.match(element("ai-model-chips").innerHTML, /second/);
  assert.equal(element("btn-emergency-toggle").textContent, "Resume Engine");
  context.testAPI.renderMoreControls({ emergency: false, state: "active", auto_reactions: false });
  assert.equal(element("btn-emergency-toggle").textContent, "Halt Engine");
  assert.equal(element("sw-reaction").dataset.state, "off");
  assert.match(element("pipeline-status").innerHTML, /Context jobs running<\/span><strong>0<[\s\S]*Last memory update<\/span><strong>None yet</, "older servers without stage fields still render defaults");
  const stages = last_context => {
    context.testAPI.renderMoreControls({ pipeline: { context: "Files", writer: "Model", humanizer: "Local", context_jobs: 2, last_context } });
    return element("pipeline-status").innerHTML;
  };
  assert.match(stages({ status: "success", detail: "", created_at: "2026-11-15 12:00:00" }), /Context jobs running<\/span><strong>2<[\s\S]*Nov 15, 5:30 PM IST · Success/, "SQLite UTC times render in IST");
  assert.match(stages({ status: "failed", detail: "Summary update failed", created_at: "2026-11-15 12:00:00" }), /5:30 PM IST · Failed/);
  assert.match(stages({ status: "<img src=x onerror=alert(1)>", created_at: "<b>" }), /&lt;b&gt; · &lt;img src=x onerror=alert\(1\)&gt;/, "stage values must be escaped");

  const field = element("ai-baseurl");
  context.testAPI.syncField("ai-baseurl", "https://original.test");
  field.value = "https://unsaved.test";
  context.testAPI.syncField("ai-baseurl", "https://remote-change.test");
  assert.equal(field.value, "https://unsaved.test");
  context.testAPI.syncField("ai-baseurl", "https://unsaved.test");
  context.testAPI.syncField("ai-baseurl", "https://saved-change.test");
  assert.equal(field.value, "https://saved-change.test");

  let reads = 0;
  const fetch = context.fetch;
  context.fetch = async (...args) => { reads++; return fetch(...args); };
  await Promise.all([context.testAPI.api("/api/state"), context.testAPI.api("/api/state")]);
  assert.equal(reads, 1, "overlapping reads should share one request");

  assert.equal(context.testAPI.enqueueAction("style", { value: "casual" }), false, "unauthenticated actions must not persist");
  context.testAPI.setUser(111);
  storage.set("teleautomator_offline_queue_v1", JSON.stringify([item(0, "apikey", { value: "fixture-secret" })]));
  context.testAPI.loadOfflineQueue();
  assert(!storage.has("teleautomator_offline_queue_v1"), "retire the old shared queue, including any credentials");
  for (const action of ["apikey", "setai", "prompt", "setcontext", "approve", "approve_all", "stop", "resume", "mode"]) {
    assert.equal(context.testAPI.enqueueAction(action, { value: "fixture-secret" }), false, `${action} must require an online request`);
  }
  storage.set(queueKey(111), '{}');
  assert.equal(context.testAPI.loadOfflineQueue().length, 0, "malformed queues must not break startup");
  storage.set(queueKey(111), JSON.stringify([{ ...item(0), time: new Date(Date.now() - 7200000).toISOString() }]));
  assert.equal(context.testAPI.loadOfflineQueue().length, 0, "expired changes must not replay");
  storage.set(queueKey(111), JSON.stringify([1, 2, 3].map(id => item(id))));
  context.testAPI.setUser(222);
  assert.equal(context.testAPI.loadOfflineQueue().length, 0, "one account must not inherit another's changes");
  context.testAPI.setUser(111);
  await context.testAPI.flushOfflineQueue();
  assert.deepEqual(queued().map(item => item.id), [1, 2, 3]);
  duringRequest = () => { storage.set(queueKey(111), JSON.stringify([...queued(), item(4, "lang", { value: "english" })])); };
  await context.testAPI.flushOfflineQueue();
  assert.deepEqual(queued().map(item => item.id), [1, 2, 3, 4]);
  storage.delete(queueKey(111));
  for (let index = 0; index < 75; index++) context.testAPI.enqueueAction("chatstyle", { chat_id: index + 1, value: "formal" });
  assert.equal(queued().length, 50, "offline preferences must remain bounded");

  const handlers = {};
  const cached = new Map();
  const deleted = [];
  const origin = "https://local.test";
  const key = request => new URL(typeof request === "string" ? request : request.url, origin + "/").href;
  const cache = {
    async addAll(assets) { for (const asset of assets) cached.set(key(asset), new Response("cached asset")); },
    async put(request, response) { cached.set(key(request), response.clone()); },
    async match(request) { return cached.get(key(request))?.clone(); },
  };
  let networkReads = 0;
  const swContext = vm.createContext({
    URL, Response, setTimeout(callback) { callback(); },
    self: { location: { origin }, addEventListener(event, handler) { handlers[event] = handler; }, skipWaiting() {}, clients: { async claim() {} } },
    caches: { async open() { return cache; }, async keys() { return ["teleautomator-v3.0.4", `teleautomator-v${projectVersion}`, "another-app"]; }, async delete(name) { deleted.push(name); } },
    async fetch() { networkReads++; return new Response("temporarily unavailable", { status: 503 }); },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../miniapp/sw.js"), "utf8"), swContext);
  let install;
  handlers.install({ waitUntil(promise) { install = promise; } });
  await install;
  let activation;
  handlers.activate({ waitUntil(promise) { activation = promise; } });
  await activation;
  assert.deepEqual(deleted, ["teleautomator-v3.0.4"], "other apps' caches must survive updates");
  for (const url of [origin + "/api/state", origin + "/api/events?initData=private", "https://telegram.org/js/telegram-web-app.js"]) {
    handlers.fetch({ request: { method: "GET", url }, respondWith() { assert.fail("private APIs and external requests must bypass this cache"); } });
  }
  let asset;
  handlers.fetch({ request: { method: "GET", mode: "cors", url: origin + `/app.js?v=${projectVersion}` }, respondWith(promise) { asset = promise; } });
  assert.equal(await (await asset).text(), "cached asset");
  assert.equal(networkReads, 0, "versioned assets should load immediately from cache");
  let navigation;
  const background = [];
  handlers.fetch({ request: { method: "GET", mode: "navigate", url: origin + "/" }, respondWith(promise) { navigation = promise; }, waitUntil(promise) { background.push(promise); } });
  assert.equal(await (await navigation).text(), "cached asset");
  await Promise.all(background);
  assert(![...cached.keys()].some(url => url.includes("/api/")));
  console.log("Mini App rendering, draft preservation, request coalescing, offline queue, and public asset caching passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
