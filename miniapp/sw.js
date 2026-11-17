/* Cache public assets only. API responses and Telegram credentials stay on the network. */
// Refresh cached controls for this change without changing the application version.
const CACHE_NAME = "teleautomator-v3.0.10" + "-thread-context";
const ASSETS_TO_CACHE = [
  "./",
  "./index.html",
  "./style.css?v=3.0.10",
  "./app.js?v=3.0.10",
  "./logo.svg"
];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key.startsWith("teleautomator-") && key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  if (req.mode !== "navigate" && !["/app.js", "/style.css", "/logo.svg"].includes(url.pathname)) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE_NAME).catch(() => null);
    const cached = await cache?.match(req.mode === "navigate" ? "./index.html" : req).catch(() => null);
    if (cached && req.mode !== "navigate") return cached;
    const network = fetch(req).then(async (response) => {
      if (response.ok && cache) await cache.put(req.mode === "navigate" ? "./index.html" : req, response.clone()).catch(() => {});
      return response;
    });
    if (!cached) return network;
    event.waitUntil(network.catch(() => {}));
    return Promise.race([
      network.then(response => response.ok ? response : cached).catch(() => cached),
      new Promise(resolve => setTimeout(() => resolve(cached), 2500)),
    ]);
  })());
});
