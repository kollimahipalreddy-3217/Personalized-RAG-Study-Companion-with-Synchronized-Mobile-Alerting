// ============================================================
//  sw.js — Service Worker for StudyEdge AI
//  Enables OFFLINE mobile alarms & BACKGROUND push notifications
//  Works even when laptop is offline, phone screen is locked/off.
// ============================================================

const CACHE_NAME = 'studyedge-v6';
const STATIC_ASSETS = [
  '/mobile',
  '/static/fonts.css',
  '/static/bootstrap-icons.css',
  '/static/style.css',
  '/static/script.js',
  '/static/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png'
];

// ── Install: cache static assets for offline capability ──
self.addEventListener('install', event => {
  console.log('[SW] Installing Service Worker v4 with offline mobile support...');
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(STATIC_ASSETS).catch(err => {
        console.warn('[SW Cache Warn]', err);
      });
    })
  );
  self.skipWaiting();
});

// ── Activate: clean old caches and claim clients ──
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// ── Fetch: Network first, fallback to cache for offline usage ──
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Bypass service worker for dynamic API requests (except when offline)
  if (url.pathname.startsWith('/session') ||
      url.pathname.startsWith('/generate-test') ||
      url.pathname.startsWith('/test-job') ||
      url.pathname.startsWith('/ask') ||
      url.pathname.startsWith('/socket.io')) {
    return;
  }

  // For /mobile and static assets, try network first, fall back to offline cache
  event.respondWith(
    fetch(event.request)
      .then(response => {
        if (response && response.status === 200 && event.request.method === 'GET') {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});

// ── In-Worker Local Alarms Map ──
const localAlarms = new Map();

// ── Message Listener: Handles alarms and schedule synchronization ──
self.addEventListener('message', event => {
  if (!event.data) return;

  // Single alarm schedule
  if (event.data.type === 'SCHEDULE_LOCAL_ALARM') {
    const { id, title, body, delayMs, tag } = event.data;
    console.log(`[SW] Scheduling local alarm in ${Math.round(delayMs / 1000)}s: "${title}"`);

    if (localAlarms.has(id)) {
      clearTimeout(localAlarms.get(id));
    }

    const timerId = setTimeout(() => {
      self.registration.showNotification(title, {
        body: body,
        icon: '/static/icon-192.png',
        badge: '/static/icon-192.png',
        vibrate: [500, 250, 500, 250, 500],
        tag: tag || `studyedge-alarm-${id}`,
        renotify: true,
        requireInteraction: true,
        actions: [
          { action: 'open', title: '▶ Open App' },
          { action: 'dismiss', title: 'Dismiss' }
        ],
        data: { url: '/mobile' }
      });
      localAlarms.delete(id);
    }, Math.max(delayMs, 100));

    localAlarms.set(id, timerId);
  }

  // Bulk schedule sync: stores and schedules ALL upcoming study plans on the phone
  else if (event.data.type === 'SYNC_ALL_SCHEDULES') {
    const plans = event.data.plans || [];
    console.log(`[SW] Synchronizing ${plans.length} study plans for phone lock-screen alerting...`);
    const now = Date.now();

    for (const plan of plans) {
      if (plan.status === 'completed' || plan.status === 'missed') continue;

      const startTime = new Date(plan.planned_start).getTime();
      const delayMs = startTime - now;

      // Only schedule alarms that are in the future (within next 48 hours)
      if (delayMs > 0 && delayMs < 48 * 60 * 60 * 1000) {
        const planKey = `plan_${plan.id}`;
        if (localAlarms.has(planKey)) {
          clearTimeout(localAlarms.get(planKey));
        }

        const timerId = setTimeout(() => {
          self.registration.showNotification(` Study Session: ${plan.topic}`, {
            body: `Your scheduled session "${plan.topic}" starts now! Tap to begin.`,
            icon: '/static/icon-192.png',
            badge: '/static/icon-192.png',
            vibrate: [500, 250, 500, 250, 500],
            tag: `studyedge-plan-${plan.id}`,
            renotify: true,
            requireInteraction: true,
            actions: [
              { action: 'open', title: '▶ Start Session' },
              { action: 'dismiss', title: 'Dismiss' }
            ],
            data: { url: '/mobile' }
          });
          localAlarms.delete(planKey);
        }, delayMs);

        localAlarms.set(planKey, timerId);
      }
    }
  }

  // Cancel alarm
  else if (event.data.type === 'CANCEL_LOCAL_ALARM') {
    const { id } = event.data;
    if (localAlarms.has(id)) {
      clearTimeout(localAlarms.get(id));
      localAlarms.delete(id);
      console.log(`[SW] Cancelled local alarm: ${id}`);
    }
  }

  // Cancel ALL alarms (when reminders are paused / DND)
  else if (event.data.type === 'CANCEL_ALL_LOCAL_ALARMS') {
    console.log(`[SW] Clearing all ${localAlarms.size} local alarms due to reminders paused / DND.`);
    for (const [id, timerId] of localAlarms.entries()) {
      clearTimeout(timerId);
    }
    localAlarms.clear();
  }
});

// ── Push: receive remote Web Push notifications from server ──
self.addEventListener('push', event => {
  console.log('[SW] Push received on mobile.');
  let data = {
    title: 'StudyEdge AI Study Reminder',
    body: 'Time for your study session!',
    icon: '/static/icon-192.png'
  };

  if (event.data) {
    try {
      data = JSON.parse(event.data.text());
    } catch (e) {
      data.body = event.data.text();
    }
  }

  const options = {
    body: data.body,
    icon: data.icon || '/static/icon-192.png',
    badge: '/static/icon-192.png',
    vibrate: [500, 250, 500, 250, 500],
    tag: 'studyedge-reminder',
    renotify: true,
    requireInteraction: true,
    actions: [
      { action: 'open', title: 'Open App' },
      { action: 'dismiss', title: 'Dismiss' }
    ],
    data: { url: '/mobile' }
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

// ── Notification Click: open /mobile on phone ──
self.addEventListener('notificationclick', event => {
  event.notification.close();
  if (event.action === 'dismiss') return;

  const targetUrl = event.notification.data?.url || '/mobile';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
      for (const client of windowClients) {
        if (client.url.includes('/mobile') && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});
