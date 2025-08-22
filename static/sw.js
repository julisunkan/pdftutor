// Service Worker for PDF Tutorial App PWA
const CACHE_NAME = 'pdf-tutorial-v1';
const urlsToCache = [
    '/',
    '/static/css/style.css',
    '/static/js/app.js',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css',
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js'
];

// Install event - cache resources
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log('Opened cache');
                return cache.addAll(urlsToCache);
            })
            .catch(error => {
                console.log('Cache installation failed:', error);
            })
    );
});

// Fetch event - serve from cache when offline
self.addEventListener('fetch', event => {
    event.respondWith(
        caches.match(event.request)
            .then(response => {
                // Return cached version or fetch from network
                if (response) {
                    return response;
                }
                
                // Clone the request because it's a stream
                const fetchRequest = event.request.clone();
                
                return fetch(fetchRequest).then(response => {
                    // Check if we received a valid response
                    if (!response || response.status !== 200 || response.type !== 'basic') {
                        return response;
                    }
                    
                    // Clone the response because it's a stream
                    const responseToCache = response.clone();
                    
                    // Add to cache for future use
                    caches.open(CACHE_NAME)
                        .then(cache => {
                            // Only cache GET requests
                            if (event.request.method === 'GET') {
                                cache.put(event.request, responseToCache);
                            }
                        });
                    
                    return response;
                }).catch(() => {
                    // Return offline page for navigation requests
                    if (event.request.mode === 'navigate') {
                        return caches.match('/');
                    }
                });
            })
    );
});

// Activate event - clean up old caches
self.addEventListener('activate', event => {
    const cacheWhitelist = [CACHE_NAME];
    
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.map(cacheName => {
                    if (cacheWhitelist.indexOf(cacheName) === -1) {
                        console.log('Deleting old cache:', cacheName);
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
});

// Background sync for saving bookmarks and notes when back online
self.addEventListener('sync', event => {
    if (event.tag === 'background-sync') {
        event.waitUntil(
            // Sync any pending bookmarks or notes
            syncData()
        );
    }
});

// Push notifications (placeholder for future implementation)
self.addEventListener('push', event => {
    const options = {
        body: event.data ? event.data.text() : 'New notification',
        icon: '/static/icon-192x192.png',
        badge: '/static/badge-72x72.png'
    };
    
    event.waitUntil(
        self.registration.showNotification('PDF Tutorial', options)
    );
});

// Notification click handler
self.addEventListener('notificationclick', event => {
    event.notification.close();
    
    event.waitUntil(
        clients.openWindow('/')
    );
});

// Helper function to sync data when back online
async function syncData() {
    try {
        // This would sync any offline bookmarks or notes
        console.log('Syncing offline data...');
        
        // Get stored offline data from IndexedDB or localStorage
        // and sync with server when connection is restored
        
        return Promise.resolve();
    } catch (error) {
        console.error('Sync failed:', error);
        return Promise.reject(error);
    }
}

// Message handler for communication with main thread
self.addEventListener('message', event => {
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});

