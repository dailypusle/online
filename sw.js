/* DailyPulse service worker
 * Handles PWA caching, offline access and Web Push notifications.
 */

const CACHE_NAME = "dailypulse-app-v4";

const APP_SHELL = [
  "/online/",
  "/online/index.html",
  "/online/manifest.webmanifest",
  "/online/favicon.svg",
  "/online/icons/dailypulse-192.png"
];

const HOME_URL = "https://dailypusle.github.io/online/";

// INSTALL
self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);

    await Promise.all(APP_SHELL.map(async path => {
      try {
        await cache.add(path);
      } catch (error) {
        console.warn("DailyPulse: cache skipped", path, error);
      }
    }));

    await self.skipWaiting();
  })());
});

// ACTIVATE
self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const cacheNames = await caches.keys();

    await Promise.all(
      cacheNames
        .filter(name =>
          name.startsWith("dailypulse-app-") &&
          name !== CACHE_NAME
        )
        .map(name => caches.delete(name))
    );

    await self.clients.claim();
  })());
});

// OFFLINE SUPPORT
self.addEventListener("fetch", event => {
  const request = event.request;

  if (request.method !== "GET") return;

  const requestUrl = new URL(request.url);

  if (
    requestUrl.origin !== self.location.origin ||
    request.mode !== "navigate"
  ) return;

  event.respondWith((async () => {
    try {
      const response = await fetch(request);

      if (response && response.ok) {
        const cache = await caches.open(CACHE_NAME);
        await cache.put("/online/index.html", response.clone());
      }

      return response;

    } catch (error) {
      const cachedPage = await caches.match("/online/index.html");

      if (cachedPage) return cachedPage;

      return new Response(
        "DailyPulse is offline. Please reconnect and try again.",
        {
          status: 503,
          headers: {
            "Content-Type": "text/plain; charset=utf-8"
          }
        }
      );
    }
  })());
});

// RECEIVE PUSH NOTIFICATIONS
self.addEventListener("push", event => {
  event.waitUntil((async () => {

    let data = {};

    if (event.data) {
      try {
        data = event.data.json();
      } catch (error) {
        data = {
          body: event.data.text()
        };
      }
    }

    const title = data.title || "DailyPulse — Top Story";

    const body =
      data.body ||
      data.message ||
      "Your daily top story is ready. Tap to read it on DailyPulse.";

    let targetUrl = HOME_URL;

    try {
      const candidate = new URL(
        data.url || HOME_URL,
        HOME_URL
      );

      if (
        candidate.protocol === "https:" ||
        candidate.origin === self.location.origin
      ) {
        targetUrl = candidate.href;
      }

    } catch (error) {
      targetUrl = HOME_URL;
    }

    const options = {
      body: String(body).slice(0, 240),

      icon: "/online/icons/dailypulse-192.png",

      badge: "/online/icons/dailypulse-192.png",

      tag: data.tag || "dailypulse-daily-top-story",

      renotify: false,

      timestamp: Date.now(),

      data: {
        url: targetUrl
      }
    };

    if (data.image) {
      options.image = data.image;
    }

    if (Array.isArray(data.actions)) {
      options.actions = data.actions.slice(0, 2);
    }

    await self.registration.showNotification(
      title,
      options
    );

  })());
});

// OPEN DAILY PULSE WHEN NOTIFICATION IS TAPPED
self.addEventListener("notificationclick", event => {

  event.notification.close();

  event.waitUntil((async () => {

    let targetUrl = HOME_URL;

    try {
      const candidate = new URL(
        event.notification.data?.url || HOME_URL,
        HOME_URL
      );

      if (
        candidate.protocol === "https:" ||
        candidate.origin === self.location.origin
      ) {
        targetUrl = candidate.href;
      }

    } catch (error) {
      targetUrl = HOME_URL;
    }

    const windows = await self.clients.matchAll({
      type: "window",
      includeUncontrolled: true
    });

    for (const client of windows) {

      if (client.url.startsWith("https://dailypusle.github.io/")) {

        if ("navigate" in client) {
          await client.navigate(targetUrl);
        }

        return client.focus();
      }
    }

    return self.clients.openWindow(targetUrl);

  })());
});

// HANDLE NOTIFICATION DISMISSAL
self.addEventListener("notificationclose", () => {
  // No additional action required.
});
