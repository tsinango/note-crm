/**
 * drafts.js — Form draft auto-save using localStorage.
 * Protects user input from being lost on submission failure, network error,
 * CSRF error, or accidental page refresh.
 *
 * Usage:
 *   var dk = Draft.key('meeting:new', { customer_id: 1 });
 *   Draft.bindAutosave('meetingForm', dk, ['meetingDate','meetingParticipants','meetingContent']);
 *   Draft.restoreIfExists('meetingForm', dk, 'Restore meeting draft?');
 */
(function (w) {
  'use strict';

  var PREFIX = 'crm:draft:';

  // ── Storage helpers ────────────────────────────────────────
  function saveDraft(key, data) {
    try {
      data._savedAt = Date.now();
      localStorage.setItem(key, JSON.stringify(data));
      return true;
    } catch (e) {
      console.warn('Draft save failed:', e);
      return false;
    }
  }

  function loadDraft(key) {
    try {
      var raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function deleteDraft(key) {
    try {
      localStorage.removeItem(key);
    } catch (e) { /* ignore */ }
  }

  function getAllDraftKeys() {
    var keys = [];
    for (var i = 0; i < localStorage.length; i++) {
      var k = localStorage.key(i);
      if (k && k.indexOf(PREFIX) === 0) keys.push(k);
    }
    return keys;
  }

  // ── Key builder ────────────────────────────────────────────
  function buildKey(entity, action, ids) {
    ids = ids || {};
    var parts = [PREFIX, entity, action];
    if (entity === 'meeting') {
      if (action === 'new') parts.push('c' + (ids.customer_id || ''));
      else if (action === 'edit') parts.push('m' + (ids.meeting_id || ''));
    } else if (entity === 'task') {
      if (action === 'new') parts.push('c' + (ids.customer_id || '') + '_m' + (ids.meeting_id || '0'));
      else if (action === 'edit') parts.push('t' + (ids.task_id || ''));
    } else if (entity === 'customer') {
      if (action === 'new') parts.push('list');
      else if (action === 'edit') parts.push('c' + (ids.customer_id || ''));
    }
    return parts.join(':');
  }

  // ── Status indicator ───────────────────────────────────────
  function updateIndicator(formId, state, msg) {
    var el = document.getElementById('draft-' + formId);
    if (!el) return;
    el.className = 'draft-indicator small ms-2';
    if (state === 'saving') {
      el.className += ' text-info';
      el.innerHTML = '<i class="bi bi-arrow-repeat"></i> ' + (msg || 'Saving...');
    } else if (state === 'saved') {
      el.className += ' text-success';
      el.innerHTML = '<i class="bi bi-check-circle"></i> ' + (msg || 'Autosaved');
    } else if (state === 'error') {
      el.className += ' text-danger';
      el.innerHTML = '<i class="bi bi-exclamation-triangle"></i> ' + (msg || 'Save failed');
    } else if (state === 'clear') {
      el.innerHTML = '';
    }
  }

  // ── Bind auto-save on input events ─────────────────────────
  function bindAutosave(formId, draftKey, fieldIds, debounceMs) {
    debounceMs = debounceMs || 500;
    var timer = null;

    function collectData() {
      var data = {};
      if (!fieldIds || fieldIds.length === 0) {
        // Auto-collect all form fields
        var form = document.getElementById(formId);
        if (form) {
          var els = form.querySelectorAll('input, textarea, select');
          for (var i = 0; i < els.length; i++) {
            var el = els[i];
            if (el.name && el.name !== '_csrf_token' && el.type !== 'hidden') {
              data[el.name] = el.value;
            } else if (el.type === 'hidden' && el.name && el.id) {
              data[el.name] = el.value;
            }
          }
        }
        // Also grab hidden fields by id
        var hiddenIds = ['meetingId', 'meetingLocalId', 'taskId', 'taskLocalId', 'taskMeetingId',
                         'custId', 'custLocalId', 'meeting_date', 'due_date'];
        hiddenIds.forEach(function(id) {
          var el = document.getElementById(id);
          if (el && el.name && !data[el.name]) data[el.name] = el.value;
        });
      } else {
        fieldIds.forEach(function(id) {
          var el = document.getElementById(id);
          if (el) data[el.name || id] = el.value;
        });
      }
      return data;
    }

    function doSave() {
      var data = collectData();
      var ok = saveDraft(draftKey, data);
      updateIndicator(formId, ok ? 'saved' : 'error',
                      ok ? null : 'Autosave failed. Save manually.');
    }

    // Debounced input listener
    var form = document.getElementById(formId);
    if (!form) return;

    form.addEventListener('input', function () {
      updateIndicator(formId, 'saving');
      if (timer) clearTimeout(timer);
      timer = setTimeout(doSave, debounceMs);
    });

    // Also save on select/change
    form.addEventListener('change', function () {
      updateIndicator(formId, 'saving');
      if (timer) clearTimeout(timer);
      timer = setTimeout(doSave, debounceMs);
    });

    // Save immediately on form submit (before actual submission)
    form.addEventListener('submit', function () {
      doSave();
    });

    // Expose doSave for external call
    form._draftSave = doSave;
  }

  // ── Restore draft on page load ────────────────────────────
  function restoreIfExists(formId, draftKey, promptMsg) {
    var draft = loadDraft(draftKey);
    if (!draft) return false;

    // Check if draft is too old (> 24 hours), auto-discard
    if (draft._savedAt && Date.now() - draft._savedAt > 24 * 3600 * 1000) {
      deleteDraft(draftKey);
      return false;
    }

    var form = document.getElementById(formId);
    if (!form) return false;

    // Offer to restore
    var restored = false;
    if (w.confirm(promptMsg || 'An unsaved draft was found. Restore it?')) {
      for (var key in draft) {
        if (key === '_savedAt') continue;
        var el = form.elements[key] || document.getElementById(key);
        if (el) el.value = draft[key];
      }
      restored = true;
      updateIndicator(formId, 'saved', 'Draft restored');
    } else {
      // Discard
      deleteDraft(draftKey);
    }
    return restored;
  }

  // ── Expose API ─────────────────────────────────────────────
  w.Draft = {
    save: saveDraft,
    load: loadDraft,
    delete: deleteDraft,
    key: buildKey,
    getAllKeys: getAllDraftKeys,
    bindAutosave: bindAutosave,
    restoreIfExists: restoreIfExists,
    indicator: updateIndicator,
  };

})(window);
