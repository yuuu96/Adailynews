self.addEventListener('install', event => {
  event.waitUntil(
    caches.open('a-stock-intel-v1').then(cache => cache.addAll(['/', '/manifest.webmanifest']))
  );
});

self.addEventListener('fetch', event => {
  if (event.request.url.includes('/api/')) return;
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request).then(response => response || caches.match('/')))
  );
});
