/**
 * Service Worker for CRM PWA
 * Caches core assets for offline use.
 */

const CACHE_NAME = 'crm-cache-v1';
const STATIC_ASSETS = [
  '/',
  '/customers',
  '/tasks',
  '/static/css/style.css',
  '/static/js/app.js',
  '/static/manifest.json',
  '/static/vendor/bootstrap/bootstrap.min.css',
  '/static/vendor/bootstrap-icons/bootstrap-icons.css',
  '/static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff2',
  '/static/vendor/bootstrap/bootstrap.bundle.min.js',
];

// Install: pre-cache static assets
self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      return cache.addAll(STATIC_ASSETS).catch(function (err) {
        console.warn('SW: some assets failed to cache', err);
      });
    })
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.filter(function (key) { return key !== CACHE_NAME; })
            .map(function (key) { return caches.delete(key); })
      );
    })
  );
  self.clients.claim();
});

// Fetch: network-first for HTML, cache-first for static
self.addEventListener('fetch', function (event) {
  var url = new URL(event.request.url);

  // Skip sync API and POST requests — always go to network
  if (url.pathname.startsWith('/api/') || event.request.method !== 'GET') {
    return;
  }

  // For HTML pages: network-first, fall back to cache
  if (event.request.headers.get('Accept') && event.request.headers.get('Accept').indexOf('text/html') !== -1) {
    event.respondWith(
      fetch(event.request).then(function (response) {
        var cloned = response.clone();
        caches.open(CACHE_NAME).then(function (cache) {
          cache.put(event.request, cloned);
        });
        return response;
      }).catch(function () {
        return caches.match(event.request).then(function (cached) {
          return cached || caches.match('/customers');
        });
      })
    );
    return;
  }

  // For static assets: cache-first
  event.respondWith(
    caches.match(event.request).then(function (cached) {
      return cached || fetch(event.request).then(function (response) {
        var cloned = response.clone();
        caches.open(CACHE_NAME).then(function (cache) {
          cache.put(event.request, cloned);
        });
        return response;
      });
    })
  );
});
