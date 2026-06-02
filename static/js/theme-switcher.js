/**
 * theme-switcher.js — Bootswatch theme selector with localStorage persistence.
 * Loads themes.json, renders dropdown, applies selected theme instantly.
 */
(function () {
  'use strict';

  var LS_KEY = 'notecrm:bootswatch-theme';
  var DEFAULT = 'default';
  var MANIFEST_URL = '/static/vendor/bootswatch/themes.json';

  var currentTheme = localStorage.getItem(LS_KEY) || DEFAULT;

  // ── Apply theme CSS ──
  function applyTheme(name) {
    var link = document.getElementById('bootswatch-theme-css');
    if (!link) return;

    if (name === DEFAULT || name === 'default') {
      link.href = '';
    } else {
      link.href = '/static/vendor/bootswatch/' + name + '/bootstrap.min.css';
    }
  }

  // ── Update all theme selectors on the page ──
  function syncSelectors(name) {
    var selects = document.querySelectorAll('.bootswatch-selector');
    for (var i = 0; i < selects.length; i++) {
      selects[i].value = name;
    }
  }

  // ── Change theme ──
  function setTheme(name) {
    currentTheme = name;
    localStorage.setItem(LS_KEY, name);
    applyTheme(name);
    syncSelectors(name);
  }

  // ── Render selector from themes.json ──
  function renderSelector(selectEl, themes) {
    if (!selectEl) return;

    // Default option
    selectEl.innerHTML = '';
    var defOpt = document.createElement('option');
    defOpt.value = 'default';
    defOpt.textContent = 'Default';
    selectEl.appendChild(defOpt);

    // Recommended themes ⭐
    var recommended = ['flatly', 'litera', 'lumen', 'materia', 'minty',
                       'sandstone', 'simplex', 'yeti', 'zephyr'];
    var sketchy = ['sketchy', 'vapor', 'cyborg', 'solar', 'superhero',
                   'slate', 'darkly', 'quartz'];

    // Add themes in display order: recommended → others → sketchy
    function addGroup(groupThemes, star) {
      for (var i = 0; i < groupThemes.length; i++) {
        for (var j = 0; j < themes.length; j++) {
          if (themes[j].name === groupThemes[i]) {
            var opt = document.createElement('option');
            opt.value = themes[j].name;
            opt.textContent = (star ? '⭐ ' : '') + themes[j].displayName;
            selectEl.appendChild(opt);
            break;
          }
        }
      }
    }

    addGroup(recommended, true);

    // Add remaining themes not in recommended or sketchy
    var added = new Set(['default'].concat(recommended).concat(sketchy));
    for (var k = 0; k < themes.length; k++) {
      if (!added.has(themes[k].name)) {
        var opt = document.createElement('option');
        opt.value = themes[k].name;
        opt.textContent = themes[k].displayName;
        selectEl.appendChild(opt);
      }
    }

    addGroup(sketchy, false);

    // Set current value
    selectEl.value = currentTheme;
  }

  // ── Load manifest and init selectors ──
  function initSelectors() {
    fetch(MANIFEST_URL)
      .then(function(res) { return res.ok ? res.json() : null; })
      .then(function(data) {
        var themes = (data && data.themes) || [];
        var selects = document.querySelectorAll('.bootswatch-selector');
        for (var i = 0; i < selects.length; i++) {
          renderSelector(selects[i], themes);
          // Listen for changes
          selects[i].addEventListener('change', function (e) {
            setTheme(e.target.value);
          });
        }
      })
      .catch(function() {
        // Fallback: just show current selection
        var selects = document.querySelectorAll('.bootswatch-selector');
        for (var i = 0; i < selects.length; i++) {
          selects[i].innerHTML = '<option value="default">Default</option>';
        }
      });
  }

  // ── Init ──
  applyTheme(currentTheme);
  document.addEventListener('DOMContentLoaded', function () {
    initSelectors();
    syncSelectors(currentTheme);
  });

  // Expose for external calls
  window.setTheme = setTheme;
  window.getCurrentTheme = function () { return currentTheme; };

})();
