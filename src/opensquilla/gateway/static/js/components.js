/** OpenSquilla Web UI — Reusable UI components. */

const UI = (() => {

  // -- Toast notifications --
  let _toastContainer = null;
  const _visibleToasts = new Map();
  const _TOAST_TYPES = { error: 'err', danger: 'err', success: 'ok' };

  function toast(message, type = 'info', duration = 3000) {
    type = _TOAST_TYPES[type] || type;
    const toastKey = `${type}\u0000${message}`;
    if (_visibleToasts.has(toastKey)) return;

    if (!_toastContainer) {
      _toastContainer = document.createElement('div');
      _toastContainer.className = 'toast-stack';
      _toastContainer.setAttribute('role', 'status');
      _toastContainer.setAttribute('aria-live', 'polite');
      _toastContainer.setAttribute('aria-atomic', 'false');
      document.body.appendChild(_toastContainer);
    }
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    if (type === 'err' || type === 'warn') {
      el.setAttribute('role', 'alert');
    }
    el.textContent = message;
    _visibleToasts.set(toastKey, el);
    _toastContainer.appendChild(el);
    setTimeout(() => {
      el.remove();
      if (_visibleToasts.get(toastKey) === el) {
        _visibleToasts.delete(toastKey);
      }
    }, duration);
  }

  // -- Modal --
  let _modalSeq = 0;
  function modal(title, contentHtml, actions = []) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-backdrop';
    const titleId = `modal-title-${++_modalSeq}`;
    overlay.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="${titleId}">
        <div class="modal-title" id="${titleId}">${title}</div>
        <div class="modal-body">${contentHtml}</div>
        <div class="modal-foot"></div>
      </div>`;
    const actionsEl = overlay.querySelector('.modal-foot');
    const dialog = overlay.querySelector('.modal');
    const previousFocus = document.activeElement;
    let closed = false;

    const focusableSelector = [
      'a[href]',
      'button:not([disabled])',
      'textarea:not([disabled])',
      'input:not([disabled])',
      'select:not([disabled])',
      '[tabindex]:not([tabindex="-1"])',
    ].join(',');

    const close = () => {
      if (closed) return;
      closed = true;
      document.removeEventListener('keydown', onKey, true);
      overlay.dispatchEvent(new CustomEvent('ui:modal-close'));
      overlay.remove();
      try { previousFocus && previousFocus.focus && previousFocus.focus(); } catch (_) {}
    };

    actions.forEach(({ label, cls, onClick }) => {
      const btn = document.createElement('button');
      btn.className = `btn ${cls || ''}`;
      btn.textContent = label;
      btn.type = 'button';
      btn.addEventListener('click', () => { onClick?.(); close(); });
      actionsEl.appendChild(btn);
    });
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) close();
    });
    const onKey = (e) => {
      if (!document.body.contains(overlay)) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        close();
        return;
      }
      if (e.key === 'Tab') {
        const focusables = Array.from(dialog.querySelectorAll(focusableSelector))
          .filter(el => el.offsetWidth || el.offsetHeight || el === document.activeElement);
        if (focusables.length === 0) {
          e.preventDefault();
          dialog.focus();
          return;
        }
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey, true);
    document.body.appendChild(overlay);
    dialog.setAttribute('tabindex', '-1');
    const firstAction = dialog.querySelector('[autofocus], button, input, textarea, select, a[href]');
    if (firstAction) firstAction.focus();
    else dialog.focus();
    overlay.close = close;
    return overlay;
  }

  function confirm({
    title = 'Confirm action',
    message = '',
    confirmLabel = 'Confirm',
    cancelLabel = 'Cancel',
    danger = false,
  } = {}) {
    return new Promise((resolve) => {
      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        resolve(value);
      };
      const overlay = modal(title, message, [
        { label: cancelLabel, cls: 'btn--ghost', onClick: () => finish(false) },
        { label: confirmLabel, cls: danger ? 'btn--danger' : 'btn--primary', onClick: () => finish(true) },
      ]);
      overlay.addEventListener('ui:modal-close', () => finish(false), { once: true });
    });
  }

  // -- Data table with sort + pagination --
  function dataTable(container, { columns, data, pageSize = 20 }) {
    let sortCol = null;
    let sortAsc = true;
    let page = 0;

    function _render() {
      let sorted = [...data];
      if (sortCol !== null) {
        const key = columns[sortCol].key;
        sorted.sort((a, b) => {
          const va = a[key] ?? '', vb = b[key] ?? '';
          const cmp = va < vb ? -1 : va > vb ? 1 : 0;
          return sortAsc ? cmp : -cmp;
        });
      }
      const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
      page = Math.min(page, totalPages - 1);
      const slice = sorted.slice(page * pageSize, (page + 1) * pageSize);

      let html = '<table class="data-table"><thead><tr>';
      columns.forEach((col, i) => {
        const sortable = col.sortable !== false;
        const sortState = sortCol === i ? (sortAsc ? 'ascending' : 'descending') : 'none';
        const arrow = sortCol === i ? (sortAsc ? ' \u25b2' : ' \u25bc') : '';
        html += `<th ${sortable ? `aria-sort="${sortState}"` : ''}>`;
        html += sortable
          ? `<button type="button" class="table-sort-btn" data-col="${i}">${col.label}<span class="sort-arrow" aria-hidden="true">${arrow}</span></button>`
          : `${col.label}`;
        html += '</th>';
      });
      html += '</tr></thead><tbody>';
      slice.forEach(row => {
        html += '<tr>';
        columns.forEach(col => {
          const val = col.render ? col.render(row[col.key], row) : (row[col.key] ?? '');
          html += `<td>${val}</td>`;
        });
        html += '</tr>';
      });
      if (slice.length === 0) {
        html += `<tr><td colspan="${columns.length}" style="text-align:center;color:var(--text-muted);padding:var(--sp-6)">No data</td></tr>`;
      }
      html += '</tbody></table>';

      if (totalPages > 1) {
        html += `<div class="pagination">
          <button class="btn btn--sm" data-page="prev" ${page === 0 ? 'disabled' : ''}>Prev</button>
          <span>${page + 1} / ${totalPages}</span>
          <button class="btn btn--sm" data-page="next" ${page >= totalPages - 1 ? 'disabled' : ''}>Next</button>
        </div>`;
      }

      container.innerHTML = html;
      container.querySelectorAll('[data-col]').forEach(btn => {
        btn.addEventListener('click', () => {
          const ci = Number(btn.dataset.col);
          if (sortCol === ci) { sortAsc = !sortAsc; } else { sortCol = ci; sortAsc = true; }
          _render();
        });
      });
      container.querySelectorAll('[data-page]').forEach(btn => {
        btn.addEventListener('click', () => {
          page += btn.dataset.page === 'prev' ? -1 : 1;
          _render();
        });
      });
    }

    _render();
    return { refresh: (newData) => { data = newData; _render(); } };
  }

  // -- Skeleton placeholder --
  function skeleton(width = '100%', height = '1em') {
    return `<div class="skel" style="width:${width};height:${height}"></div>`;
  }

  // -- Chip/Badge --
  function chip(label, type = '') {
    const cls = type ? `chip chip-${type}` : 'chip';
    return `<span class="${cls}">${label}</span>`;
  }

  // -- Relative time --
  function relTime(isoOrTs) {
    const numeric = typeof isoOrTs === 'number'
      ? isoOrTs
      : (typeof isoOrTs === 'string' && isoOrTs.trim() !== '' ? Number(isoOrTs) : NaN);
    const d = Number.isFinite(numeric)
      ? new Date(Math.abs(numeric) < 10000000000 ? numeric * 1000 : numeric)
      : new Date(isoOrTs);
    if (Number.isNaN(d.getTime())) return '—';
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  // -- Session status helpers --
  // Mirrors SessionStatus enum in session/models.py. Backend types status
  // as plain str, so helpers default-branch on unknown / legacy inputs.
  // Maps a status to the .dot color variant and the .chip color modifier
  // from the design system (components.css). Running and timeout get a
  // visible color; done is informational; failed is danger; killed is muted.
  const _SESSION_STATUS_DOT = {
    running: 'ok',
    done:    'off',
    failed:  'err',
    killed:  'off',
    timeout: 'warn',
  };
  const _SESSION_STATUS_CHIP = {
    running: 'chip-ok',
    done:    'chip-info',
    failed:  'chip-danger',
    killed:  '',
    timeout: 'chip-warn',
  };
  const _SESSION_STATUS_LABEL = {
    running: 'Running',
    done:    'Completed',
    failed:  'Failed',
    killed:  'Aborted by operator',
    timeout: 'Timed out',
  };

  /** Returns the .dot color variant ("ok"/"warn"/"err"/"off") for a SessionStatus. */
  function sessionStatusClass(status) {
    const k = String(status || '').toLowerCase();
    return _SESSION_STATUS_DOT[k] || 'off';
  }

  /** Returns the .chip color modifier (e.g. "chip-ok", "chip-info") for a SessionStatus. Empty string for the muted variant. */
  function sessionStatusChip(status) {
    const k = String(status || '').toLowerCase();
    return _SESSION_STATUS_CHIP[k] != null ? _SESSION_STATUS_CHIP[k] : '';
  }

  /** Returns human-readable tooltip text for a SessionStatus value. Falls back to the raw string, or 'Unknown' if empty. */
  function sessionStatusLabel(status) {
    const k = String(status || '').toLowerCase();
    return _SESSION_STATUS_LABEL[k] || (status ? String(status) : 'Unknown');
  }

  // -- Drawer (right-side slide-out panel) --
  // Promise-based: `drawer.result` resolves with the value passed to
  // `drawer.close(reason, value)` (or `null` on backdrop/esc/cancel).
  // `beforeClose` gates close attempts (return false / await false to block,
  // useful for unsaved-changes guards).
  let _drawerSeq = 0;
  const _drawerStack = [];

  function _onDrawerKey(e) {
    if (e.key !== 'Escape') return;
    const top = _drawerStack[_drawerStack.length - 1];
    if (top) {
      e.stopImmediatePropagation();
      top.close('esc', null);
    }
  }

  function drawer({
    title = '',
    width = 480,
    side = 'right',
    bodyHtml = '',
    footerHtml = '',
    onClose = null,
    beforeClose = null,
    closeOnBackdrop = true,
  } = {}) {
    const id = ++_drawerSeq;
    const titleId = `drawer-title-${id}`;
    const overlay = document.createElement('div');
    overlay.className = 'drawer-backdrop';
    overlay.innerHTML = `
      <aside class="drawer drawer--${side}" role="dialog" aria-modal="true" aria-labelledby="${titleId}" style="width:${typeof width === 'number' ? width + 'px' : width}">
        <header class="drawer__head">
          <h2 class="drawer__title" id="${titleId}"></h2>
          <button class="drawer__close" type="button" aria-label="Close">×</button>
        </header>
        <div class="drawer__body"></div>
        <footer class="drawer__foot"></footer>
      </aside>`;

    const aside = overlay.querySelector('.drawer');
    const titleEl = overlay.querySelector('.drawer__title');
    const bodyEl = overlay.querySelector('.drawer__body');
    const footEl = overlay.querySelector('.drawer__foot');
    const closeBtn = overlay.querySelector('.drawer__close');

    titleEl.textContent = title;
    bodyEl.innerHTML = bodyHtml;
    footEl.innerHTML = footerHtml;

    let resolveResult;
    const result = new Promise(res => { resolveResult = res; });
    let closing = false;

    const previousFocus = document.activeElement;

    async function close(reason = 'api', value = null) {
      if (closing) return;
      if (typeof beforeClose === 'function') {
        try {
          const ok = await beforeClose(reason);
          if (ok === false) return;
        } catch {
          return;
        }
      }
      closing = true;
      const idx = _drawerStack.indexOf(api);
      if (idx >= 0) _drawerStack.splice(idx, 1);
      if (_drawerStack.length === 0) {
        document.removeEventListener('keydown', _onDrawerKey, true);
      }
      aside.classList.add('is-closing');
      overlay.classList.add('is-closing');
      const finish = () => {
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        try { onClose?.(reason, value); } catch (e) { /* noop */ }
        try { previousFocus && previousFocus.focus && previousFocus.focus(); } catch (e) { /* noop */ }
        resolveResult(value);
      };
      // Wait for slide-out animation; fall back if no transition fires.
      let done = false;
      const onEnd = () => { if (!done) { done = true; finish(); } };
      aside.addEventListener('transitionend', onEnd, { once: true });
      setTimeout(onEnd, 280);
    }

    closeBtn.addEventListener('click', () => close('button', null));
    overlay.addEventListener('mousedown', (e) => {
      if (closeOnBackdrop && e.target === overlay) close('backdrop', null);
    });

    function _focusFirst() {
      const target = aside.querySelector('[autofocus], input, textarea, select, button:not(.drawer__close)');
      if (target && typeof target.focus === 'function') target.focus();
    }

    function _trapTab(e) {
      if (e.key !== 'Tab') return;
      const focusables = aside.querySelectorAll(
        'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    aside.addEventListener('keydown', _trapTab);

    const api = {
      element: overlay,
      body: () => bodyEl,
      footer: () => footEl,
      head: () => overlay.querySelector('.drawer__head'),
      setTitle(t) { titleEl.textContent = t; },
      setBody(html) {
        if (typeof html === 'string') bodyEl.innerHTML = html;
        else if (html instanceof Node) { bodyEl.innerHTML = ''; bodyEl.appendChild(html); }
      },
      setFooter(html) {
        if (typeof html === 'string') footEl.innerHTML = html;
        else if (html instanceof Node) { footEl.innerHTML = ''; footEl.appendChild(html); }
      },
      setMode(mode) {
        aside.classList.remove('drawer--mode-create', 'drawer--mode-view', 'drawer--mode-edit');
        aside.classList.add(`drawer--mode-${mode}`);
      },
      close,
      resolve: (value) => close('save', value),
      result,
    };

    if (_drawerStack.length === 0) {
      document.addEventListener('keydown', _onDrawerKey, true);
    }
    _drawerStack.push(api);

    document.body.appendChild(overlay);
    // Trigger slide-in on next frame.
    requestAnimationFrame(() => { aside.classList.add('is-open'); overlay.classList.add('is-open'); });
    setTimeout(_focusFirst, 50);
    return api;
  }

  // -- Combobox (input + listbox + create-on-miss) --
  // Returns a controller with explicit get/set/setItems for the host component.
  // Items shape: { id, label, sublabel?, disabled? }.
  // When `allowCreate` and the typed text matches no item id/label, a sticky
  // "create" row appears at the bottom of the dropdown; activating it calls
  // `onCreate(typed)` (consumer typically updates state and resolves a drawer).
  let _comboSeq = 0;
  function combobox({
    items = [],
    value = '',
    placeholder = '',
    emptyText = 'No matches',
    onChange = null,
    onCreate = null,
    allowCreate = false,
    createLabel = (typed) => `↵ Create new "${typed}"`,
    filter = null,
    id = null,
    autofocus = false,
  } = {}) {
    const seq = ++_comboSeq;
    const rootId = id || `ui-combo-${seq}`;
    const listId = `${rootId}-list`;

    const root = document.createElement('div');
    root.className = 'ui-combo';
    root.innerHTML = `
      <input
        id="${rootId}"
        class="ui-combo__input"
        type="text"
        role="combobox"
        autocomplete="off"
        spellcheck="false"
        aria-expanded="false"
        aria-controls="${listId}"
        aria-autocomplete="list"
        placeholder="${placeholder.replace(/"/g, '&quot;')}"
      />
      <ul id="${listId}" class="ui-combo__list" role="listbox" hidden></ul>`;

    const input = root.querySelector('input');
    const list = root.querySelector('ul');

    let _items = items.slice();
    let _value = value;
    let _highlightIdx = -1;
    let _open = false;
    let _typed = '';
    // Distinguish "user is typing to narrow" from "input shows the picked
    // item's label" — when false, the dropdown shows all items unfiltered.
    let _userTyped = false;

    // Initialize input display from value
    const initEntry = _items.find(it => it.id === _value);
    if (initEntry) {
      input.value = initEntry.label || initEntry.id;
      _typed = input.value;
    } else if (_value) {
      input.value = _value;
      _typed = _value;
    }

    function _defaultFilter(item, q) {
      if (!q) return true;
      const needle = q.toLowerCase();
      return (
        String(item.id || '').toLowerCase().includes(needle) ||
        String(item.label || '').toLowerCase().includes(needle) ||
        String(item.sublabel || '').toLowerCase().includes(needle)
      );
    }

    function _match() {
      // Until the user explicitly types into the input, show every item.
      // The input may currently display the picked item's label, but that
      // shouldn't be treated as a filter query.
      if (!_userTyped) return _items.slice();
      const q = _typed.trim();
      const fn = typeof filter === 'function' ? filter : _defaultFilter;
      return _items.filter(it => fn(it, q));
    }

    function _showCreate() {
      if (!allowCreate || !onCreate) return false;
      // No "create new" suggestion until user actually types something fresh.
      if (!_userTyped) return false;
      const q = _typed.trim();
      if (!q) return false;
      const exact = _items.some(
        it => String(it.id).toLowerCase() === q.toLowerCase() ||
              String(it.label || '').toLowerCase() === q.toLowerCase()
      );
      return !exact;
    }

    function _esc(s) {
      return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function _render() {
      const matched = _match();
      const showCreate = _showCreate();
      const total = matched.length + (showCreate ? 1 : 0);
      if (_highlightIdx >= total) _highlightIdx = total - 1;
      if (_highlightIdx < 0 && total > 0) _highlightIdx = 0;

      let html = '';
      if (matched.length === 0 && !showCreate) {
        html = `<li class="ui-combo__empty" aria-disabled="true">${_esc(emptyText)}</li>`;
      } else {
        matched.forEach((it, i) => {
          const optId = `${rootId}-opt-${i}`;
          const cls = `ui-combo__option${_highlightIdx === i ? ' is-active' : ''}${it.disabled ? ' is-disabled' : ''}`;
          const sub = it.sublabel ? `<span class="ui-combo__sublabel">${_esc(it.sublabel)}</span>` : '';
          html += `<li id="${optId}" role="option" data-idx="${i}" class="${cls}" aria-selected="${_highlightIdx === i}">
            <span class="ui-combo__label">${_esc(it.label || it.id)}</span>${sub}
          </li>`;
        });
        if (showCreate) {
          const i = matched.length;
          const optId = `${rootId}-opt-create`;
          const active = _highlightIdx === i ? ' is-active' : '';
          html += `<li id="${optId}" role="option" data-idx="${i}" data-create="1" class="ui-combo__option ui-combo__option--create${active}" aria-selected="${_highlightIdx === i}">
            ${_esc(createLabel(_typed.trim()))}
          </li>`;
        }
      }
      list.innerHTML = html;
      const active = list.querySelector('.is-active');
      input.setAttribute('aria-activedescendant', active ? active.id : '');
    }

    function _open_() {
      if (_open) return;
      _open = true;
      list.hidden = false;
      input.setAttribute('aria-expanded', 'true');
      _render();
    }

    function _close() {
      if (!_open) return;
      _open = false;
      list.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
    }

    function _commit(idx) {
      const matched = _match();
      const showCreate = _showCreate();
      if (idx < matched.length) {
        const item = matched[idx];
        if (item.disabled) return;
        _value = item.id;
        input.value = item.label || item.id;
        _typed = input.value;
        _userTyped = false;
        _close();
        if (onChange) onChange(item.id, item);
      } else if (showCreate && idx === matched.length) {
        _close();
        if (onCreate) onCreate(_typed.trim());
      }
    }

    input.addEventListener('focus', () => {
      // Selecting the current display lets the user just start typing to
      // override it (and visually signals "this is replaceable text").
      try { input.select(); } catch (e) { /* noop */ }
      _open_();
    });
    input.addEventListener('input', () => {
      _typed = input.value;
      _userTyped = true;
      _value = '';
      _highlightIdx = 0;
      _open_();
      if (onChange) onChange(null, null);
    });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        _open_();
        const total = _match().length + (_showCreate() ? 1 : 0);
        if (total > 0) _highlightIdx = (_highlightIdx + 1) % total;
        _render();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        _open_();
        const total = _match().length + (_showCreate() ? 1 : 0);
        if (total > 0) _highlightIdx = (_highlightIdx - 1 + total) % total;
        _render();
      } else if (e.key === 'Enter') {
        if (_open && _highlightIdx >= 0) {
          e.preventDefault();
          _commit(_highlightIdx);
        }
      } else if (e.key === 'Escape') {
        if (_open) {
          e.stopPropagation();
          _close();
        }
      } else if (e.key === 'Tab') {
        _close();
      }
    });

    list.addEventListener('mousedown', (e) => {
      // Use mousedown + preventDefault so the input doesn't lose focus before the click resolves.
      const li = e.target.closest('li[data-idx]');
      if (!li) return;
      e.preventDefault();
      const idx = Number(li.dataset.idx);
      _commit(idx);
    });
    list.addEventListener('mousemove', (e) => {
      const li = e.target.closest('li[data-idx]');
      if (!li) return;
      const idx = Number(li.dataset.idx);
      if (_highlightIdx !== idx) {
        _highlightIdx = idx;
        _render();
      }
    });

    const onDocumentMouseDown = (e) => {
      if (!root.contains(e.target)) _close();
    };
    document.addEventListener('mousedown', onDocumentMouseDown);

    if (autofocus) {
      setTimeout(() => input.focus(), 0);
    }

    return {
      element: root,
      input,
      getValue: () => _value,
      getTyped: () => _typed.trim(),
      isCreatePending: () => _showCreate() && (_highlightIdx === _match().length),
      setValue: (v) => {
        _value = v;
        const entry = _items.find(it => it.id === v);
        input.value = entry ? (entry.label || entry.id) : (v || '');
        _typed = input.value;
        _userTyped = false;
        _render();
      },
      setItems: (next) => {
        _items = next.slice();
        _render();
      },
      open: _open_,
      close: _close,
      focus: () => input.focus(),
      destroy: () => {
        document.removeEventListener('mousedown', onDocumentMouseDown);
        _close();
        if (root.parentNode) root.parentNode.removeChild(root);
      },
    };
  }

  return {
    toast, modal, confirm, dataTable, skeleton, chip, relTime,
    sessionStatusClass, sessionStatusChip, sessionStatusLabel,
    drawer, combobox,
  };
})();

window.UI = UI;
