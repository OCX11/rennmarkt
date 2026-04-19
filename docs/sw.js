// PTOX11 — Service Worker v2
// Handles: caching, push notifications, notification click → open listing URL

const CACHE_NAME = 'ptox11-v2';
const ASSETS = [
  '/PTOX11/',
  '/PTOX11/index.html',
];

// ── Install ────────────────────────────────────────────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

// ── Activate ───────────────────────────────────────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// ── Fetch (network-first) ──────────────────────────────────────────────────────
self.addEventListener('fetch', event => {
  event.respondWith(
    fetch(event.request)
      .then(response => {
        if (response.ok && event.request.url.includes('/PTOX11/')) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});

// ── Push received ──────────────────────────────────────────────────────────────
self.addEventListener('push', event => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { title: 'PTOX11', body: event.data ? event.data.text() : '' };
  }

  const title   = data.title  || 'PTOX11';
  const body    = data.body   || '';
  const url     = data.url    || 'https://ocx11.github.io/PTOX11/';
  const icon    = data.icon   || '/PTOX11/icons/icon-192.png';
  const badge   = data.badge  || '/PTOX11/icons/icon-192.png';

  const options = {
    body,
    icon,
    badge,
    data: { url },
    requireInteraction: false,
    vibrate: [200, 100, 200],
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

// ── Notification click → open listing URL ─────────────────────────────────────
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url)
    ? event.notification.data.url
    : 'https://ocx11.github.io/PTOX11/';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clientList => {
      // If a PTOX11 tab is already open, focus it then navigate
      for (const client of clientList) {
        if (client.url.includes('ocx11.github.io') && 'focus' in client) {
          client.focus();
          client.navigate(url);
          return;
        }
      }
      // Otherwise open a new tab
      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    })
  );
});
