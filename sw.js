/* DailyPulse service worker
 * Keeps the existing /online/ PWA cache/offline behaviour, caches the news
 * feeds, and handles Web Push notifications sent by the DailyPulse Cloudflare Worker.
 */
const CACHE_NAME = "dailypulse-app-v7-notification-history";

// Notification history: every push received on this device is saved here so the
// bell menu on the page can list it. The page reads the same IndexedDB database.
const NOTIF_DB = "dailypulse-notifications";
const NOTIF_STORE = "history";
const NOTIF_MAX = 50;

function openNotifDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(NOTIF_DB, 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(NOTIF_STORE)) {
        db.createObjectStore(NOTIF_STORE, { keyPath: "id", autoIncrement: true }).createIndex("time", "time");
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function saveNotification(entry) {
  try {
    const db = await openNotifDb();
    await new Promise((resolve, reject) => {
      const tx = db.transaction(NOTIF_STORE, "readwrite");
      const store = tx.objectStore(NOTIF_STORE);
      store.add(entry);
      const keys = store.getAllKeys();
      keys.onsuccess = () => {
        const extra = keys.result.length - NOTIF_MAX;   // keep only the newest NOTIF_MAX
        for (let i = 0; i < extra; i++) store.delete(keys.result[i]);
      };
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
    db.close();
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    windows.forEach(client => client.postMessage({ type: "dp-notification-saved" }));
  } catch (error) {
    console.warn("DailyPulse: could not save notification history", error);
  }
}
const FEED_CACHE = "dailypulse-feeds-v1"; // not prefixed "dailypulse-app-", so activate() won't delete it
const APP_SHELL = [
  "/online/",
  "/online/index.html",
  "/online/manifest.webmanifest",
  "/online/favicon.svg",
  "/online/icons/dailypulse-192.png"
];
const FEED_PATH = /\/(news-preview\.json|feeds\/[^/]+\.xml)$/;
const HOME_URL = new URL("./", self.registration.scope).href;

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    await Promise.all(APP_SHELL.map(async path => {
      try { await cache.add(path); }
      catch (error) { console.warn("DailyPulse: app-shell cache skipped", path, error); }
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const cacheNames = await caches.keys();
    await Promise.all(cacheNames
      .filter(name => name.startsWith("dailypulse-app-") && name !== CACHE_NAME)
      .map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});

// News feeds: stale-while-revalidate.
// - Normal loads (first paint, switching category) are answered instantly from
//   the cache while a background request updates it.
// - Refresh button / timer (fetch with cache:"reload" or "no-store") go to the
//   network first and fall back to the cache if offline.
// - The ?t=... query is ignored, so cache entries are not duplicated per request.
async function handleFeed(event) {
  const request = event.request;
  const url = new URL(request.url);
  const cleanUrl = url.origin + url.pathname;
  const cache = await caches.open(FEED_CACHE);
  const cached = await cache.match(cleanUrl);
  const forceFresh = request.cache === "reload" || request.cache === "no-store";

  // "no-cache" = revalidate with the server (cheap 304 when nothing changed),
  // so GitHub Pages' own short HTTP cache can't serve stale feed data.
  const refresh = fetch(cleanUrl, { cache: "no-cache" }).then(response => {
    if (response && response.ok) cache.put(cleanUrl, response.clone());
    return response;
  });

  if (cached && !forceFresh) {
    event.waitUntil(refresh.catch(() => {}));
    return cached;
  }

  try {
    return await refresh;
  } catch (error) {
    return cached || Response.error();
  }
}

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;

  const requestUrl = new URL(request.url);
  if (requestUrl.origin !== self.location.origin) return;

  // News feed files
  if (FEED_PATH.test(requestUrl.pathname)) {
    event.respondWith(handleFeed(event));
    return;
  }

  // Preserve the existing offline fallback for page navigations.
  if (request.mode !== "navigate") return;

  event.respondWith((async () => {
    try {
      const response = await fetch(new Request(request, { cache: "no-store" }));
      if (response && response.ok) {
        const cache = await caches.open(CACHE_NAME);
        await cache.put("/online/index.html", response.clone());
      }
      return response;
    } catch (error) {
      const cachedPage = await caches.match("/online/index.html");
      if (cachedPage) return cachedPage;
      return new Response("DailyPulse is offline. Please reconnect and try again.", {
        status: 503,
        headers: { "Content-Type": "text/plain; charset=utf-8" }
      });
    }
  })());
});

// Display the daily Top Story sent by the Cloudflare Worker.
self.addEventListener("push", event => {
  event.waitUntil((async () => {
    let data = {};
    if (event.data) {
      try {
        data = event.data.json();
      } catch (_) {
        data = { body: event.data.text() };
      }
    }

    const title = data.title || "DailyPulse — Top Story";
    const body = data.body || data.message || "Your daily top story is ready. Tap to read it on DailyPulse.";
    let targetUrl = HOME_URL;
    try {
      const candidate = new URL(data.url || HOME_URL, HOME_URL);
      if (candidate.protocol === "https:" || candidate.origin === self.location.origin) {
        targetUrl = candidate.href;
      }
    } catch (_) {
      targetUrl = HOME_URL;
    }

    const options = {
      body: String(body).slice(0, 240),
      icon: "/online/icons/dailypulse-192.png",
      badge: "/online/icons/dailypulse-192.png",
      tag: data.tag || "dailypulse-daily-top-story",
      renotify: false,
      timestamp: Date.now(),
      data: { url: targetUrl }
    };

    // Optional media fields are supported if the Worker adds them later.
    if (data.image) options.image = data.image;
    if (data.actions && Array.isArray(data.actions)) options.actions = data.actions.slice(0, 2);

    await self.registration.showNotification(title, options);
    await saveNotification({
      title,
      body: options.body,
      url: targetUrl,
      image: data.image || "",
      time: Date.now()
    });
  })());
});

// Open the story when the visitor taps the notification.
self.addEventListener("notificationclick", event => {
  event.notification.close();
  event.waitUntil((async () => {
    let targetUrl = HOME_URL;
    try {
      const candidate = new URL(event.notification.data && event.notification.data.url || HOME_URL, HOME_URL);
      if (candidate.protocol === "https:" || candidate.origin === self.location.origin) {
        targetUrl = candidate.href;
      }
    } catch (_) {
      targetUrl = HOME_URL;
    }

    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of windows) {
      if (client.url.startsWith("https://dailypusle.github.io/")) {
        if ("navigate" in client) await client.navigate(targetUrl);
        return client.focus();
      }
    }
    return self.clients.openWindow(targetUrl);
  })());
});

// Close a notification if the user explicitly dismisses it; no background work needed.
self.addEventListener("notificationclose", () => {});
