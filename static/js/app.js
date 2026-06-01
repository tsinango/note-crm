/**
 * CRM — Main JavaScript
 * Handles: online/offline detection, PWA registration, IndexedDB sync
 */
(function () {
  'use strict';

  // ============================================================
  //  NETWORK STATUS
  // ============================================================
  var offlineBanner = document.getElementById('offline-banner');
  var syncBanner = document.getElementById('sync-banner');
  var syncStatusText = document.getElementById('sync-status-text');

  function updateOnlineStatus() {
    if (navigator.onLine) {
      if (offlineBanner) offlineBanner.classList.add('d-none');
    } else {
      if (offlineBanner) offlineBanner.classList.remove('d-none');
    }
  }

  window.addEventListener('online', function () {
    updateOnlineStatus();
    showSyncBanner('已联网，正在同步...');
    syncAll();
  });

  window.addEventListener('offline', function () {
    updateOnlineStatus();
    showSyncBanner('已离线，数据保存在本地');
  });

  function showSyncBanner(msg) {
    if (!syncBanner) return;
    syncBanner.classList.remove('d-none');
    if (syncStatusText) syncStatusText.textContent = msg;
    setTimeout(function () {
      syncBanner.classList.add('d-none');
    }, 4000);
  }

  updateOnlineStatus();

  // ============================================================
  //  PWA SERVICE WORKER
  // ============================================================
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/js/sw.js').catch(function (err) {
      console.warn('SW registration failed:', err);
    });
  }

  // ============================================================
  //  MANUAL SYNC
  // ============================================================
  window.manualSync = function () {
    if (!navigator.onLine) {
      showSyncBanner('离线中，无法同步');
      return;
    }
    showSyncBanner('正在同步...');
    syncAll();
  };

  // ============================================================
  //  INDEXEDDB HELPERS
  // ============================================================
  var DB_NAME = 'crm_offline';
  var DB_VERSION = 1;

  function openDB() {
    return new Promise(function (resolve, reject) {
      var req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function (e) {
        var db = e.target.result;
        ['customers', 'meetings', 'tasks', 'attachments'].forEach(function (store) {
          if (!db.objectStoreNames.contains(store)) {
            var s = db.createObjectStore(store, { keyPath: 'local_id' });
            s.createIndex('sync_status', 'sync_status', { unique: false });
            s.createIndex('customer_id', 'customer_id', { unique: false });
          }
        });
      };
      req.onsuccess = function (e) { resolve(e.target.result); };
      req.onerror = function (e) { reject(e.target.error); };
    });
  }

  function clearStore(db, storeName) {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(storeName, 'readwrite');
      tx.objectStore(storeName).clear();
      tx.oncomplete = resolve;
      tx.onerror = reject;
    });
  }

  function putAll(db, storeName, items) {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(storeName, 'readwrite');
      var store = tx.objectStore(storeName);
      items.forEach(function (item) { store.put(item); });
      tx.oncomplete = resolve;
      tx.onerror = reject;
    });
  }

  function getAll(db, storeName) {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(storeName, 'readonly');
      var req = tx.objectStore(storeName).getAll();
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = reject;
    });
  }

  function getPending(db, storeName) {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(storeName, 'readonly');
      var index = tx.objectStore(storeName).index('sync_status');
      var results = [];
      ['pending_create', 'pending_update', 'pending_delete'].forEach(function (status) {
        var req = index.getAll(status);
        req.onsuccess = function () { results = results.concat(req.result); };
      });
      tx.oncomplete = function () { resolve(results); };
      tx.onerror = reject;
    });
  }

  // ============================================================
  //  SYNC LOGIC
  // ============================================================
  function syncAll() {
    if (!navigator.onLine) return;
    pullFromServer()
      .then(function () { return pushToServer(); })
      .then(function () { showSyncBanner('同步完成'); })
      .catch(function (err) {
        console.error('Sync failed:', err);
        showSyncBanner('同步失败，请稍后重试');
      });
  }

  function pullFromServer() {
    return openDB().then(function (db) {
      return fetch('/api/sync/bootstrap', { credentials: 'same-origin' })
        .then(function (res) { return res.json(); })
        .then(function (data) {
          var ops = [];
          ['customers', 'meetings', 'tasks', 'attachments'].forEach(function (store) {
            if (data[store]) {
              ops.push(clearStore(db, store).then(function () {
                return putAll(db, store, data[store]);
              }));
            }
          });
          return Promise.all(ops).then(function () { db.close(); });
        });
    });
  }

  function pushToServer() {
    return openDB().then(function (db) {
      var stores = ['customers', 'meetings', 'tasks', 'attachments'];
      return Promise.all(stores.map(function (s) { return getPending(db, s); }))
        .then(function (results) {
          var payload = {};
          var hasPending = false;
          stores.forEach(function (store, i) {
            if (results[i].length > 0) {
              payload[store] = results[i];
              hasPending = true;
            }
          });
          if (!hasPending) { db.close(); return; }
          return fetch('/api/sync/push', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify(payload)
          }).then(function (res) { return res.json(); })
            .then(function (serverResult) {
              // Mark successfully synced items as 'synced'
              var ops = [];
              stores.forEach(function (store) {
                (payload[store] || []).forEach(function (item) {
                  if (item.local_id && !serverResult.errors.some(function (e) { return e.local_id === item.local_id; })) {
                    ops.push(new Promise(function (resolve, reject) {
                      var tx = db.transaction(store, 'readwrite');
                      var storeObj = tx.objectStore(store);
                      var getReq = storeObj.get(item.local_id);
                      getReq.onsuccess = function () {
                        var record = getReq.result;
                        if (record) {
                          record.sync_status = 'synced';
                          storeObj.put(record);
                        }
                        resolve();
                      };
                      getReq.onerror = reject;
                    }));
                  }
                });
              });
              return Promise.all(ops).then(function () { db.close(); });
            });
        });
    });
  }

  // ============================================================
  //  HELPER: Local save for offline use
  // ============================================================
  window.saveLocal = function (store, data) {
    return openDB().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(store, 'readwrite');
        data.sync_status = data.sync_status || 'pending_create';
        tx.objectStore(store).put(data);
        tx.oncomplete = function () { db.close(); resolve(); };
        tx.onerror = reject;
      });
    });
  };

  // ============================================================
  //  AUTO-DISMISS FLASH
  // ============================================================
  setTimeout(function () {
    document.querySelectorAll('.alert-dismissible').forEach(function (el) {
      var bsAlert = bootstrap.Alert.getOrCreateInstance(el);
      if (bsAlert) bsAlert.close();
    });
  }, 5000);

})();
