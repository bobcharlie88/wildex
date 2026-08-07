const CACHE_NAME = "wildex-v1";
const CORE_ASSETS = [
  "/",
  "/static/home.html",
  "/static/index.html",
  "/static/card_renderer.css",
  "/static/card_renderer.js",
  "/static/manifest.webmanifest",
  "/static/icons/wildex-192.png",
  "/static/icons/wildex-512.png",
  "/static/icons/wildex.svg"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
