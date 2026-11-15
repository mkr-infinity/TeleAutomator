const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const path = require("node:path");

const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    textContent: "", innerHTML: "", value: "", style: {}, dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    querySelectorAll() { return []; }, addEventListener() {}, setAttribute() {},
  });
  return elements.get(id);
}
let queue = [];
let duringRequest = () => {};
const context = {
  console, URLSearchParams, setTimeout() {}, clearTimeout() {}, navigator: {},
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
  /\n  init\(\);\n/, "\n  globalThis.testAPI = { refreshMore, renderMoreControls, flushOfflineQueue };\n"
);
vm.runInContext(source, context, { filename: file });

(async () => {
  await context.testAPI.refreshMore();
  assert.match(element("ai-model-chips").innerHTML, /first/);
  assert.match(element("ai-model-chips").innerHTML, /second/);
  assert.equal(element("btn-emergency-toggle").textContent, "Resume Engine");
  context.testAPI.renderMoreControls({ emergency: false, state: "active", auto_reactions: false });
  assert.equal(element("btn-emergency-toggle").textContent, "Halt Engine");
  assert.equal(element("sw-reaction").dataset.state, "off");

  queue = [1, 2, 3].map(id => ({ id, action: "style", params: { value: "casual" } }));
  await context.testAPI.flushOfflineQueue();
  assert.deepEqual(queue.map(item => item.id), [1, 2, 3]);
  duringRequest = () => { queue.push({ id: 4, action: "pause", params: {} }); };
  await context.testAPI.flushOfflineQueue();
  assert.deepEqual(queue.map(item => item.id), [1, 2, 3, 4]);
  console.log("Mini App model rendering, live controls, and offline queue workflows passed");
})().catch(error => { console.error(error); process.exitCode = 1; });
