/* DailyPulse service worker
 * Keeps the existing /online/ PWA cache/offline behaviour and handles
 * Web Push notifications sent by the DailyPulse Cloudflare Worker.
 */
const CACHE_NAME = "dailypulse-app-v6-notification-image";
const APP_SHELL = [
  "/online/",
  "/online/index.html",
  "/online/manifest.webmanifest",
  "/online/favicon.svg",
  "/online/icons/dailypulse-192.png"
];
const HOME_URL = new URL("./", self.registration.scope).href;
const ICON_URL = "/online/icons/dailypulse-192.png";

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

// Preserve the existing offline fallback for page navigations.
self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;

  const requestUrl = new URL(request.url);
  if (requestUrl.origin !== self.location.origin || request.mode !== "navigate") return;

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

function httpsUrl(value) {
  try {
    const u = new URL(value);
    return u.protocol === "https:" ? u.href : "";
  } catch (_) {
    return "";
  }
}

const normalize = value => String(value || "").toLowerCase().replace(/\s+/g, " ").trim();

// When the push message has no picture, look up the story's photo in the site's
// news-preview.json (matched by link, then by headline). Returns "" if none is found.
async function findStoryImage(data, title) {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 4000);
    const response = await fetch(new URL("news-preview.json?t=" + Date.now(), self.registration.scope).href, {
      cache: "no-store",
      signal: controller.signal
    });
    clearTimeout(timer);
    if (!response.ok) return "";

    const feed = await response.json();
    const records = Object.values(feed || {}).filter(Array.isArray).flat();
    const link = String(data.url || data.link || "").split("#")[0];
    const wantedTitle = normalize(data.storyTitle || data.title || title);

    const match =
      (link && records.find(r => r && String(r.link || "").split("#")[0] === link)) ||
      (wantedTitle && records.find(r => r && normalize(r.title) === wantedTitle)) ||
      (wantedTitle && records.find(r => r && normalize(r.title) && wantedTitle.includes(normalize(r.title))));

    return match ? httpsUrl(match.image) : "";
  } catch (_) {
    return "";
  }
}

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
      icon: ICON_URL,
      badge: ICON_URL,
      tag: data.tag || "dailypulse-daily-top-story",
      renotify: false,
      timestamp: Date.now(),
      data: { url: targetUrl }
    };

    // Large picture: use the one in the push, otherwise find the story's photo on the site.
    const image = httpsUrl(data.image || data.imageUrl || data.picture || "") ||
      await findStoryImage(data, title);
    if (image) options.image = image;
    if (data.actions && Array.isArray(data.actions)) options.actions = data.actions.slice(0, 2);

    await self.registration.showNotification(title, options);
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
