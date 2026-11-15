const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const path = require("node:path");

const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    textContent: "", innerHTML: "", value: "", style: {}, dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    querySelectorAll() { return []; }, addEventListener() {}, setAttribute() {}, closest() { return null; },
  });
  return elements.get(id);
}
let queue = [];
let duringRequest = () => {};
const context = {
  console, URLSearchParams, AbortController, setTimeout() {}, clearTimeout() {}, navigator: {},
  location: { search: "" }, window: { addEventListener() {} },
  document: { activeElement: null, getElementById: element, querySelectorAll() { return []; } },
  localStorage: {
    getItem() { return JSON.stringify(queue); },
    setItem(key, value) { queue = JSON.parse(value); },
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
  /\n  init\(\)\.catch\([^\n]+\);\n/, "\n  globalThis.testAPI = { api, syncField, refreshMore, renderMoreControls, flushOfflineQueue };\n"
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

  queue = [1, 2, 3].map(id => ({ id, action: "style", params: { value: "casual" } }));
  await context.testAPI.flushOfflineQueue();
  assert.deepEqual(queue.map(item => item.id), [1, 2, 3]);
  duringRequest = () => { queue.push({ id: 4, action: "pause", params: {} }); };
  await context.testAPI.flushOfflineQueue();
  assert.deepEqual(queue.map(item => item.id), [1, 2, 3, 4]);

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
    caches: { async open() { return cache; }, async keys() { return ["teleautomator-v3.0.4", "teleautomator-v3.0.5", "another-app"]; }, async delete(name) { deleted.push(name); } },
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
  handlers.fetch({ request: { method: "GET", mode: "cors", url: origin + "/app.js?v=3.0.5" }, respondWith(promise) { asset = promise; } });
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
