/** OpenSquilla Web UI — Chat view. */

const ChatView = (() => {
  /* ── Private state ─────────────────────────────────────────────────── */
  let _el = null;
  let _rpc = null;
  let _unsubs = [];
  let _intervals = [];

  // Session
  const _WEBCHAT_SESSION_KEY = 'agent:main:webchat:default';
  let _sessionKey = '';
  let _pendingSessionIntent = null;

  // Browser-scoped elevated mode. "full" maps to /elevated full.
  const _ELEVATED_MODE_KEY = 'opensquilla.elevatedMode';
  let _elevatedMode = '';
  // The /api/elevated-mode endpoint is owner-only. When the gateway is bound
  // to a wildcard address (LAN deploy), no peer is treated as owner and the
  // endpoint always returns 403. We latch this state on the first failed
  // sync so the pill can disable itself instead of toasting on every click.
  let _elevatedUnavailable = false;

  // Streaming
  let _isStreaming = false;
  let _aborted = false;
  let _streamBubble = null;
  let _streamRaw = '';           // full accumulated text (for export)
  let _segments = [];             // [{type:'text', raw:'', el:DOM}, {type:'tool', el:DOM}, ...]
  let _activeTextSeg = null;      // pointer to current text segment's DOM element
  let _activeTextRaw = '';        // raw text for current active segment only
  let _streamArtifacts = [];
  let _autoScroll = true;
  let _streamIdleTimer = null;
  let _streamIdlePausedForApproval = false;
  let _historySyncTimer = null;
  const _DEFAULT_STREAM_IDLE_TIMEOUT_MS = 210000; // server should emit terminal first
  let _streamIdleTimeoutMs = _DEFAULT_STREAM_IDLE_TIMEOUT_MS;
  let _lastStreamSeq = 0;
  let _activeTaskGroups = new Set();
  // Session epoch counter. Frames carrying an older epoch are stale
  // (arrived from a turn that predates the last reset) and must be discarded.
  let _currentEpoch = 0;

  // Attachments
  // Two-mode attachment buffer: each entry is either
  //   {kind:'inline',  name, mime, data,      dataUrl}      (≤ 2 MB; base64 inline)
  //   {kind:'staged',  name, mime, file_uuid, size}         (image/PDF > 2 MB; POSTed to /api/v1/files/upload)
  // Single source of truth for the inline-vs-staged threshold; never re-typed.
  const INLINE_THRESHOLD_BYTES = 2_000_000;
  const ATTACHMENT_TEXT_HARD_CAP_BYTES = INLINE_THRESHOLD_BYTES;
  const ATTACHMENT_IMAGE_HARD_CAP_BYTES = 5 * 1024 * 1024;
  const ATTACHMENT_PDF_HARD_CAP_BYTES = 30 * 1024 * 1024; // staged PDF bridge cap
  const ATTACHMENT_IMAGE_MIMES = [
    'image/png',
    'image/jpeg',
    'image/gif',
    'image/webp',
  ];
  const ATTACHMENT_TEXT_MIMES = [
    'text/plain',
    'text/markdown',
    'text/html',
    'text/csv',
    'application/json',
  ];
  const ATTACHMENT_ALLOWED_MIMES = [
    ...ATTACHMENT_IMAGE_MIMES,
    'application/pdf',
    ...ATTACHMENT_TEXT_MIMES,
  ];
  const ATTACHMENT_EXTENSION_MIMES = {
    png: 'image/png',
    jpg: 'image/jpeg',
    jpeg: 'image/jpeg',
    gif: 'image/gif',
    webp: 'image/webp',
    pdf: 'application/pdf',
    txt: 'text/plain',
    md: 'text/markdown',
    markdown: 'text/markdown',
    html: 'text/html',
    htm: 'text/html',
    csv: 'text/csv',
    json: 'application/json',
  };
  const ATTACHMENT_ALLOWED_LABEL = 'PNG, JPEG, GIF, WEBP, PDF, TXT, MD, HTML, CSV, JSON';
  function _isAllowedAttachmentMime(mime) {
    return typeof mime === 'string' && ATTACHMENT_ALLOWED_MIMES.indexOf(mime) !== -1;
  }
  function _isImageAttachmentMime(mime) {
    return typeof mime === 'string' && ATTACHMENT_IMAGE_MIMES.indexOf(mime) !== -1;
  }
  function _isTextAttachmentMime(mime) {
    return typeof mime === 'string' && ATTACHMENT_TEXT_MIMES.indexOf(mime) !== -1;
  }
  function _canStageAttachmentMime(mime) {
    return mime === 'application/pdf' || _isImageAttachmentMime(mime);
  }
  function _attachmentHardCapBytes(mime) {
    if (mime === 'application/pdf') return ATTACHMENT_PDF_HARD_CAP_BYTES;
    if (_isImageAttachmentMime(mime)) return ATTACHMENT_IMAGE_HARD_CAP_BYTES;
    if (_isTextAttachmentMime(mime)) return ATTACHMENT_TEXT_HARD_CAP_BYTES;
    return ATTACHMENT_IMAGE_HARD_CAP_BYTES;
  }
  let _nextAttachmentId = 1;
  let _pendingAttachments = []; // entries shaped per the two-mode comment above

  // Pending-send queue.
  // Send during an in-flight turn does NOT interrupt the current response;
  // it appends to this queue. On natural turn completion the queue is
  // drained head-first (FIFO). On ESC / Stop or server-side cancel, the
  // queue is recovered into the textarea (see _popAllPendingIntoComposer)
  // so the user can edit and resend rather than losing pending text.
  //   - Alt+↑ tail-pops the most recent into the input for edit
  //   - Alt+↓ enqueues the textarea content (if non-empty and queue not full)
  //   - bounded at _MAX_PENDING to avoid unbounded backlogs
  //   - in-memory only; localStorage + cross-tab sync are follow-ups
  const _MAX_PENDING = 5;
  let _pendingQueue = []; // [{text, attachments, intent}]
  let _stopRequestedByUser = false;
  let _pendingArea = null;
  let _stopBtn = null;
  let _runStatusEl = null;

  // Sent-message history navigation (↑/↓ on empty textarea).
  // History is derived from _messages (role==='user') so there is a single
  // source of truth — _inputHistoryIdx is the cursor into that derived list.
  // When the user starts editing, the cursor is reset (see input listener).
  // _inputHistoryDraft stashes the textarea content at the moment the user
  // first presses ↑, so ↓ past the newest entry restores it.
  let _inputHistoryIdx = null;
  let _inputHistoryDraft = '';
  let _suppressHistoryReset = false;

  // Thinking indicator
  let _thinkingEl = null;
  let _thinkingStartTime = 0;
  let _thinkingTimerInterval = null;
  let _thinkingDelayTimer = null;
  const _THINKING_DELAY_MS = 400;  // don't show for fast responses
  const _THINKING_TTL_MS = 60000;  // 60s auto-hide

  // Inline directive tags — control signals the LLM emits per system prompt
  // instructions (e.g. reply threading).  Must be stripped before display.
  const _DIRECTIVE_TAG_RE = /\[\[\s*(?:reply_to_current|reply_to\s*:\s*[^\]\n]+)\s*\]\]\s*/g;
  function _stripDirectiveTags(text) {
    return text.replace(_DIRECTIVE_TAG_RE, '').replace(/^\n+/, '');
  }

  // Server-side per-turn time prefix: [YYYY-MM-DDTHH:MM±HH:MM Day TZ_NAME]\n{body}
  const _TIME_PREFIX_RE = /^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[+\-]\d{2}:\d{2} (?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) [A-Za-z0-9_+\-/]+\]\n/;
  function _stripTimePrefix(text) {
    return typeof text === 'string' ? text.replace(_TIME_PREFIX_RE, '') : text;
  }

  // Render debouncing
  let _renderDirty = false;
  let _renderRafId = null;

  // IME composition guard
  let _composing = false;

  // Cached active search provider (fetched once per session)
  let _searchProvider = '';
  const _PROVIDER_LOGOS = { brave: '\uD83E\uDD81', duckduckgo: '\uD83E\uDD86' }; // 🦁 🦆

  function _injectProviderBadge(summary, provider) {
    if (!summary || !provider) return;
    if (summary.querySelector('.chat-tool-provider')) return;
    const badge = document.createElement('span');
    badge.className = 'chat-tool-provider';
    badge.textContent = (_PROVIDER_LOGOS[provider] || '') + ' ' + provider;
    badge.title = 'Search provider: ' + provider;
    summary.appendChild(badge);
  }

  function _toolResultProvider(payloadOrSegment, content) {
    const direct = payloadOrSegment?.provider
      || payloadOrSegment?.search_provider
      || payloadOrSegment?.searchProvider;
    if (direct) return direct;
    if (!content) return '';
    try {
      const parsed = JSON.parse(content);
      return parsed.provider || '';
    } catch {
      const match = String(content).match(/"provider"\s*:\s*"([^"]+)"/);
      return match ? match[1] : '';
    }
  }

  // Slash-command menu
  let _slashOpen = false;
  let _slashIdx = 0;
  let _filteredCmds = [];
  const _SLASH_CMDS = [
    { cmd: '/new',     label: 'New chat',        desc: 'Start a fresh chat session in the current agent' },
    { cmd: '/reset',   label: 'Reset session',   desc: 'Clear session history' },
    { cmd: '/compact', label: 'Compact context',  desc: 'Compact session context' },
  ];

  // Tool icon mapping
  const _TOOL_EMOJI = {
    bash: '\uD83D\uDCBB',         // 💻
    read_file: '\uD83D\uDCC4',    // 📄
    write_file: '\u270F\uFE0F',   // ✏️
    edit_file: '\u270F\uFE0F',    // ✏️
    web_search: '\uD83D\uDD0D',   // 🔍
    search: '\uD83D\uDD0D',       // 🔍
    http_request: '\uD83C\uDF10', // 🌐
    web_fetch: '\uD83C\uDF10',    // 🌐
    list_files: '\uD83D\uDCC2',   // 📂
    memory_search: '\uD83E\uDDE0',// 🧠
    memory_store: '\uD83E\uDDE0', // 🧠
  };
  function _toolEmoji(name) {
    return _TOOL_EMOJI[name] || '\u26A1'; // ⚡ default
  }

  // Context-usage tracking
  let _totalTokens = 0;
  const _CTX_WARN_THRESHOLD = 170000;

  // Token visualization shim. Gated by window.OPENSQUILLA_FEATURES.tokenViz; when off
  // every method is a no-op so downstream call sites don't need to special-case
  // a missing widget. SavingsFX (popup) is independent of this flag.
  const _viz = (() => {
    const on = () => window.OPENSQUILLA_FEATURES && window.OPENSQUILLA_FEATURES.tokenViz === true;
    return {
      create(el) { if (on() && el && window.TokenWidget) window.TokenWidget.create(el); },
      update(d)  { if (on() && window.TokenWidget) window.TokenWidget.update(d); },
      reset()    { if (on() && window.TokenWidget) window.TokenWidget.reset(); },
      destroy()  { if (on() && window.TokenWidget) window.TokenWidget.destroy(); },
    };
  })();

  // Savings popup gating (product rules: routed savings obey a 10-minute
  // cooldown; cache hits bypass that cooldown; routed model changes suppress
  // only the current turn so the next same-model/cache-hit turn can surface).
  // _maybeFireSavingsPopup applies these; _resetSavingsPopupCooldown is
  // invoked on session boundaries so a fresh chat can fire on the very
  // first qualifying turn.
  const _SAVINGS_POPUP_COOLDOWN_MS = 10 * 60 * 1000;
  let _savingsPopupLastTs = 0;
  let _lastSavingsPopupIdentity = '';
  function _resetSavingsPopupCooldown() {
    _savingsPopupLastTs = 0;
    _lastSavingsPopupIdentity = '';
    if (window.SavingsFX) window.SavingsFX.resetStreak();
  }

  // Token widget accumulator
  let _usageAccum = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: null, routedTurns: 0, sessionSaved: 0 };
  let _usageModel = '';

  function _saveWidgetState() {
    if (!window.OPENSQUILLA_FEATURES?.tokenViz) return;
    if (!_sessionKey) return;
    try {
      localStorage.setItem('opensquilla-widget:' + _sessionKey, JSON.stringify({
        input: _usageAccum.input, output: _usageAccum.output,
        cost: _usageAccum.cost, model: _usageModel,
      }));
    } catch { /* quota exceeded — ignore */ }
  }

  function _restoreWidgetState() {
    if (!window.OPENSQUILLA_FEATURES?.tokenViz) return;
    if (!_sessionKey) return;
    try {
      const raw = localStorage.getItem('opensquilla-widget:' + _sessionKey);
      if (raw) {
        const d = JSON.parse(raw);
        _usageAccum.input = d.input || 0;
        _usageAccum.output = d.output || 0;
        _usageAccum.cost = d.cost || null;
        _usageModel = d.model || '';
        _viz.update({ ..._usageAccum, model: _usageModel });
      }
    } catch { /* corrupted — ignore */ }
  }

  async function _loadCurrentSessionUsage() {
    if (!_sessionKey) return;
    try {
      await _rpc.waitForConnection();
      const usage = await _rpc.call('usage.status');
      const sessions = usage?.sessions || [];
      const current = sessions.find(s =>
        (s.session || s.sessionKey || s.key) === _sessionKey
      );
      if (current) {
        _usageAccum.input = Number(current.input_tokens || current.inputTokens || 0);
        _usageAccum.output = Number(current.output_tokens || current.outputTokens || 0);
        _usageAccum.cacheRead = Number(current.cache_read_tokens || current.cacheReadTokens || 0);
        _usageAccum.cacheWrite = Number(current.cache_write_tokens || current.cacheWriteTokens || 0);
        const costVal = Number(current.cost_usd || current.costUsd || 0);
        _usageAccum.cost = costVal > 0 ? costVal : null;
        _usageModel = current.model || '';
        _viz.update({ ..._usageAccum, model: _usageModel });
        _saveWidgetState();
      }
    } catch { /* usage load optional */ }
  }

  // Messages (for export)
  let _messages = [];

  // Collapsed-header tracking (role + day dedup)
  let _lastHeaderRole = '';
  let _lastHeaderDay = '';   // 'YYYY-MM-DD'

  // DOM refs
  let _thread = null;
  let _textarea = null;
  let _sendBtn = null;
  let _sessionInput = null;
  let _sessionChip = null;
  let _attachPreview = null;
  let _slashEl = null;
  let _ctxWarn = null;
  let _fileInput = null;
  let _toolbar = null;
  let _elevatedPill = null;
  let _composer = null;
  let _composerObserver = null;

  /* ── Helpers ────────────────────────────────────────────────────────── */

  function _esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* ── Inline SVG icons local to chat.js (icons.js owned by another agent) ── */

  // 14px sliders icon — three horizontal rails with knobs at different
  // positions. Reads as "adjustable runtime modes" rather than "global config",
  // distinguishing this control from the sidebar Config (gear) entry.
  function _iconGear() {
    return '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" '
      + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
      + '<line x1="3" y1="6" x2="21" y2="6"/>'
      + '<line x1="3" y1="12" x2="21" y2="12"/>'
      + '<line x1="3" y1="18" x2="21" y2="18"/>'
      + '<circle cx="8" cy="6" r="2.2" fill="currentColor"/>'
      + '<circle cx="16" cy="12" r="2.2" fill="currentColor"/>'
      + '<circle cx="10" cy="18" r="2.2" fill="currentColor"/>'
      + '</svg>';
  }

  function _iconChevronDown() {
    return '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" '
      + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
      + '<polyline points="6 9 12 15 18 9"/></svg>';
  }

  /* ── Welcome / empty-state card ──────────────────────────────────────── */

  // Empty state — a single muted line, no interactive elements. The textarea
  // below is the entry point; the empty thread shouldn't compete with it.
  function _emptyStateHTML() {
    return '<div class="chat-empty">No messages yet.</div>';
  }

  /* ── Per-bubble hover action row (Copy / Regenerate / Edit) ───────── */

  function _iconRefreshSmall() {
    return '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" '
      + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
      + '<polyline points="23 4 23 10 17 10"/>'
      + '<path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>';
  }
  function _iconCopySmall() {
    return '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" '
      + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
      + '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>'
      + '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  }
  function _iconEditSmall() {
    return '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" '
      + 'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
      + '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>'
      + '<path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>';
  }

  // Append the hover-action row to a message bubble. Buttons are CSS-hidden
  // until the bubble is hovered/focus-within; click handling lives in
  // _bindHoverActions (delegated on the thread). The row is anchored inside
  // .msg-body so its absolute positioning aligns to the bubble's edge,
  // letting CSS float it in the bubble's outer side gutter — never in the
  // dead space between consecutive turns. Idempotent: history-render
  // rewrites body.innerHTML for tool calls and attachments, so callers
  // re-attach after those mutations.
  function _attachHoverActions(div, role) {
    if (!div || (role !== 'user' && role !== 'assistant')) return;
    const body = div.querySelector(':scope > .msg-body');
    if (!body) return;
    const existing = body.querySelector(':scope > .msg-actions');
    if (existing) existing.remove();
    const row = document.createElement('div');
    row.className = 'msg-actions';
    row.setAttribute('role', 'toolbar');
    row.setAttribute('aria-label', role === 'user' ? 'User message actions' : 'Assistant message actions');

    if (role === 'assistant') {
      row.innerHTML =
        '<button type="button" class="msg-action" data-action="copy" title="Copy message" aria-label="Copy message">'
        + _iconCopySmall() + '</button>'
        + '<button type="button" class="msg-action" data-action="regenerate" title="Regenerate" aria-label="Regenerate response">'
        + _iconRefreshSmall() + '</button>';
    } else {
      row.innerHTML =
        '<button type="button" class="msg-action" data-action="copy" title="Copy message" aria-label="Copy message">'
        + _iconCopySmall() + '</button>'
        + '<button type="button" class="msg-action" data-action="edit" title="Edit message" aria-label="Edit message">'
        + _iconEditSmall() + '</button>';
    }
    body.appendChild(row);
  }

  // Returns the rendered text content of a message bubble, stripping inline
  // action-row buttons and meta footers so the user's clipboard contains
  // only the message itself.
  function _extractBubbleText(div) {
    if (!div) return '';
    const body = div.querySelector(':scope > .msg-body');
    if (!body) return '';
    // .msg-attachment-text only appears on attachment-bearing user messages.
    const txtNode = body.querySelector('.msg-attachment-text');
    if (txtNode) return (txtNode.textContent || '').trim();
    // Strip nested .msg-actions inside the body (defensive — shouldn't exist).
    const clone = body.cloneNode(true);
    clone.querySelectorAll('.msg-actions, .msg-meta').forEach((n) => n.remove());
    return (clone.textContent || '').trim();
  }

  function _copyTextToClipboard(text) {
    if (!text) return Promise.resolve();
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } finally { ta.remove(); }
    return ok ? Promise.resolve() : Promise.reject(new Error('Copy failed'));
  }

  // Re-send the most recent user turn. Pops the trailing assistant bubble
  // from DOM + _messages and re-issues chat.send with the same text.
  function _regenerateLastTurn() {
    if (_isStreaming) {
      UI.toast('Wait for the current response to finish', 'warn', 2000);
      return;
    }
    // Find last user message in _messages.
    let lastUserIdx = -1;
    for (let i = _messages.length - 1; i >= 0; i--) {
      if (_messages[i].role === 'user') { lastUserIdx = i; break; }
    }
    if (lastUserIdx < 0) {
      UI.toast('No previous message to regenerate', 'info', 2000);
      return;
    }
    const userText = _messages[lastUserIdx].text || '';
    // Remove trailing assistant DOM bubbles and message records after that user turn.
    _messages.splice(lastUserIdx + 1);
    // Walk DOM: strip everything after the corresponding user .msg in the thread.
    if (_thread) {
      const userBubbles = _thread.querySelectorAll(':scope > .msg.user');
      const target = userBubbles[userBubbles.length - 1];
      if (target) {
        let nxt = target.nextElementSibling;
        while (nxt) {
          const toRemove = nxt;
          nxt = nxt.nextElementSibling;
          toRemove.remove();
        }
      }
    }
    _textarea.value = userText;
    _autoResizeTextarea();
    // Trigger send synchronously — _onSend will read _textarea.
    _onSend();
  }

  // Pop the user message back into the textarea for editing. Removes the
  // user bubble and any subsequent assistant bubbles + their _messages
  // records so the conversation cleanly rewinds to the moment before that
  // turn was sent.
  function _editUserBubble(bubble) {
    if (!bubble || _isStreaming) {
      if (_isStreaming) UI.toast('Wait for the current response to finish', 'warn', 2000);
      return;
    }
    const text = _extractBubbleText(bubble);
    // Find which user message index this corresponds to.
    const userBubbles = Array.from(_thread.querySelectorAll(':scope > .msg.user'));
    const idxAmongUser = userBubbles.indexOf(bubble);
    if (idxAmongUser < 0) return;
    // Find that user message in _messages (Nth user role).
    let count = -1;
    let cutIdx = -1;
    for (let i = 0; i < _messages.length; i++) {
      if (_messages[i].role === 'user') {
        count++;
        if (count === idxAmongUser) { cutIdx = i; break; }
      }
    }
    if (cutIdx >= 0) _messages.splice(cutIdx);
    // Strip from DOM: this user bubble onward.
    let nxt = bubble.nextElementSibling;
    bubble.remove();
    while (nxt) {
      const toRemove = nxt;
      nxt = nxt.nextElementSibling;
      toRemove.remove();
    }
    // If thread is now empty, restore welcome.
    if (_thread.children.length === 0) {
      _thread.innerHTML = _emptyStateHTML();
    }
    if (_textarea) {
      _textarea.value = text;
      _autoResizeTextarea();
      _textarea.focus();
      _textarea.setSelectionRange(text.length, text.length);
    }
  }

  function _bindHoverActions() {
    if (!_thread || _thread.dataset.hoverBound === '1') return;
    _thread.dataset.hoverBound = '1';
    _thread.addEventListener('click', (ev) => {
      const artifactBtn = ev.target.closest('[data-artifact-download]');
      if (artifactBtn) {
        ev.preventDefault();
        ev.stopPropagation();
        _downloadArtifact({
          id: artifactBtn.dataset.artifactId || '',
          name: artifactBtn.dataset.artifactName || 'artifact',
          download_url: artifactBtn.dataset.artifactDownload || '',
        });
        return;
      }
      const btn = ev.target.closest('.msg-action');
      if (!btn) return;
      ev.preventDefault();
      ev.stopPropagation();
      const bubble = btn.closest('.msg');
      if (!bubble) return;
      const action = btn.dataset.action;
      if (action === 'copy') {
        const text = _extractBubbleText(bubble);
        _copyTextToClipboard(text)
          .then(() => UI.toast('Copied', 'info', 1200))
          .catch((err) => UI.toast('Copy failed: ' + err.message, 'err', 2500));
      } else if (action === 'regenerate') {
        _regenerateLastTurn();
      } else if (action === 'edit') {
        _editUserBubble(bubble);
      }
    });
  }

  function _truncate(s, max = 200) {
    if (!s || s.length <= max) return s || '';
    return s.slice(0, max) + '\u2026';
  }

  function _relTime(ts) {
    if (!ts) return '';
    const d = typeof ts === 'number' ? new Date(ts) : new Date(ts);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  function _fmtTok(n) {
    if (!n) return '0';
    if (n >= 1_000_000) return `${+(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${+(n / 1_000).toFixed(1)}k`;
    return String(n);
  }

  const _TURN_META_LS = 'opensquilla.turnmeta.';
  function _storeTurnMeta(sessionKey, idx, model, input, output, saved) {
    try {
      const k = _TURN_META_LS + sessionKey;
      const arr = JSON.parse(localStorage.getItem(k) || '[]');
      arr[idx] = { model, input, output, saved: saved || null };
      localStorage.setItem(k, JSON.stringify(arr));
    } catch { /* ignore */ }
  }
  function _recallTurnMeta(sessionKey, idx) {
    try {
      const arr = JSON.parse(localStorage.getItem(_TURN_META_LS + sessionKey) || '[]');
      return arr[idx] || null;
    } catch { return null; }
  }

  function _savedUsageFromMeta(meta) {
    if (!meta || !meta.saved) return null;
    const saved = { ...meta.saved };
    if (!saved.model && !saved.routed_model && meta.model) saved.model = meta.model;
    return saved;
  }

  function _turnSavingsIdentity(u) {
    const model = u?.routed_model || u?.model || '';
    return model ? `${model}|${u?.routed_tier || ''}` : '';
  }

  function _attachTurnMeta(bubble, model, totalIn, totalOut, turnUsage) {
    if (!bubble) return;
    bubble.querySelectorAll(':scope > .msg-meta').forEach((el) => el.remove());
    const hasModel = model && model.trim();
    const hasTokens = totalIn > 0 || totalOut > 0;
    const u = turnUsage || {};
    const savingsDetailSuppressed = !!u.__savings_ui_suppressed;
    const streak = window.SavingsFX ? window.SavingsFX.getStreak().current | 0 : 0;
    const hasTier  = !!(u.routed_tier && u.routing_source && u.routing_source !== 'none');
    const turnSavedPct = (typeof u.total_savings_pct === 'number' && u.total_savings_pct > 0)
      ? u.total_savings_pct : 0;
    const hasSaved = !savingsDetailSuppressed && hasTier && turnSavedPct > 0;
    const hasCombo = hasSaved && streak >= 2;
    if (!hasModel && !hasTokens && !hasCombo && !hasSaved) return;
    const meta = document.createElement('div');
    meta.className = 'msg-meta';
    if (hasModel) {
      const shortModel = model.includes('/') ? model.split('/').pop() : model;
      const span = document.createElement('span');
      span.className = 'msg-meta__model';
      span.textContent = shortModel;
      meta.appendChild(span);
    }
    if (hasTokens) {
      const span = document.createElement('span');
      span.className = 'msg-meta__tokens';
      span.textContent = `↑${_fmtTok(totalIn)} ↓${_fmtTok(totalOut)}`;
      span.title = `Session API total — input: ${totalIn.toLocaleString()}, output: ${totalOut.toLocaleString()} tokens`;
      meta.appendChild(span);
    }
    if (hasSaved) {
      const span = document.createElement('span');
      const tier = turnSavedPct >= 65 ? ' msg-meta__saved--peak'
                  : turnSavedPct >= 45 ? ' msg-meta__saved--high'
                  : '';
      span.className = 'msg-meta__saved' + tier;
      span.title = `Squilla router routed this turn (~${Math.round(turnSavedPct)}% vs flagship)`;
      const NS = 'http://www.w3.org/2000/svg';
      const flame = document.createElementNS(NS, 'svg');
      flame.setAttribute('class', 'msg-meta__saved-flame');
      flame.setAttribute('viewBox', '0 0 16 16');
      flame.setAttribute('aria-hidden', 'true');
      flame.setAttribute('width', '1em');
      flame.setAttribute('height', '1em');
      const path = document.createElementNS(NS, 'path');
      path.setAttribute('d',
        'M8 16c3.4 0 6-2.55 6-5.78 0-3.05-2.7-4.6-2.7-7.55 0 0-1.55 1.45-2.5 4.4C8.55 4.5 8.4 1 6.5 0 6.6 3 4 4.45 4 7.6 4 11.05 5.65 16 8 16z'
      );
      path.setAttribute('fill', 'currentColor');
      flame.appendChild(path);
      span.appendChild(flame);
      const label = document.createElement('span');
      label.className = 'msg-meta__saved-label';
      label.textContent = window.SavingsFX
        ? window.SavingsFX.savingsLabel(turnSavedPct)
        : (turnSavedPct > 0 ? `Saved ~${Math.round(turnSavedPct)}%` : 'Cost optimized');
      span.appendChild(label);
      meta.appendChild(span);
    }
    if (hasCombo) {
      const span = document.createElement('span');
      const tier = streak >= 5 ? ' msg-meta__combo--blaze'
                  : streak >= 3 ? ' msg-meta__combo--hot'
                  : '';
      span.className = 'msg-meta__combo' + tier;
      span.title = 'Squilla router combo — ' + streak + ' consecutive savings turns';
      span.setAttribute('aria-label', 'Combo ' + streak);
      // Inline SVG flame — color is owned by CSS so it always reads as red,
      // independent of the OS-rendered emoji palette.
      const NS = 'http://www.w3.org/2000/svg';
      const flame = document.createElementNS(NS, 'svg');
      flame.setAttribute('class', 'msg-meta__combo-flame');
      flame.setAttribute('viewBox', '0 0 16 16');
      flame.setAttribute('aria-hidden', 'true');
      flame.setAttribute('width', '1em');
      flame.setAttribute('height', '1em');
      const path = document.createElementNS(NS, 'path');
      // Stylized flame silhouette, fill driven by currentColor.
      path.setAttribute('d',
        'M8 16c3.4 0 6-2.55 6-5.78 0-3.05-2.7-4.6-2.7-7.55 0 0-1.55 1.45-2.5 4.4C8.55 4.5 8.4 1 6.5 0 6.6 3 4 4.45 4 7.6 4 11.05 5.65 16 8 16z'
      );
      path.setAttribute('fill', 'currentColor');
      flame.appendChild(path);
      span.appendChild(flame);
      const label = document.createElement('span');
      label.className = 'msg-meta__combo-label';
      label.textContent = 'COMBO';
      span.appendChild(label);
      const count = document.createElement('span');
      count.className = 'msg-meta__combo-count';
      count.textContent = '×' + streak;
      span.appendChild(count);
      meta.appendChild(span);
    }
    bubble.appendChild(meta);
  }

  function _normalizeAgentId(agentId) {
    const raw = String(agentId || '').trim().toLowerCase();
    if (!raw || raw === 'default') return 'main';
    const normalized = raw.replace(/[^a-z0-9_-]/g, '-').replace(/^-+|-+$/g, '');
    return normalized && normalized !== 'default' ? normalized : 'main';
  }

  function _agentIdFromSessionKey(key) {
    const value = String(key || '').trim();
    if (!value.startsWith('agent:')) return 'main';
    return _normalizeAgentId(value.split(':')[1] || 'main');
  }

  function _webchatSessionKey(agentId, suffix = 'default') {
    return 'agent:' + _normalizeAgentId(agentId) + ':webchat:' + suffix;
  }

  function _genKey() {
    return _webchatSessionKey(_agentIdFromSessionKey(_sessionKey), Math.random().toString(36).slice(2, 10));
  }

  function _canonicalSessionKey(key) {
    const value = (key || '').trim();
    if (!value || value === 'default' || value === 'webchat:default') return _WEBCHAT_SESSION_KEY;
    if (value.startsWith('agent:default:')) return 'agent:main:' + value.slice('agent:default:'.length);
    if (value.startsWith('sess-')) return 'agent:main:webchat:' + value.slice('sess-'.length);
    return value;
  }

  function _persistSession(key) {
    const canonicalKey = _canonicalSessionKey(key);
    if (canonicalKey !== _sessionKey) _clearActiveTaskGroups();
    _sessionKey = canonicalKey;
    if (_sessionInput && _sessionInput.value !== canonicalKey) _sessionInput.value = canonicalKey;
    try { localStorage.setItem('opensquilla_active_session', canonicalKey); } catch {}
    try {
      const url = new URL(window.location);
      url.searchParams.set('session', canonicalKey);
      url.searchParams.delete('agent');
      history.replaceState(null, '', url);
    } catch {}
  }

  function _readSessionFromUrl() {
    try {
      const params = new URLSearchParams(window.location.search);
      return params.get('session') || '';
    } catch { return ''; }
  }

  function _readAgentFromUrl() {
    try {
      const params = new URLSearchParams(window.location.search);
      return params.get('agent') || '';
    } catch { return ''; }
  }

  /* ── Render ─────────────────────────────────────────────────────────── */

  function render(el) {
    _el = el;
    _rpc = App.getRpc();
    _applyRpcPolicy(_rpc?.policy || {});

    // Fetch active search provider on every render so config changes take effect immediately
    if (_rpc) {
      _rpc.call('tools.search_provider', {}).then(res => {
        if (res && res.provider) _searchProvider = res.provider;
      }).catch(() => { /* ignore; badge will fill in from result JSON */ });
    }

    // Session key priority: URL query > localStorage > canonical WebChat default
    const urlSession = _readSessionFromUrl();
    const urlAgent = _readAgentFromUrl();
    const storedSession = localStorage.getItem('opensquilla_active_session') || '';
    _sessionKey = _canonicalSessionKey(urlSession || (urlAgent ? _webchatSessionKey(urlAgent) : storedSession));
    _persistSession(_sessionKey);

    _el.innerHTML = `
      <div class="chat">
        <div class="chat-header">
          <div class="chat-header-left">
            <label class="chat-label">Chat session</label>
            <button type="button" class="chat-session-chip" id="chat-session-chip"
                    aria-label="Switch chat session" aria-haspopup="dialog" aria-expanded="false">
              <span class="chat-session-chip-key" id="chat-session-chip-key" title="${_esc(_sessionKey)}">${_esc(_sessionKey)}</span>
              <span class="chat-session-chip-caret" aria-hidden="true">${_iconChevronDown()}</span>
            </button>
            <button class="chat-session-copy-btn" id="chat-session-copy" title="Copy session key" aria-label="Copy session key">${icons.copy()}</button>
          </div>
          <div class="chat-header-right">
            <span class="chip" id="chat-run-status" title="Idle">Idle</span>
            <span class="chat-ctx-warn hidden" id="chat-ctx-warn">Context &gt; 85%</span>
          </div>
        </div>
        <div class="chat-body">
          <div class="chat-thread" id="chat-thread"
               role="region"
               aria-label="Chat conversation"
               aria-busy="false">
            ${_emptyStateHTML()}
          </div>
        </div>
        <div class="chat-pending hidden" id="chat-pending"></div>
        <div class="chat-slash hidden" id="chat-slash"></div>
        <div class="chat-composer" id="chat-composer">
          <div class="chat-attachments hidden" id="chat-attach-preview"></div>
          <div class="chat-bypass-warn hidden" id="chat-bypass-warn" role="status" aria-live="polite">
            <span class="chat-bypass-warn__glyph" aria-hidden="true">!</span>
            <span class="chat-bypass-warn__text">Approvals bypassed for this session</span>
          </div>
          <div class="chat-input-bar">
            <button class="btn btn--icon btn--ghost" id="chat-btn-attach" title="Attach files: PNG, JPEG, GIF, WEBP, PDF, TXT, MD, HTML, CSV, JSON">${icons.paperclip()}</button>
            <div class="chat-toolbar-wrap">
              <button type="button" class="btn btn--icon btn--ghost chat-toolbar-trigger" id="chat-toolbar-trigger"
                      title="Run modes — tool compress, approvals, router"
                      aria-label="Run modes"
                      aria-haspopup="dialog"
                      aria-expanded="false">${_iconGear()}<span class="chat-toolbar-trigger-dots" aria-hidden="true"><i data-dot="bypass"></i><i data-dot="compress"></i><i data-dot="router"></i></span></button>
              <div class="chat-toolbar-popover hidden" id="chat-toolbar-popover" role="dialog" aria-label="Composer settings">
                <div class="chat-toolbar-popover-arrow" aria-hidden="true"></div>
                <div class="chat-toolbar-popover-inner" id="chat-toolbar">
                  <div class="chat-toolbar-row">
                    <span class="chat-toolbar-row-label">Tool Compress</span>
                    <button class="chat-pill" id="pill-tool-compress"
                            title="Cycle tool result handling: off, truncate, or summarize with the configured cheap model">Tool Compress</button>
                  </div>
                  <div class="chat-toolbar-row">
                    <span class="chat-toolbar-row-label">Approvals</span>
                    <button class="chat-pill chat-pill--danger" id="pill-elevated"
                            title="Approval prompts active. Click to enable full bypass for this browser session.">Bypass Off</button>
                  </div>
                  <div class="chat-toolbar-row">
                    <span class="chat-toolbar-row-label">Squilla Router</span>
                    <div class="toggle-switch-wrap" id="pill-router-group" title="Squilla router">
                      <label class="toggle-switch" aria-label="Squilla Router">
                        <input type="checkbox" id="toggle-router" />
                        <span class="toggle-track"><span class="toggle-thumb"></span></span>
                      </label>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div class="chat-input-wrap">
              <textarea class="chat-textarea" id="chat-textarea" rows="1"
                        placeholder="Send a message..." maxlength="100000"
                        aria-label="Message to send"></textarea>
            </div>
            <button class="btn btn--icon btn--ghost" id="chat-btn-new" title="New chat session in the current agent" aria-label="New chat session in the current agent">${icons.plus()}</button>
            <button class="btn btn--icon btn--ghost" id="chat-btn-export" title="Export as Markdown">${icons.download()}</button>
            <button class="btn btn--icon btn--primary" id="chat-btn-send" title="Send (queues while streaming)">${icons.send()}</button>
            <button class="btn btn--icon btn--danger hidden" id="chat-btn-stop" title="Stop current response (Esc)">${icons.stop()}</button>
          </div>
        </div>
        <input type="file" id="chat-file-input" accept="image/png,image/jpeg,image/gif,image/webp,application/pdf,text/plain,text/markdown,text/html,text/csv,application/json,.md,.markdown" multiple class="hidden" />
      </div>`;

    // Cache DOM refs
    _thread       = _el.querySelector('#chat-thread');
    _textarea     = _el.querySelector('#chat-textarea');
    _sendBtn      = _el.querySelector('#chat-btn-send');
    _sessionInput = null;  // replaced by chip; session key lives in _sessionKey
    _sessionChip  = _el.querySelector('#chat-session-chip');
    _attachPreview = _el.querySelector('#chat-attach-preview');
    _pendingArea  = _el.querySelector('#chat-pending');
    _stopBtn      = _el.querySelector('#chat-btn-stop');
    _slashEl      = _el.querySelector('#chat-slash');
    _ctxWarn      = _el.querySelector('#chat-ctx-warn');
    _runStatusEl  = _el.querySelector('#chat-run-status');
    _fileInput    = _el.querySelector('#chat-file-input');
    _toolbar      = _el.querySelector('#chat-toolbar');
    _elevatedPill = _el.querySelector('#pill-elevated');
    _composer     = _el.querySelector('#chat-composer');

    _messages = [];
    _totalTokens = 0;
    _lastHeaderRole = '';
    _lastHeaderDay = '';
    _applySessionRunState({ run_status: 'idle' });

    _loadElevatedMode();
    _bindEvents();
    _bindToolbarPills();
    _bindToolbarTrigger();
    _bindSessionChip();
    _bindComposerResize();
    _bindHoverActions();
    _restoreWidgetState();
    _subscribeRpcEvents();
    _subscribeSession();
    _loadHistory();
    _loadFeatureToggles();

    // Autofocus chat input
    if (_textarea) _textarea.focus();
  }

  /* ── Toolbar Pills (feature toggles) ────────────────────────────────── */

  function _bindToolbarPills() {
    if (_elevatedPill) {
      _elevatedPill.addEventListener('click', () => {
        if (_elevatedUnavailable) {
          UI.toast(
            'Bypass requires a local owner session (loopback only).',
            'warn',
            4000,
          );
          return;
        }
        if (_elevatedMode) {
          _setElevatedMode('', { toast: true, sync: true });
          return;
        }
        const ok = window.confirm(
          'Enable Bypass All Permissions for this browser session? This maps to /elevated full: host execution, no approval prompts, and sensitive-path checks bypassed.'
        );
        if (ok) _setElevatedMode('full', { toast: true, sync: true });
      });
    }

    const elevatedListener = (event) => {
      _setElevatedMode(event?.detail?.mode || '', { toast: false, sync: false });
    };
    window.addEventListener('opensquilla:elevated-mode', elevatedListener);
    _unsubs.push(() => window.removeEventListener('opensquilla:elevated-mode', elevatedListener));

    const toolCompressBtn = _el.querySelector('#pill-tool-compress');
    if (toolCompressBtn) {
      toolCompressBtn.addEventListener('click', async () => {
        try {
          const cfg = await _rpc.call('config.get');
          const current = _resolveToolCompressMode(cfg?.agent_token_saving);
          const mode = _nextToolCompressMode(current);
          await _rpc.call('config.patch.safe', {
            patches: {
              'agent_token_saving.tool_result_compression_mode': mode,
              'agent_token_saving.tool_result_compression_enabled': mode !== 'off'
            }
          });
          _setToolCompressButton(toolCompressBtn, mode);
          UI.toast('Tool result compression: ' + mode.toUpperCase(), 'info');
        } catch (e) { UI.toast('Failed: ' + e.message, 'err'); }
      });
    }

    // Squilla Router toggle switch
    const routerToggle = _el.querySelector('#toggle-router');
    if (routerToggle) {
      routerToggle.addEventListener('change', async () => {
        const enabled = routerToggle.checked;
        try {
          const patches = { 'squilla_router.enabled': enabled };
          patches['squilla_router.rollout_phase'] = enabled ? 'full' : 'observe';
          await _rpc.call('config.patch.safe', {
            patches
          });
          _toolbarState.router = enabled;
          _refreshToolbarTriggerGlow();
          UI.toast('Squilla Router: ' + (enabled ? 'ON' : 'OFF'), 'info');
        } catch (e) {
          // Revert on failure
          routerToggle.checked = !enabled;
          UI.toast('Failed: ' + e.message, 'err');
        }
      });
    }

  }

  async function _loadFeatureToggles() {
    try {
      await _rpc.waitForConnection();
      const cfg = await _rpc.call('config.get');
      const toolCompressBtn = _el?.querySelector('#pill-tool-compress');
      if (toolCompressBtn) {
        _setToolCompressButton(
          toolCompressBtn,
          _resolveToolCompressMode(cfg?.agent_token_saving)
        );
      }
      const routerEnabled = (cfg?.squilla_router?.enabled ?? false) && cfg?.squilla_router?.rollout_phase === 'full';
      const routerToggle = _el?.querySelector('#toggle-router');
      if (routerToggle) routerToggle.checked = routerEnabled;
      _toolbarState.router = routerEnabled;
      _refreshToolbarTriggerGlow();

      // Load current session usage for the token widget (survives page refresh)
      await _loadCurrentSessionUsage();
    } catch { /* ignore */ }
  }

  function _resolveToolCompressMode(cfg) {
    const mode = cfg?.tool_result_compression_mode;
    if (mode === 'off' || mode === 'truncate' || mode === 'summarize') return mode;
    return (cfg?.tool_result_compression_enabled ?? true) ? 'truncate' : 'off';
  }

  function _nextToolCompressMode(mode) {
    if (mode === 'off') return 'truncate';
    if (mode === 'truncate') return 'summarize';
    return 'off';
  }

  function _setToolCompressButton(btn, mode) {
    const labels = { off: 'OFF', truncate: 'TRIM', summarize: 'SUMMARY' };
    btn.textContent = labels[mode] || 'TRIM';
    btn.classList.toggle('is-active', mode !== 'off');
    btn.classList.toggle('chat-pill--summary', mode === 'summarize');
    _toolbarState.toolCompress = mode;
    _refreshToolbarTriggerGlow();
  }

  /* ── Session Chip ────────────────────────────────────────────────────── */

  function _updateSessionChip(key) {
    _sessionKey = key;
    const chipKey = _el && _el.querySelector('#chat-session-chip-key');
    const copyBtn = _el && _el.querySelector('#chat-session-copy');
    if (chipKey) {
      chipKey.textContent = key;
      chipKey.title = key;
    }
    if (copyBtn) copyBtn.title = 'Copy session key: ' + key;
  }

  function _runStatusLabel(status) {
    const labels = {
      queued: 'Queued',
      running: 'Running',
      interrupted: 'Interrupted',
      failed: 'Failed',
      timeout: 'Timed out',
      cancelled: 'Cancelled',
      idle: 'Idle',
    };
    return labels[status] || 'Idle';
  }

  function _normalizeRunStatus(status) {
    const value = String(status || '').toLowerCase();
    if (value === 'abandoned') return 'interrupted';
    if (value === 'succeeded' || value === 'success' || value === 'complete') return 'idle';
    if (['queued', 'running', 'interrupted', 'failed', 'timeout', 'cancelled'].includes(value)) {
      return value;
    }
    return 'idle';
  }

  // Chip color mapping for the chat header run-status pill. Idle and cancelled
  // stay muted (plain chip) so finished sessions don't compete with active
  // ones for attention.
  function _runStatusChipClass(status) {
    return {
      queued: 'chip-warn',
      running: 'chip-ok',
      interrupted: 'chip-warn',
      failed: 'chip-danger',
      timeout: 'chip-warn',
    }[status] || '';
  }

  function _sessionRunStatus(source) {
    source = source || {};
    const active = source.active_task || source.activeTask || null;
    const last = source.last_task || source.lastTask || null;
    const activeStatus = active ? _normalizeRunStatus(active.status) : '';
    const rawStatus = source.run_status || source.runStatus || active?.status || last?.status || '';
    let status = _normalizeRunStatus(rawStatus);
    if (active && (activeStatus === 'queued' || activeStatus === 'running')) status = activeStatus;
    const task = active || last || null;
    return { status, label: _runStatusLabel(status), task };
  }

  function _taskGroupId(payload) {
    const id = payload && payload.group_id;
    return (typeof id === 'string' && id) ? id : '';
  }

  function _clearActiveTaskGroups() {
    _activeTaskGroups.clear();
  }

  function _activeTaskGroupRunState(payload = {}) {
    return {
      run_status: 'running',
      active_task: {
        ...(payload || {}),
        status: 'running',
        task_group_count: _activeTaskGroups.size,
      },
    };
  }

  function _noteTaskGroupActive(payload) {
    const groupId = _taskGroupId(payload);
    if (groupId) _activeTaskGroups.add(groupId);
    _applySessionRunState(_activeTaskGroupRunState(payload));
  }

  function _noteTaskGroupTerminal(payload, terminalStatus) {
    const groupId = _taskGroupId(payload);
    if (groupId) _activeTaskGroups.delete(groupId);
    if (_activeTaskGroups.size > 0) {
      _applySessionRunState(_activeTaskGroupRunState(payload));
      return;
    }
    _applySessionRunState({
      run_status: terminalStatus === 'failed' ? 'failed' : 'idle',
      last_task: { ...(payload || {}), status: terminalStatus },
    });
  }

  function _applySessionRunState(source) {
    const el = _runStatusEl || (_el && _el.querySelector('#chat-run-status'));
    if (!el) return;
    _runStatusEl = el;
    const state = _sessionRunStatus(source);
    el.className = `chip ${_runStatusChipClass(state.status)}`.trim();
    el.textContent = state.label;
    const taskId = state.task && state.task.task_id ? state.task.task_id : '';
    const reason = state.task && state.task.terminal_reason ? state.task.terminal_reason : '';
    el.title = [state.label, taskId, reason].filter(Boolean).join(' - ');
  }

  function _copySessionKeyToClipboard() {
    if (!_sessionKey) return Promise.reject(new Error('No session key'));
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      return navigator.clipboard.writeText(_sessionKey);
    }

    const textarea = document.createElement('textarea');
    textarea.value = _sessionKey;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    textarea.style.top = '0';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();

    let copied = false;
    try {
      copied = document.execCommand('copy');
    } finally {
      textarea.remove();
    }
    return copied
      ? Promise.resolve()
      : Promise.reject(new Error('Copy command failed'));
  }

  function _switchToSession(key) {
    if (!key || key === _sessionKey) return;
    _unsubscribeSession();
    _updateSessionChip(key);
    _persistSession(key);
    _messages = [];
    _pendingSessionIntent = 'new_chat';
    _pendingQueue = []; if (_pendingArea) _renderPendingQueue();
    _applySessionRunState({ run_status: 'idle' });
    _totalTokens = 0;
    _lastHeaderRole = '';
    _lastHeaderDay = '';
    _usageAccum = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: null, routedTurns: 0, sessionSaved: 0 };
    _usageModel = '';
    _viz.reset(); _resetSavingsPopupCooldown();
    _restoreWidgetState();
    _loadCurrentSessionUsage();
    _subscribeSession();
    _loadHistory();
  }

  function _bindSessionChip() {
    // The chip itself now acts as the dropdown trigger (one-control session
    // chip per the design review). The copy button stays as a sibling.
    const switchBtn = _el && _el.querySelector('#chat-session-chip');
    const copyBtn = _el && _el.querySelector('#chat-session-copy');
    if (!switchBtn && !copyBtn) return;

    if (copyBtn) {
      copyBtn.addEventListener('click', (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        _copySessionKeyToClipboard()
          .then(() => UI.toast('Session key copied', 'info', 1500))
          .catch((err) => UI.toast('Copy failed: ' + err.message, 'err', 3000));
      });
    }

    if (!switchBtn) return;

    let _popover = null;
    let _docHandlers = null;

    function _itemKey(item) {
      return typeof item === 'string' ? item : (item.key || item.session || item.sessionKey || '');
    }

    function _classifyKey(item) {
      const key = _itemKey(item);
      if (!key || key === 'unknown') return null;
      const channelKind = typeof item === 'object' && item
        ? (item.channel_kind || item.channelKind || item.channel || '')
        : '';
      const sourceKind = typeof item === 'object' && item
        ? (item.source_kind || item.sourceKind || '')
        : '';
      if (channelKind === 'webchat' || sourceKind === 'webui') return 'Web chat';
      if (channelKind === 'cli' || sourceKind === 'cli') return 'CLI';
      if (key.startsWith('agent:')) {
        if (key.includes(':webchat')) return 'Web chat';
        if (key.includes(':cli:') || key.includes(':standalone:')) return 'CLI';
        if (key.includes(':subagent')) return 'Sub-agents';
        return 'Agents';
      }
      if (key.startsWith('sess-')) return 'Sessions';
      return 'Other';
    }

    function _dismiss() {
      if (!_popover) return;
      try { _popover.remove(); } catch (_) { /* already detached */ }
      _popover = null;
      if (_docHandlers) {
        document.removeEventListener('mousedown', _docHandlers.click, true);
        document.removeEventListener('keydown', _docHandlers.key);
        _docHandlers = null;
      }
      if (switchBtn.isConnected) {
        switchBtn.classList.remove('is-active');
        switchBtn.setAttribute('aria-expanded', 'false');
      }
    }

    // Cleanup on view destroy.
    _unsubs.push(_dismiss);

    function _renderItems(list, sessions, filter, current) {
      list.innerHTML = '';
      const groups = { 'Web chat': [], CLI: [], 'Sub-agents': [], Agents: [], Sessions: [], Other: [] };
      for (const item of sessions) {
        const g = _classifyKey(item);
        if (g) groups[g].push(item);
      }
      const f = (filter || '').toLowerCase();
      let total = 0;
      for (const [label, items] of Object.entries(groups)) {
        const visible = f ? items.filter(item => _itemKey(item).toLowerCase().includes(f)) : items;
        if (!visible.length) continue;
        total += visible.length;
        const group = document.createElement('div');
        group.className = 'chat-session-popover-group';
        const lbl = document.createElement('div');
        lbl.className = 'chat-session-popover-group-label';
        lbl.textContent = label;
        group.appendChild(lbl);
        for (const item of visible) {
          const k = _itemKey(item);
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = 'chat-session-popover-item';
          if (k === current) btn.classList.add('is-current');
          const span = document.createElement('span');
          span.className = 'chat-session-popover-item-key';
          span.textContent = k;
          span.title = k;
          btn.appendChild(span);
          const run = _sessionRunStatus(item);
          if (run.status !== 'idle') {
            const runTag = document.createElement('span');
            runTag.className = `chat-session-popover-item-run chat-session-popover-item-run--${run.status}`;
            runTag.textContent = run.label;
            btn.appendChild(runTag);
          }
          if (k === current) {
            const tag = document.createElement('span');
            tag.className = 'chat-session-popover-item-tag';
            tag.textContent = 'current';
            btn.appendChild(tag);
          }
          btn.addEventListener('click', () => {
            _dismiss();
            if (k !== current) _switchToSession(k);
          });
          group.appendChild(btn);
        }
        list.appendChild(group);
      }
      if (!total) {
        const empty = document.createElement('div');
        empty.className = 'chat-session-popover-empty';
        empty.textContent = f ? 'No matches.' : 'No sessions found.';
        list.appendChild(empty);
      }
    }

    switchBtn.addEventListener('click', async (ev) => {
      ev.stopPropagation();
      // Toggle off if already open.
      if (_popover) { _dismiss(); return; }

      const chip = _el.querySelector('#chat-session-chip');
      if (!chip) return;

      // Build popover skeleton.
      const pop = document.createElement('div');
      pop.className = 'chat-session-popover';
      pop.setAttribute('role', 'dialog');
      pop.setAttribute('aria-label', 'Switch session');

      const search = document.createElement('input');
      search.type = 'search';
      search.className = 'chat-session-popover-search';
      search.placeholder = 'Search sessions…';
      search.autocomplete = 'off';
      search.spellcheck = false;
      pop.appendChild(search);

      const list = document.createElement('div');
      list.className = 'chat-session-popover-list';
      list.innerHTML = '<div class="chat-session-popover-empty">Loading…</div>';
      pop.appendChild(list);

      // Anchor below the chip via fixed positioning so the popover escapes
      // any `overflow:hidden` ancestor (the chip itself clips its key text).
      const rect = chip.getBoundingClientRect();
      pop.style.position = 'fixed';
      pop.style.left = rect.left + 'px';
      pop.style.top = (rect.bottom + 4) + 'px';
      document.body.appendChild(pop);
      _popover = pop;
      switchBtn.classList.add('is-active');
      switchBtn.setAttribute('aria-expanded', 'true');

      // Dismiss on outside-click / Escape. Mousedown (capture phase) so we
      // beat any item click handler that needs a clean tree.
      _docHandlers = {
        click: (e) => {
          if (pop.contains(e.target) || switchBtn.contains(e.target)) return;
          _dismiss();
        },
        key: (e) => {
          if (e.key === 'Escape') { e.stopPropagation(); _dismiss(); }
        },
      };
      // Defer registration so the click that opened us isn't picked up.
      setTimeout(() => {
        if (!_popover) return;
        document.addEventListener('mousedown', _docHandlers.click, true);
        document.addEventListener('keydown', _docHandlers.key);
      }, 0);

      // Fetch session list.
      let sessions = [];
      let fetched = false;
      try {
        const resp = await fetch('/api/sessions');
        if (resp.ok) {
          const data = await resp.json();
          const raw = data.sessions || data.keys || [];
          sessions = raw.filter((s) => !!(typeof s === 'string' ? s : (s.key || s.session || s.sessionKey)));
          fetched = true;
        }
      } catch (_) { /* network error — fall through to prompt */ }

      // Bail if dismissed during await.
      if (!_popover) return;

      if (!fetched) {
        search.placeholder = 'Enter session key...';
        search.value = _sessionKey || '';
        list.innerHTML = '';
        const note = document.createElement('div');
        note.className = 'chat-session-popover-empty';
        note.textContent = 'Session list unavailable. Enter a key above.';
        list.appendChild(note);
        const manualBtn = document.createElement('button');
        manualBtn.type = 'button';
        manualBtn.className = 'chat-session-popover-item';
        const span = document.createElement('span');
        span.className = 'chat-session-popover-item-key';
        span.textContent = 'Switch to typed session';
        manualBtn.appendChild(span);
        const switchTyped = () => {
          const key = search.value.trim();
          if (!key) return;
          _dismiss();
          if (key !== _sessionKey) _switchToSession(key);
        };
        manualBtn.addEventListener('click', switchTyped);
        search.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            switchTyped();
          }
        });
        search.focus();
        search.select();
        return;
      }

      _renderItems(list, sessions, '', _sessionKey);
      search.addEventListener('input', () => {
        _renderItems(list, sessions, search.value.trim(), _sessionKey);
      });
      search.focus();
    });
  }

  /* ── Composer Toolbar Popover (gear button) ────────────────────────── */

  // Track non-default state on three controls so the gear glows accent only
  // when at least one is set away from defaults: bypass on, tool-compress
  // != truncate, OR router off.
  let _toolbarState = {
    bypass: false,        // true when elevated mode is on
    toolCompress: 'truncate', // 'off' | 'truncate' | 'summarize'
    router: true,         // false when router toggle is off
  };

  function _toolbarTriggerActive() {
    if (_toolbarState.bypass) return true;
    if (_toolbarState.toolCompress !== 'truncate') return true;
    if (_toolbarState.router === false) return true;
    return false;
  }

  function _refreshToolbarTriggerGlow() {
    const trigger = _el && _el.querySelector('#chat-toolbar-trigger');
    if (!trigger) return;
    trigger.classList.toggle('is-glowing', _toolbarTriggerActive());
    // Per-toggle status dots — each lights independently so a glance at the
    // composer reveals which mode is non-default, not just that something is.
    const bypass = !!_toolbarState.bypass;
    const compress = _toolbarState.toolCompress !== 'truncate';
    const routerOff = _toolbarState.router === false;
    trigger.classList.toggle('has-dot-bypass', bypass);
    trigger.classList.toggle('has-dot-compress', compress);
    trigger.classList.toggle('has-dot-router', routerOff);
    // Bypass warning chip — only "Approvals bypassed" rises to a visible chip.
    // Tool compress and router-off are non-default but not safety-critical.
    const warn = _el && _el.querySelector('#chat-bypass-warn');
    if (warn) warn.classList.toggle('hidden', !bypass);
  }

  function _bindToolbarTrigger() {
    const trigger = _el && _el.querySelector('#chat-toolbar-trigger');
    const popover = _el && _el.querySelector('#chat-toolbar-popover');
    if (!trigger || !popover) return;

    let _open = false;
    let _docHandlers = null;

    function _close() {
      if (!_open) return;
      _open = false;
      popover.classList.add('hidden');
      popover.classList.remove('is-open');
      trigger.classList.remove('is-active');
      trigger.setAttribute('aria-expanded', 'false');
      if (_docHandlers) {
        document.removeEventListener('mousedown', _docHandlers.click, true);
        document.removeEventListener('keydown', _docHandlers.key);
        _docHandlers = null;
      }
    }

    function _show() {
      if (_open) return;
      _open = true;
      popover.classList.remove('hidden');
      // Force a reflow so the .is-open transition runs even if we just removed .hidden
      // eslint-disable-next-line no-unused-expressions
      popover.offsetHeight;
      popover.classList.add('is-open');
      trigger.classList.add('is-active');
      trigger.setAttribute('aria-expanded', 'true');

      _docHandlers = {
        click: (e) => {
          if (popover.contains(e.target) || trigger.contains(e.target)) return;
          _close();
        },
        key: (e) => {
          if (e.key === 'Escape') { e.stopPropagation(); _close(); }
        },
      };
      // Defer registration so the click that opened us isn't picked up.
      setTimeout(() => {
        if (!_open) return;
        document.addEventListener('mousedown', _docHandlers.click, true);
        document.addEventListener('keydown', _docHandlers.key);
      }, 0);
    }

    trigger.addEventListener('click', (ev) => {
      ev.stopPropagation();
      if (_open) _close(); else _show();
    });

    // Cleanup on view destroy.
    _unsubs.push(_close);

    _refreshToolbarTriggerGlow();
  }

  /* ── Composer Resize Observer (mobile overlap fix) ───────────────────── */

  function _bindComposerResize() {
    if (!_composer) return;
    const chatEl = _el.querySelector('.chat');
    if (!chatEl) return;

    const update = () => {
      const h = _composer.getBoundingClientRect().height;
      chatEl.style.setProperty('--composer-h', h + 'px');
      // Propagate to root so global consumers (e.g. .toast-stack on mobile,
      // which lives at body level) can lift themselves above the composer.
      document.documentElement.style.setProperty('--composer-h', h + 'px');
      // Swap placeholder for the cramped phone width — iOS forces 16px on
      // inputs to prevent auto-zoom, which makes "Send a message..." truncate
      // to "Send a…". A shorter placeholder reads cleanly on every iPhone.
      if (_textarea) {
        const w = window.innerWidth;
        const want = w <= 480 ? 'Message...' : 'Send a message...';
        if (_textarea.getAttribute('placeholder') !== want) {
          _textarea.setAttribute('placeholder', want);
        }
      }
    };

    update(); // initial measurement
    _composerObserver = new ResizeObserver(update);
    _composerObserver.observe(_composer);
    // Window resize covers viewport changes (phone rotation, dev-tools width
     // change) where the composer height stays constant but the placeholder
     // breakpoint may flip.
    window.addEventListener('resize', update);
    _unsubs.push(() => {
      if (_composerObserver) { _composerObserver.disconnect(); _composerObserver = null; }
      window.removeEventListener('resize', update);
    });
  }

  function _normalizeElevatedMode(mode) {
    return mode === 'on' || mode === 'bypass' || mode === 'full' ? mode : '';
  }

  function _loadElevatedMode() {
    let mode = '';
    try { mode = localStorage.getItem(_ELEVATED_MODE_KEY) || ''; } catch {}
    _setElevatedMode(mode, { persist: false, toast: false, sync: true });
  }

  function _setElevatedMode(mode, options = {}) {
    const normalized = _normalizeElevatedMode(mode);
    _elevatedMode = normalized;
    if (options.persist !== false) {
      try {
        if (normalized) localStorage.setItem(_ELEVATED_MODE_KEY, normalized);
        else localStorage.removeItem(_ELEVATED_MODE_KEY);
      } catch {}
    }
    _toolbarState.bypass = !!normalized;
    _refreshToolbarTriggerGlow();
    _updateElevatedPill();
    if (options.toast) {
      UI.toast(
        normalized
          ? `Bypass mode: ${normalized}`
          : 'Bypass mode disabled',
        normalized ? 'warn' : 'info',
        2500
      );
    }
    if (options.sync) _syncElevatedMode(normalized);
  }

  async function _syncElevatedMode(mode) {
    if (!_sessionKey || _elevatedUnavailable) return;
    try {
      const resp = await fetch('/api/elevated-mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sessionKey: _sessionKey, mode: mode || 'off' }),
      });
      if (resp.status === 403) {
        // Owner-only endpoint, but the current connection isn't a local-owner
        // session (typically: gateway bound to 0.0.0.0). Latch the disabled
        // state, clear any cached "full" mode, refresh the pill UI, and let
        // the user know once instead of toasting on every click.
        _elevatedUnavailable = true;
        try { localStorage.removeItem(_ELEVATED_MODE_KEY); } catch {}
        _elevatedMode = '';
        _updateElevatedPill();
        UI.toast(
          'Bypass requires a local owner session (loopback only).',
          'warn',
          4000,
        );
        return;
      }
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const payload = await resp.json().catch(() => ({}));
      if (payload?.resolvedPending && window.ApprovalMonitor) {
        ApprovalMonitor.pollNow();
      }
    } catch (err) {
      UI.toast('Failed to sync bypass mode: ' + err.message, 'err', 3500);
    }
  }

  function _updateElevatedPill() {
    if (!_elevatedPill) return;
    if (_elevatedUnavailable) {
      _elevatedPill.classList.remove('is-active');
      _elevatedPill.classList.add('chat-pill--disabled');
      _elevatedPill.textContent = 'Bypass N/A';
      _elevatedPill.title =
        'Bypass requires a local owner session. The gateway is bound to a non-loopback address, so this client cannot toggle elevated mode.';
      _elevatedPill.setAttribute('aria-disabled', 'true');
      return;
    }
    const active = !!_elevatedMode;
    _elevatedPill.classList.remove('chat-pill--disabled');
    _elevatedPill.removeAttribute('aria-disabled');
    _elevatedPill.classList.toggle('is-active', active);
    _elevatedPill.textContent = active ? `Bypass ${_elevatedMode.toUpperCase()}` : 'Bypass Off';
    _elevatedPill.title = active
      ? 'Bypass all permissions is ON for this browser session. Click to turn it off.'
      : 'Approval prompts active. Click to enable full bypass for this browser session.';
  }

  /* ── Event Bindings ─────────────────────────────────────────────────── */

  function _bindEvents() {
    const attachBtn = _el.querySelector('#chat-btn-attach');
    const newBtn    = _el.querySelector('#chat-btn-new');
    const exportBtn = _el.querySelector('#chat-btn-export');

    // Send
    _sendBtn.addEventListener('click', _onSend);
    if (_stopBtn) _stopBtn.addEventListener('click', _onStop);
    if (_pendingArea) _pendingArea.addEventListener('click', _onPendingAreaClick);

    // Session key is now managed via chip + switch (see _bindSessionChip).
    // _sessionInput is null; no listener needed here.

    // New session button
    newBtn.addEventListener('click', () => {
      _unsubscribeSession();
      const key = _genKey();
      _updateSessionChip(key);
      _persistSession(key);
      _pendingSessionIntent = 'new_chat'; _pendingQueue = []; if (_pendingArea) _renderPendingQueue();
      _messages = [];
      _totalTokens = 0;
      _lastHeaderRole = '';
      _lastHeaderDay = '';
      _usageAccum = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: null, routedTurns: 0, sessionSaved: 0 };
      _usageModel = '';
      _viz.reset(); _resetSavingsPopupCooldown();
      _thread.innerHTML = _emptyStateHTML(); // safe: static string, no user data
      _subscribeSession();
      UI.toast('New chat session in the current agent: ' + key, 'info');
    });

    // Export
    exportBtn.addEventListener('click', _exportMarkdown);

    // File picker
    attachBtn.addEventListener('click', () => _fileInput.click());
    _fileInput.addEventListener('change', () => {
      Array.from(_fileInput.files).forEach(_addAttachment);
      _fileInput.value = '';
    });

    // IME composition
    _textarea.addEventListener('compositionstart', () => { _composing = true; });
    _textarea.addEventListener('compositionend', () => { _composing = false; });

    // Textarea auto-resize + history-cursor reset on user-typed input.
    // Programmatic writes via _setTextareaProgrammatic temporarily set
    // _suppressHistoryReset so ↑/↓ navigation doesn't clobber its own state.
    _textarea.addEventListener('input', () => {
      _autoResizeTextarea();
      _handleSlashInput();
      if (!_suppressHistoryReset) {
        _inputHistoryIdx = null;
        _inputHistoryDraft = '';
      }
    });

    // Keyboard: Enter to send; slash navigation; ↑/↓ history; Alt+↑/↓ pending edit.
    // ESC streaming abort lives on the document-level handler below so it works
    // regardless of focus.
    _textarea.addEventListener('keydown', (e) => {
      if (_composing || e.isComposing || e.keyCode === 229) return;

      // Slash menu navigation takes precedence over history / pending bindings.
      if (_slashOpen) {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          _slashIdx = Math.min(_slashIdx + 1, _filteredCmds.length - 1);
          _renderSlashMenu();
          return;
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          _slashIdx = Math.max(_slashIdx - 1, 0);
          _renderSlashMenu();
          return;
        }
        if (e.key === 'Enter' || e.key === 'Tab') {
          if (_filteredCmds.length > 0) {
            e.preventDefault();
            _selectSlashCmd(_filteredCmds[_slashIdx]);
            return;
          }
        }
        if (e.key === 'Escape') {
          e.preventDefault();
          _closeSlashMenu();
          return;
        }
      }

      // ESC inside textarea: when not streaming, clear the input. The
      // streaming-abort path is handled by _onDocKeydown so it works from
      // any focus context. Slash menu close is already handled above.
      if (e.key === 'Escape' && !_isStreaming && _pendingQueue.length === 0 && _textarea.value) {
        e.preventDefault();
        _textarea.value = '';
        _autoResizeTextarea();
        return;
      }

      // Alt+↑: tail-pop the most-recent pending into textarea for editing.
      if (e.key === 'ArrowUp' && e.altKey && _pendingQueue.length > 0) {
        e.preventDefault();
        _popPendingTail();
        return;
      }

      // Alt+↓: enqueue current textarea content (if non-empty and queue not full).
      if (e.key === 'ArrowDown' && e.altKey && _textarea.value && _pendingQueue.length < _MAX_PENDING) {
        e.preventDefault();
        _enqueueCurrentInput();
        return;
      }

      // Plain ↑: walk backwards through sent-message history when the
      // textarea is empty (entering nav mode) OR when we're already
      // navigating (continue further back). Without the second clause,
      // the first ↑ fills the textarea and the next ↑ would silently
      // fail the empty-textarea guard, stalling navigation after one step.
      if (e.key === 'ArrowUp' && !e.altKey && !e.shiftKey
          && (!_textarea.value || _inputHistoryIdx !== null)) {
        if (_cycleHistory(-1)) {
          e.preventDefault();
          return;
        }
      }

      // Plain ↓: walk forward only when already navigating history. ↓ never
      // enters nav mode on its own — that's a deliberate choice to keep a
      // first-press ↓ from doing anything surprising on a fresh composer.
      if (e.key === 'ArrowDown' && !e.altKey && !e.shiftKey && _inputHistoryIdx !== null) {
        if (_cycleHistory(1)) {
          e.preventDefault();
          return;
        }
      }

      // Enter to send (no shift)
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        _onSend();
      }
    });

    // Document-level ESC: works regardless of focus. Priority chain mirrors
    // claude-code-rebuilt useCancelRequest:
    //   1. streaming  → _onStop (which also recovers pending)
    //   2. pending    → _popAllPendingIntoComposer
    //   3. otherwise drop through to the textarea handler / popovers / no-op
    //
    // This handler is registered on view mount, before any popover / modal /
    // search-bar opens its own document-level keydown handler. Since handlers
    // on the same target+phase fire in registration order, we run FIRST — so
    // we can't rely on later overlays' stopPropagation/preventDefault to
    // signal "ESC already consumed." Two complementary gates handle that:
    //   - e.defaultPrevented: catches target-phase consumers (slash menu close
    //     in the textarea keydown handler), which fires before us.
    //   - DOM probe: catches sibling document-level consumers that haven't
    //     run yet — if any overlay is currently visible, defer to its handler
    //     instead of treating ESC as a turn abort.
    function _onDocKeydown(e) {
      if (e.key !== 'Escape') return;
      if (typeof Router !== 'undefined' && Router.currentPath && Router.currentPath() !== '/chat') return;
      if (e.defaultPrevented) return;
      if (_chatOverlayVisible()) return;
      if (_isStreaming) {
        e.preventDefault();
        _onStop();
        return;
      }
      const target = e.target;
      const inEditable = target && (
        target === _textarea
        || target.tagName === 'INPUT'
        || target.tagName === 'TEXTAREA'
        || target.isContentEditable
      );
      if (inEditable) return; // textarea handler will deal with the empty-clear case
      if (_pendingQueue.length > 0) {
        e.preventDefault();
        _popAllPendingIntoComposer();
      }
    }
    document.addEventListener('keydown', _onDocKeydown);
    _unsubs.push(() => document.removeEventListener('keydown', _onDocKeydown));

    // Drag & drop on thread
    _thread.addEventListener('dragover', (e) => {
      e.preventDefault();
      _thread.classList.add('drag-over');
    });
    _thread.addEventListener('dragleave', () => {
      _thread.classList.remove('drag-over');
    });
    _thread.addEventListener('drop', (e) => {
      e.preventDefault();
      _thread.classList.remove('drag-over');
      Array.from(e.dataTransfer.files).forEach(_addAttachment);
    });

    // Clipboard paste (images)
    const pasteHandler = (e) => {
      if (Router.currentPath() !== '/chat') return;
      const items = e.clipboardData && e.clipboardData.items;
      if (!items) return;
      for (let i = 0; i < items.length; i++) {
        if (items[i].type.startsWith('image/')) {
          const file = items[i].getAsFile();
          if (file) _addAttachment(file);
        }
      }
    };
    document.addEventListener('paste', pasteHandler);
    _unsubs.push(() => document.removeEventListener('paste', pasteHandler));

    // Auto-scroll detection
    _thread.addEventListener('scroll', () => {
      const gap = _thread.scrollHeight - _thread.scrollTop - _thread.clientHeight;
      _autoScroll = gap < 60;
    });

    // Pill toggle behavior is handled by _bindToolbarPills after the RPC write succeeds.
  }

  function _autoResizeTextarea() {
    _textarea.style.height = 'auto';
    _textarea.style.height = Math.min(_textarea.scrollHeight, 160) + 'px';
  }

  /* ── Slash Command Menu ─────────────────────────────────────────────── */

  function _handleSlashInput() {
    const val = _textarea.value;
    if (val.startsWith('/') && !val.includes(' ')) {
      const query = val.slice(1).toLowerCase();
      _filteredCmds = _SLASH_CMDS.filter(c => c.cmd.slice(1).startsWith(query));
      if (_filteredCmds.length > 0) {
        _slashOpen = true;
        _slashIdx = 0;
        _renderSlashMenu();
        return;
      }
    }
    _closeSlashMenu();
  }

  function _renderSlashMenu() {
    if (!_slashEl || _filteredCmds.length === 0) { _closeSlashMenu(); return; }
    let html = '';
    _filteredCmds.forEach((c, i) => {
      const active = i === _slashIdx ? ' chat-slash-item--active' : '';
      html += `<div class="chat-slash-item${active}" data-idx="${i}">
        <span class="chat-slash-cmd">${_esc(c.cmd)}</span>
        <span class="chat-slash-desc">${_esc(c.desc)}</span>
      </div>`;
    });
    _slashEl.innerHTML = html;
    _slashEl.classList.remove('hidden');

    // Click to select
    _slashEl.querySelectorAll('.chat-slash-item').forEach((item) => {
      item.addEventListener('click', () => {
        _selectSlashCmd(_filteredCmds[parseInt(item.dataset.idx)]);
      });
    });
  }

  function _closeSlashMenu() {
    _slashOpen = false;
    _filteredCmds = [];
    if (_slashEl) {
      _slashEl.classList.add('hidden');
      _slashEl.innerHTML = '';
    }
  }

  function _selectSlashCmd(cmd) {
    _closeSlashMenu();
    _textarea.value = '';
    _autoResizeTextarea();

    switch (cmd.cmd) {
      case '/new': {
        _unsubscribeSession();
        const key = _genKey();
        _updateSessionChip(key);
        _persistSession(key);
        _pendingSessionIntent = 'new_chat'; _pendingQueue = []; if (_pendingArea) _renderPendingQueue();
        _messages = [];
        _totalTokens = 0;
        _lastHeaderRole = '';
        _lastHeaderDay = '';
        _usageAccum = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: null, routedTurns: 0, sessionSaved: 0 };
        _usageModel = '';
        _viz.reset(); _resetSavingsPopupCooldown();
        _thread.innerHTML = _emptyStateHTML(); // safe: static string, no user data
        _subscribeSession();
        UI.toast('New chat session in the current agent: ' + key, 'info');
        break;
      }
      case '/reset':
        _rpc.call('sessions.reset', { key: _sessionKey })
          .then(() => {
            _messages = [];
            _pendingQueue = [];
            if (_pendingArea) _renderPendingQueue();
            _totalTokens = 0;
            _clearActiveTaskGroups();
            _thread.innerHTML = _emptyStateHTML();
            UI.toast('Session reset', 'info');
          })
          .catch((err) => UI.toast('Reset failed: ' + err.message, 'err'));
        break;
      case '/compact':
        _rpc.call('sessions.contextCompact', { key: _sessionKey })
          .then((result) => {
            if (result && result.compacted) {
              const summaryLen = Number(result.summary_len || 0);
              UI.toast(
                'Context compacted' + (summaryLen ? ' (summary ' + summaryLen + ' chars)' : ''),
                'info'
              );
            } else {
              UI.toast('Context already compact enough', 'info');
            }
          })
          .catch((err) => UI.toast('Compact failed: ' + err.message, 'err'));
        break;
    }
  }

  /* ── Session Message Subscription ───────────────────────────────────── */

  async function _subscribeSession() {
    if (!_rpc || !_sessionKey) return;
    try {
      await _rpc.waitForConnection();
      const params = { key: _sessionKey };
      params.since_stream_seq = _lastStreamSeq;
      const res = await _rpc.call('sessions.messages.subscribe', params);
      if (res && res.subscribed === false) throw new Error('No subscription manager available');
      _applySessionRunState(res);
      if (res && res.replay_complete === false) {
        _lastStreamSeq = typeof res.current_stream_seq === 'number' ? res.current_stream_seq : 0;
        UI.toast('Session stream gap detected; reloading transcript.', 'warn', 5000);
        _loadHistory();
      } else if (res && typeof res.current_stream_seq === 'number') {
        _lastStreamSeq = Math.max(_lastStreamSeq, res.current_stream_seq);
      }
      if (_isStreaming) _resetStreamIdleTimer();
    } catch (err) {
      UI.toast('Session stream subscription failed: ' + (err?.message || err), 'err', 6000);
    }
  }

  async function _unsubscribeSession() {
    if (!_rpc || !_sessionKey) return;
    try {
      await _rpc.call('sessions.messages.unsubscribe', { key: _sessionKey });
    } catch { /* ignore */ }
  }

  /* ── RPC Event Subscriptions ────────────────────────────────────────── */

  function _subscribeRpcEvents() {
    const approvalsPendingListener = (event) => {
      const pending = Array.isArray(event?.detail?.pending) ? event.detail.pending : [];
      const hasPendingForCurrentSession = pending.some((item) =>
        (item.sessionKey || item.session_key || '') === _sessionKey
      );
      _setStreamIdlePausedForApproval(hasPendingForCurrentSession);
    };
    window.addEventListener('opensquilla:approvals-pending', approvalsPendingListener);
    _unsubs.push(() => window.removeEventListener('opensquilla:approvals-pending', approvalsPendingListener));

    // Text delta: accumulate into streaming bubble
    _unsubs.push(_rpc.on('session.event.text_delta', (payload) => {
      if (_isStaleEpoch(payload)) return;
      _noteStreamSeq(payload);
      _resetStreamIdleTimer();
      _appendDelta(payload.text || '');
    }));

    // Tool call events (engine emits tool_use_start)
    _unsubs.push(_rpc.on('session.event.tool_use_start', (payload) => {
      if (_isStaleEpoch(payload)) return;
      if (_aborted) return;
      _noteStreamSeq(payload);
      _resetStreamIdleTimer();
      _appendToolCall(payload);
    }));

    // Tool result events
    _unsubs.push(_rpc.on('session.event.tool_result', (payload) => {
      if (_isStaleEpoch(payload)) return;
      if (_aborted) return;
      _noteStreamSeq(payload);
      _resetStreamIdleTimer();
      _appendToolResult(payload);
    }));

    _unsubs.push(_rpc.on('session.event.artifact', (payload) => {
      if (_isStaleEpoch(payload)) return;
      if (_aborted) return;
      _noteStreamSeq(payload);
      _resetStreamIdleTimer();
      _appendArtifact(payload);
    }));

    _unsubs.push(_rpc.on('session.event.subagent_completion', (payload) => {
      if (_isStaleEpoch(payload)) return;
      if (_aborted) return;
      _noteStreamSeq(payload);
      _appendSubagentCompletion(payload);
    }));

    // Agent state transitions (thinking → streaming → tool_calling → done)
    _unsubs.push(_rpc.on('session.event.state_change', (payload) => {
      if (_isStaleEpoch(payload)) return;
      if (!payload || _aborted) return;
      _noteStreamSeq(payload);
      _resetStreamIdleTimer();
      const to = payload.to_state || payload.toState || '';
      // Only use state_change to SHOW thinking indicator (on thinking/tool_calling
      // transitions). Never hide it here — hiding is handled by _ensureStreamBubble()
      // when the first text_delta or tool_use_start arrives, which is more reliable
      // than state_change timing (streaming state arrives before first token).
        if ((to === 'thinking') && !_streamBubble) {
          if (!_isStreaming) _startStreaming();
          _showThinkingIndicator();
        }
    }));

    _unsubs.push(_rpc.on('session.event.run_heartbeat', (payload) => {
      if (_isStaleEpoch(payload)) return;
      if (_aborted) return;
      _noteStreamSeq(payload);
      if (!_isStreaming) _startStreaming();
      _resetStreamIdleTimer();
      if (!_streamBubble) _showThinkingIndicator();
    }));

    _unsubs.push(_rpc.on('session.event.cron_result', (payload) => {
      if (_isStaleEpoch(payload)) return;
      _noteStreamSeq(payload);
      const msg = payload?.message || payload || {};
      const targetSession = payload?.sessionKey || '';
      if (targetSession && _sessionKey && targetSession !== _sessionKey) return;
      _messages.push({
        role: 'assistant',
        text: msg.text || '',
        ts: msg.timestamp || null,
        provenanceKind: msg.provenanceKind || '',
      });
      _addMessage(
        'assistant',
        msg.text || '',
        msg.timestamp || null,
        { provenanceKind: msg.provenanceKind || '' },
      );
    }));

    // Non-persistent warnings surfaced by the turn runner (e.g. model claimed
    // to generate an image but never called the tool). Toast only — never
    // written to the transcript, never fed back to the LLM.
    _unsubs.push(_rpc.on('session.event.warning', (payload) => {
      if (_isStaleEpoch(payload)) return;
      const msg = (payload && payload.message) || 'Assistant warning';
      if (payload && payload.code === 'tool_result_summary_disabled') {
        const toolCompressBtn = _el?.querySelector('#pill-tool-compress');
        if (toolCompressBtn) _setToolCompressButton(toolCompressBtn, 'off');
        const overlay = UI.modal(
          'Tool Compress Disabled',
          '<p>' + _esc(msg) + '</p>',
          [{ label: 'OK', cls: 'btn-primary' }]
        );
        setTimeout(() => {
          if (overlay && document.body.contains(overlay)) overlay.remove();
        }, 8000);
        return;
      }
      UI.toast(msg, 'warn', 5000);
    }));

    // Track session epoch to discard stale frames from pre-reset turns.
    _unsubs.push(_rpc.on('session.epoch_changed', (payload) => {
      const ep = payload && payload.epoch;
      if (typeof ep === 'number' && Number.isFinite(ep) && ep > _currentEpoch) {
        _clearActiveTaskGroups();
        _currentEpoch = ep;
      }
    }));

    // sessions.changed carries epoch — drop if stale.
    _unsubs.push(_rpc.on('sessions.changed', (payload) => {
      if (_isStaleEpoch(payload)) return;
    }));

    _unsubs.push(_rpc.on('task.queued', (payload) => {
      _applySessionRunState({
        run_status: 'queued',
        active_task: { ...(payload || {}), status: 'queued' },
      });
    }));

    _unsubs.push(_rpc.on('task.running', (payload) => {
      _applySessionRunState({
        run_status: 'running',
        active_task: { ...(payload || {}), status: 'running' },
      });
    }));

    _unsubs.push(_rpc.on('session.event.task_group.waiting', (payload) => {
      if (_isStaleEpoch(payload)) return;
      _noteStreamSeq(payload);
      _noteTaskGroupActive(payload);
    }));

    _unsubs.push(_rpc.on('session.event.task_group.synthesizing', (payload) => {
      if (_isStaleEpoch(payload)) return;
      _noteStreamSeq(payload);
      _noteTaskGroupActive(payload);
    }));

    _unsubs.push(_rpc.on('session.event.task_group.done', (payload) => {
      if (_isStaleEpoch(payload)) return;
      _noteStreamSeq(payload);
      _noteTaskGroupTerminal(payload, 'succeeded');
    }));

    _unsubs.push(_rpc.on('session.event.task_group.failed', (payload) => {
      if (_isStaleEpoch(payload)) return;
      _noteStreamSeq(payload);
      _noteTaskGroupTerminal(payload, 'failed');
    }));

    // Wildcard listener for done + error events (tool events handled by dedicated listeners above)
    _unsubs.push(_rpc.on('*', (rawEvent, rawPayload) => {
      const terminalStatus = _taskTerminalStatus(rawEvent);
      if (terminalStatus) {
        const terminalRunStatus = terminalStatus === 'succeeded' ? 'idle'
          : terminalStatus === 'abandoned' ? 'interrupted'
          : terminalStatus;
        if (_activeTaskGroups.size > 0) {
          _applySessionRunState(_activeTaskGroupRunState(rawPayload));
        } else {
          _applySessionRunState({
            run_status: terminalRunStatus,
            last_task: { ...(rawPayload || {}), status: terminalStatus },
          });
        }
      }
      const normalized = _taskTerminalAsSessionEvent(rawEvent, rawPayload);
      // Drop normalized terminal events from epochs we've already left behind
      // (stale residue) and from turns we've already locally finalized
      // (_onStop synchronously calls _endStreaming, so _isStreaming is false
      // by the time the matching task.cancelled arrives).
      if (normalized && _isStaleEpoch(rawPayload)) return;
      if (normalized && !_isStreaming) return;
      const event = normalized ? normalized.event : rawEvent;
      const payload = normalized ? normalized.payload : rawPayload;
      if (typeof event !== 'string') return;
      // Discard done/error frames that pre-date the current epoch.
      if (event.startsWith('session.event.') && _isStaleEpoch(payload)) return;
      _noteStreamSeq(payload);
      if (event.startsWith('session.event.task_group.')) return;

      if (event === 'sessions.changed' && payload?.reason === 'turn_complete' && (!payload?.key || payload.key === _sessionKey)) {
        _scheduleHistorySync();
        return;
      }

      if (event.endsWith('.done') || event === 'chat.done') {
        // Done event payload is flat: { text, input_tokens, output_tokens, iterations,
        // routed_tier, routing_source, ... }
        // Also support nested { usage: { ... } } for future compat
        const u = payload?.usage || payload || {};
        if (u.input_tokens || u.output_tokens) {
          _usageAccum.input += u.input_tokens || 0;
          _usageAccum.output += u.output_tokens || 0;
          _usageAccum.cacheRead += u.cached_tokens || 0;
          _usageAccum.cacheWrite += u.cache_write || 0;
          if (u.cost_usd != null) {
            _usageAccum.cost = (_usageAccum.cost || 0) + u.cost_usd;
          }
          if (u.savings_usd > 0) {
            _usageAccum.sessionSaved = (_usageAccum.sessionSaved || 0) + u.savings_usd;
          }
          if (u.model) _usageModel = u.model;
          _viz.update({ ..._usageAccum, model: _usageModel });
          _saveWidgetState();
        }
        // Track context usage
        const total = (u.input_tokens || 0) + (u.output_tokens || 0);
        if (total > 0) {
          _totalTokens = total;
          _updateCtxWarning();
        }
        const finalText = typeof u.text === 'string' ? u.text : '';
        if (finalText && finalText !== _streamRaw) {
          _reconcileFinalStreamText(finalText);
        }
        // Capture stream bubble before _endStreaming() clears the reference.
        // Final-text reconciliation can create the bubble when a refresh only
        // replays the terminal done frame.
        const _finishedBubble = _streamBubble;
        const _doneWasAborted = payload?.reason === 'aborted';
        _endStreaming(_doneWasAborted ? { reason: 'aborted' } : undefined);

        // Populate savings indicator if data exists
        if (_finishedBubble) {
          const savingsIndicator = _finishedBubble.querySelector('.savings-indicator');
          if (savingsIndicator && u.savings && u.savings.total_usd_estimated > 0) {
            savingsIndicator.textContent = `⚡${Math.round(u.savings.total_pct_estimated)}%`;
            savingsIndicator.title = `⚡ Saved ~${u.savings.total_usd_estimated.toFixed(4)}$`;
            savingsIndicator.classList.add('active'); // Add a class for styling
          }
        }

        // Attach per-turn savings chips to the just-finished assistant bubble
        _maybeFireSavingsPopup(_finishedBubble, u);

        // Attach model + session token footer below the assistant bubble
        _attachTurnMeta(_finishedBubble, _usageModel, _usageAccum.input, _usageAccum.output, u);
        const _metaIdx = _messages.filter(m => m.role === 'assistant').length - 1;
        if (_metaIdx >= 0) {
          _storeTurnMeta(_sessionKey, _metaIdx, _usageModel, _usageAccum.input, _usageAccum.output, {
            cached_tokens: u.cached_tokens || 0,
            cache_hit_active: !!u.cache_hit_active,
            model: u.model || _usageModel || null,
            routed_model: u.routed_model || null,
            routed_tier: u.routed_tier || null,
            routing_source: u.routing_source || 'none',
            total_savings_pct: u.total_savings_pct || 0,
            __savings_ui_suppressed: !!u.__savings_ui_suppressed,
          });
        }
        _scheduleHistorySync();

        // On natural completion, drain the head of the pending queue (FIFO).
        // On abort, recover pending into the composer instead — the user
        // explicitly stopped the turn, so silently auto-firing queued
        // messages is wrong, but losing them is also wrong. _onStop()
        // already runs the same recovery; this branch handles the
        // server-initiated cancel path (timeout, external abort) where
        // _onStop never fired.
        if (_doneWasAborted) {
          _stopRequestedByUser = false;
          _popAllPendingIntoComposer();
        } else if (_pendingQueue.length > 0) {
          _drainQueueHead();
        }
        if (_activeTaskGroups.size > 0) {
          _applySessionRunState(_activeTaskGroupRunState({ reason: 'task_group_active' }));
        } else {
          _applySessionRunState({ run_status: 'idle', last_task: { status: 'succeeded' } });
        }
      } else if (event.endsWith('.error')) {
        _endStreaming();
        _addMessage('error', _sessionErrorMessage(payload));
        if (_activeTaskGroups.size > 0) {
          _applySessionRunState(_activeTaskGroupRunState(payload));
        } else {
          _applySessionRunState({
            run_status: 'failed',
            last_task: { ...(payload || {}), status: 'failed' },
          });
        }
      }
    }));

    // Connection state changes
    _unsubs.push(_rpc.on('_state', (state) => {
      if (state === 'connected' && _sessionKey) {
        _applyRpcPolicy(_rpc?.policy || {});
        _hideThinkingIndicator();
        _subscribeSession();
        _loadCurrentSessionUsage();
        _loadHistory();
      }
      if (state === 'disconnected' && _isStreaming) {
        _clearStreamIdleTimer();
        _showThinkingIndicator();
      }
    }));

    _unsubs.push(_rpc.on('_hello', (hello) => {
      _applyRpcPolicy(hello?.policy || {});
    }));

    _unsubs.push(_rpc.on('_gap', () => {
      if (!_isStreaming) return;
      _clearStreamIdleTimer();
      UI.toast('Stream connection gap detected; reconnecting.', 'warn', 4000);
    }));
  }

  /* ── Savings Popup (squilla-router routing or cache hit) ───────────── */

  // Decoupled from the token widget: this fires SavingsFX only when the
  // server reports a real squilla-router routed savings percentage or an
  // active provider/OpenSquilla cache hit. Cache hits do not increment the
  // savings streak unless the turn also has routed savings.
  function _maybeFireSavingsPopup(bubble, u) {
    u = u || {};
    const now = Date.now();
    const identityModel = u.routed_model || u.model || '';
    const identity = identityModel ? `${identityModel}|${u.routed_tier || ''}` : '';
    let suppressPopup = false;
    if (identity) {
      const identityChanged = !!(_lastSavingsPopupIdentity && _lastSavingsPopupIdentity !== identity);
      _lastSavingsPopupIdentity = identity;
      if (identityChanged) {
        suppressPopup = true;
      }
    }
    if (suppressPopup) {
      u.__savings_ui_suppressed = true;
    }

    if (!window.SavingsFX) return;

    // Always tell SavingsFX about this turn after model-switch suppression is
    // known. Suppressed savings turns hide current UI, but still let the next
    // visible same-identity savings turn continue combo.
    window.SavingsFX.noteTurn(u);
    if (suppressPopup) return;

    const hasTier  = !!(u.routed_tier && u.routing_source && u.routing_source !== 'none');
    const turnSavedPct = (typeof u.total_savings_pct === 'number' && u.total_savings_pct > 0)
      ? u.total_savings_pct : 0;
    const hasRoutedSavings = hasTier && turnSavedPct > 0;
    const cacheHit = !!(u.cache_hit_active || (u.cached_tokens || 0) > 0);
    if (!hasRoutedSavings && !cacheHit) return;
    if (!cacheHit && now - _savingsPopupLastTs < _SAVINGS_POPUP_COOLDOWN_MS) return;
    if (!bubble || !bubble.isConnected) return;

    window.SavingsFX.fire(bubble, u);
    _savingsPopupLastTs = now;
  }

  /* ── Context Usage Warning ──────────────────────────────────────────── */

  function _updateCtxWarning() {
    if (!_ctxWarn) return;
    if (_totalTokens > _CTX_WARN_THRESHOLD) {
      _ctxWarn.classList.remove('hidden');
      _ctxWarn.textContent = `Context > 85% (~${Math.round(_totalTokens / 1000)}k tokens)`;
    } else {
      _ctxWarn.classList.add('hidden');
    }
  }

  /* ── Chat History ───────────────────────────────────────────────────── */

  function _scheduleHistorySync() {
    if (_historySyncTimer) clearTimeout(_historySyncTimer);
    _historySyncTimer = setTimeout(() => {
      _historySyncTimer = null;
      _loadHistory();
    }, 50);
  }

  async function _loadHistory() {
    if (!_sessionKey || !_thread) return;
    try {
      await _rpc.waitForConnection();
      const data = await _rpc.call('chat.history', { sessionKey: _sessionKey });
      const messages = data.messages || [];
      if (messages.length === 0) {
        _thread.innerHTML = '';
        _messages = [];
        _lastHeaderRole = '';
        _lastHeaderDay = '';
        if (window.SavingsFX) window.SavingsFX.resetStreak();
        _lastSavingsPopupIdentity = '';
        _thread.innerHTML = _emptyStateHTML();
        return;
      }
      const existingByStableIdentity = new Map();
      const existingByFallbackIdentity = new Map();
      _thread.querySelectorAll('.msg').forEach((el) => {
        const stable = el.getAttribute('data-message-id') || '';
        if (stable) existingByStableIdentity.set(stable, el);
        const fallback = el.getAttribute('data-history-fallback-id') || _historyElementFallbackIdentity(el);
        if (fallback) _pushIdentityElement(existingByFallbackIdentity, fallback, el);
      });
      const empty = _thread.querySelector('.chat-empty');
      if (empty) empty.remove();
      _thread.querySelectorAll('.chat-day-sep').forEach((el) => el.remove());
      _messages = [];
      _lastHeaderRole = '';
      _lastHeaderDay = '';
      if (window.SavingsFX) window.SavingsFX.resetStreak();
      let historySavingsIdentity = '';
      let _histAsstIdx = 0;
      const consumedHistoryElements = new Set();
      messages.forEach((msg) => {
        const rawText = msg.text || '';
        const displayText = msg.role === 'user' ? _stripTimePrefix(rawText) : rawText;
        const stableIdentity = _historyStableMessageIdentity(msg);
        const fallbackIdentity = _historyFallbackMessageIdentity(msg.role, displayText);
        const msgOptions = {
          provenanceKind: msg.provenance_kind || '',
          provenanceSourceSessionKey: msg.provenance_source_session_key || '',
          provenanceSourceTool: msg.provenance_source_tool || '',
        };
        _messages.push({
          role: msg.role,
          text: displayText,
          ts: msg.timestamp || msg.ts || null,
          artifacts: msg.artifacts || [],
          ...msgOptions,
        });
        _appendHistoryDaySeparator(msg.timestamp || msg.ts || null);
        let div = stableIdentity ? existingByStableIdentity.get(stableIdentity) : null;
        if (!div) {
          div = _shiftIdentityElement(
            existingByFallbackIdentity,
            fallbackIdentity,
            consumedHistoryElements,
          );
        }
        if (div) {
          consumedHistoryElements.add(div);
          _replaceHistoryMessage(div, msg.role, displayText, msgOptions);
        } else {
          div = _addMessage(
            msg.role,
            displayText,
            msg.timestamp || msg.ts || null,
            msgOptions,
          );
          consumedHistoryElements.add(div);
        }
        _stampHistoryElement(div, stableIdentity, msg.role, displayText);
        _appendHistoryElementInOrder(div);
        if (msg.role === 'assistant' && msg.tool_calls && msg.tool_calls.length > 0) {
          _reconstructToolCalls(div, msg.tool_calls);
        }
        if (msg.attachments && msg.attachments.length > 0) {
          const body = div.querySelector('.msg-body');
          body.classList.add('msg-body--has-attachments');
          if (msg.role === 'user' && body.textContent.trim()) {
            body.innerHTML = `<div class="msg-attachment-text">${_esc(body.textContent)}</div>`;
          }
          let thumbsHtml = '<div class="msg-attachments">';
          msg.attachments.forEach((a) => {
            thumbsHtml += _renderMessageAttachmentHtml(a);
          });
          thumbsHtml += '</div>';
          body.innerHTML += thumbsHtml;
        }
        if (msg.artifacts && msg.artifacts.length > 0) {
          const body = div.querySelector('.msg-body');
          body.innerHTML += _renderArtifacts(msg.artifacts || []);
        }
        // Tool-call reconstruction and attachment rendering above rewrite
        // body.innerHTML, which wipes the toolbar attached during _addMessage.
        // Re-attach so action buttons survive a history reload.
        _attachHoverActions(div, msg.role);
        if (msg.role === 'assistant') {
          const m = _recallTurnMeta(_sessionKey, _histAsstIdx++);
          if (m) {
            const savedUsage = _savedUsageFromMeta(m);
            if (savedUsage) {
              const identity = _turnSavingsIdentity(savedUsage);
              if (identity) {
                const identityChanged = !!(historySavingsIdentity && historySavingsIdentity !== identity);
                historySavingsIdentity = identity;
                if (identityChanged) savedUsage.__savings_ui_suppressed = true;
              }
              if (window.SavingsFX) window.SavingsFX.noteTurn(savedUsage);
            } else if (window.SavingsFX) {
              window.SavingsFX.noteTurn(null);
            }
            _attachTurnMeta(div, m.model, m.input, m.output, savedUsage || undefined);
          } else if (window.SavingsFX) {
            window.SavingsFX.noteTurn(null);
          }
        }
      });
      _thread.querySelectorAll('.msg').forEach((el) => {
        if (_isStreaming && el === _streamBubble) return;
        if (!consumedHistoryElements.has(el)) el.remove();
      });
      _lastSavingsPopupIdentity = historySavingsIdentity;
      _scrollToBottom();
    } catch {
      // History endpoint may not exist yet; silently keep the view empty
    }
  }

  function _appendHistoryDaySeparator(timestamp) {
    const day = _dayKey(timestamp);
    if (!day || day === _lastHeaderDay) return;
    const sep = document.createElement('div');
    sep.className = 'chat-day-sep';
    sep.innerHTML = `<span>${_dayLabel(day)}</span>`;
    if (_isStreaming && _streamBubble) {
      _thread.insertBefore(sep, _streamBubble);
    } else {
      _thread.appendChild(sep);
    }
    _lastHeaderDay = day;
    _lastHeaderRole = '';
  }

  function _appendHistoryElementInOrder(div) {
    if (!div) return;
    if (_isStreaming && _streamBubble && div !== _streamBubble) {
      _thread.insertBefore(div, _streamBubble);
      return;
    }
    _thread.appendChild(div);
  }

  function _historyStableMessageIdentity(msg) {
    const stableId = msg.message_id || msg.id || '';
    return stableId ? String(stableId) : '';
  }

  function _historyFallbackMessageIdentity(role, text) {
    return `${role || ''}|${_historyFallbackText(role, text)}`;
  }

  function _historyFallbackText(role, text) {
    if (role === 'assistant') return _stripDirectiveTags(text || '').trim();
    if (role === 'user') return _stripTimePrefix(text || '').trim();
    return (text || '').trim();
  }

  function _pushIdentityElement(map, identity, el) {
    const elements = map.get(identity) || [];
    elements.push(el);
    map.set(identity, elements);
  }

  function _shiftIdentityElement(map, identity, consumedElements = null) {
    if (!identity) return null;
    const elements = map.get(identity);
    if (!elements || elements.length === 0) return null;
    while (elements.length > 0) {
      const el = elements.shift();
      if (!consumedElements || !consumedElements.has(el)) return el;
    }
    return null;
  }

  function _historyElementRole(el) {
    const tagged = el.getAttribute('data-history-role') || '';
    if (tagged) return tagged;
    if (el.classList.contains('user')) return 'user';
    if (el.classList.contains('assistant')) return 'assistant';
    if (el.classList.contains('subagent')) return 'system';
    if (el.classList.contains('system')) return 'system';
    return '';
  }

  function _historyElementText(el) {
    const raw = el.getAttribute('data-history-raw-text') || '';
    if (raw) return raw;
    const body = el.querySelector('.msg-body');
    return body ? body.textContent.trim() : '';
  }

  function _historyElementFallbackIdentity(el) {
    const role = _historyElementRole(el);
    const text = _historyElementText(el);
    return role || text ? _historyFallbackMessageIdentity(role, text) : '';
  }

  function _stampHistoryElement(div, stableIdentity, role, text) {
    if (stableIdentity) div.setAttribute('data-message-id', stableIdentity);
    div.setAttribute('data-history-role', role || '');
    div.setAttribute('data-history-raw-text', text || '');
    div.setAttribute('data-history-fallback-id', _historyFallbackMessageIdentity(role, text));
  }

  function _replaceHistoryMessage(div, role, text, options = {}) {
    const isSubagentCompletion = _isSubagentCompletionMessage(role, text, options);
    const displayRole = isSubagentCompletion ? 'subagent' : role;
    div.className = `msg ${displayRole}`;
    const body = div.querySelector('.msg-body');
    if (body) {
      _renderMessageBody(body, role, text, options);
    }
    _attachHoverActions(div, displayRole);
  }

  function _replaceStreamText(finalText) {
    if (!_isStreaming) _startStreaming();
    _ensureStreamBubble();
    if (!_streamBubble) {
      _streamRaw = finalText;
      return;
    }
    const body = _streamBubble.querySelector('.msg-body');
    if (body) body.innerHTML = '';
    _streamRaw = finalText;
    _segments = [];
    _activeTextSeg = null;
    _activeTextRaw = '';
    _newTextSegment();
    _activeTextRaw = finalText;
    const lastSeg = _segments[_segments.length - 1];
    if (lastSeg && lastSeg.type === 'text') lastSeg.raw = finalText;
    _renderDirty = true;
    _flushRender();
    _renderStreamArtifacts();
  }

  function _reconcileFinalStreamText(finalText) {
    if (!finalText || finalText === _streamRaw) return;
    if (_streamRaw && finalText.startsWith(_streamRaw)) {
      _appendDelta(finalText.slice(_streamRaw.length));
      return;
    }
    const textOnly = _segments.every((seg) => seg.type === 'text');
    if (!_streamRaw || textOnly) {
      _replaceStreamText(finalText);
      return;
    }
    _streamRaw = finalText;
  }

  /* ── Send Message ───────────────────────────────────────────────────── */

  function _onSend() {
    const text = _textarea.value.trim();
    const hasPayload = text || _pendingAttachments.length > 0;

    if (_hasPendingAttachmentWork()) {
      UI.toast('Wait for file attachment processing to finish', 'warn', 2500);
      return;
    }

    // While a turn is streaming, Send enqueues (Proposal C). Use ESC or the
    // Stop button to actually halt the current response.
    if (_isStreaming) {
      if (!hasPayload) return; // empty + streaming = no-op
      if (_pendingQueue.length >= _MAX_PENDING) {
        UI.toast(
          `Pending queue full (${_MAX_PENDING}). Wait for the current response or clear.`,
          'warning',
          3000,
        );
        return;
      }
      _pendingQueue.push({
        text,
        attachments: _pendingAttachments.map((a) => ({ ...a })),
        intent: _pendingSessionIntent,
      });
      _textarea.value = '';
      _pendingAttachments = [];
      _pendingSessionIntent = null;
      _renderAttachmentPreview();
      _renderPendingQueue();
      _autoResizeTextarea();
      UI.toast(`Queued (${_pendingQueue.length}/${_MAX_PENDING})`, 'info', 1500);
      return;
    }

    if (!hasPayload || !_sessionKey) return;

    // Intercept slash commands
    if (text.startsWith('/')) {
      const cmdText = text.split(' ')[0].toLowerCase();
      const match = _SLASH_CMDS.find(c => c.cmd === cmdText);
      if (match) {
        _selectSlashCmd(match);
        return;
      }
    }

    // Reset abort flag for new message
    _aborted = false;

    // Close slash menu if open
    _closeSlashMenu();

    // Record message for export
    const now = new Date().toISOString();
    const userText = text || '(attachment)';
    _messages.push({ role: 'user', text: userText, ts: now });

    // Show user message
    const userDiv = _addMessage('user', '', now);
    _stampHistoryElement(userDiv, '', 'user', userText);
    const userBody = userDiv.querySelector('.msg-body');
    let userHtml = _esc(userText);
    if (_pendingAttachments.length > 0) {
      userBody.classList.add('msg-body--has-attachments');
      userHtml = userText ? `<div class="msg-attachment-text">${_esc(userText)}</div>` : '';
      userHtml += '<div class="msg-attachments">';
      _pendingAttachments.forEach((a) => { userHtml += _renderMessageAttachmentHtml(a); });
      userHtml += '</div>';
    }
    userBody.innerHTML = userHtml;
    // Restore the hover toolbar that _addMessage attached — the innerHTML
    // write above wiped it (same pattern as the history-render path).
    _attachHoverActions(userDiv, 'user');

    // Build RPC params
    const params = { message: text || 'Describe these attachments', sessionKey: _sessionKey };
    const elevatedMode = _normalizeElevatedMode(_elevatedMode);
    if (elevatedMode) params._source = { elevated: elevatedMode };
    if (_pendingSessionIntent) {
      params.intent = _pendingSessionIntent;
      _pendingSessionIntent = null;
    }
    if (_pendingAttachments.length > 0) {
      params.attachments = _pendingAttachments.map((a) => {
        if (a.kind === 'staged') {
          return { type: a.mime, file_uuid: a.file_uuid, mime: a.mime, name: a.name };
        }
        return { type: a.mime || 'image/png', data: a.data, mime: a.mime, name: a.name };
      });
    }

    // Clear input and attachments
    _textarea.value = '';
    _autoResizeTextarea();
    _pendingAttachments = [];
    _renderAttachmentPreview();

    // Start streaming UI
    _startStreaming();
    _showThinkingIndicator();

    // Send
    _rpc.call('chat.send', params).then((res) => {
      if (res && res.sessionKey && res.sessionKey !== _sessionKey) _persistSession(res.sessionKey);
    }).catch((err) => {
      _endStreaming();
      _addMessage('error', 'Send failed: ' + err.message);
    });
  }

  /* ── Streaming ──────────────────────────────────────────────────────── */

  function _clearStreamIdleTimer() {
    if (_streamIdleTimer) {
      clearTimeout(_streamIdleTimer);
      _streamIdleTimer = null;
    }
  }

  function _setStreamIdlePausedForApproval(paused) {
    _streamIdlePausedForApproval = !!paused;
    if (_streamIdlePausedForApproval) {
      _clearStreamIdleTimer();
    } else if (_isStreaming) {
      _resetStreamIdleTimer();
    }
  }

  function _resetStreamIdleTimer() {
    _clearStreamIdleTimer();
    if (!_isStreaming || _streamIdlePausedForApproval) return;
    _streamIdleTimer = setTimeout(() => {
      if (_isStreaming && !_streamIdlePausedForApproval) {
        _endStreaming();
        const seconds = Math.round(_streamIdleTimeoutMs / 1000);
        _addMessage('error', `Response timed out — no events received for ${seconds}s`);
      }
    }, _streamIdleTimeoutMs);
  }

  function _applyRpcPolicy(policy) {
    const raw = policy && policy.webui_stream_idle_grace_ms;
    if (typeof raw === 'number' && Number.isFinite(raw) && raw > 0) {
      _streamIdleTimeoutMs = raw;
    } else {
      _streamIdleTimeoutMs = _DEFAULT_STREAM_IDLE_TIMEOUT_MS;
    }
  }

  function _taskTerminalStatus(event) {
    if (typeof event !== 'string' || !event.startsWith('task.')) return '';
    const status = event.slice('task.'.length);
    return ['succeeded', 'failed', 'timeout', 'abandoned', 'cancelled'].includes(status)
      ? status
      : '';
  }

  function _taskTerminalAsSessionEvent(event, payload) {
    if (event === 'task.cancelled') {
      return {
        event: 'session.event.done',
        payload: { ...(payload || {}), reason: 'aborted' },
      };
    }
    if (!['task.failed', 'task.timeout', 'task.abandoned'].includes(event)) return null;
    const status = event.replace('task.', '');
    const message = _taskTerminalMessage(status, payload);
    return {
      event: 'session.event.error',
      payload: {
        ...(payload || {}),
        message,
        code: status,
      },
    };
  }

  function _taskTerminalMessage(status, payload) {
    if (typeof payload?.terminal_message === 'string' && payload.terminal_message.trim()) {
      return payload.terminal_message.trim();
    }
    if (status === 'timeout' || payload?.terminal_reason === 'timeout') {
      return 'The task timed out before it could finish.';
    }
    if (status === 'abandoned') {
      return 'The task stopped before it could finish.';
    }
    if (status === 'cancelled') {
      return 'The task was cancelled before it finished.';
    }
    if (status === 'failed') {
      return 'The task failed before it could finish.';
    }
    return 'The task ended before it could finish.';
  }

  function _sessionErrorMessage(payload) {
    if (typeof payload?.terminal_message === 'string' && payload.terminal_message.trim()) {
      return payload.terminal_message.trim();
    }
    const message = typeof payload?.message === 'string' ? payload.message : '';
    const code = typeof payload?.code === 'string' ? payload.code.toLowerCase() : '';
    if (code.includes('timeout') || message.toLowerCase().includes('stream idle')) {
      return 'The task timed out before it could finish.';
    }
    if (message) return message;
    return 'Agent error';
  }

  function _noteStreamSeq(payload) {
    const seq = payload && payload.stream_seq;
    if (typeof seq === 'number' && Number.isFinite(seq) && seq > _lastStreamSeq) {
      _lastStreamSeq = seq;
    }
  }

  // Returns true when a session event payload carries an epoch that
  // predates the current reset counter — such frames must be discarded.
  function _isStaleEpoch(payload) {
    const ep = payload && payload.epoch;
    if (typeof ep !== 'number' || !Number.isFinite(ep)) return false;
    return ep < _currentEpoch;
  }

  function _showThinkingIndicator() {
    // Already scheduled or visible — keep the original timer/element to avoid
    // hide-then-rebuild flicker when send + state_change both fire.
    if (_thinkingEl || _thinkingDelayTimer) return;
    _thinkingStartTime = Date.now();

    // Delay showing the indicator — fast responses won't flash it
    _thinkingDelayTimer = setTimeout(_showThinkingIndicatorNow, _THINKING_DELAY_MS);
  }

  function _showThinkingIndicatorNow() {
    _thinkingDelayTimer = null;
    if (_streamBubble) return; // content already arrived, skip

    const empty = _thread.querySelector('.chat-empty');
    if (empty) empty.remove();

    _thinkingEl = document.createElement('div');
    _thinkingEl.className = 'msg assistant thinking';
    _thinkingEl.setAttribute('role', 'status');
    _thinkingEl.setAttribute('aria-live', 'polite');

    // Show header only on speaker change (thinking indicator is transient;
    // it will be removed before the real bubble is inserted, so don't update
    // _lastHeaderRole here — that update happens in _ensureStreamBubble).
    if (_lastHeaderRole !== 'assistant') {
      const header = document.createElement('div');
      header.className = 'msg-header';
      const roleLabel = document.createElement('span');
      roleLabel.className = 'role-label';
      roleLabel.textContent = 'Assistant';
      header.appendChild(roleLabel);
      _thinkingEl.appendChild(header);
    }

    const body = document.createElement('div');
    body.className = 'msg-body thinking-body';
    const status = document.createElement('div');
    status.className = 'thinking-status';

    const dots = document.createElement('div');
    dots.className = 'typing-indicator';
    for (let i = 0; i < 3; i++) {
      const dot = document.createElement('span');
      dot.className = 'dot';
      dots.appendChild(dot);
    }

    const elapsed = document.createElement('span');
    elapsed.className = 'thinking-elapsed';
    const secs = Math.floor((Date.now() - _thinkingStartTime) / 1000);
    elapsed.textContent = 'Working (' + secs + 's)';

    status.appendChild(dots);
    status.appendChild(elapsed);
    body.appendChild(status);
    _thinkingEl.appendChild(body);
    _thread.appendChild(_thinkingEl);
    if (_autoScroll) _scrollToBottom();

    _thinkingTimerInterval = setInterval(() => {
      if (!_thinkingEl) { clearInterval(_thinkingTimerInterval); return; }
      const s = Math.floor((Date.now() - _thinkingStartTime) / 1000);
      const label = _thinkingEl.querySelector('.thinking-elapsed');
      if (label) label.textContent = 'Working (' + s + 's)';

      if (s >= _THINKING_TTL_MS / 1000) {
        _hideThinkingIndicator();
        _addMessage('system', 'Still waiting for agent response\u2026');
      }
    }, 1000);
  }

  function _hideThinkingIndicator() {
    if (_thinkingDelayTimer) {
      clearTimeout(_thinkingDelayTimer);
      _thinkingDelayTimer = null;
    }
    if (_thinkingTimerInterval) {
      clearInterval(_thinkingTimerInterval);
      _thinkingTimerInterval = null;
    }
    if (_thinkingEl) {
      _thinkingEl.remove();
      _thinkingEl = null;
    }
  }

  function _startStreaming() {
    _isStreaming = true;
    _applySessionRunState({ run_status: 'running', active_task: { status: 'running' } });
    _streamRaw = '';
    _segments = []; _activeTextSeg = null; _activeTextRaw = '';
    _streamArtifacts = [];
    _streamBubble = null;
    _autoScroll = true;
    if (_thread) _thread.setAttribute('aria-busy', 'true');
    _updateSendButton();
    _resetStreamIdleTimer();
  }

  function _ensureStreamBubble() {
    _hideThinkingIndicator();
    if (!_streamBubble) {
      // Remove "No messages yet." placeholder
      const empty = _thread.querySelector('.chat-empty');
      if (empty) empty.remove();

      _streamBubble = document.createElement('div');
      _streamBubble.className = 'msg assistant streaming';
      _streamBubble.setAttribute('data-history-role', 'assistant');
      _streamBubble.setAttribute('aria-live', 'polite');

      // Day separator for streaming bubbles (use current time as timestamp)
      const now = new Date().toISOString();
      const day = _dayKey(now);
      if (day && day !== _lastHeaderDay) {
        const sep = document.createElement('div');
        sep.className = 'chat-day-sep';
        sep.innerHTML = `<span>${_dayLabel(day)}</span>`;
        _thread.insertBefore(sep, null);
        _lastHeaderDay = day;
        _lastHeaderRole = '';
      }

      // Show header only on speaker change (role dedup)
      const sameGroup = (_lastHeaderRole === 'assistant');
      if (!sameGroup) {
        _streamBubble.innerHTML = `
          <div class="msg-header">
            <span class="role-label">Assistant</span>
            <span class="savings-indicator"></span>
            <span class="msg-time"></span>
          </div>
          <div class="msg-body"></div>`;
        _lastHeaderRole = 'assistant';
      } else {
        _streamBubble.innerHTML = `<div class="msg-body"></div>`;
      }

      _thread.appendChild(_streamBubble);

      // Create the first text segment
      _newTextSegment();
    }
    return _streamBubble;
  }

  /** Create a new .msg-text-seg inside .msg-body and set it as the active text target. */
  function _newTextSegment() {
    const body = _streamBubble.querySelector('.msg-body');
    const seg = document.createElement('div');
    seg.className = 'msg-text-seg';
    seg.setAttribute('data-seg', String(_segments.length));
    body.appendChild(seg);
    _activeTextSeg = seg;
    _activeTextRaw = '';
    _segments.push({ type: 'text', raw: '', el: seg });
    return seg;
  }

  function _appendDelta(text) {
    if (_aborted) return;
    if (!_isStreaming) _startStreaming();
    _ensureStreamBubble();
    _streamRaw += text;
    _activeTextRaw += text;
    // Keep segment raw in sync for final render
    const lastSeg = _segments[_segments.length - 1];
    if (lastSeg && lastSeg.type === 'text') lastSeg.raw = _activeTextRaw;

    // First delta: render immediately for snappy feel; subsequent deltas batch via rAF
    if (!_renderRafId && _activeTextRaw.length === text.length) {
      _renderDirty = true;
      _flushRender();
    } else {
      _renderDirty = true;
      if (!_renderRafId) {
        _renderRafId = requestAnimationFrame(_flushRender);
      }
    }
  }

  function _flushRender() {
    _renderRafId = null;
    if (!_renderDirty || !_streamBubble) { _renderDirty = false; return; }
    if (_activeTextSeg && _activeTextRaw) {
      _activeTextSeg.innerHTML = Markdown.render(_stripDirectiveTags(_activeTextRaw));  // eslint-disable-line no-unsanitized/property
      Markdown.bindCopy(_activeTextSeg);
    }
    _renderDirty = false;
    if (_autoScroll) _scrollToBottom();
  }

  function _endStreaming(opts) {
    const reason = opts && opts.reason;
    const wasAborted = reason === 'aborted';
    _hideThinkingIndicator();
    if (_historySyncTimer) { clearTimeout(_historySyncTimer); _historySyncTimer = null; }
    if (_renderRafId) { cancelAnimationFrame(_renderRafId); _renderRafId = null; }
    _renderDirty = false;
    _clearStreamIdleTimer();
    _streamIdlePausedForApproval = false;
    if (_streamBubble) {
      _streamBubble.classList.remove('streaming');
      const cleanedText = _stripDirectiveTags(_streamRaw).trim();

      // Suppress sentinel tokens that the LLM may emit instead of a real reply.
      // Don't suppress when aborted — we want the interrupted bubble to show
      // even if the partial happens to match a sentinel string.
      const _SENTINELS = ['NO_REPLY', 'HEARTBEAT_OK'];
      if (!wasAborted && _SENTINELS.includes(cleanedText)) {
        _streamBubble.remove();
        _streamBubble = null;
        _isStreaming = false;
        _streamRaw = '';
        _segments = []; _activeTextSeg = null; _activeTextRaw = '';
        _streamArtifacts = [];
        _updateSendButton();
        return;
      }

      // Aborted with no partial output: drop the empty bubble entirely so
      // the transcript doesn't grow stub assistant messages every ESC.
      if (wasAborted && !cleanedText) {
        _streamBubble.remove();
        _streamBubble = null;
        _isStreaming = false;
        _streamRaw = '';
        _segments = []; _activeTextSeg = null; _activeTextRaw = '';
        _streamArtifacts = [];
        if (_thread) _thread.setAttribute('aria-busy', 'false');
        _updateSendButton();
        return;
      }
      _stampHistoryElement(_streamBubble, '', 'assistant', cleanedText);

      // Final render: render each text segment with its own content
      for (const seg of _segments) {
        if (seg.type !== 'text' || !seg.el) continue;
        const segText = _stripDirectiveTags(seg.raw).trim();
        if (segText) {
          seg.el.innerHTML = Markdown.render(segText);  // eslint-disable-line no-unsanitized/property
          Markdown.bindCopy(seg.el);
        } else {
          // Remove empty text segments (e.g., no text after last tool call)
          seg.el.remove();
        }
      }

      const body = _streamBubble.querySelector('.msg-body');
      // Append an "interrupted" marker for aborted turns so the transcript
      // makes the half-finished response unambiguous. CSS in chat.css
      // styles .msg-interrupt-mark; the element itself is plain text so
      // copy / export still surface the partial content cleanly.
      if (wasAborted && body && !body.querySelector('.msg-interrupt-mark')) {
        const mark = document.createElement('span');
        mark.className = 'msg-interrupt-mark';
        mark.textContent = 'interrupted';
        body.appendChild(mark);
      }

      // Record assistant message for export (store full cleaned text). The
      // interrupted flag is in-memory only — _loadHistory() does not surface
      // it from the server, by design (transcript schema unchanged).
      _messages.push({
        role: 'assistant',
        text: cleanedText,
        ts: new Date().toISOString(),
        artifacts: _streamArtifacts.slice(),
        ...(wasAborted ? { interrupted: true } : {}),
      });

      // Clear any orphaned tool running indicators
      if (body) body.querySelectorAll('.chat-tools-collapse--running').forEach(el => el.classList.remove('chat-tools-collapse--running'));

      // Attach hover-action row (Copy / Regenerate) to the just-finished bubble.
      _attachHoverActions(_streamBubble, 'assistant');
    }
    _isStreaming = false;
    _streamBubble = null;
    _streamRaw = '';
    _segments = []; _activeTextSeg = null; _activeTextRaw = '';
    _streamArtifacts = [];
    if (_thread) _thread.setAttribute('aria-busy', 'false');
    _updateSendButton();
  }

  function _updateSendButton() {
    if (!_sendBtn) return;
    // Send button stays as paper-plane always. During streaming a click
    // enqueues (see _onSend). The separate Stop button (_stopBtn) handles
    // abort and is toggled by _updateStopButton(). Keeping two buttons lets
    // Send remain a "push a message forward" action instead of toggling
    // meaning mid-stream.
    _sendBtn.innerHTML = icons.send();
    _sendBtn.classList.remove('btn--danger');
    _sendBtn.classList.add('primary');
    _sendBtn.title = _isStreaming
      ? 'Send (queues for after current response)'
      : 'Send';
    _updateStopButton();
  }

  /* ── Tool Call / Tool Result Display ────────────────────────────────── */

  function _buildToolCallDOM(name, toolId, input, isRunning) {
    const preview = _truncate(
      typeof input === 'string' ? input : JSON.stringify(input || '', null, 2),
      200
    );

    const details = document.createElement('details');
    details.className = 'chat-tools-collapse' + (isRunning ? ' chat-tools-collapse--running' : '');
    if (toolId) details.setAttribute('data-tool-id', toolId);

    const summary = document.createElement('summary');
    summary.className = 'chat-tools-summary';
    if (isRunning) summary.setAttribute('aria-disabled', 'true');
    // Block expansion while the tool is still running; cleared when state flips to success/error.
    summary.addEventListener('click', (e) => {
      if (details.classList.contains('chat-tools-collapse--running')) e.preventDefault();
    });
    const iconSpan = document.createElement('span');
    iconSpan.className = 'chat-tools-icon';
    iconSpan.textContent = _toolEmoji(name);
    summary.appendChild(iconSpan);
    summary.appendChild(document.createTextNode(' ' + name));

    const toolsBody = document.createElement('div');
    toolsBody.className = 'chat-tools-body';

    // Only show input preview if non-empty (arguments may arrive later via tool_use_delta)
    const emptyInputs = ['', '""', '{}', 'null', 'undefined'];
    if (preview && !emptyInputs.includes(preview.trim())) {
      const cardInput = document.createElement('div');
      cardInput.className = 'chat-tool-input';
      cardInput.textContent = preview;
      toolsBody.appendChild(cardInput);
    }
    details.appendChild(summary);
    details.appendChild(toolsBody);
    return details;
  }

  function _buildToolResultDOM(content, isError) {
    const preview = _truncate(content, 200);
    if (!preview || preview.trim() === '') return null;

    const div = document.createElement('div');
    div.className = 'chat-tool-result' + (isError ? ' chat-tool-result--error' : '');

    const previewDiv = document.createElement('div');
    previewDiv.className = 'chat-tool-result-preview';
    previewDiv.textContent = preview;
    div.appendChild(previewDiv);

    if (content.length > 200) {
      const viewBtn = document.createElement('button');
      viewBtn.className = 'btn btn--sm btn--ghost chat-tool-view-btn';
      viewBtn.textContent = 'View full';
      viewBtn.addEventListener('click', () => {
        UI.modal('Tool Result', '<pre style="white-space:pre-wrap;max-height:60vh;overflow:auto;font-size:var(--fs-sm)">' + _esc(content) + '</pre>', [
          { label: 'Close', cls: 'btn-secondary' },
        ]);
      });
      div.appendChild(viewBtn);
    }
    return div;
  }

  function _appendToolCall(payload) {
    if (!payload) return;
    const name = payload.name || payload.tool_name || 'tool';
    const input = typeof payload.input === 'string'
      ? payload.input
      : JSON.stringify(payload.input || payload.arguments || '', null, 2);
    const toolId = payload.tool_use_id || '';

    const bubble = _ensureStreamBubble();
    const body = bubble.querySelector('.msg-body');

    const details = _buildToolCallDOM(name, toolId, input, true);
    if (name === 'web_search' && _searchProvider) {
      _injectProviderBadge(details.querySelector('.chat-tools-summary'), _searchProvider);
    }
    body.appendChild(details);
    _segments.push({ type: 'tool', el: details });

    // Seal the current text segment and start a new one for text after this tool call
    _newTextSegment();

    if (_autoScroll) _scrollToBottom();
  }

  function _appendToolResult(payload) {
    if (!payload) return;
    const raw = payload.result || payload.content || payload.output || '';
    const content = typeof raw === 'string' ? raw : JSON.stringify(raw, null, 2);
    const isError = !!(payload.is_error || payload.isError || payload.error);
    const toolId = payload.tool_use_id || '';

    const bubble = _ensureStreamBubble();
    const body = bubble.querySelector('.msg-body');

    // Transition tool container from running → success/error and find target container
    let resultTarget = body; // default: append to msg-body
    if (toolId) {
      const details = body.querySelector('[data-tool-id="' + toolId + '"]');
      if (details) {
        details.classList.remove('chat-tools-collapse--running');
        details.classList.add(isError ? 'chat-tools-collapse--error' : 'chat-tools-collapse--success');
        const summary = details.querySelector('.chat-tools-summary');
        if (summary) summary.removeAttribute('aria-disabled');
        const toolsBody = details.querySelector('.chat-tools-body');
        if (toolsBody) resultTarget = toolsBody;

        // web_search: add provider badge to collapsible summary (may already be present from running state)
        const provider = _toolResultProvider(payload, content);
        if (provider) {
          if (!_searchProvider) _searchProvider = provider;
          _injectProviderBadge(details.querySelector('.chat-tools-summary'), provider);
        }
      }
    }

    // Only show result preview if non-empty
    const resultDiv = _buildToolResultDOM(content, isError);
    if (!resultDiv) {
      if (_autoScroll) _scrollToBottom();
      return;
    }

    resultTarget.appendChild(resultDiv);
    if (_autoScroll) _scrollToBottom();
  }

  function _appendArtifact(payload) {
    if (!payload) return;
    _streamArtifacts.push(payload);
    const bubble = _ensureStreamBubble();
    const body = bubble.querySelector('.msg-body');
    body.insertAdjacentHTML('beforeend', _renderArtifacts([payload]));
    if (_autoScroll) _scrollToBottom();
  }

  function _renderStreamArtifacts() {
    if (!_streamBubble) return;
    const body = _streamBubble.querySelector('.msg-body');
    if (!body) return;
    body.querySelectorAll('.msg-artifacts').forEach((el) => el.remove());
    if (_streamArtifacts.length > 0) {
      body.insertAdjacentHTML('beforeend', _renderArtifacts(_streamArtifacts));
      if (_autoScroll) _scrollToBottom();
    }
  }

  function _artifactDownloadUrl(artifact) {
    let raw = artifact && artifact.download_url ? String(artifact.download_url) : '';
    if (!raw && artifact && artifact.id) raw = `/api/v1/artifacts/${encodeURIComponent(artifact.id)}`;
    if (!raw) return '';
    try {
      const url = new URL(raw, window.location.origin);
      url.searchParams.delete('sessionKey');
      url.searchParams.delete('session_key');
      return url.pathname + url.search + url.hash;
    } catch {
      return raw;
    }
  }

  function _isImageArtifact(artifact) {
    const mime = artifact && artifact.mime ? String(artifact.mime).toLowerCase() : '';
    return mime.startsWith('image/');
  }

  function _artifactPreviewUrl(artifact) {
    const raw = _artifactDownloadUrl(artifact);
    if (!raw) return '';
    try {
      const url = new URL(raw, window.location.origin);
      if (_sessionKey) url.searchParams.set('sessionKey', _sessionKey);
      return url.pathname + url.search + url.hash;
    } catch {
      return raw;
    }
  }

  function _renderArtifacts(artifacts) {
    if (!Array.isArray(artifacts) || artifacts.length === 0) return '';
    let html = '<div class="msg-artifacts">';
    artifacts.forEach((artifact) => {
      const name = artifact && artifact.name ? String(artifact.name) : 'artifact';
      const mime = artifact && artifact.mime ? String(artifact.mime) : 'artifact';
      const size = artifact && artifact.size ? `${Math.max(1, Math.round(Number(artifact.size) / 1024))} KB` : '';
      const downloadUrl = _artifactDownloadUrl(artifact || {});
      const meta = [mime, size].filter(Boolean).join(' · ');
      if (_isImageArtifact(artifact)) {
        const previewUrl = _artifactPreviewUrl(artifact || {});
        html += `<button type="button" class="msg-artifact-card msg-artifact-card--image" data-artifact-download="${_esc(downloadUrl)}" data-artifact-id="${_esc(artifact?.id || '')}" data-artifact-name="${_esc(name)}" title="Download ${_esc(name)}">
          ${previewUrl ? `<img class="msg-artifact-preview" src="${_esc(previewUrl)}" alt="${_esc(name)}" loading="lazy">` : '<span class="msg-artifact-preview msg-artifact-preview--empty" aria-hidden="true"></span>'}
          <span class="msg-artifact-card__body">
            <span class="msg-artifact-card__name">${_esc(name)}</span>
            <span class="msg-artifact-card__meta">${_esc(meta)}</span>
          </span>
          <span class="msg-artifact-card__action" aria-hidden="true">Download</span>
        </button>`;
      } else {
        html += `<button type="button" class="msg-artifact-chip" data-artifact-download="${_esc(downloadUrl)}" data-artifact-id="${_esc(artifact?.id || '')}" data-artifact-name="${_esc(name)}" title="${_esc(name)}">
          <span class="msg-file-chip__icon" aria-hidden="true">file</span>
          <span class="msg-file-chip__name">${_esc(name)}</span>
          <span class="msg-file-chip__meta">${_esc(meta)}</span>
        </button>`;
      }
    });
    html += '</div>';
    return html;
  }

  async function _downloadArtifact(artifact) {
    const downloadUrl = _artifactDownloadUrl(artifact);
    if (!downloadUrl) return;
    const headers = {};
    const token = (App.getAuthToken && App.getAuthToken()) || '';
    if (token) headers['Authorization'] = `Bearer ${token}`;
    if (_sessionKey) headers['x-opensquilla-session-key'] = _sessionKey;
    const response = await fetch(downloadUrl, {
      method: 'GET',
      headers: headers,
      credentials: 'same-origin',
    });
    if (!response.ok) {
      UI.toast(`Download failed: HTTP ${response.status}`, 'warn', 3500);
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = artifact.name || 'artifact';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function _reconstructToolCalls(bubbleDiv, segments) {
    try {
      const body = bubbleDiv.querySelector('.msg-body');
      if (!body) return;

      // Clear existing text content (will be re-rendered from segments)
      body.innerHTML = '';

      // Build tool_use_id → tool name map so tool_result segments can look up the name
      const _toolNameById = {};
      for (const seg of segments) {
        if (seg.type === 'tool_use' && seg.tool_use_id) {
          _toolNameById[seg.tool_use_id] = seg.name || 'tool';
        }
      }

      for (const seg of segments) {
        if (seg.type === 'text') {
          const text = _stripDirectiveTags(seg.text || '').trim();
          if (!text) continue;
          const textDiv = document.createElement('div');
          textDiv.className = 'msg-text-seg';
          textDiv.innerHTML = Markdown.render(text);  // eslint-disable-line no-unsanitized/property
          Markdown.bindCopy(textDiv);
          Markdown.bindHighlight(textDiv);
          body.appendChild(textDiv);
        } else if (seg.type === 'tool_use') {
          const details = _buildToolCallDOM(seg.name || 'tool', seg.tool_use_id || '', seg.input || '', false);
          body.appendChild(details);
        } else if (seg.type === 'tool_result') {
          const toolId = seg.tool_use_id || '';
          const isError = !!seg.is_error;
          const content = seg.result || '';

          if (toolId) {
            const details = body.querySelector('[data-tool-id="' + toolId + '"]');
            if (details) {
              details.classList.remove('chat-tools-collapse--running');
              details.classList.add(isError ? 'chat-tools-collapse--error' : 'chat-tools-collapse--success');
              const toolsBody = details.querySelector('.chat-tools-body');
              const resultDiv = _buildToolResultDOM(content, isError);
              if (resultDiv && toolsBody) toolsBody.appendChild(resultDiv);
              else if (resultDiv) details.appendChild(resultDiv);

              // web_search: inject provider badge and seed _searchProvider from persisted result
              if (_toolNameById[toolId] === 'web_search' && content) {
                const provider = _toolResultProvider(seg, content);
                if (provider) {
                  if (!_searchProvider) _searchProvider = provider;
                  _injectProviderBadge(details.querySelector('.chat-tools-summary'), provider);
                }
              }
            }
          }
        }
      }
    } catch {
      // Graceful degradation: leave original rendered content intact
    }
  }

  /* ── Message Rendering ──────────────────────────────────────────────── */

  function _renderMessageTags(options = {}) {
    const tags = [];
    if (options.provenanceKind === 'cron') {
      tags.push('<span class="cron-tag">Cron</span>');
    }
    if (tags.length === 0) return '';
    return `<span class="msg-tags">${tags.join('')}</span>`;
  }

  function _renderSubagentDisclosure(text) {
    const details = document.createElement('details');
    details.className = 'chat-subagent-disclosure';
    const summary = document.createElement('summary');
    summary.className = 'chat-subagent-disclosure-summary';
    let bodyEl;
    try {
      const parsed = JSON.parse(text);
      summary.textContent = 'Subagent: ' + (parsed.child_session_key || parsed.session_key || 'completion');
      const pre = document.createElement('pre');
      pre.className = 'chat-subagent-disclosure-body';
      pre.textContent = JSON.stringify(parsed, null, 2);
      bodyEl = pre;
    } catch (_) {
      summary.textContent = 'Subagent completion';
      const pre = document.createElement('pre');
      pre.className = 'chat-subagent-disclosure-body chat-subagent-disclosure-body--raw';
      pre.textContent = text;
      bodyEl = pre;
    }
    details.appendChild(summary);
    details.appendChild(bodyEl);
    return details;
  }

  function _appendSubagentCompletion(payload) {
    if (!payload) return;
    const parentSession = payload.parent_session_key || payload.parentSessionKey || '';
    if (parentSession && _sessionKey && parentSession !== _sessionKey) return;

    const text = JSON.stringify(payload);
    const timestamp = Date.now();
    const options = {
      provenanceKind: 'internal_system',
      provenanceSourceSessionKey: payload.child_session_key || payload.childSessionKey || '',
      provenanceSourceTool: 'subagent_completion',
    };
    _messages.push({
      role: 'system',
      text,
      ts: timestamp,
      ...options,
    });
    _addMessage('system', text, timestamp, options);
  }

  function _parseSubagentCompletion(text) {
    try {
      const parsed = JSON.parse(text);
      if (parsed && parsed.type === 'subagent_completion') return parsed;
    } catch (_) {
      // Not a subagent completion payload.
    }
    return null;
  }

  function _isSubagentCompletionMessage(role, text, options = {}) {
    if (role !== 'system' || !text) return false;
    if (options.provenanceSourceTool === 'subagent_completion') return true;
    return !!_parseSubagentCompletion(text);
  }

  function _dayKey(ts) {
    if (!ts) return '';
    const d = typeof ts === 'number' ? new Date(ts) : new Date(ts);
    if (isNaN(d.getTime())) return '';
    return d.toISOString().slice(0, 10); // 'YYYY-MM-DD'
  }

  function _dayLabel(isoDay) {
    if (!isoDay) return '';
    const today = new Date();
    const todayKey = today.toISOString().slice(0, 10);
    const yesterKey = new Date(today.getTime() - 86400000).toISOString().slice(0, 10);
    if (isoDay === todayKey) return 'Today';
    if (isoDay === yesterKey) return 'Yesterday';
    const d = new Date(isoDay + 'T12:00:00');
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  function _addMessage(role, text, timestamp, options = {}) {
    // Remove "No messages yet." placeholder
    const empty = _thread.querySelector('.chat-empty');
    if (empty) empty.remove();

    // Day separator: insert when calendar day changes
    const day = _dayKey(timestamp);
    if (day && day !== _lastHeaderDay) {
      const sep = document.createElement('div');
      sep.className = 'chat-day-sep';
      sep.innerHTML = `<span>${_dayLabel(day)}</span>`;
      _thread.appendChild(sep);
      _lastHeaderDay = day;
      // Day change resets role dedup so first message after separator shows its header
      _lastHeaderRole = '';
    }

    const isSubagentCompletion = _isSubagentCompletionMessage(role, text, options);
    const displayRole = isSubagentCompletion ? 'subagent' : role;

    const div = document.createElement('div');
    div.className = 'msg ' + displayRole;

    const roleText = displayRole === 'user' ? 'You'
      : displayRole === 'assistant' ? 'Assistant'
      : displayRole === 'subagent' ? 'Sub-agent'
      : displayRole.charAt(0).toUpperCase() + displayRole.slice(1);

    // Collapse header for consecutive same-speaker messages within the same day.
    // Always show for system/error/tool roles.
    const collapsible = (displayRole === 'user' || displayRole === 'assistant');
    const sameGroup = collapsible && (displayRole === _lastHeaderRole) && day === _lastHeaderDay && day !== '';
    if (collapsible) _lastHeaderRole = displayRole;

    if (!sameGroup) {
      const timeStr = timestamp ? _relTime(timestamp) : '';
      const isoStr = timestamp ? (typeof timestamp === 'string' ? timestamp : new Date(timestamp).toISOString()) : '';
      const header = document.createElement('div');
      header.className = 'msg-header';
      if (isoStr) header.title = new Date(isoStr).toLocaleString();
      header.innerHTML = `<span class="role-label">${roleText}</span>${_renderMessageTags(options)}<span class="msg-time">${_esc(timeStr)}</span>`;
      div.appendChild(header);
    } else {
      // No header; attach ISO timestamp as title on the bubble body for hover tooltip
      const isoStr = timestamp ? (typeof timestamp === 'string' ? timestamp : new Date(timestamp).toISOString()) : '';
      if (isoStr) div.title = new Date(isoStr).toLocaleString();
    }

    const body = document.createElement('div');
    _renderMessageBody(body, role, text, options);
    div.appendChild(body);
    _attachHoverActions(div, displayRole);
    _thread.appendChild(div);

    if (_autoScroll) _scrollToBottom();
    return div;
  }

  function _renderMessageBody(body, role, text, options = {}) {
    const isSubagentCompletion = _isSubagentCompletionMessage(role, text, options);
    body.className = 'msg-body';
    body.textContent = '';
    if (role === 'assistant' && text) {
      body.innerHTML = Markdown.render(_stripDirectiveTags(text));
      Markdown.bindCopy(body);
      Markdown.bindHighlight(body);
    } else if (isSubagentCompletion) {
      body.appendChild(_renderSubagentDisclosure(text));
    } else if (role === 'system' && text) {
      body.textContent = text;
    } else if (text) {
      body.textContent = role === 'user' ? _stripTimePrefix(text) : text;
    }
  }

  function _scrollToBottom() {
    if (_thread) {
      _thread.scrollTop = _thread.scrollHeight;
    }
  }

  /* ── Attachments ────────────────────────────────────────────────────── */

  function _addAttachment(file) {
    const mime = _resolveAttachmentMime(file);
    if (!_isAllowedAttachmentMime(mime)) {
      UI.toast(`Unsupported file: ${file.name || 'attachment'} (${mime}). Allowed: ${ATTACHMENT_ALLOWED_LABEL}`, 'warn', 4500);
      return;
    }
    const hardCap = _attachmentHardCapBytes(mime);
    if (file.size > hardCap) {
      UI.toast(`File too large: ${file.name || 'attachment'} (max ${Math.round(hardCap / 1024 / 1024)} MB)`, 'warn');
      return;
    }

    const localId = _nextAttachmentId++;

    // ≤ INLINE_THRESHOLD_BYTES → base64 inline on the WS frame.
    // Staged upload is intentionally limited to images and PDFs; text-family
    // files decode directly into prompt text and stay capped at the inline limit.
    if (file.size <= INLINE_THRESHOLD_BYTES) {
      _pendingAttachments.push({
        kind: 'inline_pending',
        local_id: localId,
        name: file.name,
        mime: mime,
        size: file.size,
      });
      _renderAttachmentPreview();
      const reader = new FileReader();
      reader.onload = (e) => {
        const dataUrl = e.target.result;
        const b64 = (dataUrl && dataUrl.split && dataUrl.split(',')[1]) || '';
        const index = _pendingAttachments.findIndex((att) => att.local_id === localId);
        if (index < 0) return;
        _pendingAttachments[index] = {
          kind: 'inline',
          local_id: localId,
          name: file.name,
          mime: mime,
          size: file.size,
          data: b64,
          dataUrl: dataUrl,
        };
        _renderAttachmentPreview();
      };
      reader.onerror = () => {
        _removeAttachmentByLocalId(localId);
        UI.toast(`Could not read file: ${file.name || 'attachment'}`, 'warn');
      };
      reader.readAsDataURL(file);
      return;
    }

    if (!_canStageAttachmentMime(mime)) {
      UI.toast(
        `File too large: ${file.name || 'attachment'} (text-family attachments are limited to ${Math.round(ATTACHMENT_TEXT_HARD_CAP_BYTES / 1000 / 1000)} MB)`,
        'warn',
        4500,
      );
      return;
    }

    _pendingAttachments.push({
      kind: 'uploading',
      local_id: localId,
      name: file.name,
      mime: mime,
      size: file.size,
    });
    _renderAttachmentPreview();
    _uploadAttachmentStaged(file, mime, localId).catch((err) => {
      _removeAttachmentByLocalId(localId);
      UI.toast(`Upload failed for ${file.name || 'attachment'}: ${err && err.message || err}`, 'warn', 4500);
    });
  }

  async function _uploadAttachmentStaged(file, mime, localId) {
    // The bridge upload endpoint /api/v1/files/upload; this client POSTs multipart and
    // stashes the returned file_uuid in _pendingAttachments as a staged entry.
    const form = new FormData();
    const uploadFile = file.type === mime || typeof File !== 'function'
      ? file
      : new File([file], file.name, { type: mime });
    form.append('file', uploadFile, file.name);
    form.append('mime', mime);
    const headers = {};
    const token = (App.getAuthToken && App.getAuthToken()) || '';
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const response = await fetch('/api/v1/files/upload', {
      method: 'POST',
      body: form,
      headers: headers,
      credentials: 'same-origin',
    });
    if (!response.ok) {
      const detail = await response.text().catch(() => '');
      throw new Error(`HTTP ${response.status} ${detail}`);
    }
    const result = await response.json();
    const index = _pendingAttachments.findIndex((att) => att.local_id === localId);
    if (index < 0) return;
    _pendingAttachments[index] = {
      kind: 'staged',
      local_id: localId,
      name: file.name,
      mime: mime,
      size: file.size,
      file_uuid: result.file_uuid,
    };
    _renderAttachmentPreview();
  }

  function _resolveAttachmentMime(file) {
    const name = file && file.name ? String(file.name) : '';
    const ext = name.includes('.') ? name.split('.').pop().toLowerCase() : '';
    const extensionMime = ATTACHMENT_EXTENSION_MIMES[ext];
    if (file && file.type && _isAllowedAttachmentMime(file.type)) return file.type;
    return extensionMime || (file && file.type) || 'application/octet-stream';
  }

  function _hasPendingAttachmentWork() {
    return _pendingAttachments.some((att) => att.kind === 'inline_pending' || att.kind === 'uploading');
  }

  function _removeAttachmentByLocalId(localId) {
    _pendingAttachments = _pendingAttachments.filter((att) => att.local_id !== localId);
    _renderAttachmentPreview();
  }

  function _renderMessageAttachmentHtml(att) {
    const mime = att.type || att.mime || '';
    const name = att.name || 'attachment';
    if ((mime || '').startsWith('image/') && (att.dataUrl || att.data)) {
      const src = att.dataUrl || `data:${_esc(mime || 'image/png')};base64,${att.data}`;
      return `<img class="msg-thumb" src="${src}" alt="${_esc(name)}">`;
    }
    return `<span class="msg-file-chip" title="${_esc(name)}">
      <span class="msg-file-chip__icon" aria-hidden="true">file</span>
      <span class="msg-file-chip__name">${_esc(name)}</span>
      <span class="msg-file-chip__meta">${_esc(mime || 'attachment')}</span>
    </span>`;
  }

  function _renderAttachmentPreview() {
    if (!_attachPreview) return;
    if (_pendingAttachments.length === 0) {
      _attachPreview.classList.add('hidden');
      _attachPreview.innerHTML = '';
      return;
    }
    _attachPreview.classList.remove('hidden');
    let html = '';
    _pendingAttachments.forEach((att, i) => {
      const isImage = (att.mime || '').startsWith('image/');
      const isBusy = att.kind === 'inline_pending' || att.kind === 'uploading';
      const status = att.kind === 'inline_pending' ? 'Reading...' : att.kind === 'uploading' ? 'Uploading...' : '';
      if (isImage && att.dataUrl) {
        html += `<div class="attachment-thumb">
          <img src="${att.dataUrl}" alt="${_esc(att.name)}">
          <button class="attachment-remove" data-idx="${i}">&times;</button>
          <span class="attachment-name">${_esc(att.name)}</span>
        </div>`;
      } else {
        const kb = att.size ? Math.max(1, Math.round(att.size / 1024)) + ' KB' : '';
        const stagedTag = att.kind === 'staged' ? ' • staged' : '';
        const busyClass = isBusy ? ' attachment-chip--busy' : '';
        const meta = status || `${att.mime || ''} ${kb}${stagedTag}`;
        html += `<div class="attachment-chip${busyClass}" data-mime="${_esc(att.mime || '')}">
          <span class="attachment-chip__icon" aria-hidden="true">${isBusy ? '<span class="spinner attachment-chip__spinner"></span>' : 'file'}</span>
          <span class="attachment-chip__name">${_esc(att.name)}</span>
          <span class="attachment-chip__meta">${_esc(meta)}</span>
          <button class="attachment-remove" data-idx="${i}" title="Remove">&times;</button>
        </div>`;
      }
    });
    _attachPreview.innerHTML = html;
    _attachPreview.querySelectorAll('.attachment-remove').forEach((btn) => {
      btn.addEventListener('click', () => {
        _pendingAttachments.splice(parseInt(btn.dataset.idx), 1);
        _renderAttachmentPreview();
      });
    });
  }

  /* ── Export as Markdown ─────────────────────────────────────────────── */

  function _exportMarkdown() {
    if (_messages.length === 0) {
      UI.toast('No messages to export', 'warn');
      return;
    }
    let md = `# Chat Export \u2014 ${_sessionKey}\n\n`;
    md += `Exported: ${new Date().toISOString()}\n\n---\n\n`;
    _messages.forEach((msg) => {
      const role = msg.role === 'user' ? 'You' : msg.role === 'assistant' ? 'Assistant' : msg.role;
      const time = msg.ts ? ` _(${new Date(msg.ts).toLocaleString()})_` : '';
      md += `### ${role}${time}\n\n${msg.text}${_artifactMarkdownLines(msg.artifacts || [])}\n\n---\n\n`;
    });

    const blob = new Blob([md], { type: 'text/markdown' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `chat-${_sessionKey}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
    UI.toast('Exported as Markdown', 'info');
  }

  function _artifactMarkdownLines(artifacts) {
    if (!Array.isArray(artifacts) || artifacts.length === 0) return '';
    const lines = artifacts.map((artifact) => {
      const name = artifact && artifact.name ? String(artifact.name) : 'artifact';
      const mime = artifact && artifact.mime ? String(artifact.mime) : '';
      const size = artifact && artifact.size ? `${Math.max(1, Math.round(Number(artifact.size) / 1024))} KB` : '';
      const url = _artifactExportDownloadUrl(artifact || {});
      const meta = [mime, size].filter(Boolean).join(' · ');
      const suffix = meta ? ` - ${meta}` : '';
      return `- [Download ${name}](${url})${suffix}`;
    });
    return `\n\nArtifacts:\n${lines.join('\n')}`;
  }

  function _artifactExportDownloadUrl(artifact) {
    const raw = _artifactDownloadUrl(artifact);
    if (!raw) return '';
    try {
      const url = new URL(raw, window.location.origin);
      if (_sessionKey) url.searchParams.set('sessionKey', _sessionKey);
      return url.href;
    } catch {
      return raw;
    }
  }

  /* ── Pending Queue (Proposal C) ─────────────────────────────────────── */

  function _onStop() {
    if (!_isStreaming) return;
    _stopRequestedByUser = true;
    _aborted = true;
    _rpc.call('chat.abort', { sessionKey: _sessionKey }).catch(() => {});
    _endStreaming({ reason: 'aborted' });
    // Recover queued messages back into the composer so the user can edit
    // and resend rather than losing them. Idempotent on empty queue.
    const recovered = _popAllPendingIntoComposer();
    UI.toast(recovered ? 'Stopped — pending recovered to input' : 'Stopped', 'warn', 1800);
  }

  // Delegated click handler bound once in _bindEvents() — prevents the per-render
  // listener-leak flagged by the Gemini review. All chip-remove / clear-all
  // clicks bubble here.
  function _onPendingAreaClick(ev) {
    const removeBtn = ev.target.closest('.chat-pending-chip-remove');
    if (removeBtn) {
      ev.stopPropagation();
      const idx = parseInt(removeBtn.dataset.idx, 10);
      if (!Number.isNaN(idx)) {
        _pendingQueue.splice(idx, 1);
        _renderPendingQueue();
      }
      return;
    }
    const clearBtn = ev.target.closest('[data-action="clear-all"]');
    if (clearBtn) {
      _pendingQueue = [];
      _renderPendingQueue();
    }
  }

  function _renderPendingQueue() {
    if (!_pendingArea) return;
    if (_pendingQueue.length === 0) {
      _pendingArea.classList.add('hidden');
      _pendingArea.innerHTML = '';
      return;
    }
    _pendingArea.classList.remove('hidden');
    const showClearAll = _pendingQueue.length >= 2;
    let html = `<div class="chat-pending-header">`
      + `<span class="chat-pending-label" title="Alt+↑ pulls the most recent back into the input · ESC recovers all to input · sends FIFO when the current response finishes">Pending ${_pendingQueue.length}/${_MAX_PENDING}</span>`;
    if (showClearAll) {
      html += `<button class="chat-pending-clear" data-action="clear-all" aria-label="Clear all pending messages">Clear all</button>`;
    }
    html += `</div><div class="chat-pending-chips">`;
    _pendingQueue.forEach((p, i) => {
      const raw = p.text || (p.attachments && p.attachments.length ? '(attachment only)' : '');
      const preview = _esc(raw.slice(0, 30)) + (raw.length > 30 ? '…' : '');
      const attChip = p.attachments && p.attachments.length > 0
        ? ` <span class="chat-pending-attch">📎${p.attachments.length}</span>` : '';
      const chipLabel = _esc(`Pending message ${i + 1}: ${raw.slice(0, 80)}`);
      html += `<span class="chat-pending-chip" data-idx="${i}" title="${_esc(raw)}">`
        + `<span class="chat-pending-text">${preview}</span>${attChip}`
        + `<button class="chat-pending-chip-remove" data-idx="${i}"`
        + ` aria-label="Remove ${chipLabel}" title="Remove">&times;</button>`
        + `</span>`;
    });
    html += `</div>`;
    _pendingArea.innerHTML = html;
  }

  function _drainQueueHead() {
    // Only called on natural (non-aborted) turn completion.
    if (_pendingQueue.length === 0) return;
    const head = _pendingQueue.shift();
    _renderPendingQueue();
    setTimeout(() => {
      _textarea.value = head.text || '';
      _pendingAttachments = head.attachments || [];
      _pendingSessionIntent = head.intent || null;
      _renderAttachmentPreview();
      _onSend();
    }, 0);
  }

  function _popPendingTail() {
    if (_pendingQueue.length === 0) return false;
    const tail = _pendingQueue.pop();
    _textarea.value = tail.text || '';
    _pendingAttachments = tail.attachments || [];
    _pendingSessionIntent = tail.intent || null;
    _renderAttachmentPreview();
    _renderPendingQueue();
    _autoResizeTextarea();
    return true;
  }

  // True when any modal / popover / dialog owned by the chat view is
  // currently visible in the DOM. Used by _onDocKeydown to defer ESC to the
  // overlay's own dismiss handler instead of grabbing it for turn abort or
  // pending recovery.
  //
  // The list intentionally targets exactly the widgets that register their
  // own document-level keydown handler:
  //   - .modal-backdrop  (UI.modal): exists only while open
  //   - .chat-session-popover (session picker): created on open, removed on close
  //   - #chat-toolbar-popover (composer settings gear): permanently in DOM,
  //     toggles a `hidden` class — check for absence of `.hidden`
  function _chatOverlayVisible() {
    if (document.querySelector('.modal-backdrop, .chat-session-popover')) return true;
    const toolbarPop = document.getElementById('chat-toolbar-popover');
    if (toolbarPop && !toolbarPop.classList.contains('hidden')) return true;
    return false;
  }

  // Recover the entire pending queue back into the composer for editing.
  // Modeled on claude-code-rebuilt's popAllEditable: queued texts join the
  // current textarea content with newlines (FIFO), attachments stack into
  // _pendingAttachments, and the queue is cleared. The caller decides
  // whether to send — recovery never auto-fires. Returns true when the
  // queue had something to recover.
  function _popAllPendingIntoComposer() {
    if (!_textarea || _pendingQueue.length === 0) return false;
    const queuedTexts = _pendingQueue
      .map((p) => (typeof p.text === 'string' ? p.text : ''))
      .filter(Boolean);
    const queuedAttachments = _pendingQueue.flatMap((p) => p.attachments || []);
    const headIntent = _pendingQueue[0] && _pendingQueue[0].intent;
    const current = _textarea.value || '';
    const joined = [current, ...queuedTexts].filter(Boolean).join('\n');
    _pendingQueue = [];
    _renderPendingQueue();
    _suppressHistoryReset = true;
    _textarea.value = joined;
    _suppressHistoryReset = false;
    _pendingAttachments = [..._pendingAttachments, ...queuedAttachments];
    _pendingSessionIntent = _pendingSessionIntent || headIntent || null;
    _renderAttachmentPreview();
    _autoResizeTextarea();
    try {
      const end = _textarea.value.length;
      _textarea.setSelectionRange(end, end);
      _textarea.focus();
    } catch (_) {
      /* setSelectionRange can throw on detached nodes; ignore */
    }
    // Reset history navigation: composer content is now user-editable text.
    _inputHistoryIdx = null;
    _inputHistoryDraft = '';
    return true;
  }

  // Programmatic textarea write that suppresses the input listener's
  // history-cursor reset for one event cycle. Used by _cycleHistory and
  // _popAllPendingIntoComposer when they need to set value without losing
  // their own cursor state.
  function _setTextareaProgrammatic(text) {
    if (!_textarea) return;
    const next = typeof text === 'string' ? text : '';
    _suppressHistoryReset = true;
    _textarea.value = next;
    _suppressHistoryReset = false;
    try {
      _textarea.setSelectionRange(next.length, next.length);
    } catch (_) {
      /* ignore */
    }
  }

  // Walk through the user's sent-message history (derived from _messages)
  // when ↑/↓ is pressed on an empty textarea. dir < 0 = older, dir > 0 = newer.
  // Returns true when the cursor moved (so the caller can preventDefault).
  function _cycleHistory(dir) {
    const history = _messages
      .filter((m) => m && m.role === 'user' && typeof m.text === 'string')
      .map((m) => m.text);
    if (history.length === 0) return false;

    if (dir < 0) {
      if (_inputHistoryIdx === null) {
        _inputHistoryDraft = _textarea.value || '';
        _inputHistoryIdx = history.length - 1;
      } else {
        _inputHistoryIdx = Math.max(0, _inputHistoryIdx - 1);
      }
      _setTextareaProgrammatic(history[_inputHistoryIdx]);
      _autoResizeTextarea();
      return true;
    }

    if (_inputHistoryIdx === null) return false;
    const next = _inputHistoryIdx + 1;
    if (next >= history.length) {
      _inputHistoryIdx = null;
      _setTextareaProgrammatic(_inputHistoryDraft);
      _inputHistoryDraft = '';
    } else {
      _inputHistoryIdx = next;
      _setTextareaProgrammatic(history[next]);
    }
    _autoResizeTextarea();
    return true;
  }

  // Enqueue the current textarea content into _pendingQueue. Mirrors the
  // streaming-branch logic in _onSend so Alt+↓ produces the same shape of
  // entry as "Send during streaming".
  function _enqueueCurrentInput() {
    const text = _textarea.value.trim();
    const hasPayload = text || _pendingAttachments.length > 0;
    if (!hasPayload) return false;
    if (_pendingQueue.length >= _MAX_PENDING) {
      UI.toast(`Pending queue full (${_MAX_PENDING})`, 'warn', 2000);
      return false;
    }
    _pendingQueue.push({
      text,
      attachments: _pendingAttachments.map((a) => ({ ...a })),
      intent: _pendingSessionIntent,
    });
    _textarea.value = '';
    _pendingAttachments = [];
    _pendingSessionIntent = null;
    _renderAttachmentPreview();
    _renderPendingQueue();
    _autoResizeTextarea();
    UI.toast(`Queued (${_pendingQueue.length}/${_MAX_PENDING})`, 'info', 1200);
    return true;
  }

  function _updateStopButton() {
    if (!_stopBtn) return;
    _stopBtn.classList.toggle('hidden', !_isStreaming);
  }

  /* ── Destroy ────────────────────────────────────────────────────────── */

  function destroy() {
    _viz.destroy();
    _clearActiveTaskGroups();
    _unsubscribeSession();
    _unsubs.forEach(fn => fn());
    _unsubs = [];
    _intervals.forEach(id => clearInterval(id));
    _intervals = [];
    if (_composerObserver) { _composerObserver.disconnect(); _composerObserver = null; }
    // Clear the root --composer-h so other views' toasts don't keep that offset.
    document.documentElement.style.removeProperty('--composer-h');
    if (_isStreaming) _endStreaming();
    _hideThinkingIndicator();
    if (_renderRafId) { cancelAnimationFrame(_renderRafId); _renderRafId = null; }
    _renderDirty = false;
    _closeSlashMenu();
    _pendingAttachments = [];
    _pendingQueue = [];
    _stopRequestedByUser = false;
    _messages = [];
    _totalTokens = 0;
    _lastHeaderRole = '';
    _lastHeaderDay = '';
    _composing = false;
    _thread = null;
    _textarea = null;
    _sendBtn = null;
    _stopBtn = null;
    _sessionInput = null;
    _sessionChip = null;
    _attachPreview = null;
    _pendingArea = null;
    _slashEl = null;
    _ctxWarn = null;
    _runStatusEl = null;
    _fileInput = null;
    _toolbar = null;
    _elevatedPill = null;
    _composer = null;
    _streamBubble = null;
    _streamRaw = '';
    _segments = []; _activeTextSeg = null; _activeTextRaw = '';
    _streamArtifacts = [];
    _el = null;
    _rpc = null;
  }

  return { render, destroy };
})();

window.ChatView = ChatView;
