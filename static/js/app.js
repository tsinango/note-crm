/**
 * CRM — Main JavaScript
 * PWA registration, network detection, IndexedDB sync (push-first, merge-pull),
 * offline form interception, load-more meetings.
 */
(function () {
  'use strict';

  // ============================================================
  //  NETWORK STATUS & UI
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

  window.showSyncBanner = function showSyncBanner(msg) {
    if (!syncBanner) return;
    syncBanner.classList.remove('d-none');
    if (syncStatusText) syncStatusText.textContent = msg;
    clearTimeout(syncBanner._timeout);
    syncBanner._timeout = setTimeout(function () {
      syncBanner.classList.add('d-none');
    }, 4000);
  };

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

  function putAll(db, storeName, items) {
    return new Promise(function (resolve, reject) {
      if (!items || items.length === 0) { resolve(); return; }
      var tx = db.transaction(storeName, 'readwrite');
      var store = tx.objectStore(storeName);
      items.forEach(function (item) { store.put(item); });
      tx.oncomplete = resolve;
      tx.onerror = reject;
    });
  }

  function getPending(db, storeName) {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(storeName, 'readonly');
      var index = tx.objectStore(storeName).index('sync_status');
      var results = [];
      var done = 0;
      var statuses = ['pending_create', 'pending_update', 'pending_delete'];
      statuses.forEach(function (status) {
        var req = index.getAll(status);
        req.onsuccess = function () {
          results = results.concat(req.result);
          done++;
          if (done === statuses.length) resolve(results);
        };
        req.onerror = function () {
          done++;
          if (done === statuses.length) resolve(results);
        };
      });
    });
  }

  function hasPending(db, storeName) {
    return getPending(db, storeName).then(function (items) {
      return items.length > 0;
    });
  }

  function getStoreAll(db, storeName) {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(storeName, 'readonly');
      var req = tx.objectStore(storeName).getAll();
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = reject;
    });
  }

  function putOne(db, storeName, item) {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(storeName, 'readwrite');
      tx.objectStore(storeName).put(item);
      tx.oncomplete = resolve;
      tx.onerror = reject;
    });
  }

  function deleteOne(db, storeName, localId) {
    return new Promise(function (resolve, reject) {
      var tx = db.transaction(storeName, 'readwrite');
      tx.objectStore(storeName).delete(localId);
      tx.oncomplete = resolve;
      tx.onerror = reject;
    });
  }

  // ============================================================
  //  SAVE LOCAL (called by form handlers)
  // ============================================================
  window.saveLocal = function saveLocal(store, data) {
    return openDB().then(function (db) {
      return putOne(db, store, data).then(function () { db.close(); });
    });
  };

  // ============================================================
  //  SYNC LOGIC: push first, then pull with merge
  // ============================================================
  function syncAll() {
    if (!navigator.onLine) return Promise.resolve();
    return _pushPending().then(function () {
      return _pullUpdates();
    }).then(function () {
      showSyncBanner('同步完成');
    }).catch(function (err) {
      console.error('Sync failed:', err);
      showSyncBanner('同步失败: ' + (err.message || '未知错误'));
    });
  }

  window.manualSync = function () {
    if (!navigator.onLine) {
      showSyncBanner('离线中，无法同步');
      return;
    }
    showSyncBanner('正在同步...');
    syncAll();
  };

  // ── Push: send pending items to server, then mark synced ────
  function _pushPending() {
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
          }).then(function (res) {
            if (!res.ok) throw new Error('Push failed: ' + res.status);
            return res.json();
          }).then(function (serverResult) {
            // Update local items: mark as synced, update server id
            var ops = [];
            stores.forEach(function (store) {
              (payload[store] || []).forEach(function (item) {
                ops.push(_markSynced(db, store, item.local_id, serverResult));
              });
            });
            return Promise.all(ops).then(function () { db.close(); });
          });
        });
    });
  }

  function _markSynced(db, storeName, localId, serverResult) {
    return new Promise(function (resolve) {
      var tx = db.transaction(storeName, 'readwrite');
      var storeObj = tx.objectStore(storeName);
      var getReq = storeObj.get(localId);
      getReq.onsuccess = function () {
        var record = getReq.result;
        if (!record) { resolve(); return; }
        record.sync_status = 'synced';

        // Apply id mapping from server
        var idMap = (serverResult.id_map && serverResult.id_map[storeName]) || [];
        for (var i = 0; i < idMap.length; i++) {
          if (idMap[i].local_id === localId && idMap[i].id) {
            record.id = idMap[i].id;
            break;
          }
        }
        storeObj.put(record);
        resolve();
      };
      getReq.onerror = function () { resolve(); };
      tx.oncomplete = resolve;
    });
  }

  // ── Pull: fetch server changes since last sync, merge into local DB ──
  function _pullUpdates() {
    return openDB().then(function (db) {
      // Check if any local pending items exist
      return Promise.all(
        ['customers', 'meetings', 'tasks'].map(function (s) { return hasPending(db, s); })
      ).then(function (hasPendings) {
        var anyPending = hasPendings.some(Boolean);
        var lastSyncTime = localStorage.getItem('crm_last_sync') || '1970-01-01T00:00:00';

        return fetch('/api/sync/pull?since=' + encodeURIComponent(lastSyncTime) + '&limit=500', {
          credentials: 'same-origin'
        }).then(function (res) {
          if (!res.ok) throw new Error('Pull failed: ' + res.status);
          return res.json();
        }).then(function (data) {
          var ops = [];
          ['customers', 'meetings', 'tasks', 'attachments'].forEach(function (store) {
            var items = data[store] || [];
            if (items.length > 0 && !anyPending) {
              // Safe to upsert
              items.forEach(function (item) {
                ops.push(putOne(db, store, item));
              });
            } else if (items.length > 0 && anyPending) {
              // Merge: only insert non-pending items
              ops.push(_mergePullItems(db, store, items));
            }
          });

          return Promise.all(ops).then(function () {
            localStorage.setItem('crm_last_sync', data.server_time || new Date().toISOString());
            db.close();
          });
        });
      });
    });
  }

  function _mergePullItems(db, storeName, items) {
    return new Promise(function (resolve) {
      var tx = db.transaction(storeName, 'readwrite');
      var storeObj = tx.objectStore(storeName);
      var processed = 0;
      items.forEach(function (item) {
        var getReq = storeObj.get(item.local_id);
        getReq.onsuccess = function () {
          var local = getReq.result;
          if (!local) {
            storeObj.put(item);
          } else if (local.sync_status === 'synced' || local.sync_status === 'sync_error') {
            // Server wins for synced items (latest updated_at)
            if (!local.updated_at || (item.updated_at && item.updated_at > local.updated_at)) {
              item.sync_status = 'synced';
              storeObj.put(item);
            }
          }
          // If local has pending changes, keep local
          processed++;
          if (processed >= items.length) resolve();
        };
        getReq.onerror = function () {
          processed++;
          if (processed >= items.length) resolve();
        };
      });
      if (items.length === 0) resolve();
    });
  }

  // ============================================================
  //  INIT: On page load, try to sync
  // ============================================================
  if (navigator.onLine) {
    syncAll();
  }

  // ============================================================
  //  LOAD-MORE MEETINGS
  // ============================================================
  window.loadMoreMeetings = function (customerId) {
    var btn = document.getElementById('loadMoreBtn');
    var container = document.getElementById('meetingsContainer');
    if (!btn || !container || btn.disabled) return;

    var offset = parseInt(btn.getAttribute('data-offset')) || 0;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 加载中...';

    var url = '/api/customers/' + customerId + '/meetings?limit=20&offset=' + offset;
    if (!navigator.onLine && window._offlineMeetings) {
      // Use offline data
      var offlineData = window._offlineMeetings.slice(offset, offset + 20);
      _renderMoreMeetings(offlineData, offset, btn);
      return;
    }

    fetch(url, { credentials: 'same-origin' })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        _renderMoreMeetings(data.meetings || [], offset, btn);
      })
      .catch(function () {
        btn.innerHTML = '加载失败，点击重试';
        btn.disabled = false;
      });
  };

  function _renderMoreMeetings(meetings, offset, btn) {
    var container = document.getElementById('meetingsContainer');
    if (!container) return;

    meetings.forEach(function (m) {
      var div = document.createElement('div');
      div.className = 'card mb-3 shadow-sm';
      var date = m.meeting_date || '';
      var title = m.title || '无标题';
      var participants = m.participants || '';
      var content = m.content || '';
      div.innerHTML =
        '<div class="card-header d-flex justify-content-between align-items-center py-2">' +
        '<div><span class="fw-semibold">' + _esc(date) + '</span> ' +
        '<span class="ms-2">' + _esc(title) + '</span></div>' +
        '<div class="btn-group btn-group-sm">' +
        '<button class="btn btn-outline-secondary btn-sm" onclick="editMeetingById(' + m.id + ')">' +
        '<i class="bi bi-pencil"></i></button>' +
        '</div></div>' +
        '<div class="card-body py-2">' +
        (participants ? '<p class="small text-muted mb-1"><i class="bi bi-people"></i> ' + _esc(participants) + '</p>' : '') +
        (content ? '<div class="small" style="white-space:pre-wrap">' + _esc(content) + '</div>' : '') +
        '</div>';
      container.appendChild(div);
    });

    var newOffset = offset + meetings.length;
    btn.setAttribute('data-offset', newOffset);

    if (meetings.length < 20) {
      btn.textContent = '已加载全部';
      btn.disabled = true;
    } else {
      btn.innerHTML = '加载更多...';
      btn.disabled = false;
    }
  }

  function _esc(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

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
