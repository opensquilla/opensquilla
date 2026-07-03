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

  const _RUN_MODE_FALLBACK = 'trusted';
  const _RUN_MODE_LABELS = {
    standard: 'Standard-Sandbox',
    trusted: 'Trusted-Sandbox',
    full: 'Full Host Access',
  };
  const _RUN_MODE_TITLES = {
    standard: 'Sandboxed execution. Risky actions ask before running.',
    trusted: 'Sandboxed execution with fewer routine prompts. Boundary changes still ask.',
    full: 'Host execution without per-command prompts. Use only for trusted workspaces.',
  };
  let _runModePolicyDefault = _RUN_MODE_FALLBACK;
  let _allowedRunModes = new Set(['standard', 'trusted', 'full']);
  let _fullHostAccessDisabledReason = null;
  let _runMode = _runModePolicyDefault;
  let _sandboxSetupStatus = null;
  let _sandboxSetupRequestSeq = 0;
  let _sandboxSetupInFlight = false;
  let _pendingSandboxSetupMode = '';
  let _sandboxSetupPromptDismissed = false;

  // Streaming
  let _isStreaming = false;
  let _aborted = false;
  let _streamBubble = null;
  let _streamSessionKey = '';
  let _streamRaw = '';           // full accumulated text (for export)
  let _streamGeneration = 0;
  let _segments = [];             // [{type:'text', raw:'', el:DOM}, {type:'tool', el:DOM}, ...]
  let _activeTextSeg = null;      // pointer to current text segment's DOM element
  let _activeTextRaw = '';        // raw text for current active segment only
  let _streamArtifacts = [];
  let _autoScroll = true;
  let _streamIdleTimer = null;
  let _streamIdlePausedForApproval = false;
  let _approvalPendingForCurrentSession = false;
  let _currentRunStatus = 'idle';
  let _historySyncTimer = null;
  const _AWAITING_MODEL_CLASS = 'awaiting-model';
  const _STREAM_ACTIVE_MARK_CLASS = 'streaming-active-mark';
  const _STREAM_ACTIVE_MARK_DELAY_MS = 3500;
  let _streamActiveMarkTimer = null;
  let _streamActiveMarkVisibleStartedAt = 0;
  let _lastVisibleStreamEvent = '';
  const _DEFAULT_STREAM_IDLE_TIMEOUT_MS = 210000; // server should emit terminal first
  let _streamIdleTimeoutMs = _DEFAULT_STREAM_IDLE_TIMEOUT_MS;
  let _lastStreamSeq = 0;
  const _streamSeqBySession = new Map();
  const _streamSeqSeenBySession = new Map();
  const _STREAM_SEQ_SEEN_WINDOW = 800;
  const _liveStreamStateBySession = new Map();
  let _activeTaskGroups = new Set();
  // Task id whose output the live stream is currently rendering. Empty = unknown
  // (no guard). Set on task.running, reset on session switch. Binds late events
  // to the current turn so a prior task can't leak into it (issue 344).
  let _activeStreamTaskId = '';
  let _pendingFinalizedAssistantBubble = null;
  let _pendingFinalizedAssistantFallbackId = '';
  const _pendingRouterDecisions = new Map();
  let _routerFxScanDelayTimer = null;
  let _routerFxScanPending = null;
  const _CHAT_DIAG_KEY = 'opensquilla.chat.debugLog';
  const _CHAT_DIAG_ENABLED_KEY = 'opensquilla.chat.debug.enabled';
  const _CHAT_DIAG_MAX = 300;
  // Session epoch counter. Frames carrying an older epoch are stale
  // (arrived from a turn that predates the last reset) and must be discarded.
  let _currentEpoch = 0;

  function _chatDiagEnabled() {
    try {
      return window.localStorage.getItem(_CHAT_DIAG_ENABLED_KEY) === '1';
    } catch {
      return false;
    }
  }

  function _chatDiagShortText(value, maxLen = 120) {
    if (value == null) return '';
    return String(value).replace(/\s+/g, ' ').trim().slice(0, maxLen);
  }

  function _chatDiagClassName(el) {
    if (!el) return '';
    if (typeof el.className === 'string') return el.className;
    return String(el.className || '');
  }

  function _chatDiagDescribeElement(el) {
    if (!el) return null;
    const dataset = el.dataset || {};
    return {
      tag: el.tagName || '',
      cls: _chatDiagClassName(el),
      role: el.getAttribute ? (el.getAttribute('data-history-role') || '') : '',
      live: dataset.live || '',
      state: dataset.state || '',
      scanning: dataset.scanning || '',
      sessionKey: dataset.sessionKey || '',
      turnIndex: dataset.turnIndex || '',
      routerIdentity: dataset.routerIdentity || '',
      text: _chatDiagShortText(el.textContent || '', 90),
      connected: !!el.isConnected,
    };
  }

  function _chatDiagDomSnapshot() {
    const thread = (typeof _thread !== 'undefined') ? _thread : null;
    const streamBubble = (typeof _streamBubble !== 'undefined') ? _streamBubble : null;
    const thinkingEl = (typeof _thinkingEl !== 'undefined') ? _thinkingEl : null;
    const snapshot = {
      sessionKey: (typeof _sessionKey !== 'undefined') ? _sessionKey : '',
      isStreaming: !!((typeof _isStreaming !== 'undefined') && _isStreaming),
      aborted: !!((typeof _aborted !== 'undefined') && _aborted),
      streamGeneration: (typeof _streamGeneration !== 'undefined') ? _streamGeneration : null,
      lastStreamSeq: (typeof _lastStreamSeq !== 'undefined') ? _lastStreamSeq : null,
      streamRawLen: (typeof _streamRaw === 'string') ? _streamRaw.length : 0,
      activeTextRawLen: (typeof _activeTextRaw === 'string') ? _activeTextRaw.length : 0,
      streamBubble: _chatDiagDescribeElement(streamBubble),
      thinkingEl: _chatDiagDescribeElement(thinkingEl),
      threadReady: !!thread,
    };
    if (!thread) return snapshot;
    const children = Array.from(thread.children || []);
    snapshot.childCount = children.length;
    snapshot.msgCount = thread.querySelectorAll('.msg').length;
    snapshot.userMsgCount = thread.querySelectorAll('.msg.user').length;
    snapshot.assistantMsgCount = thread.querySelectorAll('.msg.assistant').length;
    snapshot.streamingMsgCount = thread.querySelectorAll('.msg.streaming').length;
    snapshot.thinkingMsgCount = thread.querySelectorAll('.msg.thinking').length;
    snapshot.routerCount = thread.querySelectorAll('.router-fx').length;
    snapshot.liveRouterCount = thread.querySelectorAll('.router-fx[data-live="true"]').length;
    snapshot.scanningRouterCount = thread.querySelectorAll('.router-fx[data-scanning="true"]').length;
    snapshot.tail = children.slice(Math.max(0, children.length - 14)).map(_chatDiagDescribeElement);
    return snapshot;
  }

  function _chatDiagSummarizePayload(payload) {
    if (!payload || typeof payload !== 'object') {
      return { value: _chatDiagShortText(payload, 160) };
    }
    const out = {};
    [
      'event', 'stream_seq', 'epoch', 'from_state', 'to_state', 'toState',
      'tier', 'model', 'routed_tier', 'routed_model', 'routing_source',
      'routing_applied', 'rollout_phase', 'reason', 'tool_name', 'name',
      'tool_use_id', 'message_id', 'sessionKey', 'session_key',
      'input_tokens', 'output_tokens',
    ].forEach((key) => {
      if (payload[key] != null) out[key] = payload[key];
    });
    if (typeof payload.text === 'string') {
      out.textLen = payload.text.length;
      out.textHead = _chatDiagShortText(payload.text, 100);
    }
    const raw = payload.result || payload.content || payload.output;
    if (typeof raw === 'string') {
      out.resultLen = raw.length;
      out.resultHead = _chatDiagShortText(raw, 100);
    }
    if (payload.usage && typeof payload.usage === 'object') {
      out.usage = _chatDiagSummarizePayload(payload.usage);
    }
    if (payload.arguments && typeof payload.arguments === 'object') {
      out.arguments = {
        kind: payload.arguments.kind || '',
        paused: payload.arguments.paused,
        hasClarifySchema: !!payload.arguments.clarify_schema,
      };
    }
    return out;
  }

  function _chatDiagReadLog() {
    try {
      return JSON.parse(window.localStorage.getItem(_CHAT_DIAG_KEY) || '[]');
    } catch {
      return [];
    }
  }

  function _chatDiagWriteLog(entries) {
    try {
      window.localStorage.setItem(_CHAT_DIAG_KEY, JSON.stringify(entries.slice(-_CHAT_DIAG_MAX)));
    } catch {
      // Ignore quota/storage failures. Console logging below still helps.
    }
  }

  function _chatDiag(label, data) {
    if (!_chatDiagEnabled()) return;
    const entry = {
      t: Date.now(),
      iso: new Date().toISOString(),
      label,
      data: data || {},
      dom: _chatDiagDomSnapshot(),
    };
    try {
      const entries = _chatDiagReadLog();
      entries.push(entry);
      _chatDiagWriteLog(entries);
    } catch {
      // Keep diagnostics best-effort only.
    }
    try {
      console.debug('[chat-diag]', label, entry);
    } catch {}
  }

  function _installChatDiagConsole() {
    if (typeof window === 'undefined') return;
    window.OpenSquillaChatDiag = {
      key: _CHAT_DIAG_KEY,
      dump() {
        const entries = _chatDiagReadLog();
        try { console.log('[chat-diag dump]', entries); } catch {}
        return entries;
      },
      clear() {
        try { window.localStorage.removeItem(_CHAT_DIAG_KEY); } catch {}
        return [];
      },
      disable() {
        try { window.localStorage.setItem(_CHAT_DIAG_ENABLED_KEY, '0'); } catch {}
        return false;
      },
      enable() {
        try { window.localStorage.setItem(_CHAT_DIAG_ENABLED_KEY, '1'); } catch {}
        return true;
      },
      snapshot: _chatDiagDomSnapshot,
      copy() {
        const text = JSON.stringify(_chatDiagReadLog(), null, 2);
        if (window.navigator && window.navigator.clipboard) {
          window.navigator.clipboard.writeText(text).catch(() => {});
        }
        return text;
      },
    };
  }
  _installChatDiagConsole();

  // Attachments
  // Two-mode attachment buffer: each entry is either
  //   {kind:'inline',  name, mime, data,      dataUrl}      (≤ 2 MB; base64 inline)
  //   {kind:'staged',  name, mime, file_uuid, size}         (image/PDF > 2 MB; POSTed to /api/v1/files/upload)
  // Single source of truth for the inline-vs-staged threshold; never re-typed.
  const INLINE_THRESHOLD_BYTES = 2_000_000;
  const ATTACHMENT_TEXT_HARD_CAP_BYTES = INLINE_THRESHOLD_BYTES;
  const LARGE_PASTE_CHARS = 20_000;
  const PAGE_DUMP_CHARS = 8_000;
  const PAGE_DUMP_MARKER_MIN_SCORE = 3;
  const PAGE_DUMP_MARKERS = [
    'Chat session',
    'agent:main:webchat:',
    'Still waiting for agent response',
    'AI MODEL ROUTER',
    'The provider returned an empty response',
    'Pulsing',
    'Running',
    'Send a message',
    'SYSTEM',
    'SQUILLA',
  ];
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
  let _sendTextOverride = null;
  let _sendDisplayTextOverride = null;
  let _pendingDrainAfterTerminalTimer = null;
  let _compactInFlight = false;
  let _compactInFlightKey = '';
  let _compactSuppressedRouterSessionKey = '';
  let _compactSuppressedRouterTurnIndex = '';
  let _lastCompactionToastSig = '';
  let _lastCompactionToastAt = 0;
  let _compactionSeparatorEl = null;
  let _compactionSeparatorTimer = null;
  let _stopRequestedByUser = false;
  let _pendingArea = null;
  let _stopBtn = null;
  let _runStatusEl = null;
  const CHAT_HISTORY_PAGE_SIZE = 50;
  let _historyLoadedMessages = [];
  let _historyOldestCursor = null;
  let _historyNewestCursor = null;
  let _historyHasMore = false;
  let _historyScope = 'complete';
  let _historyLoadingEarlier = false;
  let _historyHydrating = false;
  let _historyHasRendered = false;
  let _historyRequestSeq = 0;
  let _historyError = '';
  let _historyCompactionSummaries = [];

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
  // kept in sync with stream.py WaitingIndicator._verbs
  const SQUILLA_VERBS = ['Watching','Tracking','Sensing','Pulsing','Thinking','Drafting','Polishing'];
  const SQUILLA_DWELL_MS = 2500;

  // Inline directive tags — control signals the LLM emits per system prompt
  // instructions (e.g. reply threading).  Must be stripped before display.
  const _DIRECTIVE_TAG_RE = /\[\[\s*(?:reply_to_current|reply_to\s*:\s*[^\]\n]+)\s*\]\]\s*/g;
  function _stripDirectiveTags(text) {
    return text.replace(_DIRECTIVE_TAG_RE, '').replace(/^\n+/, '');
  }
  const _GENERATED_ARTIFACT_MARKER_RE = /(?:^|\s*)\[generated artifact omitted:\s*[^\]\n]+?\]\s*/gi;
  function _stripGeneratedArtifactMarkers(text) {
    text = String(text || '');
    if (!text.includes('[generated artifact omitted:')) return text;
    return text
      .replace(/\r\n/g, '\n')
      .replace(_GENERATED_ARTIFACT_MARKER_RE, '')
      .replace(/[ \t]{2,}/g, ' ')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  }
  const _PROTOCOL_TEXT_MARKER_RE = /<\s*(?:minimax:tool_call|tool_calls?|tvoe_calls|invoke\b|parameter\b|effect_calls\b|details\b|angle\s+brackets\b)/i;
  const _PROTOCOL_TEXT_PARAMETER_RE = /<\s*parameter\s+name\s*=\s*["'](?:path|content|command|code|patch)["']/i;
  const _PROTOCOL_TEXT_INVOKE_RE = /<\s*invoke\s+name\s*=\s*["'][A-Za-z_][A-Za-z0-9_.:-]*["']/i;
  const _PROTOCOL_TEXT_HTML_RE = /<!doctype\s+html\b|<html\b|<\/html\s*>/i;
  const _PROTOCOL_TEXT_CLOSE_RE = /<\/\s*invoke\s*>|<\/\s*(?:tool_calls?|tvoe_calls)\s*>/i;
  const _PROTOCOL_TEXT_STANDALONE_RE = /<\s*(?:parameter|effect_calls|tool_calls?|tvoe_calls|angle\s+brackets)\s*>/i;
  const _PROTOCOL_TEXT_DETAILS_RE = /<\s*details\s*>\s*<\s*summary\s*>\s*View areas around line\b/i;

  function _looksLikeProtocolTextSuffix(suffix) {
    if (/<\s*minimax:tool_call\s*>/i.test(suffix)) return true;
    if (_PROTOCOL_TEXT_STANDALONE_RE.test(suffix)) return true;
    if (_PROTOCOL_TEXT_DETAILS_RE.test(suffix)) return true;
    if (_PROTOCOL_TEXT_PARAMETER_RE.test(suffix)) return true;
    if (_PROTOCOL_TEXT_INVOKE_RE.test(suffix) && _PROTOCOL_TEXT_CLOSE_RE.test(suffix)) return true;
    if (_PROTOCOL_TEXT_HTML_RE.test(suffix) && _PROTOCOL_TEXT_INVOKE_RE.test(suffix)) return true;
    return false;
  }

  function _stripProtocolTextLeak(text) {
    text = String(text || '');
    if (!text) return text;
    const match = _PROTOCOL_TEXT_MARKER_RE.exec(text);
    if (!match) return text;
    const suffix = text.slice(match.index);
    if (!_looksLikeProtocolTextSuffix(suffix)) return text;
    return text.slice(0, match.index).trimEnd();
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

  function _normalizeProvider(provider) {
    return String(provider || '').trim();
  }

  function _injectProviderBadge(summary, provider) {
    provider = _normalizeProvider(provider);
    if (!summary || !provider) return;
    let badge = summary.querySelector('.chat-tool-provider');
    if (!badge) {
      badge = document.createElement('span');
      badge.className = 'chat-tool-provider';
      summary.appendChild(badge);
    }
    badge.textContent = (_PROVIDER_LOGOS[provider] || '') + ' ' + provider;
    badge.title = 'Search provider: ' + provider;
  }

  function _refreshRunningSearchProviderBadges(provider) {
    provider = _normalizeProvider(provider);
    if (!_el || !provider) return;
    _el
      .querySelectorAll('.chat-tools-collapse--running[data-tool-name="web_search"] .chat-tools-summary')
      .forEach(summary => _injectProviderBadge(summary, provider));
  }

  function _setSearchProvider(provider, options = {}) {
    provider = _normalizeProvider(provider);
    if (!provider) return;
    _searchProvider = provider;
    if (options.refreshRunning !== false) {
      _refreshRunningSearchProviderBadges(provider);
    }
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
  let _slashCmds = [];
  let _slashCommandMap = new Map();
  let _slashCatalogLoaded = false;

  // Tool icon mapping
  const _TOOL_EMOJI = {
    bash: '\uD83D\uDCBB',         // 💻
    read_file: '\uD83D\uDCC4',    // 📄
    write_file: '\u270F\uFE0F',   // ✏️
    edit_file: '\u270F\uFE0F',    // ✏️
    web_search: '\uD83D\uDD0D',   // 🔍
    web_discover: '\uD83D\uDD0E', // 🔎
    search: '\uD83D\uDD0D',       // 🔍
    http_request: '\uD83C\uDF10', // 🌐
    web_fetch: '\uD83C\uDF10',    // 🌐
    list_files: '\uD83D\uDCC2',   // 📂
    memory_search: '\uD83E\uDDE0',// 🧠
    memory_store: '\uD83E\uDDE0', // 🧠
  };
  function _toolEmoji(name) {
    if (name && name.startsWith('meta-step:')) return '⚙️'; // ⚙️ meta-skill step
    return _TOOL_EMOJI[name] || '\u26A1'; // ⚡ default
  }

  // Context-pressure tracking. This is current provider context, not lifetime usage.
  let _contextStatus = null;

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
  // Per-identity celebration timestamps so the cooldown throttles only repeats
  // of the SAME routed (model|tier) — not every turn globally. Without this, a
  // standard turn's celebration would mask a following, differently-routed
  // tool-assisted turn for the whole 10-minute window.
  const _savingsPopupTsByIdentity = new Map();
  function _resetSavingsPopupCooldown() {
    _savingsPopupLastTs = 0;
    _lastSavingsPopupIdentity = '';
    _savingsPopupTsByIdentity.clear();
    if (window.SavingsFX) {
      window.SavingsFX.resetStreak();
      window.SavingsFX.cleanup();
    }
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
      const usage = await _rpc.call('usage.status', { sessionKey: _sessionKey });
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
        _applyContextStatus(current.contextStatus || current.context_status || null);
        _saveWidgetState();
      } else {
        _clearContextStatus();
      }
    } catch {
      _clearContextStatus();
    }
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
  let _micBtn = null;
  let _sessionInput = null;
  let _sessionChip = null;
  let _attachPreview = null;
  let _slashEl = null;
  let _ctxWarn = null;
  let _fileInput = null;
  let _toolbar = null;
  let _runModeControl = null;
  let _sandboxSetupBanner = null;
  let _composer = null;
  let _composerObserver = null;
  let _mediaRecorder = null;
  let _recordedAudioChunks = [];
  let _recordingStream = null;
  let _voiceInputBusy = false;

  /* ── Helpers ────────────────────────────────────────────────────────── */

  function _esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function _escAttr(s) {
    return _esc(s);
  }

  function _displayRoleLabel(role) {
    return role === 'user' ? 'You'
      : role === 'assistant' ? 'Squilla'
      : role === 'subagent' ? 'Sub-agent'
      : role ? role.charAt(0).toUpperCase() + role.slice(1)
      : '';
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

  function _clearMessageActionFocus(reason = '') {
    const active = document.activeElement;
    if (!active || !active.closest || !active.closest('.msg-actions')) return;
    active.blur();
    _chatDiag('message_actions.focus_cleared', { reason: reason || '' });
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
    row.setAttribute('aria-label', role === 'user' ? 'User message actions' : 'Squilla message actions');

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

  // Re-send the user turn that produced the clicked assistant bubble.
  // Pops that assistant bubble and any later turns from DOM + _messages.
  function _regenerateAssistantBubble(bubble) {
    if (_isStreaming) {
      UI.toast('Wait for the current response to finish', 'warn', 2000);
      return;
    }
    if (!bubble || !_thread) {
      UI.toast('No response to regenerate', 'info', 2000);
      return;
    }

    const assistantBubbles = Array.from(_thread.querySelectorAll(':scope > .msg.assistant'));
    const assistantOrdinal = assistantBubbles.indexOf(bubble);
    if (assistantOrdinal < 0) {
      UI.toast('No response to regenerate', 'info', 2000);
      return;
    }

    let assistantSeen = -1;
    let assistantIdx = -1;
    for (let i = 0; i < _messages.length; i++) {
      if (_messages[i].role !== 'assistant') continue;
      assistantSeen++;
      if (assistantSeen === assistantOrdinal) {
        assistantIdx = i;
        break;
      }
    }
    if (assistantIdx < 0) {
      UI.toast('No response to regenerate', 'info', 2000);
      return;
    }

    let userIdx = -1;
    for (let i = assistantIdx - 1; i >= 0; i--) {
      if (_messages[i].role === 'user') { userIdx = i; break; }
    }
    if (userIdx < 0) {
      UI.toast('No previous message to regenerate', 'info', 2000);
      return;
    }

    const userText = _messages[userIdx].text || '';
    _messages.splice(userIdx + 1);

    let target = bubble.previousElementSibling;
    while (target && !target.matches('.msg.user')) {
      target = target.previousElementSibling;
    }
    if (target) {
      let nxt = target.nextElementSibling;
      while (nxt) {
        const toRemove = nxt;
        nxt = nxt.nextElementSibling;
        toRemove.remove();
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
        if (artifactBtn.tagName === 'A') return;
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
      btn.blur();
      const action = btn.dataset.action;
      if (action === 'copy') {
        const text = _extractBubbleText(bubble);
        _copyTextToClipboard(text)
          .then(() => UI.toast('Copied', 'info', 1200))
          .catch((err) => UI.toast('Copy failed: ' + err.message, 'err', 2500));
      } else if (action === 'regenerate') {
        _regenerateAssistantBubble(bubble);
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

  function _historyTurnMeta(msg) {
    const u = msg?.usage || msg?.turn_usage || null;
    const model = msg?.model || u?.model || u?.routed_model || '';
    const input = Number(msg?.input ?? msg?.input_tokens ?? u?.input_tokens ?? u?.inputTokens ?? 0);
    const output = Number(msg?.output ?? msg?.output_tokens ?? u?.output_tokens ?? u?.outputTokens ?? 0);
    if (!model && input <= 0 && output <= 0 && !u) return null;
    const saved = u ? { ...u, model: u.model || model || null } : null;
    return { model, input, output, saved };
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
      const displayModel = _modelDisplayName(model);
      const span = document.createElement('span');
      span.className = 'msg-meta__model';
      span.textContent = displayModel;
      if (displayModel !== model) span.title = model;
      meta.appendChild(span);
    }
    if (hasTokens) {
      const span = document.createElement('span');
      span.className = 'msg-meta__tokens';
      span.textContent = `↑${_fmtTok(totalIn)} ↓${_fmtTok(totalOut)}`;
      span.title = `Turn — input: ${totalIn.toLocaleString()}, output: ${totalOut.toLocaleString()} tokens`;
      meta.appendChild(span);
    }
    if (u.cached_tokens > 0) {
      const span = document.createElement('span');
      span.className = 'msg-meta__cached';
      span.textContent = `cache:${_fmtTok(u.cached_tokens)}`;
      span.title = `Cached tokens: ${u.cached_tokens.toLocaleString()}`;
      meta.appendChild(span);
    }
    if (u.reasoning_tokens > 0) {
      const span = document.createElement('span');
      span.className = 'msg-meta__reasoning';
      span.textContent = `think:${_fmtTok(u.reasoning_tokens)}`;
      span.title = `Reasoning tokens: ${u.reasoning_tokens.toLocaleString()}`;
      meta.appendChild(span);
    }
    if (u.cost_usd > 0) {
      const span = document.createElement('span');
      span.className = 'msg-meta__cost';
      span.textContent = `$${u.cost_usd.toFixed(6).replace(/\.?0+$/, '')}`;
      span.title = `Turn cost: $${u.cost_usd.toFixed(6)}`;
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
    if (canonicalKey !== _sessionKey) {
      _clearActiveTaskGroups();
      // The newly shown session has its own (possibly running) task; forget the
      // previous session's active task so we stay lenient until it re-asserts.
      _activeStreamTaskId = '';
    }
    _sessionKey = canonicalKey;
    _syncLastStreamSeqFromSession(canonicalKey);
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
        if (res && res.provider) _setSearchProvider(res.provider);
      }).catch(() => { /* ignore; badge will fill in from result JSON */ });
    }

    // Session key priority: URL query > localStorage > canonical WebChat default
    const urlSession = _readSessionFromUrl();
    const urlAgent = _readAgentFromUrl();
    const storedSession = localStorage.getItem('opensquilla_active_session') || '';
    _sessionKey = _canonicalSessionKey(urlSession || (urlAgent ? _webchatSessionKey(urlAgent) : storedSession));
    _persistSession(_sessionKey);

    const topbarCenter = App.getTopbarCenter && App.getTopbarCenter();
    if (topbarCenter) {
      topbarCenter.innerHTML = `
        <label class="chat-label">Chat session</label>
        <button type="button" class="chat-session-chip" id="chat-session-chip"
                aria-label="Switch chat session" aria-haspopup="dialog" aria-expanded="false">
          <span class="chat-session-chip-key" id="chat-session-chip-key" title="${_esc(_sessionKey)}">${_esc(_sessionKey)}</span>
          <span class="chat-session-chip-caret" aria-hidden="true">${_iconChevronDown()}</span>
        </button>
        <button class="chat-session-copy-btn" id="chat-session-copy" title="Copy session key" aria-label="Copy session key">${icons.copy()}</button>
        <span class="chip" id="chat-run-status" title="Idle">Idle</span>
        <span class="chat-ctx-warn hidden" id="chat-ctx-warn">Request ctx</span>`;
      topbarCenter.classList.remove('hidden');
    }

    _el.innerHTML = `
      <div class="chat">
        <div class="chat-body">
          <div class="chat-thread" id="chat-thread"
               role="region"
               aria-label="Chat conversation"
               aria-busy="false">
            ${_emptyStateHTML()}
          </div>
        </div>
        <div class="chat-pending hidden" id="chat-pending"></div>
        <div class="chat-composer" id="chat-composer">
          <div class="chat-attachments hidden" id="chat-attach-preview"></div>
          <div class="chat-slash hidden" id="chat-slash"></div>
          <div class="chat-sandbox-setup-banner hidden" id="chat-sandbox-setup-banner">
            <div class="chat-sandbox-setup-copy">
              <strong>Establish sandbox</strong>
              <span data-sandbox-setup-detail>Standard-Sandbox and Trusted-Sandbox need a ready sandbox backend.</span>
            </div>
            <div class="chat-sandbox-setup-actions">
              <button type="button" class="btn btn--sm btn--primary" data-sandbox-setup-action="ensure">Set up</button>
              <button type="button" class="btn btn--sm btn--ghost" data-sandbox-setup-action="dismiss">Dismiss</button>
            </div>
          </div>
          <div class="chat-input-bar">
            <button class="btn btn--icon btn--ghost" id="chat-btn-attach" title="Attach files: PNG, JPEG, GIF, WEBP, PDF, TXT, MD, HTML, CSV, JSON" aria-label="Attach files">${icons.paperclip()}</button>
            <div class="chat-toolbar-wrap">
              <button type="button" class="btn btn--icon btn--ghost chat-toolbar-trigger" id="chat-toolbar-trigger"
                      title="Run modes — execution, router"
                      aria-label="Run modes"
                      aria-haspopup="dialog"
                      aria-expanded="false">${_iconGear()}<span class="chat-toolbar-trigger-dots" aria-hidden="true"><i data-dot="run-mode"></i><i data-dot="router"></i></span></button>
              <div class="chat-toolbar-popover hidden" id="chat-toolbar-popover" role="dialog" aria-label="Composer settings">
                <div class="chat-toolbar-popover-arrow" aria-hidden="true"></div>
                <div class="chat-toolbar-popover-inner" id="chat-toolbar">
                  <div class="chat-toolbar-row">
                    <span class="chat-toolbar-row-label">Run Mode</span>
                    <div class="chat-run-mode-control" id="chat-run-mode-control">
                      <button type="button" class="chat-run-mode-trigger" id="chat-run-mode-trigger"
                              aria-haspopup="listbox" aria-expanded="false" aria-controls="chat-run-mode-menu"
                              data-run-mode="trusted" data-run-mode-help="Sandboxed execution with fewer routine prompts. Boundary changes still ask.">
                        <span class="chat-run-mode-current">Trusted-Sandbox</span>
                        <span class="chat-run-mode-chevron" aria-hidden="true"></span>
                      </button>
                      <div class="chat-run-mode-menu hidden" id="chat-run-mode-menu" role="listbox" aria-label="Run Mode choices">
                        <button type="button" class="chat-run-mode-option" role="option" data-run-mode="standard"
                                data-run-mode-help="Sandboxed execution. Risky actions ask before running.">Standard-Sandbox</button>
                        <button type="button" class="chat-run-mode-option" role="option" data-run-mode="trusted"
                                data-run-mode-help="Sandboxed execution with fewer routine prompts. Boundary changes still ask.">Trusted-Sandbox</button>
                        <button type="button" class="chat-run-mode-option" role="option" data-run-mode="full"
                                data-run-mode-help="Host execution without per-command prompts. Use only for trusted workspaces.">Full Host Access</button>
                      </div>
                      <div class="chat-run-mode-tooltip hidden" id="chat-run-mode-tooltip" role="tooltip"></div>
                    </div>
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
                  <div class="chat-toolbar-row">
                    <span class="chat-toolbar-row-label">Visual effects</span>
                    <div class="toggle-switch-wrap" id="pill-router-fx-group" title="Show router and savings effects">
                      <label class="toggle-switch" aria-label="Visual effects">
                        <input type="checkbox" id="toggle-router-fx" />
                        <span class="toggle-track"><span class="toggle-thumb"></span></span>
                      </label>
                    </div>
                  </div>
                  <div class="chat-toolbar-row">
                    <span class="chat-toolbar-row-label">Coding mode</span>
                    <div class="toggle-switch-wrap" id="pill-codetask-group" title="Lock this session into coding mode: code changes go through code-task. Off makes code-task unavailable.">
                      <label class="toggle-switch" aria-label="Coding mode">
                        <input type="checkbox" id="toggle-codetask" />
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
            <button class="btn btn--icon btn--ghost" id="chat-btn-mic" title="Record voice input" aria-label="Record voice input">${icons.microphone ? icons.microphone() : icons.chat()}</button>
            <button class="btn btn--icon btn--ghost" id="chat-btn-meta-history" title="MetaSkill run history" aria-label="MetaSkill run history">${icons.logs ? icons.logs() : icons.chat()}</button>
            <button class="btn btn--icon btn--ghost" id="chat-btn-new" title="New chat session in the current agent" aria-label="New chat session in the current agent">${icons.plus()}</button>
            <button class="btn btn--icon btn--ghost" id="chat-btn-export" title="Export as Markdown" aria-label="Export as Markdown">${icons.download()}</button>
            <button class="btn btn--icon btn--primary" id="chat-btn-send" title="Send (queues while streaming)" aria-label="Send message">${icons.send()}</button>
            <button class="btn btn--icon btn--danger hidden" id="chat-btn-stop" title="Stop current response (Esc)" aria-label="Stop current response">${icons.stop()}</button>
          </div>
        </div>
        <input type="file" id="chat-file-input" accept="image/png,image/jpeg,image/gif,image/webp,application/pdf,text/plain,text/markdown,text/html,text/csv,application/json,application/mbox,message/rfc822,application/vnd.ms-outlook,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.openxmlformats-officedocument.presentationml.presentation,.md,.markdown,.docx,.xlsx,.pptx,.eml,.mbox,.msg" multiple class="hidden" />
      </div>`;

    // Cache DOM refs
    _thread       = _el.querySelector('#chat-thread');
    _textarea     = _el.querySelector('#chat-textarea');
    _sendBtn      = _el.querySelector('#chat-btn-send');
    _micBtn       = _el.querySelector('#chat-btn-mic');
    _sessionInput = null;  // replaced by chip; session key lives in _sessionKey
    _sessionChip  = document.getElementById('chat-session-chip');
    _attachPreview = _el.querySelector('#chat-attach-preview');
    _pendingArea  = _el.querySelector('#chat-pending');
    _stopBtn      = _el.querySelector('#chat-btn-stop');
    _slashEl      = _el.querySelector('#chat-slash');
    _ctxWarn      = document.getElementById('chat-ctx-warn');
    _runStatusEl  = document.getElementById('chat-run-status');
    _fileInput    = _el.querySelector('#chat-file-input');
    _toolbar      = _el.querySelector('#chat-toolbar');
    _runModeControl = _el.querySelector('#chat-run-mode-control');
    _sandboxSetupBanner = _el.querySelector('#chat-sandbox-setup-banner');
    _composer     = _el.querySelector('#chat-composer');

    _messages = [];
    _clearContextStatus();
    _resetHistoryPagingState();
    _lastHeaderRole = '';
    _lastHeaderDay = '';
    _applySessionRunState({ run_status: 'idle' });

    _bindEvents();
    _bindToolbarPills();
    _bindToolbarTrigger();
    _bindRunModePicker();
    _bindSandboxSetupBanner();
    _updateRunModeControl();
    _applyHelloRunModePolicy(_rpc?.hello);
    _bindSessionChip();
    _bindComposerResize();
    _bindHoverActions();
    _restoreWidgetState();
    _subscribeRpcEvents();
    _subscribeSession();
    // Config (which populates _routerFxModels and registers all
    // configured tiers including image_only ones) must finish before
    // the first history render — otherwise non-winner cells fall back
    // to the tier id ("c1", "c2") instead of the real model name.
    _loadFeatureToggles()
      .catch(() => { /* fall through to history anyway */ })
      .finally(() => _loadHistory());
    _loadSlashCommands();
    _bindRouterConfigRefresh();

    // Keep desktop keyboard flow quick, but avoid opening the soft keyboard on
    // mobile/touch devices before the user asks to type.
    if (_textarea && _shouldAutofocusComposer()) _textarea.focus();
  }

  /* ── Toolbar Pills (feature toggles) ────────────────────────────────── */

  function _shouldAutofocusComposer() {
    try {
      if (window.matchMedia('(max-width: 768px)').matches) return false;
      if (window.matchMedia('(pointer: coarse)').matches) return false;
    } catch {}
    return true;
  }

  function _bindToolbarPills() {
    // Squilla Router toggle switch
    const routerToggle = _el.querySelector('#toggle-router');
    if (routerToggle) {
      routerToggle.addEventListener('change', async () => {
        const enabled = routerToggle.checked;
        const previousRouterFeatureEnabled = _routerFeatureEnabled;
        _routerFeatureEnabled = enabled;
        if (!enabled) _clearRouterFxVisuals('router_disabled');
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
          _routerFeatureEnabled = previousRouterFeatureEnabled;
          routerToggle.checked = !enabled;
          if (!previousRouterFeatureEnabled) _clearRouterFxVisuals('router_patch_reverted');
          else _scheduleHistorySync();
          UI.toast('Failed: ' + e.message, 'err');
        }
      });
    }

    // Coding-mode toggle — operator-level (persists to config). ON locks the
    // session into coding mode (code changes go through code-task); OFF makes
    // code-task unavailable across every skill API.
    const codetaskToggle = _el.querySelector('#toggle-codetask');
    if (codetaskToggle) {
      codetaskToggle.addEventListener('change', async () => {
        const enabled = codetaskToggle.checked;
        try {
          await _rpc.call('config.patch.safe', { patches: { 'skills.coding_mode': enabled } });
          UI.toast('Coding mode: ' + (enabled ? 'ON' : 'OFF'), 'info');
        } catch (e) {
          codetaskToggle.checked = !enabled;  // revert on failure
          UI.toast('Failed: ' + e.message, 'err');
        }
      });
    }

    // Router-fx visualisation toggle — purely client-side (no config write):
    // it only controls whether THIS browser draws the animated grid.
    const routerFxToggle = _el.querySelector('#toggle-router-fx');
    if (routerFxToggle) {
      routerFxToggle.addEventListener('change', () => {
        _routerFx.enabled = routerFxToggle.checked;
        _routerFxSavePref();
        if (_routerFx.enabled) {
          // Re-render via the normal history rebuild — the render gates now
          // allow strips, so historical turns get their grid back.
          _scheduleHistorySync();
        } else if (_thread) {
          // Hide now. This is a user-visible preference, so remove the visual
          // immediately instead of preserving a separate live-strip path.
          _thread.querySelectorAll('.router-fx').forEach((n) => _routerFxRemoveStrip(n));
        }
        if (window.SavingsFX) window.SavingsFX.setEnabled(_routerFx.enabled);
        UI.toast('Visual effects: ' + (_routerFx.enabled ? 'ON' : 'OFF'), 'info');
      });
    }

  }

  // Re-pull router config (and rebuild history strips) when the chat
  // tab regains visibility/focus. Covers the common case where the
  // operator switches to the config view, edits tier mappings or
  // toggles squilla_router.enabled, then comes back to chat without
  // a hard refresh. We debounce so a quick visibility→focus burst
  // produces a single refresh.
  let _routerConfigRefreshTimer = null;
  function _scheduleRouterConfigRefresh() {
    if (_routerConfigRefreshTimer) clearTimeout(_routerConfigRefreshTimer);
    _routerConfigRefreshTimer = setTimeout(() => {
      _routerConfigRefreshTimer = null;
      _loadFeatureToggles()
        .catch(() => { /* keep going; history rebuild is harmless */ })
        .finally(() => _scheduleHistorySync());
    }, 120);
  }
  function _bindRouterConfigRefresh() {
    const onVisibility = () => {
      if (document.visibilityState === 'visible') _scheduleRouterConfigRefresh();
    };
    const onFocus = () => _scheduleRouterConfigRefresh();
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('focus', onFocus);
    _unsubs.push(() => document.removeEventListener('visibilitychange', onVisibility));
    _unsubs.push(() => window.removeEventListener('focus', onFocus));
  }

  async function _loadFeatureToggles() {
    try {
      await _rpc.waitForConnection();
      const cfg = await _rpc.call('config.get');
      const routerEnabled = (cfg?.squilla_router?.enabled ?? false) && cfg?.squilla_router?.rollout_phase === 'full';
      const routerToggle = _el?.querySelector('#toggle-router');
      if (routerToggle) routerToggle.checked = routerEnabled;
      _toolbarState.router = routerEnabled;
      _routerFeatureEnabled = !!(cfg?.squilla_router?.enabled);
      // Hydrate the client-side router-fx visualisation preference and sync
      // its switch. Independent of the operator routing state above; persisted
      // per browser, so it survives view re-render / navigation. Inherits the
      // visibility/focus refresh that re-runs this function for free.
      _routerFxLoadPref();
      _routerFxApplyConfigVisualMode(cfg?.squilla_router?.visual_mode);
      const routerFxToggle = _el?.querySelector('#toggle-router-fx');
      if (routerFxToggle) routerFxToggle.checked = _routerFx.enabled;
      if (window.SavingsFX) window.SavingsFX.setEnabled(_routerFx.enabled);
      // Coding mode: ON reflects skills.coding_mode.
      const codetaskToggle = _el?.querySelector('#toggle-codetask');
      if (codetaskToggle) {
        codetaskToggle.checked = !!(cfg?.skills?.coding_mode);
      }
      _refreshToolbarTriggerGlow();

      // Pre-populate the router visualisation from the operator's actual
      // configured tiers. We keep every tier in the cache, including
      // image-only routes, but render-time request-kind filtering decides
      // which candidates can really be called for this turn.
      //
      // We REPLACE _routerFxSlotList from config (rather than merge)
      // so that tiers the operator has removed drop out of the grid
      // on the next config refresh. _routerFxConfigTiers records the
      // authoritative set for downstream filtering of historic strips
      // whose routed_tier has been deleted.
      const tiers = cfg?.squilla_router?.tiers;
      const configTierKeys = [];
      const configTierSet = new Set();
      if (tiers && typeof tiers === 'object') {
        Object.keys(tiers).forEach((tier) => {
          if (typeof tier !== 'string' || !tier) return;
          const lower = _routerFxNormalizeTier(tier);
          if (!lower) return;
          configTierKeys.push(lower);
          configTierSet.add(lower);
          const rawTier = tiers[tier];
          const tierConfig = {
            model: typeof rawTier?.model === 'string' ? rawTier.model : '',
            supportsImage: rawTier?.supports_image === true,
            imageOnly: rawTier?.image_only === true,
          };
          _routerFxTierConfigs[lower] = tierConfig;
          if (tierConfig.model) _routerFxModels[lower] = tierConfig.model;
        });
      }
      Object.keys(_routerFxModels).forEach((tier) => {
        if (!configTierSet.has(tier)) delete _routerFxModels[tier];
      });
      Object.keys(_routerFxTierConfigs).forEach((tier) => {
        if (!configTierSet.has(tier)) delete _routerFxTierConfigs[tier];
      });
      _routerFxConfigTiers = configTierSet;
      if (configTierKeys.length > 0) {
        _routerFxSlotList = _routerFxSortTiers(configTierKeys);
      }
      // Mark config ready as soon as the tier cache is populated.
      // Anything waiting on _routerFxAwaitConfig() (history rebuild)
      // unblocks here, even if loadCurrentSessionUsage below throws.
      _routerFxMarkConfigReady();

      // Load current session usage for the token widget (survives page refresh)
      await _loadCurrentSessionUsage();
    } catch {
      // If config fetch itself failed, still release the gate so
      // history rebuild doesn't hang forever waiting for tiers we
      // can't fetch.
      _routerFxMarkConfigReady();
    }
  }

  /* ── Session Chip ────────────────────────────────────────────────────── */

  function _updateSessionChip(key) {
    const previousKey = _sessionKey;
    _sessionKey = key;
    const chipKey = document.getElementById('chat-session-chip-key');
    const copyBtn = document.getElementById('chat-session-copy');
    if (chipKey) {
      chipKey.textContent = key;
      chipKey.title = key;
    }
    if (copyBtn) copyBtn.title = 'Copy session key: ' + key;
    // Drop every router strip that belonged to the previous session
    // the moment the chip flips, even before the new session's
    // history_load reconciles. Otherwise a persisted strip from the
    // outgoing session sits orphaned at the top of the thread.
    if (previousKey && previousKey !== key && _thread) {
      _thread.querySelectorAll('.router-fx').forEach((el) => {
        if (el.dataset.sessionKey === key) return;
        _routerFxRemoveStrip(el);
      });
    }
  }

  function _runStatusLabel(status) {
    const labels = {
      queued: 'Queued',
      running: 'Running',
      approval_pending: 'Waiting for approval',
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
    if (value === 'killed') return 'cancelled';
    if (value === 'waiting for approval') return 'approval_pending';
    if (value === 'succeeded' || value === 'success' || value === 'complete') return 'idle';
    if (['queued', 'running', 'approval_pending', 'interrupted', 'failed', 'timeout', 'cancelled'].includes(value)) {
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
      approval_pending: 'chip-warn',
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
    if (active && ['queued', 'running', 'approval_pending'].includes(activeStatus)) status = activeStatus;
    const task = active || last || null;
    return { status, label: _runStatusLabel(status), task };
  }

  function _runStatusIsActive(status) {
    return ['queued', 'running', 'approval_pending'].includes(_normalizeRunStatus(status));
  }

  function _taskGroupId(payload) {
    const id = payload && payload.group_id;
    return (typeof id === 'string' && id) ? id : '';
  }

  function _clearActiveTaskGroups() {
    _activeTaskGroups.clear();
  }

  function _isCurrentSessionPayload(payload) {
    const key = payload?.key || payload?.session_key || payload?.sessionKey || '';
    return !key || !_sessionKey || key === _sessionKey;
  }

  function _sessionKeyFromPayload(payload) {
    return payload?.key || payload?.session_key || payload?.sessionKey || '';
  }

  function _payloadTaskId(payload) {
    const id = payload && (payload.task_id || payload.taskId);
    return (typeof id === 'string' && id) ? id : '';
  }

  // Lenient task guard (issue 344): an event is foreign only when a task owns
  // the live stream AND the event is tagged with a DIFFERENT task. Untagged
  // events (non-TaskRuntime: approvals, task groups, router…) and an unknown
  // active task always pass, so only positively-mismatched events are dropped.
  function _isForeignTaskPayload(payload) {
    if (!_activeStreamTaskId) return false;
    const taskId = _payloadTaskId(payload);
    if (!taskId) return false;
    return taskId !== _activeStreamTaskId;
  }

  function _sessionStreamSeq(key) {
    const stored = _streamSeqBySession.get(key || '');
    return (typeof stored === 'number' && Number.isFinite(stored)) ? stored : 0;
  }

  function _setSessionStreamSeq(key, seq) {
    if (!key || typeof seq !== 'number' || !Number.isFinite(seq)) return;
    const next = Math.max(_sessionStreamSeq(key), seq);
    _streamSeqBySession.set(key, next);
    if (key === _sessionKey) _lastStreamSeq = next;
  }

  function _sessionStreamSeqSeen(key) {
    const canonicalKey = key || '';
    let seen = _streamSeqSeenBySession.get(canonicalKey);
    if (!seen) {
      seen = new Set();
      _streamSeqSeenBySession.set(canonicalKey, seen);
    }
    return seen;
  }

  function _markSessionStreamSeqSeen(key, seq) {
    if (!key || typeof seq !== 'number' || !Number.isFinite(seq)) return true;
    const seen = _sessionStreamSeqSeen(key);
    if (seen.has(seq)) return false;
    seen.add(seq);
    _setSessionStreamSeq(key, seq);

    const highWater = _sessionStreamSeq(key);
    const pruneBefore = highWater - _STREAM_SEQ_SEEN_WINDOW;
    if (seen.size > _STREAM_SEQ_SEEN_WINDOW) {
      seen.forEach((value) => {
        if (value < pruneBefore) seen.delete(value);
      });
    }
    return true;
  }

  function _syncLastStreamSeqFromSession(key) {
    _lastStreamSeq = _sessionStreamSeq(key || _sessionKey || '');
  }

  function _dropForeignSessionPayload(event, payload) {
    if (!_isCurrentSessionPayload(payload)) {
      _chatDiag(`${event}.drop.foreign_session`, _chatDiagSummarizePayload(payload));
      return true;
    }
    // Same session, but a stale task's late event must not leak into the turn
    // the live stream is rendering now (issue 344).
    if (_isForeignTaskPayload(payload)) {
      _chatDiag(`${event}.drop.foreign_task`, _chatDiagSummarizePayload(payload));
      return true;
    }
    return false;
  }

  function _sessionChangeIsTerminal(payload) {
    const reason = String(payload?.reason || '').toLowerCase();
    if (reason === 'turn_complete' || reason === 'task_terminal') return true;
    const lifecycle = String(payload?.status || '').toLowerCase();
    if (['done', 'failed', 'killed', 'timeout'].includes(lifecycle)) return true;
    const runStatus = _normalizeRunStatus(payload?.run_status || payload?.runStatus);
    return ['failed', 'timeout', 'cancelled', 'interrupted'].includes(runStatus);
  }

  function _subscribeResultNeedsTerminalHistorySync(res) {
    if (!res || Number(res.replayed_count || 0) > 0) return false;
    const state = _sessionRunStatus(res);
    if (state.status !== 'idle' || !state.task) return false;
    const taskStatus = String(state.task.status || '').toLowerCase();
    const terminalReason = String(state.task.terminal_reason || state.task.terminalReason || '').toLowerCase();
    return ['succeeded', 'success', 'complete', 'completed', 'done'].includes(taskStatus)
      || terminalReason === 'completed';
  }

  function _syncTerminalSessionChange(payload = {}) {
    if (!_isCurrentSessionPayload(payload)) return false;
    _clearActiveTaskGroups();
    const state = _sessionRunStatus(payload);
    const recoverPending = ['cancelled', 'interrupted', 'failed', 'timeout'].includes(state.status);
    if (_isStreaming) _endStreaming(recoverPending ? { reason: 'aborted' } : undefined);
    _applySessionRunState(payload);
    _scheduleHistorySync();
    if (recoverPending) {
      _stopRequestedByUser = false;
      _recoverPendingAfterTerminal(state.status);
    } else {
      _schedulePendingDrainAfterTerminal();
    }
    return true;
  }

  function _dropReplayedLiveWaitEvent(meta, payload, eventName) {
    if (!(meta && meta.replayed)) return false;
    if (_isStreaming || _streamBubble) return false;
    _chatDiag(`${eventName}.drop.replayed_without_live_stream`, _chatDiagSummarizePayload(payload));
    return true;
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
    const state = _sessionRunStatus(source);
    _currentRunStatus = state.status;
    const el = _runStatusEl || document.getElementById('chat-run-status');
    if (!el) return;
    _runStatusEl = el;
    el.className = `chip ${_runStatusChipClass(state.status)}`.trim();
    el.textContent = state.label;
    const taskId = state.task && state.task.task_id ? state.task.task_id : '';
    const reason = state.task && state.task.terminal_reason ? state.task.terminal_reason : '';
    const queuePosition = state.task && (state.task.queue_position || state.task.queuePosition);
    const queueTitle = queuePosition ? `queue #${queuePosition}` : '';
    el.title = [state.label, taskId, queueTitle, reason].filter(Boolean).join(' - ');
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
    _cancelPendingRouterFxScan('session_switch');
    _parkCurrentSessionStreamState('session_switch');
    _updateSessionChip(key);
    _persistSession(key);
    _messages = [];
    _pendingSessionIntent = null;
    _clearPendingDrainAfterTerminalTimer();
    _setCompactInFlight(false);
    _hideCompactionSeparator();
    _pendingQueue = []; if (_pendingArea) _renderPendingQueue();
    _applySessionRunState({ run_status: 'idle' });
    _clearContextStatus();
    _lastHeaderRole = '';
    _lastHeaderDay = '';
    _usageAccum = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: null, routedTurns: 0, sessionSaved: 0 };
    _usageModel = '';
    _viz.reset(); _resetSavingsPopupCooldown();
    _restoreWidgetState();
    _loadCurrentSessionUsage();
    _restoreLiveStreamStateForSession(_sessionKey);
    _subscribeSession();
    _loadHistory();
  }

  function _bindSessionChip() {
    // The chip itself now acts as the dropdown trigger (one-control session
    // chip per the design review). The copy button stays as a sibling.
    const switchBtn = document.getElementById('chat-session-chip');
    const copyBtn = document.getElementById('chat-session-copy');
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

      const chip = document.getElementById('chat-session-chip');
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
      search.setAttribute('aria-label', 'Search sessions');
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
      const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 320;
      const margin = 12;
      const popWidth = Math.min(320, Math.max(240, viewportWidth - margin * 2));
      const maxLeft = Math.max(margin, viewportWidth - popWidth - margin);
      pop.style.position = 'fixed';
      pop.style.width = popWidth + 'px';
      pop.style.left = Math.min(Math.max(rect.left, margin), maxLeft) + 'px';
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

  // Track non-default state on controls so the gear glows accent only when
  // at least one is set away from defaults: run mode OR router off.
  let _toolbarState = {
    runMode: _runModePolicyDefault,
    router: true,         // false when router toggle is off
  };

  function _toolbarTriggerActive() {
    if (_toolbarState.runMode !== _runModePolicyDefault) return true;
    if (_toolbarState.router === false) return true;
    return false;
  }

  function _refreshToolbarTriggerGlow() {
    const trigger = _el && _el.querySelector('#chat-toolbar-trigger');
    if (!trigger) return;
    trigger.classList.toggle('is-glowing', _toolbarTriggerActive());
    // Per-toggle status dots — each lights independently so a glance at the
    // composer reveals which mode is non-default, not just that something is.
    const runMode = _normalizeRunMode(_toolbarState.runMode);
    const nonDefaultRunMode = runMode !== _runModePolicyDefault;
    const routerOff = _toolbarState.router === false;
    trigger.classList.toggle('has-dot-run-mode', nonDefaultRunMode);
    trigger.classList.toggle('has-dot-run-mode-full', runMode === 'full');
    trigger.classList.toggle('has-dot-router', routerOff);
    trigger.title = [
      `Run Mode: ${_RUN_MODE_LABELS[runMode] || _RUN_MODE_LABELS.standard}`,
      `Squilla Router: ${routerOff ? 'Off' : 'On'}`,
      'Visual effects',
    ].join(' · ');
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

  function _runModePolicyValue(value) {
    const normalized = String(value || '').trim().toLowerCase().replace(/_/g, '-');
    if (normalized === 'standard' || normalized === 'standard-sandbox') return 'standard';
    if (normalized === 'trusted' || normalized === 'trust' || normalized === 'trusted-sandbox') return 'trusted';
    if (normalized === 'full' || normalized === 'full-host-access' || normalized === 'host') return 'full';
    return '';
  }

  function _normalizeRunModePolicyValue(value, fallback) {
    return _runModePolicyValue(value) || _runModePolicyValue(fallback) || _RUN_MODE_FALLBACK;
  }

  function _normalizeRunMode(mode) {
    return _normalizeRunModePolicyValue(mode, _runModePolicyDefault);
  }

  function _runModeAllowed(mode) {
    const normalized = _runModePolicyValue(mode);
    return !!normalized && _allowedRunModes.has(normalized);
  }

  function _firstAllowedRunMode() {
    if (_allowedRunModes.has(_RUN_MODE_FALLBACK)) return _RUN_MODE_FALLBACK;
    if (_allowedRunModes.has('standard')) return 'standard';
    if (_allowedRunModes.has('trusted')) return 'trusted';
    if (_allowedRunModes.has('full')) return 'full';
    return _RUN_MODE_FALLBACK;
  }

  function _clampRunMode(mode) {
    const normalized = _normalizeRunModePolicyValue(mode, _runModePolicyDefault);
    if (_runModeAllowed(normalized)) return normalized;
    if (_runModeAllowed(_runModePolicyDefault)) return _runModePolicyDefault;
    return _firstAllowedRunMode();
  }

  function _fullHostAccessDisabledMessage() {
    let lang = '';
    if (typeof document !== 'undefined' && document.documentElement) {
      lang = document.documentElement.lang || '';
    }
    if (!lang && typeof navigator !== 'undefined') lang = navigator.language || '';
    if (String(lang).toLowerCase().startsWith('zh')) {
      return '当前账号不是 owner，不能选择 Full Host Access。你可以使用 Standard-Sandbox 或 Trusted-Sandbox。';
    }
    return 'This account is not the owner, so Full Host Access is unavailable. You can use Standard-Sandbox or Trusted-Sandbox.';
  }

  function _applyHelloRunModePolicy(hello) {
    const policy = hello && hello.auth && hello.auth.runModePolicy;
    const previousPolicyDefault = _runModePolicyDefault;
    const nextAllowed = new Set();
    if (policy && Array.isArray(policy.allowedRunModes)) {
      policy.allowedRunModes.forEach((mode) => {
        const normalized = _runModePolicyValue(mode);
        if (normalized) nextAllowed.add(normalized);
      });
    }
    _allowedRunModes = nextAllowed.size > 0
      ? nextAllowed
      : new Set(['standard', 'trusted']);

    const policyDefaultFallback = _allowedRunModes.has('full') ? 'full' : _RUN_MODE_FALLBACK;
    const policyDefault = _normalizeRunModePolicyValue(
      policy && policy.defaultRunMode,
      policyDefaultFallback,
    );
    _runModePolicyDefault = _allowedRunModes.has(policyDefault)
      ? policyDefault
      : _firstAllowedRunMode();

    const disabledReason = policy && policy.fullHostAccessDisabledReason;
    _fullHostAccessDisabledReason = _allowedRunModes.has('full')
      ? null
      : (disabledReason ? String(disabledReason) : 'owner_required');

    if (_runMode === previousPolicyDefault) {
      _runMode = _runModePolicyDefault;
    }
    _runMode = _clampRunMode(_runMode);
    _toolbarState.runMode = _runMode;
    _updateRunModeControl();
    _refreshToolbarTriggerGlow();
  }

  function _runModeHelp(mode) {
    const normalized = _normalizeRunMode(mode);
    return _RUN_MODE_TITLES[normalized] || _RUN_MODE_TITLES.standard;
  }

  function _showRunModeTooltip(anchor) {
    if (!_el || !anchor) return;
    const tip = _el.querySelector('#chat-run-mode-tooltip');
    if (!tip) return;
    const mode = _normalizeRunMode(anchor.dataset.runMode || _runMode);
    tip.textContent = anchor.dataset.runModeHelp || _runModeHelp(mode);
    const rect = anchor.getBoundingClientRect();
    tip.style.left = `${Math.max(12, Math.min(window.innerWidth - 292, rect.left))}px`;
    tip.style.top = `${Math.max(12, rect.bottom + 8)}px`;
    tip.classList.remove('hidden');
  }

  function _hideRunModeTooltip() {
    const tip = _el && _el.querySelector('#chat-run-mode-tooltip');
    if (!tip) return;
    tip.classList.add('hidden');
  }

  function _bindRunModePicker() {
    const control = _runModeControl;
    const trigger = control && control.querySelector('#chat-run-mode-trigger');
    const menu = control && control.querySelector('#chat-run-mode-menu');
    if (!control || !trigger || !menu) return;

    let open = false;
    const close = () => {
      open = false;
      menu.classList.add('hidden');
      trigger.classList.remove('is-open');
      trigger.setAttribute('aria-expanded', 'false');
      _hideRunModeTooltip();
    };
    const show = () => {
      open = true;
      menu.classList.remove('hidden');
      trigger.classList.add('is-open');
      trigger.setAttribute('aria-expanded', 'true');
    };

    trigger.addEventListener('click', (event) => {
      event.stopPropagation();
      if (open) close(); else show();
    });
    document.addEventListener('mousedown', (event) => {
      if (!open || control.contains(event.target)) return;
      close();
    });
    control.querySelectorAll('.chat-run-mode-option').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const mode = _normalizeRunMode(btn.dataset.runMode);
        close();
        if (btn.disabled || btn.getAttribute('aria-disabled') === 'true' || !_runModeAllowed(mode)) {
          UI.toast(_fullHostAccessDisabledMessage(), mode === 'full' ? 'warn' : 'info', 2400);
          return;
        }
        if (mode === _runMode) return;
        if (!(await _requestSandboxSetupForMode(mode))) return;
        _setRunMode(mode, { toast: true });
      });
    });
    control.querySelectorAll('[data-run-mode]').forEach((node) => {
      node.addEventListener('mouseenter', () => _showRunModeTooltip(node));
      node.addEventListener('focus', () => _showRunModeTooltip(node));
      node.addEventListener('mouseleave', _hideRunModeTooltip);
      node.addEventListener('blur', _hideRunModeTooltip);
    });
  }

  function _setRunMode(mode, options = {}) {
    const normalized = _normalizeRunMode(mode);
    const clamped = _clampRunMode(normalized);
    if (normalized !== clamped && !_runModeAllowed(normalized)) {
      UI.toast(_fullHostAccessDisabledMessage(), normalized === 'full' ? 'warn' : 'info', 2400);
      return false;
    }
    _runMode = clamped;
    _toolbarState.runMode = clamped;
    _updateRunModeControl();
    _refreshToolbarTriggerGlow();
    _refreshSandboxSetupBanner(clamped);
    if (options.toast) {
      UI.toast(`Run Mode: ${_RUN_MODE_LABELS[clamped]}`, clamped === 'full' ? 'warn' : 'info', 1800);
    }
    return true;
  }

  function _updateRunModeControl() {
    const control = _runModeControl || (_el && _el.querySelector('#chat-run-mode-control'));
    if (!control) return;
    _runModeControl = control;
    const active = _clampRunMode(_runMode);
    const trigger = control.querySelector('#chat-run-mode-trigger');
    const current = control.querySelector('.chat-run-mode-current');
    if (trigger) {
      trigger.dataset.runMode = active;
      trigger.dataset.runModeHelp = _runModeHelp(active);
      trigger.classList.toggle('is-danger', active === 'full');
    }
    if (current) current.textContent = _RUN_MODE_LABELS[active] || _RUN_MODE_LABELS.standard;
    control.querySelectorAll('.chat-run-mode-option').forEach((btn) => {
      const mode = _normalizeRunMode(btn.dataset.runMode);
      const allowed = _runModeAllowed(mode);
      const selected = mode === active;
      btn.classList.toggle('is-active', selected);
      btn.classList.toggle('is-danger', mode === 'full' && selected);
      btn.setAttribute('aria-selected', selected ? 'true' : 'false');
      btn.disabled = !allowed;
      btn.setAttribute('aria-disabled', allowed ? 'false' : 'true');
      const help = !allowed && mode === 'full'
        ? _fullHostAccessDisabledMessage()
        : _runModeHelp(mode);
      btn.dataset.runModeHelp = help;
      btn.title = help;
    });
    const menu = control.querySelector('#chat-run-mode-menu');
    if (menu) {
      let hint = menu.querySelector('[data-run-mode-disabled-hint]');
      if (!hint) {
        hint = document.createElement('div');
        hint.className = 'chat-run-mode-disabled-hint hidden';
        hint.setAttribute('data-run-mode-disabled-hint', '');
        menu.appendChild(hint);
      }
      const showHint = !!_fullHostAccessDisabledReason;
      hint.textContent = showHint ? _fullHostAccessDisabledMessage() : '';
      hint.classList.toggle('hidden', !showHint);
    }
  }

  function _isSandboxSetupReadyPayload(payload) {
    if (!payload || typeof payload !== 'object') return false;
    const state = String(payload.state || payload.status || '').toLowerCase();
    return payload.ready === true || state === 'ready' || state === 'ok' || state === 'available';
  }

  function _sandboxSetupReadyForMode(mode) {
    return _normalizeRunMode(mode) === 'full' || _isSandboxSetupReadyPayload(_sandboxSetupStatus);
  }

  function _refreshSandboxSetupBanner(mode) {
    const banner = _sandboxSetupBanner || (_el && _el.querySelector('#chat-sandbox-setup-banner'));
    if (!banner) return;
    _sandboxSetupBanner = banner;
    mode = _normalizeRunMode(mode || _runMode);
    const ready = _sandboxSetupReadyForMode(mode);
    const pendingPrompt = !!_pendingSandboxSetupMode;
    const setupKnown = _sandboxSetupStatus !== null;
    const optionalPrompt = setupKnown && !_sandboxSetupPromptDismissed;
    const shouldShow = mode !== 'full'
      && !ready
      && (pendingPrompt || optionalPrompt);
    banner.classList.toggle('hidden', !shouldShow);
    const detail = banner.querySelector('[data-sandbox-setup-detail]');
    if (detail) {
      detail.textContent = _sandboxSetupInFlight
        ? 'Preparing the trusted sandbox backend...'
        : `${_RUN_MODE_LABELS[mode]} needs a ready sandbox backend.`;
    }
  }

  async function _loadSandboxSetupStatus(mode) {
    if (!_rpc) return null;
    const requestSeq = ++_sandboxSetupRequestSeq;
    try {
      if (_rpc.waitForConnection) await _rpc.waitForConnection();
      const payload = await _rpc.call('sandbox.setup.status', {});
      if (requestSeq !== _sandboxSetupRequestSeq) return _sandboxSetupStatus;
      _sandboxSetupStatus = payload || null;
      _refreshSandboxSetupBanner(mode);
      return _sandboxSetupStatus;
    } catch {
      _sandboxSetupStatus = null;
      _refreshSandboxSetupBanner(mode);
      return null;
    }
  }

  async function _ensureSandboxSetupOnly(mode) {
    if (!_rpc || _sandboxSetupInFlight) return false;
    _sandboxSetupInFlight = true;
    _refreshSandboxSetupBanner(mode);
    try {
      if (_rpc.waitForConnection) await _rpc.waitForConnection();
      const payload = await _rpc.call('sandbox.setup.ensure', {});
      _sandboxSetupStatus = payload || null;
      return _isSandboxSetupReadyPayload(_sandboxSetupStatus);
    } catch (err) {
      UI.toast('Sandbox setup failed: ' + err.message, 'err', 3500);
      return false;
    } finally {
      _sandboxSetupInFlight = false;
      _refreshSandboxSetupBanner(mode);
    }
  }

  async function _requestSandboxSetupForMode(mode) {
    mode = _normalizeRunMode(mode);
    if (!_runModeAllowed(mode)) return false;
    if (mode === 'full') return true;
    if (_sandboxSetupReadyForMode(mode)) return true;
    _sandboxSetupPromptDismissed = false;
    _pendingSandboxSetupMode = mode;
    const status = await _loadSandboxSetupStatus(mode);
    if (_isSandboxSetupReadyPayload(status)) {
      _pendingSandboxSetupMode = '';
      _refreshSandboxSetupBanner(mode);
      return true;
    }
    _refreshSandboxSetupBanner(mode);
    return false;
  }

  function _bindSandboxSetupBanner() {
    const banner = _sandboxSetupBanner;
    if (!banner) return;
    const ensure = banner.querySelector('[data-sandbox-setup-action="ensure"]');
    const dismiss = banner.querySelector('[data-sandbox-setup-action="dismiss"]');
    if (ensure) {
      ensure.addEventListener('click', async () => {
        const mode = _pendingSandboxSetupMode || _runMode;
        if (await _ensureSandboxSetupOnly(mode)) {
          _pendingSandboxSetupMode = '';
          _setRunMode(mode, { toast: true });
        }
      });
    }
    if (dismiss) {
      dismiss.addEventListener('click', () => {
        _sandboxSetupPromptDismissed = true;
        _pendingSandboxSetupMode = '';
        _refreshSandboxSetupBanner(_runMode);
      });
    }
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

  /* ── Event Bindings ─────────────────────────────────────────────────── */

  function _bindEvents() {
    const attachBtn = _el.querySelector('#chat-btn-attach');
    const newBtn    = _el.querySelector('#chat-btn-new');
    const exportBtn = _el.querySelector('#chat-btn-export');

    // Send
    _sendBtn.addEventListener('click', _onSend);
    if (_micBtn) _micBtn.addEventListener('click', _onVoiceInputToggle);
    if (_stopBtn) _stopBtn.addEventListener('click', () => _onStop('webui_stop_button'));
    if (_pendingArea) _pendingArea.addEventListener('click', _onPendingAreaClick);

    // Session key is now managed via chip + switch (see _bindSessionChip).
    // _sessionInput is null; no listener needed here.

    // New session button
    newBtn.addEventListener('click', () => {
      _unsubscribeSession();
      _parkCurrentSessionStreamState('new_chat');
      const key = _genKey();
      _updateSessionChip(key);
      _persistSession(key);
      _clearPendingDrainAfterTerminalTimer();
      _setCompactInFlight(false);
      _hideCompactionSeparator();
      _pendingSessionIntent = 'new_chat'; _pendingQueue = []; if (_pendingArea) _renderPendingQueue();
      _messages = [];
      _clearContextStatus();
      _resetHistoryPagingState();
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
    // ESC streaming abort lives on the document-level handler below. The
    // composer textarea is allowed to bubble there while streaming; other
    // editable targets keep ESC for text editing / menu dismissal.
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

    // Document-level ESC: works across the chat view, while preserving
    // non-composer editable targets. Priority chain:
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
    //   - editable guard: preserves ESC inside non-composer inputs, while the
    //     chat textarea can still abort the active stream.
    function _onDocKeydown(e) {
      if (e.key !== 'Escape') return;
      if (typeof Router !== 'undefined' && Router.currentPath && Router.currentPath() !== '/chat') return;
      if (e.defaultPrevented) return;
      if (_chatOverlayVisible()) return;
      const target = e.target;
      const inOtherEditable = target && target !== _textarea && (
        target.tagName === 'INPUT'
        || target.tagName === 'TEXTAREA'
        || target.isContentEditable
      );
      if (inOtherEditable) return;
      if (_isStreaming) {
        e.preventDefault();
        _onStop('webui_escape');
        return;
      }
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
      let consumedAttachment = false;
      for (let i = 0; i < items.length; i++) {
        if (items[i].type.startsWith('image/')) {
          const file = items[i].getAsFile();
          if (file && _addAttachment(file)) consumedAttachment = true;
        }
      }
      if (consumedAttachment) e.preventDefault();
    };
    document.addEventListener('paste', pasteHandler);
    _unsubs.push(() => document.removeEventListener('paste', pasteHandler));

    // Auto-scroll detection
    const threadEl = _thread;
    threadEl.addEventListener('scroll', () => {
      const gap = threadEl.scrollHeight - threadEl.scrollTop - threadEl.clientHeight;
      _autoScroll = gap < 60;
    });

    // Pill toggle behavior is handled by _bindToolbarPills after the RPC write succeeds.
  }

  function _autoResizeTextarea() {
    if (!_textarea) return;
    if (!_textarea.value) {
      _textarea.style.height = '';
      return;
    }
    const minHeight = Number.parseFloat(getComputedStyle(_textarea).minHeight) || 40;
    _textarea.style.height = 'auto';
    _textarea.style.height = Math.max(minHeight, Math.min(_textarea.scrollHeight, 160)) + 'px';
  }

  /* ── Slash Command Menu ─────────────────────────────────────────────── */

  function _slashCommandKey(value) {
    const raw = String(value || '').trim().split(/\s+/, 1)[0].toLowerCase();
    if (!raw) return '';
    return raw.startsWith('/') ? raw : '/' + raw;
  }

  function _normalizeSlashCommand(cmd) {
    const name = cmd?.name || cmd?.cmd || '';
    return {
      ...cmd,
      name,
      cmd: name,
      label: cmd?.label || name,
      desc: cmd?.description || cmd?.desc || cmd?.usage || '',
      aliases: Array.isArray(cmd?.aliases) ? cmd.aliases : [],
    };
  }

  async function _loadSlashCommands() {
    if (!_rpc) return;
    try {
      await _rpc.waitForConnection();
      const res = await _rpc.call('commands.list_for_surface', { surface: 'web_chat' });
      _slashCmds = (Array.isArray(res?.commands) ? res.commands : []).map(_normalizeSlashCommand);
      _slashCommandMap = new Map();
      _slashCmds.forEach((cmd) => {
        _slashCommandMap.set(_slashCommandKey(cmd.name), cmd);
        (cmd.aliases || []).forEach((alias) => {
          _slashCommandMap.set(_slashCommandKey(alias), cmd);
        });
      });
      _slashCatalogLoaded = true;
      _handleSlashInput();
    } catch {
      _slashCmds = [];
      _slashCommandMap = new Map();
      _slashCatalogLoaded = false;
    }
  }

  function _handleSlashInput() {
    if (!_textarea) return;
    const val = _textarea.value;
    if (val.startsWith('//')) { _closeSlashMenu(); return; }
    if (val.startsWith('/') && !val.includes(' ')) {
      const query = val.slice(1).toLowerCase();
      _filteredCmds = _slashCmds.filter(c => c.cmd.slice(1).startsWith(query));
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

  function _selectSlashCmd(cmd, args = '') {
    _closeSlashMenu();
    _textarea.value = '';
    _autoResizeTextarea();

    const action = cmd?.execution?.action || cmd.cmd || cmd.name;
    const commandName = cmd?.cmd || cmd?.name || '';
    switch (action) {
      case 'new_chat':
      case '/new': {
        _unsubscribeSession();
        _parkCurrentSessionStreamState('new_chat');
        const key = _genKey();
        _updateSessionChip(key);
        _persistSession(key);
        _clearPendingDrainAfterTerminalTimer();
        _setCompactInFlight(false);
        _hideCompactionSeparator();
        _pendingSessionIntent = 'new_chat'; _pendingQueue = []; if (_pendingArea) _renderPendingQueue();
        _messages = [];
        _clearContextStatus();
        _resetHistoryPagingState();
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
      case 'reset_session':
      case 'sessions.reset':
      case '/reset':
        if (commandName === '/new') {
          _selectSlashCmd({ ...cmd, execution: { action: 'new_chat' } }, args);
          return;
        }
        _rpc.call('sessions.reset', { key: _sessionKey })
          .then(() => {
            _messages = [];
            _clearPendingDrainAfterTerminalTimer();
            _setCompactInFlight(false);
            _hideCompactionSeparator();
            _pendingQueue = [];
            if (_pendingArea) _renderPendingQueue();
            _clearContextStatus();
            _clearActiveTaskGroups();
            _thread.innerHTML = _emptyStateHTML();
            UI.toast('Session reset', 'info');
          })
          .catch((err) => UI.toast('Reset failed: ' + err.message, 'err'));
        break;
      case 'compact_context':
      case 'sessions.contextCompact':
      case '/compact': {
        const compactKey = _sessionKey;
        _setCompactInFlight(true, compactKey);
        _syncCompactionSeparator(
          { key: compactKey, source: 'manual', status: 'started', phase: 'manual' },
          'started',
          'manual',
        );
        _rpc.call('sessions.contextCompact', { key: compactKey })
          .then((result) => {
            if (compactKey !== _sessionKey) return;
            _showCompactionToast({ ...(result || {}), key: compactKey, source: 'manual' });
          })
          .catch((err) => {
            if (compactKey !== _sessionKey) return;
            _showCompactionToast({
              key: compactKey,
              source: 'manual',
              status: 'failed',
              message: err && err.message || 'unknown error',
            });
          });
        break;
      }
      case 'usage_status':
      case 'usage.status':
      case '/usage': {
        if (args.trim().toLowerCase() === 'page') {
          UI.toast('Usage page is available from the sidebar', 'info');
          break;
        }
        const usageMethod = args.trim().toLowerCase() === 'cost' ? 'usage.cost' : 'usage.status';
        _rpc.call(usageMethod)
          .then((result) => {
            if (usageMethod === 'usage.cost') {
              const total = result?.totalCostUsd ?? result?.total_cost_usd ?? result?.totals?.cost ?? result?.totals?.cost_usd;
              UI.toast(total != null ? `Usage cost: $${Number(total).toFixed(6)}` : 'Usage cost unavailable', 'info');
              return;
            }
            const totals = result?.totals || {};
            const tokens = Number(result?.totalTokens ?? result?.total_tokens ?? totals.tokens ?? totals.total_tokens ?? totals.totalTokens ?? 0);
            const cost = result?.totalCostUsd ?? result?.total_cost_usd ?? totals.cost ?? totals.cost_usd ?? totals.costUsd;
            UI.toast(
              `Usage: ${tokens.toLocaleString()} tokens` + (cost != null ? ` · $${Number(cost).toFixed(6)}` : ''),
              'info'
            );
          })
          .catch((err) => UI.toast('Usage failed: ' + err.message, 'err'));
        break;
      }
      case 'meta.menu': {
        const skillName = args.trim();
        if (!skillName) {
          // No arg → list available meta-skills.
          _rpc.call('meta.list')
            .then((result) => {
              const skills = Array.isArray(result?.skills) ? result.skills : [];
              if (result?.disabled || skills.length === 0) {
                _addMessage('system', 'No meta-skills available.');
                return;
              }
              const lines = skills.map((s) => {
                const name = s?.name || '';
                const desc = s?.description ? ` — ${s.description}` : '';
                return `- ${name}${desc}`;
              });
              _addMessage('system', 'Available meta-skills:\n' + lines.join('\n'));
            })
            .catch((err) => UI.toast('meta.list failed: ' + err.message, 'err'));
          break;
        }
        // With <name> → stamp the run, then send a normal turn so the
        // pipeline seed auto-launches the skill on the next turn.
        _rpc.call('meta.run', { name: skillName, sessionKey: _sessionKey })
          .then((result) => {
            if (result && result.ok) {
              _sendTextOverride = `/meta ${skillName}`;
              _onSend();
              return;
            }
            const error = (result && result.error) || 'meta.run failed';
            _addMessage('error', `meta.run failed: ${error}`);
          })
          .catch((err) => UI.toast('meta.run failed: ' + err.message, 'err'));
        break;
      }
    }
  }

  async function _lookupSlashCommand(text) {
    if (!_slashCatalogLoaded) await _loadSlashCommands();
    const [cmdText] = text.trim().split(/\s+/);
    return _slashCommandMap.get(_slashCommandKey(cmdText)) || null;
  }

  async function _executeSlashCommand(text) {
    const [, ...rest] = text.trim().split(/\s+/);
    const cmd = await _lookupSlashCommand(text);
    if (!cmd) {
      _closeSlashMenu();
      return false;
    }
    _selectSlashCmd(cmd, rest.join(' '));
    return true;
  }

  /* ── Session Message Subscription ───────────────────────────────────── */

  async function _subscribeSession() {
    if (!_rpc || !_sessionKey) return;
    const subscribeKey = _sessionKey;
    try {
      await _rpc.waitForConnection();
      if (subscribeKey !== _sessionKey) return;
      const params = { key: subscribeKey };
      params.since_stream_seq = _sessionStreamSeq(subscribeKey);
      const res = await _rpc.call('sessions.messages.subscribe', params);
      if (subscribeKey !== _sessionKey) return;
      if (res && res.subscribed === false) throw new Error('No subscription manager available');
      _applySessionRunState(res);
      const subscribedState = _sessionRunStatus(res);
      if (!_isStreaming && _runStatusIsActive(subscribedState.status)) {
        _startStreaming();
        _showThinkingIndicator();
      }
      if (res && res.replay_complete === false) {
        if (typeof res.current_stream_seq === 'number') {
          _setSessionStreamSeq(subscribeKey, res.current_stream_seq);
        }
        const replayGapReason = res.replay_gap_reason || res.replayGapReason || '';
        if (_replayGapShouldWarn(replayGapReason)) {
          UI.toast('Missed live stream events; transcript refreshed.', 'warn', 5000);
        } else {
          _chatDiag('session.subscribe.replay_gap.history_refresh', {
            reason: replayGapReason,
            currentStreamSeq: res.current_stream_seq,
          });
        }
        _loadHistory(_historyRefreshScrollOptions());
      } else if (
        res
        && typeof res.current_stream_seq === 'number'
        && Number(res.replayed_count || 0) <= 0
      ) {
        _setSessionStreamSeq(subscribeKey, res.current_stream_seq);
      }
      if (_subscribeResultNeedsTerminalHistorySync(res)) {
        _chatDiag('session.subscribe.terminal_without_replay.history_sync', {
          runStatus: res.run_status || res.runStatus || '',
          currentStreamSeq: res.current_stream_seq,
          replayedCount: res.replayed_count || 0,
        });
        _scheduleHistorySync();
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

  function _suppressDuplicateCompactionToast(payload, status, source) {
    const key = String(payload && payload.key || _sessionKey || '');
    const event = String(payload && payload.event || '');
    const reason = String(payload && (payload.reason || payload.skip_reason) || '');
    const sig = `${key}|${source || ''}|${status || ''}|${event}|${reason}`;
    const now = Date.now();
    if (sig === _lastCompactionToastSig && now - _lastCompactionToastAt < 1500) {
      return true;
    }
    _lastCompactionToastSig = sig;
    _lastCompactionToastAt = now;
    return false;
  }

  function _clearCompactionSeparatorTimer() {
    if (_compactionSeparatorTimer) {
      clearTimeout(_compactionSeparatorTimer);
      _compactionSeparatorTimer = null;
    }
  }

  function _hideCompactionSeparator() {
    _clearCompactionSeparatorTimer();
    if (_compactionSeparatorEl && _compactionSeparatorEl.parentNode) {
      _compactionSeparatorEl.remove();
    }
    _compactionSeparatorEl = null;
  }

  function _placeCompactionSeparator() {
    if (!_thread || !_compactionSeparatorEl) return;
    const empty = _thread.querySelector('.chat-empty');
    if (empty) empty.remove();
    if (_isStreaming && _isCurrentSessionStreamBubble(_streamBubble)) {
      if (_compactionSeparatorEl.nextSibling !== _streamBubble) {
        _thread.insertBefore(_compactionSeparatorEl, _streamBubble);
      }
      return;
    }
    if (_compactionSeparatorEl.parentNode !== _thread
        || _thread.lastElementChild !== _compactionSeparatorEl) {
      _thread.appendChild(_compactionSeparatorEl);
    }
  }

  function _ensureCompactionSeparator() {
    if (!_thread) return null;
    if (!_compactionSeparatorEl || !_compactionSeparatorEl.isConnected) {
      _compactionSeparatorEl = document.createElement('div');
      _compactionSeparatorEl.className = 'chat-context-separator chat-context-separator--session chat-context-separator--info';
      _compactionSeparatorEl.setAttribute('role', 'status');
      _compactionSeparatorEl.setAttribute('aria-live', 'polite');
    }
    _placeCompactionSeparator();
    return _compactionSeparatorEl;
  }

  function _scheduleCompactionSeparatorRemoval(delayMs = 4500) {
    _clearCompactionSeparatorTimer();
    const separator = _compactionSeparatorEl;
    if (!separator) return;
    _compactionSeparatorTimer = setTimeout(() => {
      if (_compactionSeparatorEl === separator) _hideCompactionSeparator();
    }, delayMs);
  }

  function _buildCompactionSeparator(label, tone = 'info', extraClass = '') {
    const el = document.createElement('div');
    el.className = ['chat-context-separator', extraClass, `chat-context-separator--${tone}`]
      .filter(Boolean)
      .join(' ');
    el.innerHTML = `<span>${_esc(label)}</span>`;
    return el;
  }

  const _COMPACTION_TERMINAL_STATUSES = new Set([
    'completed',
    'skipped',
    'failed',
    'error',
    'cancelled',
    'emergency_ephemeral',
  ]);

  function _compactionTerminalStatus(status) {
    return _COMPACTION_TERMINAL_STATUSES.has(String(status || '').toLowerCase());
  }

  function _compactionSeparatorAnimated(status, overrides = {}) {
    if (overrides && Object.prototype.hasOwnProperty.call(overrides, 'animated')) {
      return !!overrides.animated;
    }
    return status === 'started' || status === 'observed';
  }

  function _shouldPersistCompactionSeparator(status, source, overrides = {}) {
    if (overrides && Object.prototype.hasOwnProperty.call(overrides, 'persist')) {
      return !!overrides.persist;
    }
    if (!_compactionTerminalStatus(status)) return false;
    return status === 'completed';
  }

  function _compactionStatusLabel(payload, source, status) {
    if (status === 'started') return 'context compacting';
    if (status === 'observed') return 'context compacting';
    if (status === 'emergency_ephemeral') return 'temporary compaction';
    if (status === 'skipped') {
      const reason = _compactionReason(payload);
      return (!reason || _INTERNAL_COMPACTION_SKIP_REASONS.has(reason))
        ? 'no compaction needed'
        : 'compaction skipped';
    }
    if (status === 'failed' || status === 'error') return 'compaction failed';
    if (status === 'cancelled') return 'compaction cancelled';
    if (status === 'completed') return 'context compacted';
    return source === 'manual' ? 'manual compact' : 'context maintenance';
  }

  function _compactionSeparatorTone(status, payload = {}) {
    if (status === 'completed') return 'ok';
    if (status === 'failed' || status === 'error') return 'err';
    if (status === 'cancelled' || status === 'emergency_ephemeral') return 'warn';
    if (status === 'skipped' && _compactionReason(payload)) return 'warn';
    return 'info';
  }

  function _syncCompactionSeparator(payload, status, source, overrides = {}) {
    if (payload && Object.prototype.hasOwnProperty.call(payload, 'user_visible')
        && payload.user_visible === false) {
      _hideCompactionSeparator();
      return;
    }
    if (status === 'skipped' && !_compactionUserVisible(payload || {}, source, status)) {
      _hideCompactionSeparator();
      return;
    }
    const separator = _ensureCompactionSeparator();
    if (!separator) return;
    _clearCompactionSeparatorTimer();
    const tone = overrides.tone || _compactionSeparatorTone(status, payload || {});
    const label = overrides.label != null
      ? overrides.label
      : _compactionStatusLabel(payload || {}, source, status);
    const liveClass = _compactionSeparatorAnimated(status, overrides)
      ? 'chat-context-separator--live'
      : '';
    separator.className = [
      'chat-context-separator',
      'chat-context-separator--session',
      liveClass,
      `chat-context-separator--${tone}`,
      `chat-context-separator--${status || 'unknown'}`,
    ].filter(Boolean).join(' ');
    separator.dataset.status = status || '';
    separator.dataset.source = source || '';
    separator.innerHTML = `<span>${_esc(label)}</span>`;
    _placeCompactionSeparator();
    if (_autoScroll) _scrollToBottom();
    if (_compactionTerminalStatus(status)) {
      if (_shouldPersistCompactionSeparator(status, source, overrides)) return;
      _scheduleCompactionSeparatorRemoval();
    }
  }

  function _clearCompactionSummarySeparators() {
    if (!_thread) return;
    _thread.querySelectorAll('.chat-compaction-separator').forEach((el) => el.remove());
  }

  function _messageTranscriptId(msg) {
    const raw = msg && msg.transcript_id;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
  }

  function _summaryCoveredThroughId(summary) {
    const raw = summary && summary.covered_through_id;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
  }

  function _messageElementTranscriptId(el) {
    const value = Number(el && el.dataset ? el.dataset.transcriptId : NaN);
    return Number.isFinite(value) ? value : null;
  }

  function _insertCompactionSummarySeparator(marker, target, mode) {
    if (!target || target.parentNode !== _thread) return false;
    if (mode === 'after') {
      let anchor = target;
      while (anchor.nextElementSibling
          && anchor.nextElementSibling.classList
          && anchor.nextElementSibling.classList.contains('router-fx')) {
        anchor = anchor.nextElementSibling;
      }
      _thread.insertBefore(marker, anchor.nextSibling);
      return true;
    }
    _thread.insertBefore(marker, target);
    return true;
  }

  function _renderCompactionSummarySeparators(messages) {
    _clearCompactionSummarySeparators();
    if (!_thread || !_historyCompactionSummaries.length || !Array.isArray(messages)) return null;
    const visibleMessages = Array.from(_thread.querySelectorAll('.msg'));
    if (!visibleMessages.length) return null;
    const visibleIds = visibleMessages
      .map((el) => ({ el, id: _messageElementTranscriptId(el) }))
      .filter((item) => item.id != null);
    if (!visibleIds.length) return null;

    const seen = new Set();
    let inserted = 0;
    let firstMarker = null;
    _historyCompactionSummaries.forEach((summary) => {
      const coveredId = _summaryCoveredThroughId(summary);
      if (coveredId == null || seen.has(coveredId)) return;
      seen.add(coveredId);
      let target = visibleIds.find((item) => item.id === coveredId);
      let mode = 'after';
      if (!target) {
        target = visibleIds.find((item) => item.id > coveredId);
        mode = 'before';
      }
      if (!target) return;
      const marker = _buildCompactionSeparator(
        'context compacted',
        'info',
        'chat-compaction-separator chat-context-separator--history',
      );
      marker.dataset.coveredThroughId = String(coveredId);
      if (_insertCompactionSummarySeparator(marker, target.el, mode)) {
        inserted++;
        if (!firstMarker) firstMarker = marker;
      }
    });
    if (inserted > 0) _hideCompactionSeparator();
    return firstMarker;
  }

  function _compactFailureBlocksPending(payload) {
    if (!payload) return false;
    if (payload.refused === true || payload.safe_to_send === false || payload.safeToSend === false) {
      return true;
    }
    const reason = String(
      payload.reason ||
      payload.error_reason ||
      payload.errorClass ||
      payload.error_class ||
      payload.error && payload.error.reason ||
      payload.error && payload.error.code ||
      ''
    ).toLowerCase();
    return [
      'compaction_insufficient',
      'compaction_flush_failed',
      'context_overflow',
      'unsafe_flush_receipt',
    ].includes(reason);
  }

  function _compactSemanticMemoryNotice(payload) {
    const semantic = payload && (payload.semanticMemory || payload.semantic_memory) || null;
    const safety = payload && (payload.memorySafety || payload.memory_safety) || null;
    const semanticStatus = String(semantic && semantic.status || '').toLowerCase();
    const safetyStatus = String(safety && safety.status || '').toLowerCase();
    if (semanticStatus === 'degraded' && safetyStatus !== 'error') {
      return 'Memory saved; organizing';
    }
    return '';
  }

  function _compactSafeMessageDetail(payload) {
    const message = payload && payload.message ? String(payload.message) : '';
    if (!message) return '';
    return message.replace(
      /(?:[A-Za-z]:[\\/][^\s'"<>]*checkpoint[^\s'"<>]*|\/[^\s'"<>]*checkpoint[^\s'"<>]*|memory\/\.raw_fallbacks\/[^\s'"<>]+|[^\s'"<>]*checkpoint[^\s'"<>]*)/gi,
      '[memory checkpoint]',
    );
  }

  const _INTERNAL_COMPACTION_SKIP_REASONS = new Set([
    'already_attempted_this_turn',
    'already_compacted_this_turn',
    'no_entries',
    'stale_preimage',
    'structured_content_noop',
    'within_budget',
    'within_compaction_budget',
  ]);

  const _COMPACTION_SKIP_MESSAGES = {
    coverage_blocked: 'Context was left unchanged because required details could not be preserved.',
    empty_ephemeral_webchat_session: 'No compactable chat history yet.',
    empty_summary: 'Context was left unchanged because no usable summary was produced.',
    no_entries: 'No compactable chat history yet.',
    no_safe_turn_boundary: 'Context cannot be compacted safely during the current tool turn.',
  };

  const _COMPACTION_SKIP_DETAILS = {
    coverage_blocked: 'Required details could not be preserved',
    empty_ephemeral_webchat_session: 'No compactable history',
    empty_summary: 'No usable summary was produced',
    no_entries: 'No compactable history',
    no_safe_turn_boundary: 'Current tool turn boundary is not safe to compact',
    unsafe_flush_receipt: 'Memory safety check did not complete',
  };

  function _compactionReason(payload) {
    return String(payload && (payload.reason || payload.skip_reason) || '');
  }

  function _compactionUserVisible(payload, source, status) {
    if (payload && Object.prototype.hasOwnProperty.call(payload, 'user_visible')) {
      return payload.user_visible !== false;
    }
    if (source === 'manual') return true;
    if (status === 'skipped') {
      const reason = _compactionReason(payload);
      return !_INTERNAL_COMPACTION_SKIP_REASONS.has(reason);
    }
    return true;
  }

  function _compactionSkipMessage(payload, source) {
    const reason = _compactionReason(payload);
    if (source === 'manual') {
      return _COMPACTION_SKIP_MESSAGES[reason] || 'Already within context budget; no compact was applied.';
    }
    if (_COMPACTION_SKIP_MESSAGES[reason]) return 'Context compaction could not be applied';
    if (reason) return 'Context compaction skipped';
    return 'Already within context budget; no compact was applied.';
  }

  function _compactionStatusDetail(payload, source = '', status = '') {
    if (!_compactionUserVisible(payload, source, status)) return '';
    if (status === 'emergency_ephemeral') return 'Request-scoped; session history was not rewritten';
    const reason = _compactionReason(payload);
    if (_INTERNAL_COMPACTION_SKIP_REASONS.has(reason)) return '';
    if (_COMPACTION_SKIP_DETAILS[reason]) return _COMPACTION_SKIP_DETAILS[reason];
    if (reason) return reason.replace(/_/g, ' ');
    return '';
  }

  function _routerFxIsSuppressedForCompactionTurn(turnIndex) {
    if (!_compactSuppressedRouterTurnIndex) return false;
    if (String(turnIndex || '') !== _compactSuppressedRouterTurnIndex) return false;
    return !_compactSuppressedRouterSessionKey || _compactSuppressedRouterSessionKey === _sessionKey;
  }

  function _suppressRouterFxForCompaction(payload = {}) {
    _cancelPendingRouterFxScan('compaction');
    if (!_thread) return;
    const turnIndex = String(_routerFxCountUserMessages());
    if (!turnIndex || turnIndex === '0') return;
    const key = String(payload && payload.key || _sessionKey || '');
    _compactSuppressedRouterSessionKey = key;
    _compactSuppressedRouterTurnIndex = turnIndex;
    _thread.querySelectorAll('.router-fx[data-live="true"]').forEach((el) => {
      const sameSession = !key || !el.dataset.sessionKey || el.dataset.sessionKey === key;
      const sameTurn = !el.dataset.turnIndex || el.dataset.turnIndex === turnIndex;
      if (sameSession && sameTurn) _routerFxRemoveStrip(el);
    });
    _chatDiag('router_scan.suppressed_for_compaction', { key, turnIndex });
  }

  function _showCompactionToast(payload, meta = {}) {
    let status = String(payload && payload.status || '').toLowerCase();
    if (!status && payload && Object.prototype.hasOwnProperty.call(payload, 'compacted')) {
      status = payload.compacted ? 'completed' : 'skipped';
    }
    const source = String(payload && payload.source || '').toLowerCase();
    const isReplay = !!(meta && meta.replayed);
    if (isReplay && !_compactionTerminalStatus(status)) return;
    if (_suppressDuplicateCompactionToast(payload || {}, status, source)) return;
    // Single surface: the in-thread context separator renders every lifecycle
    // state (and hides itself for not-user-visible skips). The branches below
    // only drive non-UI side effects — in-flight tracking, router-fx
    // suppression, pending recovery — plus corner toasts when warranted.
    _syncCompactionSeparator(payload || {}, status, source);
    if (status === 'started') {
      _setCompactInFlight(true, payload && payload.key || _sessionKey);
      _hideThinkingIndicator();
      _suppressRouterFxForCompaction(payload || {});
      return;
    }
    if (status === 'observed') {
      _hideThinkingIndicator();
      _suppressRouterFxForCompaction(payload || {});
      return;
    }
    if (status === 'emergency_ephemeral') {
      _settleCompactInFlight(payload || {});
      if (!isReplay) {
        UI.toast('Continuing with temporary context compaction for this turn', 'info', 4500);
      }
      return;
    }
    if (status === 'skipped') {
      _settleCompactInFlight(payload || {});
      _scheduleCompactionSeparatorRemoval();
      return;
    }
    const semanticNotice = _compactSemanticMemoryNotice(payload || {});
    if (semanticNotice) {
      _settleCompactInFlight(payload || {});
      _syncCompactionSeparator(payload || {}, 'completed', source, {
        tone: 'ok',
        label: 'context compacted',
      });
      _scheduleHistorySync();
      return;
    }
    if (status === 'failed' || status === 'error') {
      const preservePending = _compactFailureBlocksPending(payload || {});
      const keepPendingQueued = preservePending || (source !== 'manual' && _isStreaming);
      const recovered = _settleCompactInFlight(payload || {}, {
        recoverPending: !keepPendingQueued,
        preservePending: keepPendingQueued,
      });
      const safe = _compactSafeMessageDetail(payload || {});
      const msg = safe ? ': ' + safe : '';
      const pendingSuffix = keepPendingQueued
        ? '; pending message preserved'
        : (recovered ? '; pending message recovered to input' : '');
      _syncCompactionSeparator(payload || {}, status, source, { label: 'compaction failed' });
      if (!isReplay) UI.toast('Compact failed' + msg + pendingSuffix, 'err', 5000);
      return;
    }
    if (status === 'cancelled') {
      const recovered = _settleCompactInFlight(payload || {}, { recoverPending: true });
      if (!isReplay) {
        UI.toast(
          'Compact cancelled' + (recovered ? '; pending message recovered to input' : ''),
          'info',
          4500,
        );
      }
      return;
    }
    if (status !== 'completed') return;
    _settleCompactInFlight(payload || {});
    _scheduleHistorySync();
  }

  /* ── Router slider — arcade-brutalist whac-a-mole grid ─────────────
   * Fires once per user message when session.event.router_decision lands.
   * The grid contains only the effective candidates that could actually be
   * called for this request kind, deduped by display model name. A
   * hammer-selector hops between those real cells and locks onto the routed
   * cell with a particle burst. The strip is non-blocking — assistant text
   * streams below the grid while the chase plays above. */

  // OpenSquilla's tier ids vary by tier_profile. We seed the slot
  // list from config and register any decision tier we haven't seen
  // before, so the grid never silently drops an unfamiliar tier.
  const _ROUTER_FX_DEFAULT_TIERS = ['c0', 'c1', 'c2', 'c3'];
  let _routerFxSlotList = _ROUTER_FX_DEFAULT_TIERS.slice();
  const _routerFxModels = {};
  const _routerFxTierConfigs = {};
  // Authoritative set of tier ids that exist in the *current* config
  // snapshot (populated by _loadFeatureToggles). Used to skip history
  // strips whose routed_tier has been removed from config and to know
  // whether the slider is allowed to render at all (enabled flag).
  let _routerFxConfigTiers = null;     // Set<string> | null (unknown)
  let _routerFeatureEnabled = false;

  // Per-browser preference for the router-fx VISUALISATION (distinct from
  // _routerFeatureEnabled, which mirrors the operator's squilla_router.enabled
  // routing state). `enabled` is "show the animated grid"; `variant` selects a
  // style skin stamped as data-variant on the .router-fx root ('default' = the
  // base, unstamped look). This is a cosmetic, client-side choice — it never
  // touches gateway config — so it lives in localStorage like the theme pref.
  const _ROUTER_FX_PREF_KEY = 'opensquilla-router-fx';
  // Fixed scan-animation window. The panel locks + settles by this point, so
  // the whole animation (scan + ~360ms settle transition) stays under ~1s.
  const _ROUTER_FX_SCAN_MS = 600;
  const _ROUTER_FX_START_DELAY_MS = 280;
  const _ROUTER_FX_GRID_COLS = 5;
  const _ROUTER_FX_GRID_ROWS = 3;
  const _ROUTER_FX_GRID_CELLS = _ROUTER_FX_GRID_COLS * _ROUTER_FX_GRID_ROWS;
  const _ROUTER_FX_REAL_ANCHOR_CELLS = [1, 6, 8, 13, 11, 3, 5, 9, 12, 14, 0, 4, 7, 10, 2];
  const _ROUTER_FX_DECOY_POOL = [
    'gpt-5.5',
    'claude-opus-4.8',
    'gemini-3.5-flash',
    'qwen3-coder-plus',
    'grok-4.3',
    'gpt-5.4-mini',
    'claude-sonnet-4.6',
    'gemini-3.1-pro',
    'deepseek-v3.2',
    'kimi-k2.6',
    'command-a-plus',
    'grok-build-0.1',
    'glm-4.6',
    'mistral-medium-3.5',
    'claude-haiku-4.5',
  ];
  const _routerFx = { enabled: true, visualMode: 'real_candidates', variant: 'default' };
  function _routerFxNormalizeVisualMode(mode) {
    const normalized = typeof mode === 'string'
      ? mode.trim().toLowerCase().replace(/-/g, '_')
      : '';
    if (normalized === 'legacy_grid' || normalized === 'model_space' || normalized === 'modelspace') {
      return 'legacy_grid';
    }
    return 'real_candidates';
  }
  function _routerFxPanelDataset(mode) {
    return _routerFxNormalizeVisualMode(mode) === 'legacy_grid'
      ? 'legacy-grid'
      : 'real-candidates';
  }
  function _routerFxApplyConfigVisualMode(mode) {
    _routerFx.visualMode = _routerFxNormalizeVisualMode(mode);
  }
  function _routerFxLoadPref() {
    // Defaults stand (enabled ON, default variant) unless a stored pref
    // overrides them. localStorage may throw (private mode / quota) — swallow.
    _routerFx.visualMode = 'real_candidates';
    _routerFx.variant = 'default';
    try {
      const raw = localStorage.getItem(_ROUTER_FX_PREF_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw);
      if (saved && typeof saved === 'object') {
        if (typeof saved.enabled === 'boolean') _routerFx.enabled = saved.enabled;
      }
    } catch { /* keep defaults */ }
  }
  function _routerFxSavePref() {
    try {
      localStorage.setItem(_ROUTER_FX_PREF_KEY, JSON.stringify({
        enabled: _routerFx.enabled,
      }));
    } catch { /* preference is best-effort */ }
  }

  function _routerFxSortTiers(list) {
    return list.slice().sort((a, b) => {
      const am = /^c(\d+)$/.exec(a);
      const bm = /^c(\d+)$/.exec(b);
      if (am && bm) return parseInt(am[1], 10) - parseInt(bm[1], 10);
      if (am) return -1;
      if (bm) return 1;
      return a.localeCompare(b);
    });
  }

  function _routerFxNormalizeTier(tier) {
    if (typeof tier !== 'string' || !tier) return '';
    return tier.toLowerCase().replace(/^t([0-3])$/, 'c$1');
  }

  function _routerFxRegisterTier(tier) {
    const norm = _routerFxNormalizeTier(tier);
    if (!norm) return;
    if (_routerFxSlotList.indexOf(norm) >= 0) return;
    _routerFxSlotList = _routerFxSortTiers(_routerFxSlotList.concat([norm]));
  }

  // Normalize user-facing model labels without changing stored/provider ids.
  // "z-ai/glm-5.1" -> "glm-5.1"; "glm-5.1-20260406" -> "glm-5.1".
  function _modelDisplayName(name) {
    if (!name || typeof name !== 'string') return name;
    const idx = name.lastIndexOf('/');
    const stripped = idx >= 0 ? name.slice(idx + 1) : name;
    return stripped.replace(/-\d{8}$/, '');
  }

  function _routerFxStripProvider(name) {
    return _modelDisplayName(name);
  }

  function _routerFxRequestKindFromAttachments(attachments) {
    const list = Array.isArray(attachments) ? attachments : [];
    for (const item of list) {
      const mime = String(item?.mime || item?.type || '').toLowerCase();
      if (mime.indexOf('image/') === 0) return 'image';
    }
    return 'text';
  }

  function _routerFxNormalizeRequestKind(requestKind) {
    return requestKind === 'image' ? 'image' : 'text';
  }

  function _routerFxTierConfig(tier) {
    const norm = typeof tier === 'string' ? tier.toLowerCase() : '';
    const known = norm ? _routerFxTierConfigs[norm] : null;
    if (known) return known;
    return {
      model: norm && _routerFxModels[norm] ? _routerFxModels[norm] : '',
      supportsImage: false,
      imageOnly: false,
    };
  }

  function _routerFxRememberTierDecision(tier, model) {
    if (typeof tier !== 'string' || !tier) return;
    const norm = tier.toLowerCase();
    _routerFxRegisterTier(norm);
    if (!model) return;
    const modelName = String(model);
    _routerFxModels[norm] = modelName;
    const current = _routerFxTierConfigs[norm] || {};
    _routerFxTierConfigs[norm] = {
      model: modelName,
      supportsImage: current.supportsImage === true,
      imageOnly: current.imageOnly === true,
    };
  }

  function _routerFxTierMatchesRequestKind(tierConfig, requestKind) {
    const kind = _routerFxNormalizeRequestKind(requestKind);
    if (kind === 'image') return !!(tierConfig.supportsImage || tierConfig.imageOnly);
    return !tierConfig.imageOnly;
  }

  function _routerFxRequestKindFromDecision(decision, fallbackKind) {
    if (fallbackKind) return _routerFxNormalizeRequestKind(fallbackKind);
    const source = String(decision?.source || decision?.routing_source || '').toLowerCase();
    const tier = String(decision?.tier || decision?.routed_tier || '').toLowerCase();
    if (source === 'image_route' || tier === 'image_model') return 'image';
    return 'text';
  }

  function _routerFxVisualEntries(requestKind, decision) {
    if (_routerFxConfigTiers === null) return [];
    const kind = _routerFxRequestKindFromDecision(decision, requestKind);
    const byDisplay = new Map();
    _routerFxSlotList.forEach((tier) => {
      if (_routerFxConfigTiers !== null && !_routerFxConfigTiers.has(tier)) return;
      const tierConfig = _routerFxTierConfig(tier);
      if (!_routerFxTierMatchesRequestKind(tierConfig, kind)) return;
      const displayName = tierConfig.model ? _routerFxStripProvider(tierConfig.model) : tier;
      const key = displayName ? displayName.toLowerCase() : tier;
      let entry = byDisplay.get(key);
      if (!entry) {
        entry = { key, tiers: [], model: tierConfig.model || '', displayName };
        byDisplay.set(key, entry);
      }
      entry.tiers.push(tier);
      if (!entry.model && tierConfig.model) entry.model = tierConfig.model;
    });
    const decisionTier = decision && typeof decision.tier === 'string'
      ? decision.tier.toLowerCase()
      : '';
    const decisionModel = decision && typeof decision.model === 'string' ? decision.model : '';
    if (decisionTier && decisionModel) {
      const displayName = _routerFxStripProvider(decisionModel);
      const key = displayName ? displayName.toLowerCase() : decisionTier;
      let entry = byDisplay.get(key);
      if (!entry && _routerFxTierMatchesRequestKind(_routerFxTierConfig(decisionTier), kind)) {
        entry = { key, tiers: [], model: decisionModel, displayName };
        byDisplay.set(key, entry);
      }
      if (entry) {
        if (entry.tiers.indexOf(decisionTier) < 0) entry.tiers.push(decisionTier);
        if (!entry.model) entry.model = decisionModel;
      }
    }
    return Array.from(byDisplay.values()).map((e) => ({
      key: e.key,
      tiers: _routerFxSortTiers(e.tiers),
      model: e.model,
      displayName: e.displayName || (e.model ? _routerFxStripProvider(e.model) : e.tiers[0]),
    }));
  }

  function _routerFxHasMultipleCandidates(requestKind, decision) {
    return _routerFxVisualEntries(requestKind, decision).length > 1;
  }

  // Promise resolved when _loadFeatureToggles has populated tier
  // models from config. Any _loadHistory call awaits this gate so the
  // first history rebuild never renders strips with empty tier names
  // ("c1", "c2", …) just because config hadn't returned yet.
  let _routerFxConfigReadyResolve = null;
  const _routerFxConfigReady = new Promise((resolve) => {
    _routerFxConfigReadyResolve = resolve;
  });
  function _routerFxMarkConfigReady() {
    if (_routerFxConfigReadyResolve) {
      _routerFxConfigReadyResolve();
      _routerFxConfigReadyResolve = null;
    }
  }
  async function _routerFxAwaitConfig(timeoutMs) {
    if (_routerFxConfigReadyResolve == null) return;
    await Promise.race([
      _routerFxConfigReady,
      new Promise((r) => setTimeout(r, typeof timeoutMs === 'number' ? timeoutMs : 1500)),
    ]);
  }

  // Per-turn seed cache backed by localStorage so live and history
  // rebuilds for the same turn always derive the same shuffle order.
  // Key includes sessionKey + 1-indexed user-msg position + tier; once
  // a seed is generated it sticks across every subsequent rebuild,
  // including F5 page refresh.
  function _routerFxSeedCacheKey(sessionKey, turnIndex, tier) {
    return 'osq.routerFx.seed:' + (sessionKey || '') + ':' + (turnIndex | 0) + ':' + tier;
  }
  // Soft cap on the in-localStorage seed cache. Seeds are tiny, but
  // there's no natural eviction event — without a cap the cache
  // grows unboundedly until the 5 MB domain quota kicks in and
  // setItem silently fails.
  const _ROUTER_FX_SEED_CACHE_MAX = 300;
  const _ROUTER_FX_SEED_CACHE_TRIM = 250;
  function _routerFxSeedCachePrefix() { return 'osq.routerFx.seed:'; }
  function _routerFxSeedCacheTrim() {
    try {
      const prefix = _routerFxSeedCachePrefix();
      const entries = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.indexOf(prefix) === 0) {
          const v = localStorage.getItem(k) || '';
          // Stored value starts with the millisecond timestamp from
          // _routerFxResolveSeed. Older seeds → smaller stamp.
          const stamp = parseInt(v.split(':', 1)[0], 10) || 0;
          entries.push({ key: k, stamp });
        }
      }
      if (entries.length <= _ROUTER_FX_SEED_CACHE_MAX) return;
      entries.sort((a, b) => a.stamp - b.stamp);
      const dropCount = entries.length - _ROUTER_FX_SEED_CACHE_TRIM;
      for (let i = 0; i < dropCount; i++) {
        try { localStorage.removeItem(entries[i].key); } catch (_) { /* ignore */ }
      }
    } catch (_) { /* localStorage unavailable; nothing to trim */ }
  }
  function _routerFxResolveSeed(sessionKey, turnIndex, tier, hintTimestamp) {
    const key = _routerFxSeedCacheKey(sessionKey, turnIndex, tier);
    try {
      const cached = localStorage.getItem(key);
      if (cached) return cached;
    } catch (_) { /* localStorage may be unavailable */ }
    const stamp = hintTimestamp ? String(hintTimestamp) : String(Date.now());
    const fresh = stamp + ':' + tier + ':i' + (turnIndex | 0);
    try {
      localStorage.setItem(key, fresh);
      _routerFxSeedCacheTrim();
    } catch (_) { /* ignore */ }
    return fresh;
  }
  function _routerFxResolveLayoutSeed(sessionKey, hintTimestamp) {
    return _routerFxResolveSeed(sessionKey, 0, 'layout', hintTimestamp);
  }
  function _routerFxSeedHash(seedKey) {
    const text = seedKey == null ? '' : String(seedKey);
    let hash = 2166136261;
    for (let i = 0; i < text.length; i++) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }
  function _routerFxSeededRandom(seedKey) {
    let state = _routerFxSeedHash(seedKey) || 0x9e3779b9;
    return () => {
      state += 0x6d2b79f5;
      let t = state;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function _routerFxShuffle(items, seedKey) {
    const out = items.slice();
    const random = seedKey ? _routerFxSeededRandom(seedKey) : Math.random;
    for (let i = out.length - 1; i > 0; i--) {
      const j = Math.floor(random() * (i + 1));
      const tmp = out[i];
      out[i] = out[j];
      out[j] = tmp;
    }
    return out;
  }
  function _routerFxIdentity(model, tier) {
    const modelPart = typeof model === 'string' ? model.trim().toLowerCase() : '';
    const tierPart = _routerFxNormalizeTier(tier);
    if (!modelPart && !tierPart) return '';
    return modelPart + '|' + tierPart;
  }
  function _routerFxDecisionIdentity(decision) {
    if (!decision || typeof decision !== 'object') return '';
    return _routerFxIdentity(decision.model || decision.routed_model || '', decision.tier || decision.routed_tier || '');
  }
  function _routerFxUsageIdentity(usage) {
    if (!usage || typeof usage !== 'object') return '';
    return _routerFxIdentity(usage.routed_model || usage.model || '', usage.routed_tier || '');
  }
  function _routerFxCountUserMessages() {
    if (!_thread) return 0;
    return _thread.querySelectorAll(
      '.msg.user, .msg[data-history-role="user"]'
    ).length;
  }

  function _pendingRouterDecisionKey(turnIndex) {
    return `${_sessionKey || ''}:${turnIndex || 'latest'}`;
  }

  function _cachePendingRouterDecision(payload) {
    const turnIndex = _routerFxCountUserMessages();
    const key = _pendingRouterDecisionKey(turnIndex > 0 ? turnIndex : 'latest');
    _pendingRouterDecisions.set(key, payload);
    _chatDiag('router_decision.cached_pending_anchor', {
      key,
      payload: _chatDiagSummarizePayload(payload),
    });
  }

  function _flushPendingRouterDecisions() {
    if (!_thread || !_routerFx.enabled) return;
    if (!_routerFxLastUserMessage()) return;
    const turnIndex = _routerFxCountUserMessages();
    const keys = [
      _pendingRouterDecisionKey(turnIndex),
      _pendingRouterDecisionKey('latest'),
    ];
    for (const key of keys) {
      if (!_pendingRouterDecisions.has(key)) continue;
      const payload = _pendingRouterDecisions.get(key);
      _pendingRouterDecisions.delete(key);
      _chatDiag('router_decision.flush_pending_anchor', {
        key,
        payload: _chatDiagSummarizePayload(payload),
      });
      _handleRouterDecision(payload);
      return;
    }
  }

  // Build the visual roster for this turn only. Text requests exclude
  // image-only routes; image requests include only image-capable routes.
  // Entries are deduped by display model name so provider/thinking/tier
  // differences do not create extra visual cells.
  function _routerFxRealEntries(decision, requestKind) {
    return _routerFxVisualEntries(requestKind, decision);
  }

  // Assemble the default panel from real candidates only. No filler/decoy
  // wall: every visible model name is callable for this turn.
  function _routerFxBuildCandidateGridCells(realEntries, seedKey) {
    const orderedRealEntries = realEntries.slice().sort((a, b) => (
      (a.displayName || a.key || '').localeCompare(b.displayName || b.key || '')
    ));
    return orderedRealEntries.map((entry) => ({
      kind: 'real',
      entry,
      displayName: entry.displayName,
    }));
  }

  // Legacy grid is a visual wall only: real candidates keep their in-memory
  // entries for winner lookup, while decoys are labels with no tier metadata.
  function _routerFxBuildLegacyGridCells(realEntries, seedKey) {
    const cells = Array.from({ length: _ROUTER_FX_GRID_CELLS }, () => null);
    const realNames = new Set();
    const orderedRealEntries = realEntries.slice().sort((a, b) => (
      (a.label || a.displayName || a.key || '').localeCompare(b.label || b.displayName || b.key || '')
    ));
    orderedRealEntries.forEach((entry, i) => {
      const anchor = _ROUTER_FX_REAL_ANCHOR_CELLS[i];
      const idx = typeof anchor === 'number' ? anchor : cells.findIndex((cell) => cell == null);
      if (idx < 0 || idx >= cells.length) return;
      cells[idx] = {
        kind: 'real',
        entry,
        displayName: entry.displayName,
        label: entry.label || entry.displayName,
        title: entry.title || entry.label || entry.displayName,
      };
      if (entry.displayName) realNames.add(entry.displayName);
      if (entry.label) realNames.add(entry.label);
    });

    const decoys = [];
    for (let i = 0; i < _ROUTER_FX_DECOY_POOL.length && decoys.length < _ROUTER_FX_GRID_CELLS; i++) {
      const name = _ROUTER_FX_DECOY_POOL[i];
      if (realNames.has(name)) continue;
      decoys.push({
        kind: 'decoy',
        displayName: name,
        label: name,
        title: name,
      });
    }
    while (decoys.length < _ROUTER_FX_GRID_CELLS) {
      decoys.push({
        kind: 'decoy',
        displayName: '-',
        label: '-',
        title: '-',
      });
    }
    const orderedDecoys = _routerFxShuffle(decoys, seedKey ? seedKey + ':decoy' : undefined);
    let decoyIdx = 0;
    for (let i = 0; i < cells.length; i++) {
      if (cells[i] == null) cells[i] = orderedDecoys[decoyIdx++];
    }
    return cells;
  }

  function _routerFxBuildGridCells(realEntries, seedKey, visualMode) {
    if (_routerFxNormalizeVisualMode(visualMode) === 'legacy_grid') {
      return _routerFxBuildLegacyGridCells(realEntries, seedKey);
    }
    return _routerFxBuildCandidateGridCells(realEntries, seedKey);
  }

  function _buildRouterFxElement(decision, opts) {
    opts = opts || {};
    const wrap = document.createElement('div');
    wrap.className = 'router-fx';
    wrap.setAttribute('data-history-role', 'router');
    wrap.dataset.renderMode = opts.renderMode || (opts.preSettled ? 'history' : 'live');
    wrap.dataset.state = 'idle';
    wrap.dataset.tier = _routerFxNormalizeTier(decision.tier);
    wrap.dataset.source = decision.source || 'none';
    const identity = _routerFxDecisionIdentity(decision);
    if (identity) wrap.dataset.routerIdentity = identity;
    const observeMode = decision && decision.routing_applied === false;
    if (observeMode) {
      wrap.dataset.observe = 'true';
      wrap.dataset.rolloutPhase = typeof decision.rollout_phase === 'string'
        ? decision.rollout_phase
        : 'observe';
    }
    // Style-variant seam: stamp data-variant on the root so a future skin can
    // hook [data-variant="..."] selectors (the same idiom as data-state /
    // data-source / data-observe). Only stamp non-default values, leaving the
    // base look as the attribute-free fallback. opts.variant overrides the
    // global preference for callers that want a per-render skin.
    const variant = (opts.variant != null ? opts.variant : _routerFx.variant) || 'default';
    if (variant && variant !== 'default') wrap.dataset.variant = variant;

    const header = document.createElement('div');
    header.className = 'router-fx-header';
    header.innerHTML =
      '<span class="glyph">←</span>' +
      '<span class="title">AI model router</span>' +
      '<span class="glyph">→</span>';
    wrap.appendChild(header);

    // Seed off the caller-supplied key (turn timestamp). Same key → same
    // layout on every rebuild, so the field never reshuffles after lock.
    const seedKey = opts && opts.seedKey ? String(opts.seedKey) : '';
    if (seedKey) wrap.dataset.seed = seedKey;
    const visualMode = _routerFxNormalizeVisualMode(
      opts.visualMode != null ? opts.visualMode : _routerFx.visualMode,
    );
    wrap.dataset.panel = _routerFxPanelDataset(visualMode);

    const requestKind = _routerFxRequestKindFromDecision(decision, opts.requestKind);
    const realEntries = _routerFxRealEntries(decision, requestKind);
    if (realEntries.length <= 1) return null;
    const gridCells = _routerFxBuildGridCells(realEntries, seedKey || undefined, visualMode);

    const grid = document.createElement('div');
    grid.className = 'router-fx-grid';
    const isLegacyGrid = visualMode === 'legacy_grid';
    const cols = isLegacyGrid ? _ROUTER_FX_GRID_COLS : Math.min(4, Math.max(2, gridCells.length));
    const rows = isLegacyGrid ? _ROUTER_FX_GRID_ROWS : 1;
    const mobileCols = isLegacyGrid ? 3 : (gridCells.length > 2 ? 2 : gridCells.length);
    grid.style.setProperty('--router-fx-cols', String(cols));
    grid.style.setProperty('--router-fx-rows', String(rows));
    grid.style.setProperty('--router-fx-mobile-cols', String(Math.max(1, mobileCols)));
    gridCells.forEach((cellInfo, i) => {
      const cell = document.createElement('div');
      cell.className = 'router-fx-cell';
      cell.dataset.cellIdx = String(i);
      // title surfaces the full name on hover when a long one is ellipsized.
      cell.innerHTML = `<span class="nm" title="${_esc(cellInfo.displayName)}">${_esc(cellInfo.displayName)}</span>`;
      grid.appendChild(cell);
    });
    const selector = document.createElement('div');
    selector.className = 'router-fx-selector';
    grid.appendChild(selector);
    wrap.appendChild(grid);

    wrap._fxGridCells = gridCells;
    wrap._fxRealEntries = realEntries;
    wrap._fxRequestKind = requestKind;

    if (opts.preSettled) {
      const winnerIdx = _routerFxWinnerCellIndex(wrap, _routerFxNormalizeTier(decision.tier));
      if (winnerIdx >= 0) {
        _settleRouterFxImmediate(wrap, winnerIdx, { burst: false, decision });
        _routerFxNormalizeSettledStrip(wrap, opts.renderMode || 'history', decision);
      }
    }
    return wrap;
  }

  function _routerFxWinnerCellIndex(wrap, tier) {
    if (!wrap || !tier) return -1;
    const cells = wrap._fxGridCells || [];
    const norm = String(tier).toLowerCase();
    for (let i = 0; i < cells.length; i++) {
      if (cells[i].kind === 'real' && cells[i].entry.tiers.indexOf(norm) >= 0) return i;
    }
    return -1;
  }

  // Position the hammer over a specific grid cell. CSS transition
  // handles the bouncy hop; JS only sets transform + width/height.
  function _routerFxPositionSelector(selector, cell, opts) {
    if (!selector || !cell) return;
    opts = opts || {};
    const grid = cell.parentElement;
    if (!grid || !grid.isConnected) return;
    const cellRect = cell.getBoundingClientRect();
    const gridRect = grid.getBoundingClientRect();
    if (!cellRect.width || !cellRect.height || !gridRect.width || !gridRect.height) return;
    const padLeft = parseFloat(getComputedStyle(grid).paddingLeft) || 0;
    const padTop = parseFloat(getComputedStyle(grid).paddingTop) || 0;
    const x = cellRect.left - gridRect.left - padLeft;
    const y = cellRect.top - gridRect.top - padTop;
    selector.style.width = cellRect.width + 'px';
    selector.style.height = cellRect.height + 'px';
    // Slight rotation while hopping for "weight"; settle dead level.
    const rot = opts.lock ? 0 : (((opts.hopIdx | 0) % 2) ? -1.4 : 1.4);
    selector.style.transform = `translate(${x}px, ${y}px) rotate(${rot}deg)`;
  }

  function _routerFxPing(cell) {
    if (!cell) return;
    cell.classList.remove('pinging');
    void cell.offsetWidth;
    cell.classList.add('pinging');
    setTimeout(() => cell.classList.remove('pinging'), 220);
  }

  function _routerFxClearAnimationTimers(wrap) {
    if (!wrap) return;
    if (wrap._fxAnimFrame) {
      cancelAnimationFrame(wrap._fxAnimFrame);
      wrap._fxAnimFrame = null;
    }
    if (Array.isArray(wrap._fxAnimTimers)) {
      wrap._fxAnimTimers.forEach((timer) => clearTimeout(timer));
    }
    wrap._fxAnimTimers = [];
  }

  function _routerFxApplySettledSemantics(wrap, decision, renderMode) {
    if (!wrap) return;
    const mode = renderMode || wrap.dataset.renderMode || 'history';
    const effectiveDecision = decision || {
      tier: wrap.dataset.tier || '',
      model: '',
      source: wrap.dataset.source || 'none',
    };
    wrap.dataset.renderMode = mode;
    const winnerName = _routerFxWinnerName(effectiveDecision);
    wrap.setAttribute('role', mode === 'live' ? 'status' : 'group');
    wrap.setAttribute('aria-live', mode === 'live' ? 'polite' : 'off');
    wrap.setAttribute(
      'aria-label',
      winnerName ? `Router selected ${winnerName}` : 'Router settled'
    );
  }

  function _routerFxClearVisualResidue(wrap) {
    if (!wrap) return;
    const selector = wrap.querySelector('.router-fx-selector');
    if (selector) selector.classList.remove('visible', 'lock', 'lock-impact');
    wrap.querySelectorAll('.router-fx-cell.pinging').forEach((cell) => {
      cell.classList.remove('pinging');
    });
    wrap.querySelectorAll('.router-fx-burst').forEach((burst) => burst.remove());
  }

  function _routerFxNormalizeSettledStrip(wrap, renderMode, decision) {
    if (!wrap) return;
    _routerFxStopScan(wrap);
    _routerFxClearAnimationTimers(wrap);
    _routerFxClearVisualResidue(wrap);
    wrap.dataset.state = 'settled';
    wrap.dataset.renderMode = renderMode || 'history';
    delete wrap.dataset.live;
    delete wrap.dataset.scanning;
    wrap._fxFinished = true;
    _routerFxApplySettledSemantics(wrap, decision, wrap.dataset.renderMode);
    _routerFxFitLabels(wrap);
  }

  function _routerFxDisconnectLabelFit(wrap) {
    if (!wrap) return;
    if (wrap._fxFitFrame) {
      cancelAnimationFrame(wrap._fxFitFrame);
      wrap._fxFitFrame = null;
    }
    if (wrap._fxLabelResizeObserver) {
      wrap._fxLabelResizeObserver.disconnect();
      wrap._fxLabelResizeObserver = null;
    }
  }

  function _routerFxRemoveStrip(wrap) {
    if (!wrap) return;
    _routerFxNormalizeSettledStrip(wrap, wrap.dataset.renderMode || 'history');
    _routerFxDisconnectLabelFit(wrap);
    wrap.remove();
  }

  function _routerFxStaticizeCompletedStrips(sessionKey) {
    if (!_thread) return;
    const key = sessionKey || _sessionKey || '';
    _thread.querySelectorAll('.router-fx').forEach((wrap) => {
      if (key && wrap.dataset.sessionKey && wrap.dataset.sessionKey !== key) return;
      if (wrap.dataset.state !== 'settled') return;
      _routerFxNormalizeSettledStrip(wrap, 'history', wrap._fxDecision || null);
    });
  }

  function _settleRouterFxImmediate(wrap, winnerIdx, opts) {
    opts = opts || {};
    const grid = wrap.querySelector('.router-fx-grid');
    const selector = wrap.querySelector('.router-fx-selector');
    if (!grid || !selector) return;
    const cells = grid.querySelectorAll('.router-fx-cell');
    if (!cells[winnerIdx]) return;

    wrap.dataset.state = 'settled';
    delete wrap.dataset.live;
    delete wrap.dataset.scanning;
    wrap._fxFinished = true;
    cells.forEach((c, i) => c.classList.toggle('win', i === winnerIdx));
    _routerFxApplySettledSemantics(wrap, opts.decision || wrap._fxDecision || null, wrap.dataset.renderMode);

    // Hide the chase hammer once settled — the .win cell IS the winner marker.
    // Leaving the selector visible risks it stranding mid-hop (e.g. straddling
    // two cells, the observed visual failure), since its position is measured
    // and can race a layout change.
    if (selector) selector.classList.remove('visible', 'lock', 'lock-impact');
    _routerFxFitLabels(wrap);
    if (opts.burst) {
      requestAnimationFrame(() => _routerFxFireBurst(grid, cells[winnerIdx]));
    }
  }

  function _routerFxFireBurst(grid, cell) {
    if (!grid || !cell) return;
    const cellRect = cell.getBoundingClientRect();
    const gridRect = grid.getBoundingClientRect();
    const cx = cellRect.left - gridRect.left + cellRect.width / 2;
    const cy = cellRect.top - gridRect.top + cellRect.height / 2;
    const burst = document.createElement('div');
    burst.className = 'router-fx-burst';
    burst.style.left = cx + 'px';
    burst.style.top = cy + 'px';
    burst.innerHTML = '<i></i><i></i><i></i><i></i><i></i><i></i>';
    grid.appendChild(burst);
    setTimeout(() => burst.remove(), 700);
  }

  function _animateRouterFx(wrap, winnerIdx) {
    const grid = wrap.querySelector('.router-fx-grid');
    const selector = wrap.querySelector('.router-fx-selector');
    if (!grid || !selector || winnerIdx < 0) return;
    const cells = grid.querySelectorAll('.router-fx-cell');
    if (!cells.length || !cells[winnerIdx]) return;
    _routerFxClearAnimationTimers(wrap);

    // The router panel is an explicitly toggled decorative effect — the in-app
    // "Visual effects" switch IS the motion opt-in — so it plays regardless
    // of the OS prefers-reduced-motion setting, which otherwise blanket-
    // suppresses it in environments that force reduce-motion (some remote
    // desktops / VMs do). Turn the switch off to stop it.

    wrap.dataset.state = 'playing';

    // Build a hop sequence that visits a mix of cells with no
    // immediate repeats. The final hop always lands on the winner.
    const hopCount = 9;
    const sequence = [];
    let prev = -1;
    const totalCells = cells.length;
    for (let i = 0; i < hopCount; i++) {
      let pick;
      let guard = 0;
      do {
        pick = Math.floor(Math.random() * totalCells);
        guard++;
      } while ((pick === prev || pick === winnerIdx) && guard < 12);
      sequence.push(pick);
      prev = pick;
    }
    sequence.push(winnerIdx);

    // Decelerating dwell times: tight chase → punchy landing. Total
    // sweep ≈ 1.33 s.
    const dwellTimes = [50, 55, 65, 75, 90, 110, 140, 180, 240, 330];
    let scheduled = 0;

    const placeFirst = () => {
      _routerFxPositionSelector(selector, cells[sequence[0]], { hopIdx: 0 });
      selector.classList.add('visible');
      _routerFxPing(cells[sequence[0]]);
    };

    sequence.forEach((idx, hopIdx) => {
      if (hopIdx === 0) return;
      scheduled += dwellTimes[hopIdx - 1] || 200;
      const timer = setTimeout(() => {
        if (!wrap.isConnected || wrap.dataset.renderMode !== 'live') return;
        if (hopIdx < sequence.length - 1) {
          _routerFxPositionSelector(selector, cells[idx], { hopIdx });
          _routerFxPing(cells[idx]);
        } else {
          _settleRouterFxImmediate(wrap, idx, { burst: true, decision: wrap._fxDecision });
          _routerFxPing(cells[idx]);
        }
      }, scheduled);
      wrap._fxAnimTimers.push(timer);
    });

    wrap._fxAnimFrame = requestAnimationFrame(() => {
      wrap._fxAnimFrame = null;
      if (!wrap.isConnected || wrap.dataset.renderMode !== 'live') return;
      placeFirst();
    });
  }

  // Winner label used for settled semantics and assistive text.
  function _routerFxWinnerName(decision) {
    const model = decision && (decision.model || decision.routed_model);
    if (model) return _routerFxStripProvider(String(model));
    const tier = _routerFxNormalizeTier(decision && decision.tier);
    if (tier && _routerFxModels[tier]) return _routerFxStripProvider(_routerFxModels[tier]);
    return tier || '';
  }

  // ── Scan → lock ─────────────────────────────────────────────────────────
  function _pendingRouterFxScanMatchesCurrentTurn() {
    if (!_routerFxScanPending) return false;
    return _routerFxScanPending.sessionKey === (_sessionKey || '')
      && _routerFxScanPending.turnIndex === String(_routerFxCountUserMessages());
  }

  function _cancelPendingRouterFxScan(reason = '') {
    const pending = _routerFxScanPending;
    if (_routerFxScanDelayTimer) {
      clearTimeout(_routerFxScanDelayTimer);
      _routerFxScanDelayTimer = null;
    }
    _routerFxScanPending = null;
    if (pending) {
      _chatDiag('router_scan.pending.cancelled', {
        reason: reason || '',
        sessionKey: pending.sessionKey || '',
        turnIndex: pending.turnIndex || '',
      });
    }
  }

  function _clearRouterFxVisuals(reason = '') {
    _cancelPendingRouterFxScan(reason || 'clear_visuals');
    if (!_thread) return;
    _thread.querySelectorAll('.router-fx').forEach((el) => _routerFxRemoveStrip(el));
  }

  async function _finishPendingRouterFxScan() {
    const pending = _routerFxScanPending;
    _routerFxScanDelayTimer = null;
    _routerFxScanPending = null;
    if (!pending) return;
    if (pending.sessionKey !== (_sessionKey || '')) {
      _chatDiag('router_scan.pending.drop.session_changed', {
        pendingSessionKey: pending.sessionKey || '',
        sessionKey: _sessionKey || '',
      });
      return;
    }
    if (_isCompactInFlightForCurrentSession()
        || _routerFxIsSuppressedForCompactionTurn(pending.turnIndex)) {
      _chatDiag('router_scan.pending.drop.compaction_suppressed', {
        sessionKey: pending.sessionKey || '',
        turnIndex: pending.turnIndex || '',
      });
      return;
    }
    await _routerFxAwaitConfig();
    if (pending.sessionKey !== (_sessionKey || '')) {
      _chatDiag('router_scan.pending.drop.session_changed_after_config', {
        pendingSessionKey: pending.sessionKey || '',
        sessionKey: _sessionKey || '',
      });
      return;
    }
    if (_isCompactInFlightForCurrentSession()
        || _routerFxIsSuppressedForCompactionTurn(pending.turnIndex)) {
      _chatDiag('router_scan.pending.drop.compaction_suppressed_after_config', {
        sessionKey: pending.sessionKey || '',
        turnIndex: pending.turnIndex || '',
      });
      return;
    }
    const started = _routerFxBeginScan(pending.anchorDiv, pending.seedKey, {
      requestKind: pending.requestKind,
    });
    if (!started || !pending.decision || !_thread) return;
    const liveStrip = _thread.querySelector('.router-fx[data-live="true"]');
    if (!liveStrip || liveStrip.dataset.turnIndex !== String(pending.turnIndex)) return;
    liveStrip._fxDecision = pending.decision;
    _chatDiag('router_decision.cached_on_delayed_live_strip', {
      payload: _chatDiagSummarizePayload(pending.decision),
      liveStrip: _chatDiagDescribeElement(liveStrip),
    });
    if (liveStrip._fxFinished) {
      _routerFxLock(liveStrip, pending.decision);
      _scrollToBottom();
    }
  }

  function _scheduleRouterFxBeginScan(anchorDiv, seedKey, opts) {
    opts = opts || {};
    const requestKind = _routerFxNormalizeRequestKind(opts.requestKind);
    _cancelPendingRouterFxScan('reschedule');
    if (_routerFxIsSuppressedForCompactionTurn(_routerFxCountUserMessages())) {
      _chatDiag('router_scan.schedule.skip.compaction_suppressed', {
        turnIndex: String(_routerFxCountUserMessages()),
      });
      return false;
    }
    if (!_thread || !_routerFx.enabled || !_routerFeatureEnabled) {
      _chatDiag('router_scan.schedule.skip', {
        hasThread: !!_thread,
        routerFxEnabled: !!_routerFx.enabled,
        routerFeatureEnabled: !!_routerFeatureEnabled,
      });
      return false;
    }
    if (_routerFxConfigTiers !== null && !_routerFxHasMultipleCandidates(requestKind, null)) {
      _chatDiag('router_scan.schedule.skip.single_candidate', {
        requestKind,
        candidates: _routerFxVisualEntries(requestKind, null).length,
      });
      return false;
    }
    _routerFxScanPending = {
      anchorDiv,
      seedKey,
      requestKind,
      sessionKey: _sessionKey || '',
      turnIndex: String(_routerFxCountUserMessages()),
      decision: null,
    };
    _routerFxScanDelayTimer = setTimeout(() => {
      void _finishPendingRouterFxScan();
    }, _ROUTER_FX_START_DELAY_MS);
    _chatDiag('router_scan.scheduled', {
      seedKey,
      requestKind,
      delayMs: _ROUTER_FX_START_DELAY_MS,
      turnIndex: _routerFxScanPending.turnIndex,
      anchor: _chatDiagDescribeElement(anchorDiv),
    });
    return true;
  }

  // Render the routing visualisation after a short grace period, animating
  // continuously until the router_decision arrives and locks it onto the
  // winner. The scan is JS-driven (discrete class/position changes every
  // ~170ms), so it renders regardless of any CSS-animation quirk — and it
  // fills the wait instead of trailing it, replacing the "Watching" placeholder.
  function _routerFxBeginScan(anchorDiv, seedKey, opts) {
    opts = opts || {};
    const requestKind = _routerFxNormalizeRequestKind(opts.requestKind);
    if (_routerFxIsSuppressedForCompactionTurn(_routerFxCountUserMessages())) {
      _chatDiag('router_scan.skip.compaction_suppressed', {
        turnIndex: String(_routerFxCountUserMessages()),
      });
      return false;
    }
    // Only scan when the router is actually going to route (else no decision
    // arrives to lock it). Both flags: user wants the viz AND routing is on.
    if (!_thread || !_routerFx.enabled || !_routerFeatureEnabled) {
      _chatDiag('router_scan.skip', {
        hasThread: !!_thread,
        routerFxEnabled: !!_routerFx.enabled,
        routerFeatureEnabled: !!_routerFeatureEnabled,
      });
      return false;
    }
    if (!_routerFxHasMultipleCandidates(requestKind, null)) {
      _chatDiag('router_scan.skip.single_candidate', {
        requestKind,
        candidates: _routerFxVisualEntries(requestKind, null).length,
      });
      return false;
    }
    _thread.querySelectorAll('.router-fx[data-live="true"]').forEach((el) => {
      _routerFxRemoveStrip(el);
    });
    const wrap = _buildRouterFxElement({ source: 'none' }, {
      seedKey,
      renderMode: 'live',
      requestKind,
    });
    if (!wrap) {
      _chatDiag('router_scan.skip.single_candidate', {
        requestKind,
        candidates: _routerFxVisualEntries(requestKind, null).length,
      });
      return false;
    }
    wrap.dataset.live = 'true';
    wrap.dataset.scanning = 'true';
    wrap.dataset.state = 'scanning';
    wrap.dataset.sessionKey = _sessionKey || '';
    wrap.dataset.turnIndex = String(_routerFxCountUserMessages());
    if (anchorDiv && anchorDiv.parentNode === _thread) {
      _thread.insertBefore(wrap, anchorDiv.nextSibling);
    } else {
      _routerFxInsertAnchored(wrap, null);
    }
    _routerFxScanRoam(wrap);
    _chatDiag('router_scan.started', {
      seedKey,
      anchor: _chatDiagDescribeElement(anchorDiv),
      strip: _chatDiagDescribeElement(wrap),
    });
    // HARD CAP: the scan animation lasts a fixed, short window (≤1s total incl.
    // the settle transition), independent of when the decision WS event lands.
    // The router decides up-front, so the decision is normally cached within
    // tens of ms; at the cap we lock onto it and settle. This is what makes the
    // panel "end quickly within one second" rather than roam until the event.
    wrap._fxScanCap = setTimeout(() => _routerFxFinishScan(wrap), _ROUTER_FX_SCAN_MS);
    _scrollToBottom();
    return true;
  }

  // Finish the scan exactly once: lock onto the cached decision (the winner)
  // and settle. If — vanishingly rarely — no decision has arrived yet, settle
  // to a neutral final state; a late decision still locks via the data-live
  // lookup in _handleRouterDecision.
  function _routerFxFinishScan(wrap) {
    if (!wrap || wrap._fxFinished) return;
    wrap._fxFinished = true;
    if (wrap._fxScanCap) { clearTimeout(wrap._fxScanCap); wrap._fxScanCap = null; }
    if (wrap._fxDecision) {
      _chatDiag('router_scan.finish.with_decision', {
        strip: _chatDiagDescribeElement(wrap),
        payload: _chatDiagSummarizePayload(wrap._fxDecision),
      });
      _routerFxLock(wrap, wrap._fxDecision);
    } else {
      _routerFxStopScan(wrap);
      _routerFxClearVisualResidue(wrap);
      wrap.dataset.state = 'settled';
      _routerFxApplySettledSemantics(wrap, null, 'live');
      _chatDiag('router_scan.finish.no_decision', {
        strip: _chatDiagDescribeElement(wrap),
      });
    }
  }

  // JS-driven roaming "search": every ~190ms the selector hops across a real
  // candidate cell.
  function _routerFxScanRoam(wrap) {
    const grid = wrap.querySelector('.router-fx-grid');
    if (!grid) return;
    const targets = grid.querySelectorAll('.router-fx-cell');
    if (!targets.length) return;
    const selector = grid.querySelector('.router-fx-selector');
    if (selector) selector.classList.add('visible');
    let prev = -1;
    const step = () => {
      if (!wrap.isConnected || wrap.dataset.scanning !== 'true') return;
      let i;
      let g = 0;
      do { i = Math.floor(Math.random() * targets.length); g++; } while (i === prev && g < 8);
      prev = i;
      if (selector) {
        _routerFxPositionSelector(selector, targets[i], { hopIdx: i });
        _routerFxPing(targets[i]);
      }
      wrap._fxScanTimer = setTimeout(step, 190);
    };
    step();
  }

  function _routerFxStopScan(wrap) {
    if (!wrap) return;
    if (wrap._fxScanTimer) { clearTimeout(wrap._fxScanTimer); wrap._fxScanTimer = null; }
    if (wrap._fxScanCap) { clearTimeout(wrap._fxScanCap); wrap._fxScanCap = null; }
    delete wrap.dataset.scanning;
  }

  function _routerFxPauseScanTimers(wrap) {
    if (!wrap) return;
    if (wrap._fxScanTimer) { clearTimeout(wrap._fxScanTimer); wrap._fxScanTimer = null; }
    if (wrap._fxScanCap) { clearTimeout(wrap._fxScanCap); wrap._fxScanCap = null; }
  }

  function _routerFxResumeLiveStrip(wrap) {
    if (!wrap || wrap.dataset.live !== 'true') return;
    _routerFxPauseScanTimers(wrap);
    if (wrap.dataset.scanning === 'true' && !wrap._fxFinished) {
      _routerFxScanRoam(wrap);
      if (wrap._fxDecision) {
        wrap._fxScanCap = setTimeout(() => _routerFxFinishScan(wrap), _ROUTER_FX_SCAN_MS);
      } else {
        _chatDiag('router_scan.resume_without_decision', {
          strip: _chatDiagDescribeElement(wrap),
        });
      }
      return;
    }
    if (wrap._fxFinished && wrap._fxDecision && !wrap.dataset.routerIdentity) {
      _routerFxLock(wrap, wrap._fxDecision);
    }
  }

  // When output begins, finish the in-flight selection scan without freezing
  // the strip. The text/tool stream can render immediately, while the router
  // still gets its visible winner-lock animation instead of becoming a static
  // empty frame.
  function _routerFxSettleForOutput() {
    if (!_thread) return;
    _thread.querySelectorAll('.router-fx[data-live="true"]').forEach((wrap) => {
      // Output already complete/arriving → finish the scan immediately, locking
      // onto the cached winner (no half-scan left hanging). Do not mark frozen:
      // _routerFxLockGrid owns the visible selection motion.
      if (wrap._fxDecision) {
        _routerFxFinishScan(wrap);
      } else {
        _chatDiag('router_scan.keep_scanning_without_decision_on_output', {
          strip: _chatDiagDescribeElement(wrap),
        });
      }
    });
  }

  // Lock an in-flight scanning strip onto the routed winner.
  function _routerFxLock(wrap, decision) {
    if (!wrap) return;
    decision = decision || {};
    _routerFxStopScan(wrap);
    wrap.dataset.tier = _routerFxNormalizeTier(decision.tier);
    wrap.dataset.source = decision.source || 'none';
    wrap.dataset.renderMode = wrap.dataset.renderMode || 'live';
    wrap._fxDecision = decision;
    const identity = _routerFxDecisionIdentity(decision);
    if (identity) wrap.dataset.routerIdentity = identity;
    if (decision.routing_applied === false) {
      wrap.dataset.observe = 'true';
      wrap.dataset.rolloutPhase = typeof decision.rollout_phase === 'string'
        ? decision.rollout_phase : 'observe';
    }
    _routerFxLockGrid(wrap, decision);
  }

  function _routerFxLockGrid(wrap, decision) {
    const tier = _routerFxNormalizeTier(decision.tier);
    if (tier) {
      _routerFxRememberTierDecision(tier, decision.model || '');
    }
    const winnerIdx = _routerFxWinnerCellIndex(wrap, tier);
    if (winnerIdx >= 0) {
      requestAnimationFrame(() => {
        if (wrap.isConnected) _settleRouterFxImmediate(wrap, winnerIdx, { burst: true, decision });
      });
    } else {
      wrap.dataset.state = 'settled';
      delete wrap.dataset.live;
      delete wrap.dataset.scanning;
      wrap._fxFinished = true;
      _routerFxApplySettledSemantics(wrap, decision, wrap.dataset.renderMode);
    }
  }

  // Anchor invariant: the strip must always sit immediately below
  // the user message that triggered this turn — never above it,
  // never with anything (day separators, tool cards, the assistant
  // bubble) wedged between the user prompt and the strip. Locate
  // the most recent user message in the thread and place the strip
  // as its next sibling. Falls back to streamBubble-relative or
  // thread-append only when there's literally no user msg in view.
  function _routerFxLastUserMessage() {
    if (!_thread) return null;
    const userMsgs = _thread.querySelectorAll(
      '.msg.user, .msg[data-history-role="user"]'
    );
    return userMsgs.length ? userMsgs[userMsgs.length - 1] : null;
  }

  // Walk backwards from an assistant bubble until we hit either
  // (a) the router strip that belongs to this turn, or (b) the user
  // message that triggered it (no strip in between). Used by the
  // DoneEvent handler since the strip is anchored to the user msg,
  // which means it may not be the assistant bubble's immediate
  // previousElementSibling once tool cards / day-separators arrive.
  function _routerFxUserMessageForAssistant(referenceAssistant) {
    if (!referenceAssistant) return null;
    let prev = referenceAssistant.previousElementSibling;
    while (prev) {
      if (prev.classList && (prev.classList.contains('user')
          || prev.getAttribute('data-history-role') === 'user')) {
        return prev;
      }
      prev = prev.previousElementSibling;
    }
    return null;
  }

  // Shrink any grid cell label that overflows its cell so long model names
  // (e.g. "gemini-3.1-flash-lite") show in full instead of clipping at the
  // edges. Re-runs after insertion, font load, resize, and winner lock because
  // all of those can change the measured width.
  function _routerFxMeasureLabels(wrap) {
    if (!wrap || !wrap.isConnected) return;
    wrap.querySelectorAll('.router-fx-cell').forEach((cell) => {
      const nm = cell.querySelector('.nm');
      if (!nm) return;
      nm.style.fontSize = '';
      const avail = cell.clientWidth - 12;
      if (avail <= 0) return;
      const w = nm.scrollWidth;
      if (w > avail) {
        const base = parseFloat(getComputedStyle(nm).fontSize) || 10.5;
        nm.style.fontSize = Math.max(7, base * (avail / w)).toFixed(1) + 'px';
      }
    });
  }

  function _routerFxScheduleLabelFit(wrap) {
    if (!wrap) return;
    if (wrap._fxFitFrame) cancelAnimationFrame(wrap._fxFitFrame);
    wrap._fxFitFrame = requestAnimationFrame(() => {
      wrap._fxFitFrame = null;
      _routerFxMeasureLabels(wrap);
    });
  }

  function _routerFxInstallLabelFit(wrap) {
    if (!wrap || wrap._fxFitInstalled) return;
    wrap._fxFitInstalled = true;
    const grid = wrap.querySelector('.router-fx-grid');
    if (grid && typeof ResizeObserver === 'function') {
      wrap._fxLabelResizeObserver = new ResizeObserver(() => _routerFxScheduleLabelFit(wrap));
      wrap._fxLabelResizeObserver.observe(grid);
    }
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready
        .then(() => _routerFxScheduleLabelFit(wrap))
        .catch(() => {});
    }
  }

  function _routerFxFitLabels(wrap) {
    if (!wrap) return;
    _routerFxInstallLabelFit(wrap);
    _routerFxScheduleLabelFit(wrap);
  }

  function _routerFxInsertAnchored(wrap, referenceAssistant) {
    if (!_thread) return;
    // Fit long labels once the strip is in the DOM (rAF runs after the
    // synchronous insertion below, regardless of which branch placed it).
    _routerFxFitLabels(wrap);
    // Prefer the user msg that immediately precedes the assistant
    // turn we're about to render (during history rebuild we have a
    // concrete reference div; live, we don't).
    let anchor = _routerFxUserMessageForAssistant(referenceAssistant);
    if (!anchor) anchor = _routerFxLastUserMessage();
    if (anchor && anchor.parentNode === _thread) {
      if (anchor.nextSibling) {
        _thread.insertBefore(wrap, anchor.nextSibling);
      } else {
        _thread.appendChild(wrap);
      }
      return;
    }
    if (referenceAssistant && referenceAssistant.parentNode === _thread) {
      _thread.insertBefore(wrap, referenceAssistant);
      return;
    }
    if (_isStreaming && _streamBubble) {
      _thread.insertBefore(wrap, _streamBubble);
    } else {
      _thread.appendChild(wrap);
    }
  }

  // Live entry point — wired to session.event.router_decision.
  // Async so we can await the config-ready gate before building the
  // grid; otherwise a router_decision event arriving in the gap
  // between WS connect and config.get returning would render the
  // strip with empty _routerFxModels (tier-id placeholders). The
  // gate has its own 1.5 s ceiling so the await never hard-blocks.
  async function _handleRouterDecision(payload) {
    _chatDiag('router_decision.handle.start', _chatDiagSummarizePayload(payload));
    if (!payload || typeof payload !== 'object') {
      _chatDiag('router_decision.skip.invalid_payload', {});
      return;
    }
    const tier = _routerFxNormalizeTier(payload.tier);
    if (!tier) {
      _chatDiag('router_decision.skip.no_tier', _chatDiagSummarizePayload(payload));
      return;
    }
    _routerFxRememberTierDecision(tier, payload.model || '');
    const turnIndex = _routerFxCountUserMessages();
    if (_routerFxIsSuppressedForCompactionTurn(turnIndex)) {
      if (_thread) {
        _thread.querySelectorAll('.router-fx[data-live="true"]').forEach((el) => {
          if (!el.dataset.turnIndex || el.dataset.turnIndex === String(turnIndex)) {
            _routerFxRemoveStrip(el);
          }
        });
      }
      _chatDiag('router_decision.skip.compaction_suppressed', {
        payload: _chatDiagSummarizePayload(payload),
        turnIndex: String(turnIndex),
      });
      return;
    }
    // User-pref gate: visualisation hidden. Tier/model bookkeeping above is
    // kept warm so re-enabling shows correct names without a config round-trip;
    // skip the config await and all DOM work below. (Render-only gate — never
    // purge already-rendered strips here, to stay clear of the streaming /
    // history-rebuild strip lifecycle.)
    if (!_routerFx.enabled) {
      _chatDiag('router_decision.skip.disabled_pre_config', _chatDiagSummarizePayload(payload));
      return;
    }
    if (!_thread) {
      _chatDiag('router_decision.skip.no_thread_pre_config', _chatDiagSummarizePayload(payload));
      return;
    }
    if (_pendingRouterFxScanMatchesCurrentTurn()) {
      _routerFxScanPending.decision = payload;
      _chatDiag('router_decision.cached_on_pending_scan', {
        payload: _chatDiagSummarizePayload(payload),
        turnIndex: _routerFxScanPending.turnIndex || '',
        requestKind: _routerFxScanPending.requestKind || '',
      });
      return;
    }
    // A strip for this turn was rendered when the delayed scan began. CACHE the
    // decision on it; the fixed-window scan (_routerFxFinishScan) locks onto it
    // when the window closes — so the animation runs for a consistent ≤1s
    // rather than however long the WS event took. If the window has ALREADY
    // closed (late decision), lock immediately. Match by data-live so we find
    // it whether it's still scanning or already settled-awaiting-winner.
    const liveStrip = _thread.querySelector('.router-fx[data-live="true"]');
    if (liveStrip
        && liveStrip.dataset.turnIndex === String(_routerFxCountUserMessages())) {
      liveStrip.dataset.sessionKey = _sessionKey || '';
      liveStrip._fxDecision = payload;
      _chatDiag('router_decision.cached_on_live_strip', {
        payload: _chatDiagSummarizePayload(payload),
        liveStrip: _chatDiagDescribeElement(liveStrip),
        finished: !!liveStrip._fxFinished,
      });
      if (liveStrip._fxFinished) {
        _routerFxLock(liveStrip, payload);
        _scrollToBottom();
      }
      return;
    }
    await _routerFxAwaitConfig();
    // Re-check the thread reference after the await — the view may
    // have been torn down while we were waiting.
    if (!_thread) {
      _chatDiag('router_decision.skip.no_thread_post_config', _chatDiagSummarizePayload(payload));
      return;
    }
    // Re-check the visualisation pref too: the user may have flipped it OFF
    // during the (up to 1.5s cold-start) config await. Symmetric with the
    // pre-await gate — without this a strip the user just hid would still
    // flash in before the disabled-sweep removes it on the next sync.
    if (!_routerFx.enabled) {
      _chatDiag('router_decision.skip.disabled_post_config', _chatDiagSummarizePayload(payload));
      return;
    }
    const replayRequestKind = _routerFxRequestKindFromDecision(payload, null);
    if (!_routerFxHasMultipleCandidates(replayRequestKind, payload)) {
      _chatDiag('router_decision.skip.single_candidate', _chatDiagSummarizePayload(payload));
      return;
    }
    if (!_historyHasRendered || _historyHydrating) {
      _cachePendingRouterDecision(payload);
      _chatDiag('router_decision.cached_during_history_hydration', {
        payload: _chatDiagSummarizePayload(payload),
        historyHasRendered: !!_historyHasRendered,
        historyHydrating: !!_historyHydrating,
      });
      return;
    }
    // The router strip MUST anchor below a user message. If a WS replay
    // arrives before history has rendered the user turn, cache the decision
    // and replay it after _loadHistory() has an anchor.
    const anchorUser = _routerFxLastUserMessage();
    if (!anchorUser) {
      _cachePendingRouterDecision(payload);
      return;
    }
    // No matching live scan means this decision is arriving via replay/history
    // or after the user-visible turn already settled. Preserve the panel shape
    // but render it as a settled historical result; never replay the choice
    // animation for an already-finished turn.
    const replaySeed = _routerFxResolveLayoutSeed(_sessionKey);
    const wrap = _buildRouterFxElement(payload, {
      preSettled: true,
      renderMode: 'history',
      seedKey: replaySeed,
      requestKind: replayRequestKind,
    });
    if (!wrap) {
      _chatDiag('router_decision.skip.single_candidate', _chatDiagSummarizePayload(payload));
      return;
    }
    const winnerIdx = _routerFxWinnerCellIndex(wrap, tier);
    if (winnerIdx < 0) {
      _chatDiag('router_decision.skip.no_winner', {
        payload: _chatDiagSummarizePayload(payload),
        winnerIdx,
      });
      return;
    }
    wrap.dataset.sessionKey = _sessionKey || '';
    wrap.dataset.turnIndex = String(turnIndex);
    const observeMode = payload && payload.routing_applied === false;
    // Drop any earlier strip anchored to this user msg, regardless of
    // its lifecycle flag. A WS replay arriving after F5 will have
    // built a tier-id strip before config loaded; we replace it with
    // the now-correct one instead of stacking another on top.
    const userMsg = _routerFxLastUserMessage();
    if (userMsg && userMsg.nextSibling
        && userMsg.nextSibling.classList
        && userMsg.nextSibling.classList.contains('router-fx')
        && userMsg.nextSibling !== wrap) {
      _routerFxRemoveStrip(userMsg.nextSibling);
    }
    // Drop any earlier live strip from a different turn that hasn't
    // been promoted yet — protects against rapid back-to-back sends.
    _thread.querySelectorAll('.router-fx[data-live="true"]').forEach((el) => {
      if (el !== wrap) _routerFxRemoveStrip(el);
    });
    _routerFxInsertAnchored(wrap, null);
    _routerFxNormalizeSettledStrip(wrap, 'history', payload);
    _chatDiag('router_decision.inserted_settled_strip', {
      payload: _chatDiagSummarizePayload(payload),
      strip: _chatDiagDescribeElement(wrap),
      observeMode,
      winnerIdx,
    });
    _scrollToBottom();
  }

  // History-load entry point — settled grid, no animation.
  // `seedKey` should be a stable per-turn identifier (msg.timestamp
  // or message id) so the cell shuffle reproduces deterministically
  // across page refreshes.
  function _buildRouterFxFromUsage(usage, seedKey, opts) {
    opts = opts || {};
    if (!usage) return null;
    // User-pref gate: the viewer has hidden the router-fx visualisation, so
    // no history strip is built. Distinct from the operator routing flag below
    // (_routerFeatureEnabled): this one is "do I want to see it", that one is
    // "is routing on". Caller null-checks, so suppression needs no other edit.
    if (!_routerFx.enabled) return null;
    // If the operator has flipped squilla_router off since this turn
    // was recorded, drop the historic strip on the next rebuild —
    // the slider's whole point is conveying live router behaviour.
    if (_routerFxConfigTiers !== null && !_routerFeatureEnabled) return null;
    const tier = _routerFxNormalizeTier(usage.routed_tier);
    if (!tier) return null;
    // If the operator has REMOVED this tier from config since the
    // turn was recorded, skip — rendering the strip would show a
    // ghost cell ("c2") with no current meaning.
    if (_routerFxConfigTiers !== null
        && !_routerFxConfigTiers.has(tier)) {
      return null;
    }
    _routerFxRememberTierDecision(tier, usage.routed_model || usage.model || '');
    const decision = {
      tier,
      model: usage.routed_model || usage.model || '',
      source: usage.routing_source || 'none',
      confidence: typeof usage.routing_confidence === 'number' ? usage.routing_confidence : 0,
      fallback: usage.routing_source === 'fallback',
      routing_applied: usage.routing_applied !== false,
      rollout_phase: usage.rollout_phase || 'full',
    };
    const requestKind = _routerFxRequestKindFromDecision(decision, opts.requestKind);
    // The cached seed from _routerFxResolveSeed already encodes
    // (stamp, tier, turnIndex) — pass it through verbatim so that
    // live and history paths derive the SAME shuffle for the same
    // turn. Earlier revisions concatenated ':' + tier here, which
    // produced a different hash from the live path's seedKey and
    // caused a visible cell reorder at the live→history transition.
    return _buildRouterFxElement(decision, {
      preSettled: true,
      seedKey: seedKey != null ? String(seedKey) : ('history:' + tier),
      requestKind: requestKind,
    });
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

    // Router decision: fires once per user message, right after the
    // pre-turn pipeline picks a tier and before the first text_delta.
    // Drops a per-turn inline slider above where the assistant bubble
    // will appear and sweeps the selector onto the routed tier.
    _unsubs.push(_rpc.on('session.event.router_decision', (payload) => {
      if (_dropForeignSessionPayload('event.router_decision', payload)) return;
      if (_isStaleEpoch(payload)) {
        _chatDiag('event.router_decision.drop.stale_epoch', _chatDiagSummarizePayload(payload));
        return;
      }
      if (!_acceptStreamSeq(payload)) {
        _chatDiag('event.router_decision.drop.stream_seq', _chatDiagSummarizePayload(payload));
        return;
      }
      _chatDiag('event.router_decision', _chatDiagSummarizePayload(payload));
      _handleRouterDecision(payload);
    }));

    // Text delta: accumulate into streaming bubble
    _unsubs.push(_rpc.on('session.event.text_delta', (payload) => {
      if (_dropForeignSessionPayload('event.text_delta', payload)) return;
      if (_isStaleEpoch(payload)) {
        _chatDiag('event.text_delta.drop.stale_epoch', _chatDiagSummarizePayload(payload));
        return;
      }
      if (!_acceptStreamSeq(payload)) {
        _chatDiag('event.text_delta.drop.stream_seq', _chatDiagSummarizePayload(payload));
        return;
      }
      _chatDiag('event.text_delta', _chatDiagSummarizePayload(payload));
      _resetStreamIdleTimer();
      _appendDelta(payload.text || '');
    }));

    // Tool call events (engine emits tool_use_start)
    _unsubs.push(_rpc.on('session.event.tool_use_start', (payload) => {
      if (_dropForeignSessionPayload('event.tool_use_start', payload)) return;
      if (_isStaleEpoch(payload)) {
        _chatDiag('event.tool_use_start.drop.stale_epoch', _chatDiagSummarizePayload(payload));
        return;
      }
      if (_aborted) {
        _chatDiag('event.tool_use_start.drop.aborted', _chatDiagSummarizePayload(payload));
        return;
      }
      if (!_acceptStreamSeq(payload)) {
        _chatDiag('event.tool_use_start.drop.stream_seq', _chatDiagSummarizePayload(payload));
        return;
      }
      _chatDiag('event.tool_use_start', _chatDiagSummarizePayload(payload));
      _resetStreamIdleTimer();
      _appendToolCall(payload);
    }));

    // Tool result events
    _unsubs.push(_rpc.on('session.event.tool_result', (payload) => {
      if (_dropForeignSessionPayload('event.tool_result', payload)) return;
      if (_isStaleEpoch(payload)) {
        _chatDiag('event.tool_result.drop.stale_epoch', _chatDiagSummarizePayload(payload));
        return;
      }
      if (_aborted) {
        _chatDiag('event.tool_result.drop.aborted', _chatDiagSummarizePayload(payload));
        return;
      }
      if (!_acceptStreamSeq(payload)) {
        _chatDiag('event.tool_result.drop.stream_seq', _chatDiagSummarizePayload(payload));
        return;
      }
      _chatDiag('event.tool_result', _chatDiagSummarizePayload(payload));
      _resetStreamIdleTimer();
      _appendToolResult(payload);
    }));

    // MetaSkill run progress ribbon — design §8.
    // 3 handlers + 1 action delegate. Ribbon lives in window.MetaRibbon
    // (loaded as a classic script before chat.js, see index.html).
    const _metaPreflightEl = new Map();  // run_id → DOM section element
    const _metaRibbonState = new Map();   // run_id → ribbon state
    const _metaRibbonEl = new Map();      // run_id → DOM section element

    function _openMetaRunHistory() {
      if (!window.MetaRunHistory || typeof window.MetaRunHistory.openRunHistory !== 'function') {
        UI.toast('Meta run history is not available', 'warn', 2000);
        return;
      }
      window.MetaRunHistory.openRunHistory({
        rpc: _rpc,
        sessionKey: _sessionKey,
      });
    }

    const metaHistoryBtn = _el.querySelector('#chat-btn-meta-history');
    if (metaHistoryBtn) {
      metaHistoryBtn.addEventListener('click', _openMetaRunHistory);
      _unsubs.push(() => metaHistoryBtn.removeEventListener('click', _openMetaRunHistory));
    }

    document.addEventListener('meta-run-history-open', _openMetaRunHistory);
    _unsubs.push(() => document.removeEventListener(
      'meta-run-history-open',
      _openMetaRunHistory,
    ));

    function _insertMetaRibbonElement(el) {
      const runId = el && el.dataset ? el.dataset.runId : '';
      const preflight = runId ? _metaPreflightEl.get(runId) : null;
      if (
        preflight
        && preflight.parentNode
        && preflight.parentNode === (_thread || preflight.parentNode)
      ) {
        preflight.parentNode.insertBefore(el, preflight.nextSibling);
        return;
      }
      const host = _thread || document.body;
      if (_thread && _streamBubble && _streamBubble.parentNode === _thread) {
        _thread.insertBefore(el, _streamBubble);
        return;
      }
      const liveUserAnchor = _currentSessionLiveUserAnchor(_sessionKey || '');
      if (_thread && liveUserAnchor && liveUserAnchor.parentNode === _thread) {
        _thread.insertBefore(el, liveUserAnchor.nextSibling);
        return;
      }
      host.insertBefore(el, host.firstChild || null);
    }

    function _insertMetaPreflightElement(el) {
      _insertMetaRibbonElement(el);
    }

    function _findRibbonUserMessage(ribbonEl) {
      let node = ribbonEl ? ribbonEl.previousElementSibling : null;
      while (node) {
        if (node.matches && (
          node.matches('.msg.user')
          || node.getAttribute('data-history-role') === 'user'
        )) return node;
        node = node.previousElementSibling;
      }
      return null;
    }

    function _latestUserMessageText() {
      for (let i = _messages.length - 1; i >= 0; i--) {
        if (_messages[i] && _messages[i].role === 'user') {
          return _messages[i].text || '';
        }
      }
      const userBubbles = _thread
        ? Array.from(_thread.querySelectorAll(':scope > .msg.user, :scope > .msg[data-history-role="user"]'))
        : [];
      const last = userBubbles[userBubbles.length - 1];
      return last ? _extractBubbleText(last) : '';
    }

    function _retryMetaRibbonRun(ribbonEl) {
      if (_isStreaming) {
        UI.toast('Wait for the current response to finish', 'warn', 2000);
        return;
      }
      const userBubble = _findRibbonUserMessage(ribbonEl);
      const text = userBubble ? _extractBubbleText(userBubble) : _latestUserMessageText();
      if (!text) {
        UI.toast('No previous message to retry', 'info', 2000);
        return;
      }
      if (!_textarea) return;
      _textarea.value = text;
      _autoResizeTextarea();
      _onSend();
    }

    async function _replayMetaRibbonRun(ribbonEl, mode) {
      if (_isStreaming) {
        UI.toast('Wait for the current response to finish', 'warn', 2000);
        return;
      }
      const runId = ribbonEl && ribbonEl.dataset ? ribbonEl.dataset.runId : '';
      if (!runId || !_textarea) {
        UI.toast('No MetaSkill run selected to replay', 'info', 2000);
        return;
      }
      try {
        const payload = await _rpc.call('meta.runs.replay', {
          runId,
          mode: mode || 'failed-step',
        });
        const replay = payload && payload.replay ? payload.replay : payload;
        _textarea.value = replay && replay.message ? replay.message : '';
        _autoResizeTextarea();
        if (_textarea.value) _onSend();
      } catch (err) {
        UI.toast(err && err.message ? err.message : 'MetaSkill replay failed', 'warn', 3000);
      }
    }

    async function _confirmMetaPreflight(detail) {
      const confirmed = await _rpc.call('meta.runs.confirm_preflight', {
        runId: detail.runId || '',
        interpretedRequest: detail.interpretedRequest || '',
        fields: detail.confirmedFields || {},
      });
      return confirmed || {};
    }

    _unsubs.push(_rpc.on('session.event.meta_preflight', (payload) => {
      if (_dropForeignSessionPayload('event.meta_preflight', payload)) return;
      if (!window.MetaPreflight) return;
      const state = window.MetaPreflight.createPreflight(payload);
      if (!state.runId) return;
      const el = document.createElement('section');
      el.dataset.runId = state.runId;
      _insertMetaPreflightElement(el);
      _metaPreflightEl.set(state.runId, el);
      window.MetaPreflight.renderPreflight(el, state);
    }));

    _unsubs.push(_rpc.on('session.event.meta_run_announced', (payload) => {
      if (_dropForeignSessionPayload('event.meta_run_announced', payload)) return;
      if (!window.MetaRibbon) return;
      const state = window.MetaRibbon.createRibbon(payload);
      if (!state.runId) return;
      _metaRibbonState.set(state.runId, state);
      const el = document.createElement('section');
      el.dataset.runId = state.runId;
      _insertMetaRibbonElement(el);
      _metaRibbonEl.set(state.runId, el);
      window.MetaRibbon.renderRibbon(el, state);
    }));

    _unsubs.push(_rpc.on('session.event.meta_step_state', (payload) => {
      if (_dropForeignSessionPayload('event.meta_step_state', payload)) return;
      if (!window.MetaRibbon) return;
      const state = _metaRibbonState.get(payload.run_id);
      const el = _metaRibbonEl.get(payload.run_id);
      if (!state || !el) return;
      window.MetaRibbon.updateStep(state, payload);
      window.MetaRibbon.renderRibbon(el, state);
    }));

    _unsubs.push(_rpc.on('session.event.meta_run_completed', (payload) => {
      if (_dropForeignSessionPayload('event.meta_run_completed', payload)) return;
      if (!window.MetaRibbon) return;
      const state = _metaRibbonState.get(payload.run_id);
      const el = _metaRibbonEl.get(payload.run_id);
      if (!state || !el) return;
      window.MetaRibbon.completeRun(state, payload);
      window.MetaRibbon.renderRibbon(el, state);
    }));

    // Action chip delegate (retry / switch-skill / show-detail). Listens on
    // document so dynamically-rendered ribbons all flow through one handler.
    const _onMetaRibbonAction = (ev) => {
      const { action, stepId } = (ev && ev.detail) || {};
      if (action === 'retry-run') {
        _retryMetaRibbonRun(ev && ev.target ? ev.target.closest('.meta-ribbon') : null);
      } else if (action === 'retry-step' || action === 'retry-with-partial-context') {
        const mode = action === 'retry-step' ? 'failed-step' : 'partial-context';
        _replayMetaRibbonRun(
          ev && ev.target ? ev.target.closest('.meta-ribbon') : null,
          mode,
        );
      } else if (action === 'switch-skill' || action === 'switch-meta-skill') {
        if (_textarea) {
          _textarea.placeholder = '想换哪个 meta-skill？例如：Use meta-skill `meta-kid-project-planner`';
          _textarea.focus();
        }
      } else if (action === 'install-dependency') {
        UI.toast('Install the missing dependency, then retry this MetaSkill run.', 'info', 3000);
      } else if (action === 'continue-text-only') {
        UI.toast('Continue with text outputs only, then retry if an artifact is still needed.', 'info', 3000);
      } else if (action === 'show-detail' && stepId) {
        const card = document.querySelector(`[data-tool-use-id="meta_step_${stepId}"]`);
        if (card) {
          card.setAttribute('data-expanded', 'true');
          if (typeof card.scrollIntoView === 'function') {
            card.scrollIntoView({ block: 'center', behavior: 'smooth' });
          }
        }
      }
    };
    document.addEventListener('meta-ribbon-action', _onMetaRibbonAction);
    _unsubs.push(() => document.removeEventListener('meta-ribbon-action', _onMetaRibbonAction));

    const _onMetaPreflightAction = async (ev) => {
      const detail = (ev && ev.detail) || {};
      const card = ev && ev.target ? ev.target.closest('.meta-preflight') : null;
      if (detail.action === 'dismiss') {
        if (card && window.MetaPreflight && window.MetaPreflight.renderCollapsed) {
          window.MetaPreflight.renderCollapsed(card, detail, 'cancelled');
        } else if (card) {
          card.remove();
        }
        if (detail.runId) _metaPreflightEl.delete(detail.runId);
        return;
      }
      if ((detail.action === 'continue' || detail.action === 'defaults') && _textarea) {
        try {
          if (card && window.MetaPreflight && window.MetaPreflight.setSubmitting) {
            window.MetaPreflight.setSubmitting(card, true);
          }
          const confirmed = await _confirmMetaPreflight(detail);
          if (card && window.MetaPreflight && window.MetaPreflight.renderCollapsed) {
            window.MetaPreflight.renderCollapsed(card, detail, 'running');
          } else if (card) {
            card.remove();
          }
          if (detail.runId) _metaPreflightEl.delete(detail.runId);
          _sendHiddenMetaPreflightConfirmation(confirmed, detail);
        } catch (err) {
          if (card && window.MetaPreflight && window.MetaPreflight.setSubmitting) {
            window.MetaPreflight.setSubmitting(card, false);
          }
          if (card && window.MetaPreflight && window.MetaPreflight.setError) {
            window.MetaPreflight.setError(card, err);
          }
          UI.toast(err && err.message ? err.message : 'MetaSkill confirmation failed', 'warn', 3000);
        }
        return;
      }
    };
    document.addEventListener('meta-preflight-action', _onMetaPreflightAction);
    _unsubs.push(() => document.removeEventListener(
      'meta-preflight-action',
      _onMetaPreflightAction,
    ));

    _unsubs.push(_rpc.on('session.event.artifact', (payload) => {
      if (_dropForeignSessionPayload('event.artifact', payload)) return;
      if (_isStaleEpoch(payload)) {
        _chatDiag('event.artifact.drop.stale_epoch', _chatDiagSummarizePayload(payload));
        return;
      }
      if (_aborted) {
        _chatDiag('event.artifact.drop.aborted', _chatDiagSummarizePayload(payload));
        return;
      }
      if (!_acceptStreamSeq(payload)) {
        _chatDiag('event.artifact.drop.stream_seq', _chatDiagSummarizePayload(payload));
        return;
      }
      _chatDiag('event.artifact', _chatDiagSummarizePayload(payload));
      _resetStreamIdleTimer();
      _appendArtifact(payload);
    }));

    _unsubs.push(_rpc.on('session.event.subagent_completion', (payload) => {
      if (_dropForeignSessionPayload('event.subagent_completion', payload)) return;
      if (_isStaleEpoch(payload)) {
        _chatDiag('event.subagent_completion.drop.stale_epoch', _chatDiagSummarizePayload(payload));
        return;
      }
      if (_aborted) {
        _chatDiag('event.subagent_completion.drop.aborted', _chatDiagSummarizePayload(payload));
        return;
      }
      if (!_acceptStreamSeq(payload)) {
        _chatDiag('event.subagent_completion.drop.stream_seq', _chatDiagSummarizePayload(payload));
        return;
      }
      _chatDiag('event.subagent_completion', _chatDiagSummarizePayload(payload));
      _appendSubagentCompletion(payload);
    }));

    // Agent state transitions (thinking → streaming → tool_calling → done)
    _unsubs.push(_rpc.on('session.event.state_change', (payload, meta = {}) => {
      if (_dropForeignSessionPayload('event.state_change', payload)) return;
      if (_isStaleEpoch(payload)) {
        _chatDiag('event.state_change.drop.stale_epoch', _chatDiagSummarizePayload(payload));
        return;
      }
      if (!payload || _aborted) {
        _chatDiag('event.state_change.drop.empty_or_aborted', _chatDiagSummarizePayload(payload));
        return;
      }
      if (!_acceptStreamSeq(payload)) {
        _chatDiag('event.state_change.drop.stream_seq', _chatDiagSummarizePayload(payload));
        return;
      }
      if (_dropReplayedLiveWaitEvent(meta, payload, 'event.state_change')) return;
      _chatDiag('event.state_change', _chatDiagSummarizePayload(payload));
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

    _unsubs.push(_rpc.on('session.event.run_heartbeat', (payload, meta = {}) => {
      if (_dropForeignSessionPayload('event.run_heartbeat', payload)) return;
      if (_isStaleEpoch(payload)) {
        _chatDiag('event.run_heartbeat.drop.stale_epoch', _chatDiagSummarizePayload(payload));
        return;
      }
      if (_aborted) {
        _chatDiag('event.run_heartbeat.drop.aborted', _chatDiagSummarizePayload(payload));
        return;
      }
      if (!_acceptStreamSeq(payload)) {
        _chatDiag('event.run_heartbeat.drop.stream_seq', _chatDiagSummarizePayload(payload));
        return;
      }
      if (_dropReplayedLiveWaitEvent(meta, payload, 'event.run_heartbeat')) return;
      _chatDiag('event.run_heartbeat', _chatDiagSummarizePayload(payload));
      if (!_isStreaming) _startStreaming();
      _resetStreamIdleTimer();
      if (_streamBubble) {
        _showAwaitingModelHintAfterToolResult();
      } else {
        _showThinkingIndicator();
      }
    }));

    _unsubs.push(_rpc.on('session.event.cron_result', (payload) => {
      if (_dropForeignSessionPayload('event.cron_result', payload)) return;
      if (_isStaleEpoch(payload)) return;
      if (!_acceptStreamSeq(payload)) return;
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

    _unsubs.push(_rpc.on('session.event.compaction', (payload, meta) => {
      if (_dropForeignSessionPayload('event.compaction', payload)) return;
      if (_isStaleEpoch(payload)) return;
      if (!_acceptStreamSeq(payload)) return;
      _showCompactionToast(payload || {}, meta || {});
    }));

    // Non-persistent warnings surfaced by the turn runner (e.g. model claimed
    // to generate an image but never called the tool). Toast only — never
    // written to the transcript, never fed back to the LLM.
    _unsubs.push(_rpc.on('session.event.warning', (payload) => {
      if (_dropForeignSessionPayload('event.warning', payload)) return;
      if (_isStaleEpoch(payload)) return;
      const code = String((payload && payload.code) || '');
      const silentWarningCodes = new Set([
        'provider_reasoning_only_retry',
      ]);
      if (silentWarningCodes.has(code)) return;
      const msg = (payload && payload.message) || 'Squilla warning';
      UI.toast(msg, 'warn', 5000);
    }));

    // Track session epoch to discard stale frames from pre-reset turns.
    _unsubs.push(_rpc.on('session.epoch_changed', (payload) => {
      if (_dropForeignSessionPayload('session.epoch_changed', payload)) return;
      const ep = payload && payload.epoch;
      if (typeof ep === 'number' && Number.isFinite(ep) && ep > _currentEpoch) {
        _clearActiveTaskGroups();
        _currentEpoch = ep;
      }
    }));

    // sessions.changed carries epoch — drop if stale.
    _unsubs.push(_rpc.on('sessions.changed', (payload) => {
      if (_isStaleEpoch(payload)) return;
      if (!_isCurrentSessionPayload(payload)) return;
      if (_sessionChangeIsTerminal(payload)) {
        _syncTerminalSessionChange(payload);
        return;
      }
      _applySessionRunState(payload);
    }));

    _unsubs.push(_rpc.on('task.queued', (payload) => {
      if (!_isCurrentSessionPayload(payload)) return;
      if (_currentRunStatus === 'running' || _currentRunStatus === 'approval_pending') return;
      _applySessionRunState({
        run_status: 'queued',
        active_task: { ...(payload || {}), status: 'queued' },
      });
    }));

    _unsubs.push(_rpc.on('task.running', (payload) => {
      if (!_isCurrentSessionPayload(payload)) return;
      // task.running is the authoritative "this task now owns the live stream"
      // signal; bind subsequent stream events to it (issue 344).
      const taskId = _payloadTaskId(payload);
      if (taskId) _activeStreamTaskId = taskId;
      _applySessionRunState({
        run_status: 'running',
        active_task: { ...(payload || {}), status: 'running' },
      });
    }));

    _unsubs.push(_rpc.on('session.event.task_group.waiting', (payload) => {
      if (_dropForeignSessionPayload('event.task_group.waiting', payload)) return;
      if (_isStaleEpoch(payload)) return;
      if (!_acceptStreamSeq(payload)) return;
      _noteTaskGroupActive(payload);
    }));

    _unsubs.push(_rpc.on('session.event.task_group.synthesizing', (payload) => {
      if (_dropForeignSessionPayload('event.task_group.synthesizing', payload)) return;
      if (_isStaleEpoch(payload)) return;
      if (!_acceptStreamSeq(payload)) return;
      _noteTaskGroupActive(payload);
    }));

    _unsubs.push(_rpc.on('session.event.task_group.done', (payload) => {
      if (_dropForeignSessionPayload('event.task_group.done', payload)) return;
      if (_isStaleEpoch(payload)) return;
      if (!_acceptStreamSeq(payload)) return;
      _noteTaskGroupTerminal(payload, 'succeeded');
    }));

    _unsubs.push(_rpc.on('session.event.task_group.failed', (payload) => {
      if (_dropForeignSessionPayload('event.task_group.failed', payload)) return;
      if (_isStaleEpoch(payload)) return;
      if (!_acceptStreamSeq(payload)) return;
      _noteTaskGroupTerminal(payload, 'failed');
    }));

    // Wildcard listener for done + error events (tool events handled by dedicated listeners above)
    _unsubs.push(_rpc.on('*', (rawEvent, rawPayload, rawMeta = {}) => {
      const isReplayedFrame = !!(rawMeta && rawMeta.replayed);
      const terminalStatus = _taskTerminalStatus(rawEvent);
      if (terminalStatus) {
        if (!_isCurrentSessionPayload(rawPayload)) return;
        // A stale task's terminal must not flip run-state, end the stream, or
        // drain the pending queue for the turn rendering now (issue 344). The
        // normalized done/error path below is covered by _dropForeignSessionPayload.
        if (_isForeignTaskPayload(rawPayload)) {
          _chatDiag('event.terminal.drop.foreign_task', _chatDiagSummarizePayload(rawPayload));
          return;
        }
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
        if (rawEvent === 'task.succeeded') {
          _scheduleSucceededTaskTerminalSync(rawPayload);
          if (!_isStreaming) _schedulePendingDrainAfterTerminal();
        } else if (!_isStreaming) {
          _recoverPendingAfterTerminal(terminalRunStatus);
        }
      }
      const normalized = _taskTerminalAsSessionEvent(rawEvent, rawPayload);
      // Drop normalized terminal events from epochs we've already left behind
      // (stale residue) and from turns we've already locally finalized
      // (_onStop synchronously calls _endStreaming, so _isStreaming is false
      // by the time the matching task.cancelled arrives).
      if (normalized && _isStaleEpoch(rawPayload)) {
        _chatDiag('event.normalized.drop.stale_epoch', _chatDiagSummarizePayload(rawPayload));
        return;
      }
      if (normalized && !_isStreaming) {
        _chatDiag('event.normalized.drop.not_streaming', _chatDiagSummarizePayload(rawPayload));
        return;
      }
      const event = normalized ? normalized.event : rawEvent;
      const payload = normalized ? normalized.payload : rawPayload;
      if (typeof event !== 'string') return;
      if (event.startsWith('session.event.') && _dropForeignSessionPayload('event.generic', payload)) return;
      // Discard done/error frames that pre-date the current epoch.
      if (event.startsWith('session.event.') && _isStaleEpoch(payload)) {
        _chatDiag('event.generic.drop.stale_epoch', {
          event,
          payload: _chatDiagSummarizePayload(payload),
        });
        return;
      }
      if (!_acceptStreamSeq(payload)) {
        if (_eventHasSpecificSessionHandler(event)) {
          _chatDiag('event.generic.skip.specific_handler_stream_seq', {
            event,
            payload: _chatDiagSummarizePayload(payload),
          });
          return;
        }
        _chatDiag('event.generic.drop.stream_seq', {
          event,
          payload: _chatDiagSummarizePayload(payload),
        });
        return;
      }
      if (event.startsWith('session.event.task_group.')) return;

      if (event === 'sessions.changed') {
        return;
      }

      if (event.endsWith('.done') || event === 'chat.done') {
        _chatDiag('event.done', {
          event,
          payload: _chatDiagSummarizePayload(payload),
        });
        // Done event payload is flat: { text, input_tokens, output_tokens, iterations,
        // routed_tier, routing_source, ... }
        // Also support nested { usage: { ... } } for future compat
        const u = payload?.usage || payload || {};
        const snapshot = u.session_totals;
        if (snapshot && typeof snapshot === 'object') {
          // Authoritative: overwrite from snapshot
          _usageAccum.input = snapshot.input_tokens | 0;
          _usageAccum.output = snapshot.output_tokens | 0;
          _usageAccum.cacheRead = snapshot.cache_read_tokens | 0;
          _usageAccum.cacheWrite = snapshot.cache_write_tokens | 0;
          _usageAccum.cost = Number(snapshot.cost_usd || 0);
        } else if (u.input_tokens || u.output_tokens) {
          // Fallback: legacy accumulation for transcripts without session_totals
          _usageAccum.input += u.input_tokens || 0;
          _usageAccum.output += u.output_tokens || 0;
          _usageAccum.cacheRead += u.cached_tokens || 0;
          _usageAccum.cacheWrite += u.cache_write || 0;
          if (u.cost_usd != null) {
            _usageAccum.cost = (_usageAccum.cost || 0) + u.cost_usd;
          }
        }
        if (u.savings_usd > 0) {
          _usageAccum.sessionSaved = (_usageAccum.sessionSaved || 0) + u.savings_usd;
        }
        if (u.model) _usageModel = u.model;
        _viz.update({ ..._usageAccum, model: _usageModel });
        _saveWidgetState();
        const turnContextStatus = u.contextStatus || u.context_status
          || u.session_totals?.contextStatus || u.session_totals?.context_status || null;
        if (turnContextStatus) {
          _applyContextStatus(turnContextStatus);
        } else {
          _loadCurrentSessionUsage();
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
        // Keep the router strip lifecycle owned by the scan/history paths.
        // _loadHistory no longer preserves strips just because they are live;
        // it only matches persisted strips by turn identity.
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
        _maybeFireSavingsPopup(_finishedBubble, u, { animate: !isReplayedFrame });

        // Attach model + session token footer below the assistant bubble
        _attachTurnMeta(_finishedBubble, _usageModel, u.input_tokens | 0, u.output_tokens | 0, u);
        const _metaIdx = _messages.filter(m => m.role === 'assistant').length - 1;
        if (_metaIdx >= 0) {
          _storeTurnMeta(_sessionKey, _metaIdx, _usageModel, u.input_tokens | 0, u.output_tokens | 0, {
            cached_tokens: u.cached_tokens || 0,
            cache_hit_active: !!u.cache_hit_active,
            model: u.model || _usageModel || null,
            routed_model: u.routed_model || null,
            routed_tier: u.routed_tier || null,
            routing_source: u.routing_source || 'none',
            routing_applied: u.routing_applied !== false,
            rollout_phase: u.rollout_phase || 'full',
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
        if (_doneWasAborted) {
          _applySessionRunState({
            run_status: 'cancelled',
            last_task: { ...(payload || {}), status: 'cancelled' },
          });
        } else if (_activeTaskGroups.size > 0) {
          _applySessionRunState(_activeTaskGroupRunState({ reason: 'task_group_active' }));
        } else {
          _applySessionRunState({ run_status: 'idle', last_task: { status: 'succeeded' } });
        }
      } else if (event.endsWith('.error')) {
        _endStreaming();
        _addMessage('error', _sessionErrorMessage(payload));
        _scheduleHistorySync();
        _recoverPendingAfterTerminal(_normalizeRunStatus(payload?.code || payload?.status || 'failed'));
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
        _applyHelloRunModePolicy(_rpc?.hello);
        _hideThinkingIndicator();
        _subscribeSession();
        _loadCurrentSessionUsage();
        _loadHistory(_historyRefreshScrollOptions());
      }
      if (state === 'disconnected' && _isStreaming) {
        _clearStreamIdleTimer();
        _showThinkingIndicator();
      }
    }));

    _unsubs.push(_rpc.on('_hello', (hello) => {
      _applyRpcPolicy(hello?.policy || {});
      _applyHelloRunModePolicy(hello);
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
  function _maybeFireSavingsPopup(bubble, u, opts = {}) {
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
    if (opts.animate === false) return;

    const hasTier  = !!(u.routed_tier && u.routing_source && u.routing_source !== 'none');
    const turnSavedPct = (typeof u.total_savings_pct === 'number' && u.total_savings_pct > 0)
      ? u.total_savings_pct : 0;
    const hasRoutedSavings = hasTier && turnSavedPct > 0;
    const cacheHit = !!(u.cache_hit_active || (u.cached_tokens || 0) > 0);
    if (!hasRoutedSavings && !cacheHit) return;
    // Cooldown is now per routed-identity (cache hits still bypass). A distinct
    // qualifying turn — e.g. a tool-assisted turn routed differently than a
    // preceding standard turn — is no longer suppressed by an unrelated
    // celebration's global wall.
    const _identityLastTs = identity ? (_savingsPopupTsByIdentity.get(identity) || 0) : _savingsPopupLastTs;
    if (!cacheHit && now - _identityLastTs < _SAVINGS_POPUP_COOLDOWN_MS) return;

    // The burst + "Saved ~X%" label are viewport-centered and need no bubble;
    // only the reduced-motion border pulse uses one (and self-guards null). Fall
    // back to the last assistant bubble so tool-assisted turns (and refresh-only
    // terminal frames) still celebrate even if the stream bubble reference was
    // already cleared. (querySelectorAll + last, since :last-of-type keys off
    // element type, not the .msg.assistant class.)
    let fxBubble = (bubble && bubble.isConnected) ? bubble : null;
    if (!fxBubble && _thread) {
      const _assistants = _thread.querySelectorAll('.msg.assistant');
      fxBubble = _assistants.length ? _assistants[_assistants.length - 1] : null;
    }

    window.SavingsFX.fire(fxBubble, u);
    _savingsPopupLastTs = now;
    if (identity) _savingsPopupTsByIdentity.set(identity, now);
  }

  /* ── Context Usage Warning ──────────────────────────────────────────── */

  function _contextStatusNumber(status, ...names) {
    for (const name of names) {
      const value = Number(status && status[name]);
      if (Number.isFinite(value) && value >= 0) return value;
    }
    return null;
  }

  function _applyContextStatus(status) {
    _contextStatus = status || null;
    _updateCtxWarning();
  }

  function _clearContextStatus() {
    _contextStatus = null;
    _updateCtxWarning();
  }

  function _updateCtxWarning() {
    if (!_ctxWarn) return;
    const status = _contextStatus || {};
    const tokens = _contextStatusNumber(status, 'contextTokens', 'context_tokens');
    const windowTokens = _contextStatusNumber(status, 'contextWindowTokens', 'context_window_tokens');
    let pressure = _contextStatusNumber(status, 'pressure', 'contextPressure', 'context_pressure');
    if (pressure == null && tokens != null && windowTokens > 0) pressure = tokens / windowTokens;
    if (pressure != null) pressure = Math.min(1, Math.max(0, pressure));
    if (tokens == null || !windowTokens || pressure == null || pressure < 0.85) {
      _ctxWarn.classList.add('hidden');
      return;
    }
    _ctxWarn.classList.remove('hidden');
    _ctxWarn.textContent = `Request ctx ${Math.round(pressure * 100)}% (~${Math.round(tokens / 1000)}k/${Math.round(windowTokens / 1000)}k)`;
  }

  /* ── Chat History ───────────────────────────────────────────────────── */

  function _historyRefreshScrollOptions() {
    if (!_thread || !_historyHasRendered) return {};
    const gap = _thread.scrollHeight - _thread.scrollTop - _thread.clientHeight;
    if (gap < 60) return {};
    return {
      preserveScroll: true,
      previousScrollHeight: _thread.scrollHeight,
      previousScrollTop: _thread.scrollTop,
    };
  }

  function _replayGapShouldWarn(reason) {
    const value = String(reason || '').toLowerCase();
    return !['stream_buffer_empty', 'stream_buffer_reset', 'cursor_ahead_of_stream'].includes(value);
  }

  function _scheduleHistorySync() {
    if (_historySyncTimer) clearTimeout(_historySyncTimer);
    _historySyncTimer = setTimeout(() => {
      _historySyncTimer = null;
      _loadHistory(_historyRefreshScrollOptions());
    }, 50);
  }

  function _resetHistoryPagingState() {
    _historyLoadedMessages = [];
    _historyOldestCursor = null;
    _historyNewestCursor = null;
    _historyHasMore = false;
    _historyScope = 'complete';
    _historyLoadingEarlier = false;
    _historyHydrating = false;
    _historyHasRendered = false;
    _historyError = '';
    _historyCompactionSummaries = [];
    _historyRequestSeq++;
    _removeHistoryScopeRows();
    _clearCompactionSummarySeparators();
  }

  function _historyResponseMetadata(data) {
    return {
      hasMore: !!(data && data.has_more),
      oldestCursor: data ? (data.oldest_cursor || null) : null,
      newestCursor: data ? (data.newest_cursor || null) : null,
      scope: data ? (data.history_scope || 'complete') : 'complete',
      summaries: Array.isArray(data && data.compaction_summaries)
        ? data.compaction_summaries
        : [],
    };
  }

  function _applyHistoryMetadata(data) {
    const meta = _historyResponseMetadata(data);
    _historyOldestCursor = meta.oldestCursor;
    _historyNewestCursor = meta.newestCursor;
    _historyHasMore = meta.hasMore;
    _historyScope = meta.scope;
    _historyCompactionSummaries = meta.summaries;
  }

  function _messagePageIdentity(msg) {
    if (!msg) return '';
    const stable = msg.message_id || msg.id || '';
    if (stable) return `stable:${stable}`;
    return `fallback:${_historyFallbackMessageIdentity(msg.role, msg.text || '')}`;
  }

  function _mergeHistoryMessagePages(olderMessages, currentMessages) {
    const seen = new Set();
    const merged = [];
    (olderMessages || []).concat(currentMessages || []).forEach((msg) => {
      const identity = _messagePageIdentity(msg);
      if (identity && seen.has(identity)) return;
      if (identity) seen.add(identity);
      merged.push(msg);
    });
    return merged;
  }

  function _removeHistoryScopeRows() {
    if (!_thread) return;
    _thread.querySelectorAll('.chat-history-scope').forEach((el) => el.remove());
  }

  function _renderHistoryScopeRow() {
    if (!_thread) return;
    _removeHistoryScopeRows();
    if (_messages.length === 0 && !_historyError) return;

    let tone = '';
    let message = '';
    let detail = '';
    let showLoadEarlier = false;
    let showRetry = false;

    if (_historyLoadingEarlier) {
      tone = 'loading';
      message = 'Loading earlier messages...';
    } else if (_historyError) {
      tone = 'error';
      message = _historyError;
      showRetry = true;
    } else if (_historyHasMore || _historyScope === 'latest_window') {
      tone = 'partial';
      message = `Showing latest ${_historyLoadedMessages.length} messages.`;
      detail = 'Older history is available.';
      showLoadEarlier = !!_historyOldestCursor;
    } else if (_historyScope === 'compacted' || _historyCompactionSummaries.length > 0) {
      tone = 'compacted';
      message = 'Older context was compacted for the model.';
      detail = 'Export the session for exact text.';
    } else {
      return;
    }

    const row = document.createElement('div');
    row.className = `chat-history-scope chat-history-scope--${tone}`;
    row.setAttribute('role', tone === 'loading' ? 'status' : 'note');
    if (tone === 'loading') row.setAttribute('aria-busy', 'true');
    row.innerHTML = ''
      + `<span class="chat-history-scope__text">${_esc(message)}</span>`
      + (detail ? `<span class="chat-history-scope__detail">${_esc(detail)}</span>` : '')
      + '<span class="chat-history-scope__actions"></span>';
    const actions = row.querySelector('.chat-history-scope__actions');
    if (actions && showLoadEarlier) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn--sm btn--ghost';
      btn.textContent = 'Load earlier';
      btn.disabled = _historyLoadingEarlier;
      btn.addEventListener('click', () => _loadEarlierHistory());
      actions.appendChild(btn);
    }
    if (actions && showRetry) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn--sm btn--ghost';
      btn.textContent = _historyHasMore && _historyOldestCursor ? 'Retry' : 'Retry history';
      btn.addEventListener('click', () => {
        if (_historyHasMore && _historyOldestCursor) {
          _loadEarlierHistory();
        } else {
          _loadHistory();
        }
      });
      actions.appendChild(btn);
    }
    _thread.insertBefore(row, _thread.firstChild || null);
  }

  async function _loadHistory(opts = {}) {
    if (!_sessionKey || !_thread) return;
    const requestSessionKey = _sessionKey;
    const requestSeq = ++_historyRequestSeq;
    _historyHydrating = true;
    _historyError = '';
    _chatDiag('history.start', {
      sessionKey: requestSessionKey,
      streaming: _isStreaming,
      hasStreamBubble: !!_streamBubble,
    });
    try {
      await _rpc.waitForConnection();
      // Wait until router config (tier → model cache) is populated so
      // historical strips never render with "c1"/"c2"/"c3" placeholders
      // just because we raced the config.get response.
      await _routerFxAwaitConfig();
      const data = await _rpc.call('chat.history', {
        sessionKey: requestSessionKey,
        limit: CHAT_HISTORY_PAGE_SIZE,
        includeCanonical: false,
        includeSummaries: true,
      });
      if (requestSessionKey !== _sessionKey || requestSeq !== _historyRequestSeq) {
        _chatDiag('history.stale_response.drop', { requestSessionKey, requestSeq });
        return;
      }
      const messages = data.messages || [];
      _historyLoadedMessages = messages.slice();
      _applyHistoryMetadata(data || {});
      _chatDiag('history.loaded', {
        count: messages.length,
        rolesTail: messages.slice(-8).map((msg) => msg && msg.role).filter(Boolean),
        streaming: _isStreaming,
        hasStreamBubble: !!_streamBubble,
        hasMore: _historyHasMore,
        historyScope: _historyScope,
      });
      _historyHydrating = false;
      _renderHistoryMessages(messages, opts);
    } catch (err) {
      if (requestSessionKey === _sessionKey && requestSeq === _historyRequestSeq) {
        _historyHydrating = false;
      }
      _historyError = 'Could not load chat history.';
      _chatDiag('history.error', {
        message: err && err.message ? err.message : String(err),
      });
      _renderHistoryScopeRow();
    }
  }

  async function _loadEarlierHistory() {
    if (!_sessionKey || !_thread || !_historyOldestCursor || _historyLoadingEarlier) return;
    const requestSessionKey = _sessionKey;
    const requestSeq = ++_historyRequestSeq;
    const previousScrollHeight = _thread.scrollHeight;
    const previousScrollTop = _thread.scrollTop;
    _historyLoadingEarlier = true;
    _historyError = '';
    _renderHistoryScopeRow();
    _chatDiag('history.load_earlier.start', {
      sessionKey: requestSessionKey,
      before: _historyOldestCursor,
    });
    try {
      await _rpc.waitForConnection();
      const data = await _rpc.call('chat.history', {
        sessionKey: requestSessionKey,
        limit: CHAT_HISTORY_PAGE_SIZE,
        before: _historyOldestCursor,
        includeCanonical: false,
        includeSummaries: true,
      });
      if (requestSessionKey !== _sessionKey || requestSeq !== _historyRequestSeq) {
        _chatDiag('history.load_earlier.stale_response.drop', { requestSessionKey, requestSeq });
        if (requestSessionKey === _sessionKey) {
          _historyLoadingEarlier = false;
          _renderHistoryScopeRow();
        }
        return;
      }
      const olderMessages = data.messages || [];
      _historyLoadedMessages = _mergeHistoryMessagePages(olderMessages, _historyLoadedMessages);
      _applyHistoryMetadata({
        ...(data || {}),
        messages: _historyLoadedMessages,
        newest_cursor: _historyNewestCursor || (data && data.newest_cursor),
      });
      _historyLoadingEarlier = false;
      _chatDiag('history.load_earlier.loaded', {
        count: olderMessages.length,
        totalLoaded: _historyLoadedMessages.length,
        hasMore: _historyHasMore,
      });
      _renderHistoryMessages(_historyLoadedMessages, {
        preserveScroll: true,
        previousScrollHeight,
        previousScrollTop,
      });
    } catch (err) {
      _historyLoadingEarlier = false;
      _historyError = 'Could not load earlier history.';
      _chatDiag('history.load_earlier.error', {
        message: err && err.message ? err.message : String(err),
      });
      _renderHistoryScopeRow();
    }
  }

  function _renderHistoryMessages(messages, opts = {}) {
    if (!_thread) return;
    _clearMessageActionFocus('history_rebuild');
    _removeHistoryScopeRows();
    if (messages.length === 0) {
      const liveRouterStrips = _currentSessionLiveRouterStrips(_sessionKey || '');
      const liveUserAnchor = _currentSessionLiveUserAnchor(_sessionKey || '');
      const liveThinking = _isCurrentSessionThinkingIndicator(_thinkingEl) ? _thinkingEl : null;
      if (_isStreaming && (
        _isCurrentSessionStreamBubble(_streamBubble)
        || liveRouterStrips.length > 0
        || liveUserAnchor
        || liveThinking
      )) {
        _thread.querySelectorAll('.msg').forEach((el) => {
          if (el !== _streamBubble && el !== liveUserAnchor && el !== liveThinking) el.remove();
        });
        _thread.querySelectorAll('.chat-day-sep, .chat-empty').forEach((el) => el.remove());
        if (liveUserAnchor && !liveUserAnchor.isConnected) _thread.appendChild(liveUserAnchor);
        if (_streamBubble && !_streamBubble.isConnected) _thread.appendChild(_streamBubble);
        if (liveThinking && !liveThinking.isConnected) _thread.appendChild(liveThinking);
        liveRouterStrips.forEach((el) => {
          if (!el.isConnected) _insertLiveRouterStripForAnchor(el, liveUserAnchor, _streamBubble);
        });
        _scrollToBottom();
        _chatDiag('history.empty.keep_live_stream_view', {
          hasStreamBubble: !!_streamBubble,
          hasLiveUserAnchor: !!liveUserAnchor,
          liveRouterCount: liveRouterStrips.length,
        });
        return;
      }
      if (_pendingFinalizedAssistantBubble && _pendingFinalizedAssistantBubble.isConnected) {
        _scrollToBottom();
        _chatDiag('history.empty.keep_pending_finalized_assistant', {
          bubble: _chatDiagDescribeElement(_pendingFinalizedAssistantBubble),
        });
        return;
      }
      _thread.innerHTML = '';
      _messages = [];
      _lastHeaderRole = '';
      _lastHeaderDay = '';
      if (window.SavingsFX) window.SavingsFX.resetStreak();
      _lastSavingsPopupIdentity = '';
      _thread.innerHTML = _emptyStateHTML();
      _historyHasRendered = true;
      _chatDiag('history.empty.rendered_empty_state', {});
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
    // Drop every stale router strip that is not already associated with this
    // session/turn. Reorder repair below keeps attached strips in place.
    _thread.querySelectorAll('.router-fx').forEach((el) => {
      if (el.dataset.sessionKey === (_sessionKey || '') && el.dataset.turnIndex) return;
      _routerFxRemoveStrip(el);
    });
    _messages = [];
    _lastHeaderRole = '';
    _lastHeaderDay = '';
    if (window.SavingsFX) window.SavingsFX.resetStreak();
    let historySavingsIdentity = '';
    let _histAsstIdx = 0;
    // 1-indexed running count of user messages seen so far during
    // this rebuild. The router strip's localStorage seed cache is
    // keyed by (sessionKey, userMsgIndex, tier); using this counter
    // means live + history rebuilds for the same turn reuse the same layout.
    let _histUserIdx = 0;
    let _histLastUserRequestKind = 'text';
    const consumedHistoryElements = new Set();
    messages.forEach((msg) => {
        if (msg.role === 'user') {
          _histUserIdx++;
          _histLastUserRequestKind = _routerFxRequestKindFromAttachments(msg.attachments || []);
        }
        const rawText = msg.text || '';
        const displayText = msg.role === 'user' ? _stripTimePrefix(rawText) : rawText;
        const stableIdentity = _historyStableMessageIdentity(msg);
        const fallbackIdentity = _historyFallbackMessageIdentity(msg.role, displayText);
        const msgOptions = {
          timestamp: msg.timestamp || msg.ts || null,
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
        _stampHistoryElement(div, stableIdentity, msg.role, displayText, _messageTranscriptId(msg));
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
          const m = _historyTurnMeta(msg) || _recallTurnMeta(_sessionKey, _histAsstIdx);
          _histAsstIdx++;
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
              const routerPanel = _routerFxPanelDataset(_routerFx.visualMode);
              // Place a pre-settled router slider directly beneath the
              // user message that triggered this turn — never above
              // it, never with anything wedged in between.
              //
              // Reuse a persisted strip already sitting in that slot instead of
              // rebuilding, so the user doesn't see the cell order shift after
              // the hammer locked.
              //
              // Otherwise build a fresh one, seeded off the
              // assistant message's stable timestamp so the layout
              // reproduces deterministically across page refreshes.
              const userMsg = _routerFxUserMessageForAssistant(div);
              const routerIdentity = _routerFxUsageIdentity(savedUsage);
              // The message-reorder pass above (_appendHistoryElementInOrder)
              // moves user .msg elements together with their attached router
              // strip. Match this turn's remaining strip(s) by (session, turn
              // index) instead of using a separate live-strip preservation path:
              // keep the one whose routing identity matches, drop any extras
              // accumulated across earlier syncs, and let the positional
              // backstop catch anything that is still detached.
              if (userMsg && userMsg.parentNode === _thread) {
                const ownStrips = Array.from(_thread.querySelectorAll('.router-fx')).filter(
                  (el) => el.dataset.sessionKey === (_sessionKey || '')
                    && el.dataset.turnIndex === String(_histUserIdx)
                    && _routerFxPanelDataset(el.dataset.panel) === routerPanel,
                );
                const keep = ownStrips.find((el) => el.dataset.routerIdentity === routerIdentity)
                  || null;
                ownStrips.forEach((el) => { if (el !== keep) _routerFxRemoveStrip(el); });
                if (keep) {
                  if (userMsg.nextSibling !== keep) {
                    _thread.insertBefore(keep, userMsg.nextSibling);
                    _chatDiag('history.reanchor_identity_strip', {
                      user: _chatDiagDescribeElement(userMsg),
                      strip: _chatDiagDescribeElement(keep),
                      routerIdentity,
                    });
                  }
                  _routerFxNormalizeSettledStrip(keep, 'history', savedUsage);
                }
              }
              const placed = userMsg && userMsg.nextSibling;
              const existingStrip = (placed && placed.classList
                  && placed.classList.contains('router-fx')) ? placed : null;
              const alreadyInPlace = existingStrip
                && existingStrip.dataset.routerIdentity === routerIdentity
                && _routerFxPanelDataset(existingStrip.dataset.panel) === routerPanel;
              if (!alreadyInPlace) {
                if (existingStrip) _routerFxRemoveStrip(existingStrip);
                const hint = msg.timestamp || msg.ts || msg.message_id || '';
                const cachedSeed = _routerFxResolveLayoutSeed(_sessionKey, hint);
                const routerStrip = _buildRouterFxFromUsage(savedUsage, cachedSeed, {
                  requestKind: _histLastUserRequestKind,
                });
                if (routerStrip) {
                  routerStrip.dataset.sessionKey = _sessionKey || '';
                  routerStrip.dataset.turnIndex = String(_histUserIdx);
                  _routerFxInsertAnchored(routerStrip, div);
                }
              }
            } else if (window.SavingsFX) {
              window.SavingsFX.noteTurn(null);
            }
            _attachTurnMeta(div, m.model, m.input, m.output, savedUsage || undefined);
          } else if (window.SavingsFX) {
            window.SavingsFX.noteTurn(null);
          }
        }
      });
      _historyHasRendered = true;
      _flushPendingRouterDecisions();
      const liveUserAnchor = _currentSessionLiveUserAnchor(_sessionKey || '');
      _thread.querySelectorAll('.msg').forEach((el) => {
        if (_isStreaming && _isCurrentSessionStreamBubble(el)) return;
        if (_isStreaming && _isCurrentSessionThinkingIndicator(el)) return;
        if (_isStreaming && el === liveUserAnchor) return;
        if (_isPendingFinalizedAssistantBubble(el) && _historyStillWaitingForAssistant(messages)) return;
        if (!consumedHistoryElements.has(el)) el.remove();
      });
      _thread.querySelectorAll('.router-fx').forEach((el) => {
        const turnIndex = el.dataset.turnIndex || '';
        if (el.dataset.sessionKey === (_sessionKey || '') && turnIndex) return;
        _routerFxRemoveStrip(el);
      });
      // Orphan backstop: outside an active stream every kept strip must sit
      // immediately beneath its user message; drop any that do not so a stranded
      // grid can never linger at the top of the thread.
      if (!_isStreaming) {
        _thread.querySelectorAll('.router-fx').forEach((el) => {
          const prev = el.previousElementSibling;
          const anchored = !!prev && !!prev.classList && prev.classList.contains('msg')
            && (prev.classList.contains('user')
              || prev.getAttribute('data-history-role') === 'user');
          if (!anchored) _routerFxRemoveStrip(el);
        });
      }
      // User-pref disabled-sweep: the viewer has hidden the router-fx
      // visualisation. New strips are already gated off above; this drops any
      // strip left from before the toggle flipped.
      if (!_routerFx.enabled) {
        _thread.querySelectorAll('.router-fx').forEach((el) => _routerFxRemoveStrip(el));
      }
      if (_pendingFinalizedAssistantBubble
          && (consumedHistoryElements.has(_pendingFinalizedAssistantBubble)
            || !_pendingFinalizedAssistantBubble.isConnected
            || !_historyStillWaitingForAssistant(messages))) {
        _clearPendingFinalizedAssistantBubble();
      }
	      _lastSavingsPopupIdentity = historySavingsIdentity;
	      _renderHistoryScopeRow();
	      _renderCompactionSummarySeparators(messages);
	      if (opts.preserveScroll) {
	        const oldHeight = Number(opts.previousScrollHeight || 0);
	        const oldTop = Number(opts.previousScrollTop || 0);
	        _thread.scrollTop = Math.max(0, _thread.scrollHeight - oldHeight + oldTop);
	      } else {
	        _scrollToBottom();
	      }
	      _chatDiag('history.done', {
	        count: messages.length,
	        consumed: consumedHistoryElements.size,
	        streaming: _isStreaming,
	        hasStreamBubble: !!_streamBubble,
	        hasMore: _historyHasMore,
	        historyScope: _historyScope,
	      });
	  }

  function _historyLiveTailAnchor() {
    if (!_isStreaming) return null;
    if (_isCurrentSessionStreamBubble(_streamBubble)) return _streamBubble;
    if (_isCurrentSessionThinkingIndicator(_thinkingEl)) return _thinkingEl;
    return null;
  }

  function _appendHistoryDaySeparator(timestamp) {
    const day = _dayKey(timestamp);
    if (!day || day === _lastHeaderDay) return;
    const sep = document.createElement('div');
    sep.className = 'chat-day-sep';
    sep.innerHTML = `<span>${_dayLabel(day)}</span>`;
    const liveTail = _historyLiveTailAnchor();
    if (liveTail) {
      _thread.insertBefore(sep, liveTail);
    } else {
      _thread.appendChild(sep);
    }
    _lastHeaderDay = day;
    _lastHeaderRole = '';
  }

  function _appendHistoryElementInOrder(div) {
    if (!div) return;
    // History rebuilds reuse and move .msg nodes. If the user message already
    // owns a live router strip, move that strip with the user message as one
    // turn unit; otherwise the DOM reorder can strand the strip above the user
    // while output is streaming.
    const attachedRouterStrip = _routerFxStripImmediatelyAfterUser(div);
    const liveTail = _historyLiveTailAnchor();
    if (liveTail && div !== liveTail) {
      _thread.insertBefore(div, liveTail);
      _restoreRouterFxAfterHistoryUser(div, attachedRouterStrip);
      return;
    }
    _thread.appendChild(div);
    _restoreRouterFxAfterHistoryUser(div, attachedRouterStrip);
  }

  function _routerFxStripImmediatelyAfterUser(div) {
    if (!div || !div.classList) return null;
    const isUser = div.classList.contains('user')
      || div.getAttribute('data-history-role') === 'user';
    if (!isUser) return null;
    const next = div.nextElementSibling;
    return (next && next.classList && next.classList.contains('router-fx')) ? next : null;
  }

  function _restoreRouterFxAfterHistoryUser(div, routerStrip) {
    if (!div || !routerStrip || routerStrip.parentNode !== _thread) return;
    if (routerStrip.previousElementSibling === div) return;
    _thread.insertBefore(routerStrip, div.nextSibling);
    _chatDiag('history.move_attached_router_strip', {
      user: _chatDiagDescribeElement(div),
      strip: _chatDiagDescribeElement(routerStrip),
    });
  }

  function _historyStableMessageIdentity(msg) {
    const stableId = msg.message_id || msg.id || '';
    return stableId ? String(stableId) : '';
  }

  function _historyFallbackMessageIdentity(role, text) {
    return `${role || ''}|${_historyFallbackText(role, text)}`;
  }

  function _historyFallbackText(role, text) {
    if (role === 'assistant') return _stripProtocolTextLeak(_stripDirectiveTags(_stripGeneratedArtifactMarkers(text || ''))).trim();
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

  function _markPendingFinalizedAssistantBubble(bubble, text) {
    if (!bubble || !text) return;
    _pendingFinalizedAssistantBubble = bubble;
    _pendingFinalizedAssistantFallbackId = _historyFallbackMessageIdentity('assistant', text);
    bubble.dataset.pendingFinalizedAssistant = 'true';
    bubble.dataset.pendingFinalizedSessionKey = _sessionKey || '';
    bubble.dataset.pendingFinalizedFallbackId = _pendingFinalizedAssistantFallbackId;
    _chatDiag('stream.end.pending_finalized_assistant', {
      fallbackId: _pendingFinalizedAssistantFallbackId,
      bubble: _chatDiagDescribeElement(bubble),
    });
  }

  function _clearPendingFinalizedAssistantBubble() {
    if (_pendingFinalizedAssistantBubble) {
      delete _pendingFinalizedAssistantBubble.dataset.pendingFinalizedAssistant;
      delete _pendingFinalizedAssistantBubble.dataset.pendingFinalizedSessionKey;
      delete _pendingFinalizedAssistantBubble.dataset.pendingFinalizedFallbackId;
    }
    _pendingFinalizedAssistantBubble = null;
    _pendingFinalizedAssistantFallbackId = '';
  }

  function _isPendingFinalizedAssistantBubble(el) {
    return !!el
      && el === _pendingFinalizedAssistantBubble
      && el.dataset.pendingFinalizedAssistant === 'true'
      && el.dataset.pendingFinalizedSessionKey === (_sessionKey || '');
  }

  function _isCurrentSessionStreamBubble(el) {
    if (!el || el !== _streamBubble) return false;
    const currentKey = _sessionKey || '';
    const streamKey = _streamSessionKey || el.dataset.streamSessionKey || '';
    return !!currentKey
      && streamKey === currentKey
      && (!el.dataset.streamSessionKey || el.dataset.streamSessionKey === currentKey);
  }

  function _isCurrentSessionThinkingIndicator(el) {
    if (!el || el !== _thinkingEl) return false;
    const currentKey = _streamSessionKey || _sessionKey || '';
    if (!currentKey) return false;
    const thinkingKey = el.dataset ? (el.dataset.sessionKey || currentKey) : currentKey;
    return thinkingKey === currentKey;
  }

  function _historyStillWaitingForAssistant(messages) {
    if (!Array.isArray(messages) || messages.length === 0) return true;
    const last = messages[messages.length - 1] || {};
    return last.role !== 'assistant';
  }

  function _currentSessionLiveRouterStrips(key = _sessionKey || '') {
    if (!_thread || !key) return [];
    return Array.from(_thread.querySelectorAll('.router-fx')).filter((el) => (
      el.dataset.sessionKey === key
      && (el.dataset.live === 'true' || el.dataset.scanning === 'true')
    ));
  }

  function _isUserMessageElement(el) {
    return !!el && !!el.classList && (
      el.classList.contains('user')
      || el.getAttribute('data-history-role') === 'user'
    );
  }

  function _currentSessionLiveUserAnchor(key = _sessionKey || '') {
    if (!_thread || !key) return null;
    const routerStrips = _currentSessionLiveRouterStrips(key);
    for (const strip of routerStrips) {
      const prev = strip.previousElementSibling;
      if (_isUserMessageElement(prev)) return prev;
    }
    if (_isCurrentSessionStreamBubble(_streamBubble)) {
      const streamAnchor = _routerFxUserMessageForAssistant(_streamBubble);
      if (streamAnchor) return streamAnchor;
    }
    return _isStreaming ? _routerFxLastUserMessage() : null;
  }

  function _insertLiveRouterStripForAnchor(strip, userAnchor, streamBubble) {
    if (!_thread || !strip) return;
    if (userAnchor && userAnchor.parentNode === _thread) {
      _thread.insertBefore(strip, userAnchor.nextSibling);
      return;
    }
    if (streamBubble && streamBubble.parentNode === _thread) {
      _thread.insertBefore(strip, streamBubble);
      return;
    }
    _thread.appendChild(strip);
  }

  function _stampHistoryElement(div, stableIdentity, role, text, transcriptId = null) {
    if (stableIdentity) div.setAttribute('data-message-id', stableIdentity);
    div.setAttribute('data-history-role', role || '');
    div.setAttribute('data-history-raw-text', text || '');
    div.setAttribute('data-history-fallback-id', _historyFallbackMessageIdentity(role, text));
    if (transcriptId != null) {
      div.dataset.transcriptId = String(transcriptId);
    } else {
      delete div.dataset.transcriptId;
    }
  }

  function _syncMessageHeader(div, displayRole, timestamp, options = {}) {
    if (!div) return;
    const day = _dayKey(timestamp);
    const collapsible = (displayRole === 'user' || displayRole === 'assistant');
    const sameGroup = collapsible
      && (displayRole === _lastHeaderRole)
      && day === _lastHeaderDay
      && day !== '';
    if (collapsible) _lastHeaderRole = displayRole;
    const existing = div.querySelector(':scope > .msg-header');
    const isoStr = timestamp
      ? (typeof timestamp === 'string' ? timestamp : new Date(timestamp).toISOString())
      : '';
    if (sameGroup) {
      if (existing) existing.remove();
      if (isoStr) div.title = new Date(isoStr).toLocaleString();
      return;
    }
    const header = existing || document.createElement('div');
    header.className = 'msg-header';
    if (isoStr) {
      header.title = new Date(isoStr).toLocaleString();
      div.removeAttribute('title');
    }
    header.innerHTML = `<span class="role-label">${_esc(_displayRoleLabel(displayRole))}</span>${_renderMessageTags(options)}<span class="msg-time">${_esc(timestamp ? _relTime(timestamp) : '')}</span>`;
    if (!existing) div.insertBefore(header, div.firstChild);
  }

  function _replaceHistoryMessage(div, role, text, options = {}) {
    const isSubagentCompletion = _isSubagentCompletionMessage(role, text, options);
    const displayRole = isSubagentCompletion ? 'subagent' : role;
    div.className = `msg ${displayRole}`;
    _syncMessageHeader(div, displayRole, options.timestamp || null, options);
    const body = div.querySelector('.msg-body');
    if (body) {
      _renderMessageBody(body, role, text, options);
    }
    _attachHoverActions(div, displayRole);
  }

  function _replaceStreamText(finalText) {
    if (!_isStreaming) _startStreaming();
    _ensureStreamBubble();
    _markVisibleStreamEvent('text_delta');
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

  function _metaPreflightFallbackMessage(detail) {
    const interpreted = (detail && detail.interpretedRequest) || '';
    const runId = (detail && detail.runId) || '';
    const lines = [
      interpreted,
      '',
      '<!-- opensquilla:meta_preflight_confirmed=1 -->',
    ];
    if (runId) lines.push(`<!-- opensquilla:meta_preflight_run_id=${runId} -->`);
    return lines.join('\n');
  }

  function _metaPreflightDisplayText(detail) {
    const interpreted = detail && typeof detail.interpretedRequest === 'string'
      ? detail.interpretedRequest.trim()
      : '';
    return interpreted || '已确认，开始运行。';
  }

  function _sendHiddenMetaPreflightConfirmation(confirmed, detail) {
    _sendTextOverride = confirmed && confirmed.message
      ? confirmed.message
      : _metaPreflightFallbackMessage(detail);
    _sendDisplayTextOverride = _metaPreflightDisplayText(detail);
    _onSend();
  }

  async function _onSend() {
    const textOverride = _sendTextOverride;
    const displayTextOverride = _sendDisplayTextOverride;
    _sendTextOverride = null;
    _sendDisplayTextOverride = null;
    let text = (textOverride !== null ? textOverride : _textarea.value).trim();
    let attachmentsForSend = textOverride !== null ? [] : _pendingAttachments;
    const sessionIntentForSend = textOverride !== null ? null : _pendingSessionIntent;
    let hasPayload = text || attachmentsForSend.length > 0;
    let isLiteralSlash = false;

    if (textOverride === null && _hasPendingAttachmentWork()) {
      UI.toast('Wait for file attachment processing to finish', 'warn', 2500);
      return;
    }

    if (text.startsWith('//')) {
      isLiteralSlash = true;
      text = text.slice(1);
      hasPayload = text || attachmentsForSend.length > 0;
    }
    const isSlashCommand = !isLiteralSlash && text.startsWith('/')
      && !!(await _lookupSlashCommand(text));
    const normalized = await _normalizeOutgoingComposerPayload(
      text,
      attachmentsForSend,
      { allowSlashCommand: isSlashCommand },
    );
    if (!normalized) return;
    text = normalized.text;
    attachmentsForSend = normalized.attachments;

    // While a turn is streaming, Send enqueues. Use ESC or the
    // Stop button to actually halt the current response. Manual compaction uses
    // the same queue: users may keep typing, but the next turn must wait until
    // the transcript maintenance action reaches a terminal state.
    if (_isStreaming || _isCompactInFlightForCurrentSession()) {
      if (isSlashCommand) {
        const waitReason = _isCompactInFlightForCurrentSession()
          ? 'context compaction'
          : 'the current response';
        UI.toast(`Wait for ${waitReason} before running ${text.split(/\s+/, 1)[0]}.`, 'warn', 2500);
        return;
      }
      if (!hasPayload) return; // empty + busy = no-op
      _enqueuePendingInput(
        text,
        _isCompactInFlightForCurrentSession()
          ? 'Message queued until compaction finishes'
          : null,
        _isCompactInFlightForCurrentSession()
          ? 'context compaction'
          : 'the current response',
        attachmentsForSend,
        displayTextOverride,
        sessionIntentForSend,
        textOverride !== null,
      );
      return;
    }

    if (!isLiteralSlash && text.startsWith('/')) {
      const handled = await _executeSlashCommand(text);
      if (handled) return;
    }

    if (!hasPayload || !_sessionKey) return;

    // Reset abort flag for new message
    _aborted = false;

    // Close slash menu if open
    _closeSlashMenu();

    // Record message for export
    const now = new Date().toISOString();
    const userText = displayTextOverride !== null ? displayTextOverride : text;
    const providerText = text || 'Describe these attachments';
    _messages.push({ role: 'user', text: userText, ts: now });

    // Show user message
    const userDiv = _addMessage('user', '', now);
    _stampHistoryElement(userDiv, '', 'user', userText);
    const userBody = userDiv.querySelector('.msg-body');
    let userHtml = _esc(userText);
    if (attachmentsForSend.length > 0) {
      userBody.classList.add('msg-body--has-attachments');
      userHtml = userText ? `<div class="msg-attachment-text">${_esc(userText)}</div>` : '';
      userHtml += '<div class="msg-attachments">';
      attachmentsForSend.forEach((a) => { userHtml += _renderMessageAttachmentHtml(a); });
      userHtml += '</div>';
    }
    userBody.innerHTML = userHtml;
    // Restore the hover toolbar that _addMessage attached — the innerHTML
    // write above wiped it (same pattern as the history-render path).
    _attachHoverActions(userDiv, 'user');

    // Build RPC params
    const params = { message: providerText, sessionKey: _sessionKey };
    const sendRunMode = _clampRunMode(_runMode);
    _runMode = sendRunMode;
    _toolbarState.runMode = sendRunMode;
    params._source = {};
    params._source.runMode = sendRunMode;
    if (sessionIntentForSend) {
      params.intent = sessionIntentForSend;
      if (textOverride === null) _pendingSessionIntent = null;
    }
    if (userText !== providerText || attachmentsForSend.length > 0) {
      params.displayText = userText;
    }
    if (attachmentsForSend.length > 0) {
      params.attachments = attachmentsForSend.map((a) => {
        if (a.kind === 'staged') {
          return { type: a.mime, file_uuid: a.file_uuid, mime: a.mime, name: a.name };
        }
        return { type: a.mime || 'image/png', data: a.data, mime: a.mime, name: a.name };
      });
    }
    const normalizationProvenance = _inputNormalizationProvenanceFromAttachments(attachmentsForSend);
    if (normalizationProvenance) params.inputProvenance = normalizationProvenance;
    const routerFxRequestKind = _routerFxRequestKindFromAttachments(params.attachments || []);

    // Clear input and attachments
    if (textOverride === null) {
      _textarea.value = '';
      _autoResizeTextarea();
      _pendingAttachments = [];
      _renderAttachmentPreview();
    }

    // Start streaming UI. Delay the routing scan briefly so request-time
    // compaction can claim the turn without a competing one-frame router flash.
    _startStreaming();
    const routerScanStarted = _scheduleRouterFxBeginScan(userDiv, _routerFxResolveLayoutSeed(_sessionKey), {
      requestKind: routerFxRequestKind,
    });
    _chatDiag('send.start', {
      textLen: providerText.length,
      attachments: params.attachments ? params.attachments.length : 0,
      routerScanStarted,
      routerFxEnabled: !!_routerFx.enabled,
      routerFeatureEnabled: !!_routerFeatureEnabled,
      user: _chatDiagDescribeElement(userDiv),
    });
    _showThinkingIndicator();

    // Send
    _rpc.call('chat.send', params).then((res) => {
      _chatDiag('send.rpc.resolved', {
        responseSessionKey: res && res.sessionKey ? res.sessionKey : '',
      });
      if (res && res.sessionKey && res.sessionKey !== _sessionKey) _persistSession(res.sessionKey);
    }).catch((err) => {
      _chatDiag('send.rpc.error', {
        message: err && err.message ? err.message : String(err),
      });
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
    const nextPaused = !!paused;
    const changed = _approvalPendingForCurrentSession !== nextPaused;
    _streamIdlePausedForApproval = nextPaused;
    _approvalPendingForCurrentSession = nextPaused;
    if (_streamIdlePausedForApproval) {
      _clearStreamIdleTimer();
      if (changed || _isStreaming) {
        _applySessionRunState({
          run_status: 'approval_pending',
          active_task: { status: 'approval_pending', terminal_reason: 'tool_approval' },
        });
      }
    } else if (_isStreaming) {
      _applySessionRunState({ run_status: 'running', active_task: { status: 'running' } });
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

  function _scheduleSucceededTaskTerminalSync(payload = {}) {
    const streamGeneration = _streamGeneration;
    setTimeout(() => {
      if (!_isCurrentSessionPayload(payload) || _isStaleEpoch(payload)) return;
      _scheduleHistorySync();
      if (_isStreaming && _streamGeneration === streamGeneration) {
        _endStreaming();
        _schedulePendingDrainAfterTerminal();
      }
    }, 75);
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
      const failedDetail = _payloadErrorDetail(payload);
      if (failedDetail) return failedDetail;
      return 'The task failed before it could finish.';
    }
    return 'The task ended before it could finish.';
  }

  function _payloadErrorDetail(payload) {
    const candidates = [
      payload?.error,
      payload?.message,
      payload?.error_message,
      payload?.detail,
    ];
    for (const candidate of candidates) {
      if (typeof candidate === 'string' && candidate.trim()) {
        return candidate.trim();
      }
    }
    return '';
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

  function _acceptStreamSeq(payload) {
    const seq = payload && payload.stream_seq;
    if (typeof seq !== 'number' || !Number.isFinite(seq)) return true;
    const key = _sessionKeyFromPayload(payload) || _sessionKey || '';
    return _markSessionStreamSeqSeen(key, seq);
  }

  function _eventHasSpecificSessionHandler(event) {
    return [
      'session.event.state_change',
      'session.event.text_delta',
      'session.event.router_decision',
      'session.event.tool_use_start',
      'session.event.tool_result',
      'session.event.artifact',
      'session.event.compaction',
      'session.event.subagent_start',
      'session.event.subagent_progress',
      'session.event.subagent_result',
      'session.event.task_group.started',
      'session.event.task_group.update',
      'session.event.task_group.completed',
      'session.event.task_group.failed',
    ].includes(event);
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
    if (_isCompactInFlightForCurrentSession()) {
      _chatDiag('thinking.skip.compaction_in_flight', {});
      return;
    }
    // Timer starts at send so "Watching · N.Ns" reads total wait. Keep this
    // independent from router scanning: provider first-byte waits can be long,
    // and the user still needs an immediate progress signal.
    _thinkingStartTime = Date.now();

    // Delay showing the indicator — fast responses won't flash it
    _thinkingDelayTimer = setTimeout(_showThinkingIndicatorNow, _THINKING_DELAY_MS);
  }

  function _showThinkingIndicatorNow() {
    _thinkingDelayTimer = null;
    if (_streamBubble) {
      _chatDiag('thinking.skip.stream_bubble', {});
      return; // content already arrived, skip
    }
    if (_isCompactInFlightForCurrentSession()) {
      _chatDiag('thinking.defer.compaction_in_flight', {});
      _thinkingDelayTimer = setTimeout(_showThinkingIndicatorNow, 150);
      return;
    }
    const empty = _thread.querySelector('.chat-empty');
    if (empty) empty.remove();

    _thinkingEl = document.createElement('div');
    _thinkingEl.className = 'msg assistant thinking';
    _thinkingEl.setAttribute('role', 'status');
    _thinkingEl.setAttribute('aria-live', 'polite');
    _thinkingEl.dataset.sessionKey = _streamSessionKey || _sessionKey || '';

    // Show header only on speaker change (thinking indicator is transient;
    // it will be removed before the real bubble is inserted, so don't update
    // _lastHeaderRole here — that update happens in _ensureStreamBubble).
    if (_lastHeaderRole !== 'assistant') {
      const header = document.createElement('div');
      header.className = 'msg-header';
      const roleLabel = document.createElement('span');
      roleLabel.className = 'role-label';
      roleLabel.textContent = _displayRoleLabel('assistant');
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
    elapsed.setAttribute('aria-live', 'off');
    const elapsedMs = Date.now() - _thinkingStartTime;
    const seconds = Math.floor(elapsedMs / 1000);
    const verb = SQUILLA_VERBS[Math.floor(elapsedMs / SQUILLA_DWELL_MS) % SQUILLA_VERBS.length];
    elapsed.textContent = `${verb} (${seconds}s)`;

    status.appendChild(dots);
    status.appendChild(elapsed);
    body.appendChild(status);
    _thinkingEl.appendChild(body);
    _thread.appendChild(_thinkingEl);
    _chatDiag('thinking.show', {
      thinking: _chatDiagDescribeElement(_thinkingEl),
    });
    if (_autoScroll) _scrollToBottom();

    _thinkingTimerInterval = setInterval(() => {
      if (!_thinkingEl) { clearInterval(_thinkingTimerInterval); return; }
      const eMs = Date.now() - _thinkingStartTime;
      const s = Math.floor(eMs / 1000);
      const v = SQUILLA_VERBS[Math.floor(eMs / SQUILLA_DWELL_MS) % SQUILLA_VERBS.length];
      const label = _thinkingEl.querySelector('.thinking-elapsed');
      if (label) label.textContent = `${v} (${s}s)`;

      if (s >= _THINKING_TTL_MS / 1000) {
        _hideThinkingIndicator();
        _addMessage('system', 'Still waiting for agent response\u2026');
      }
    }, 1000);
  }

  function _hideThinkingIndicator() {
    const hadThinking = !!_thinkingEl || !!_thinkingDelayTimer || !!_thinkingTimerInterval;
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
    if (hadThinking) _chatDiag('thinking.hide', {});
  }

  function _clearAwaitingModelHint() {
    if (_streamBubble) _streamBubble.classList.remove(_AWAITING_MODEL_CLASS);
  }

  function _markVisibleStreamEvent(kind) {
    _lastVisibleStreamEvent = kind || '';
    if (_lastVisibleStreamEvent !== 'tool_result') _clearAwaitingModelHint();
  }

  function _showAwaitingModelHintAfterToolResult() {
    if (!_streamBubble || _lastVisibleStreamEvent !== 'tool_result') return false;
    if (!_streamBubble.classList.contains(_AWAITING_MODEL_CLASS)) {
      _streamBubble.classList.add(_AWAITING_MODEL_CLASS);
      if (_autoScroll) _scrollToBottom();
    }
    return true;
  }

  function _clearStreamActiveMarkReveal() {
    if (_streamActiveMarkTimer) {
      clearTimeout(_streamActiveMarkTimer);
      _streamActiveMarkTimer = null;
    }
    _streamActiveMarkVisibleStartedAt = 0;
    if (_streamBubble) _streamBubble.classList.remove(_STREAM_ACTIVE_MARK_CLASS);
  }

  function _beginStreamActiveMarkRevealWindow() {
    _streamActiveMarkVisibleStartedAt = Date.now();
    _scheduleStreamActiveMarkReveal();
  }

  function _maybeRevealStreamActiveMark() {
    if (!_isStreaming || !_streamBubble) return false;
    const elapsedMs = _streamActiveMarkVisibleStartedAt ? Date.now() - _streamActiveMarkVisibleStartedAt : 0;
    if (elapsedMs < _STREAM_ACTIVE_MARK_DELAY_MS) return false;
    _streamBubble.classList.add(_STREAM_ACTIVE_MARK_CLASS);
    return true;
  }

  function _scheduleStreamActiveMarkReveal() {
    if (_streamActiveMarkTimer) clearTimeout(_streamActiveMarkTimer);
    const generation = _streamGeneration;
    _streamActiveMarkTimer = setTimeout(() => {
      _streamActiveMarkTimer = null;
      if (_streamGeneration !== generation) return;
      _maybeRevealStreamActiveMark();
    }, _STREAM_ACTIVE_MARK_DELAY_MS);
  }

  function _startStreaming() {
    _chatDiag('stream.start.before', {
      wasStreaming: _isStreaming,
      hadStreamBubble: !!_streamBubble,
      streamRawLen: _streamRaw.length,
    });
    _isStreaming = true;
    _streamSessionKey = _sessionKey || '';
    if (_streamSessionKey) _liveStreamStateBySession.delete(_streamSessionKey);
    _streamGeneration += 1;
    _applySessionRunState({ run_status: 'running', active_task: { status: 'running' } });
    _streamRaw = '';
    _segments = []; _activeTextSeg = null; _activeTextRaw = '';
    _streamArtifacts = [];
    _lastVisibleStreamEvent = '';
    _streamBubble = null;
    _autoScroll = true;
    if (_thread) _thread.setAttribute('aria-busy', 'true');
    _updateSendButton();
    _resetStreamIdleTimer();
    _chatDiag('stream.start.after', {});
  }

  function _ensureStreamBubble() {
    _chatDiag('stream.ensure.start', {
      hadStreamBubble: !!_streamBubble,
      streamRawLen: _streamRaw.length,
      activeTextRawLen: _activeTextRaw.length,
    });
    _hideThinkingIndicator();
    // Output is about to render. Finish any in-flight scan so the router does
    // not keep roaming, but allow the winner-lock animation to play.
    _routerFxSettleForOutput();
    if (!_streamBubble) {
      // Remove "No messages yet." placeholder
      const empty = _thread.querySelector('.chat-empty');
      if (empty) empty.remove();

      _streamBubble = document.createElement('div');
      _streamBubble.className = 'msg assistant streaming';
      _streamBubble.setAttribute('data-history-role', 'assistant');
      _streamBubble.setAttribute('aria-live', 'polite');
      _streamBubble.dataset.sessionKey = _streamSessionKey || _sessionKey || '';
      _streamBubble.dataset.streamSessionKey = _streamSessionKey || _sessionKey || '';

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
            <span class="role-label">${_esc(_displayRoleLabel('assistant'))}</span>
            <span class="savings-indicator"></span>
            <span class="msg-time"></span>
          </div>
          <div class="msg-body"></div>`;
        _lastHeaderRole = 'assistant';
      } else {
        _streamBubble.innerHTML = `<div class="msg-body"></div>`;
      }

      _thread.appendChild(_streamBubble);
      _beginStreamActiveMarkRevealWindow();

      // Create the first text segment
      _newTextSegment();
      _chatDiag('stream.bubble.created', {
        streamBubble: _chatDiagDescribeElement(_streamBubble),
      });
    }
    _maybeRevealStreamActiveMark();
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
    _chatDiag('stream.delta.start', {
      len: text ? text.length : 0,
      head: _chatDiagShortText(text, 100),
      wasStreaming: _isStreaming,
      hasStreamBubble: !!_streamBubble,
    });
    if (!_isStreaming) _startStreaming();
    _ensureStreamBubble();
    _markVisibleStreamEvent('text_delta');
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
    _chatDiag('stream.delta.queued', {
      streamRawLen: _streamRaw.length,
      activeTextRawLen: _activeTextRaw.length,
    });
  }

  function _flushPendingTextSegment() {
    if (!_renderDirty) return;
    if (_renderRafId) {
      cancelAnimationFrame(_renderRafId);
      _renderRafId = null;
    }
    _flushRender();
  }

  function _flushRender() {
    _renderRafId = null;
    if (!_renderDirty || !_streamBubble) {
      _chatDiag('stream.flush.skip', {
        renderDirty: !!_renderDirty,
        hasStreamBubble: !!_streamBubble,
      });
      _renderDirty = false;
      return;
    }
    if (_activeTextSeg && _activeTextRaw) {
      _activeTextSeg.innerHTML = Markdown.render(_stripProtocolTextLeak(_stripDirectiveTags(_stripGeneratedArtifactMarkers(_activeTextRaw))));  // eslint-disable-line no-unsanitized/property
      Markdown.bindCopy(_activeTextSeg);
    }
    _renderDirty = false;
    if (_autoScroll) _scrollToBottom();
    _chatDiag('stream.flush.done', {
      streamRawLen: _streamRaw.length,
      activeTextRawLen: _activeTextRaw.length,
      activeSeg: _chatDiagDescribeElement(_activeTextSeg),
    });
  }

  function _endStreaming(opts) {
    const reason = opts && opts.reason;
    const wasAborted = reason === 'aborted';
    _chatDiag('stream.end.start', {
      reason: reason || '',
      wasAborted,
      hasStreamBubble: !!_streamBubble,
      streamRawLen: _streamRaw.length,
    });
    _hideThinkingIndicator();
    _cancelPendingRouterFxScan('stream_end');
    _clearAwaitingModelHint();
    _lastVisibleStreamEvent = '';
    if (_historySyncTimer) { clearTimeout(_historySyncTimer); _historySyncTimer = null; }
    if (_renderRafId) { cancelAnimationFrame(_renderRafId); _renderRafId = null; }
    _renderDirty = false;
    _clearStreamIdleTimer();
    _clearStreamActiveMarkReveal();
    _streamIdlePausedForApproval = false;
    _approvalPendingForCurrentSession = false;
    if (_streamBubble) {
      _streamBubble.classList.remove('streaming');
      const cleanedText = _stripProtocolTextLeak(_stripDirectiveTags(_stripGeneratedArtifactMarkers(_streamRaw))).trim();

      // Suppress sentinel tokens that the LLM may emit instead of a real reply.
      // Don't suppress when aborted — we want the interrupted bubble to show
      // even if the partial happens to match a sentinel string.
      const _SENTINELS = ['NO_REPLY', 'HEARTBEAT_OK'];
      if (!wasAborted && _SENTINELS.includes(cleanedText)) {
        _chatDiag('stream.end.remove.sentinel', {
          cleanedText,
        });
        _streamBubble.remove();
        _streamBubble = null;
        _isStreaming = false;
        if (_streamSessionKey) _liveStreamStateBySession.delete(_streamSessionKey);
        _streamSessionKey = '';
        _streamRaw = '';
        _segments = []; _activeTextSeg = null; _activeTextRaw = '';
        _streamArtifacts = [];
        _updateSendButton();
        return;
      }

      // Aborted with no partial output: drop the empty bubble entirely so
      // the transcript doesn't grow stub assistant messages every ESC.
      if (wasAborted && !cleanedText) {
        _chatDiag('stream.end.remove.aborted_empty', {});
        _streamBubble.remove();
        _streamBubble = null;
        _isStreaming = false;
        if (_streamSessionKey) _liveStreamStateBySession.delete(_streamSessionKey);
        _streamSessionKey = '';
        _streamRaw = '';
        _segments = []; _activeTextSeg = null; _activeTextRaw = '';
        _streamArtifacts = [];
        if (_thread) _thread.setAttribute('aria-busy', 'false');
        _updateSendButton();
        return;
      }
      _stampHistoryElement(_streamBubble, '', 'assistant', cleanedText);
      _markPendingFinalizedAssistantBubble(_streamBubble, cleanedText);

      // Final render: render each text segment with its own content
      for (const seg of _segments) {
        if (seg.type !== 'text' || !seg.el) continue;
        const segText = _stripProtocolTextLeak(_stripDirectiveTags(_stripGeneratedArtifactMarkers(seg.raw))).trim();
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
    _routerFxStaticizeCompletedStrips(_streamSessionKey || _sessionKey || '');
    if (_streamSessionKey) _liveStreamStateBySession.delete(_streamSessionKey);
    _streamBubble = null;
    _streamSessionKey = '';
    _streamRaw = '';
    _segments = []; _activeTextSeg = null; _activeTextRaw = '';
    _streamArtifacts = [];
    if (_thread) _thread.setAttribute('aria-busy', 'false');
    _updateSendButton();
    _chatDiag('stream.end.done', {
      reason: reason || '',
      wasAborted,
    });
  }

  function _hasViewLocalStreamState() {
    return !!(
      _isStreaming
      || _streamBubble
      || _streamRaw
      || _segments.length
      || _activeTextRaw
      || _streamArtifacts.length
      || _currentSessionLiveRouterStrips(_streamSessionKey || _sessionKey || '').length
      || _thinkingEl
      || _thinkingDelayTimer
    );
  }

  function _parkCurrentSessionStreamState(reason) {
    const key = _streamSessionKey || _sessionKey || '';
    const routerStrips = _currentSessionLiveRouterStrips(key);
    const liveUserAnchor = _currentSessionLiveUserAnchor(key);
    if (!key || !_hasViewLocalStreamState()) {
      _clearViewLocalStreamState(reason);
      return false;
    }
    _flushPendingTextSegment();
    const state = {
      isStreaming: _isStreaming,
      streamBubble: _streamBubble,
      streamSessionKey: key,
      streamRaw: _streamRaw,
      liveUserAnchor,
      segments: _segments,
      activeTextSeg: _activeTextSeg,
      activeTextRaw: _activeTextRaw,
      streamArtifacts: _streamArtifacts.slice(),
      lastVisibleStreamEvent: _lastVisibleStreamEvent,
      routerStrips,
      streamGeneration: _streamGeneration,
      autoScroll: _autoScroll,
      pendingFinalizedAssistantBubble: _pendingFinalizedAssistantBubble,
      pendingFinalizedAssistantFallbackId: _pendingFinalizedAssistantFallbackId,
    };
    _liveStreamStateBySession.set(key, state);
    _hideThinkingIndicator();
    if (_historySyncTimer) { clearTimeout(_historySyncTimer); _historySyncTimer = null; }
    if (_renderRafId) { cancelAnimationFrame(_renderRafId); _renderRafId = null; }
    _renderDirty = false;
    _clearStreamIdleTimer();
    _streamIdlePausedForApproval = false;
    _approvalPendingForCurrentSession = false;
    if (_streamBubble) _streamBubble.remove();
    routerStrips.forEach((el) => {
      _routerFxPauseScanTimers(el);
      if (el.parentNode) el.remove();
    });
    if (liveUserAnchor && liveUserAnchor.parentNode) liveUserAnchor.remove();
    _isStreaming = false;
    _streamBubble = null;
    _streamSessionKey = '';
    _streamRaw = '';
    _segments = []; _activeTextSeg = null; _activeTextRaw = '';
    _streamArtifacts = [];
    _lastVisibleStreamEvent = '';
    if (_thread) _thread.setAttribute('aria-busy', 'false');
    _updateSendButton();
    _chatDiag('stream.view_state_parked', {
      reason: reason || '',
      sessionKey: key,
      streamRawLen: state.streamRaw.length,
      hasStreamBubble: !!state.streamBubble,
      hasLiveUserAnchor: !!state.liveUserAnchor,
      routerStripCount: routerStrips.length,
    });
    return true;
  }

  function _restoreLiveStreamStateForSession(key) {
    const sessionKey = key || _sessionKey || '';
    const state = _liveStreamStateBySession.get(sessionKey);
    if (!state || state.streamSessionKey !== sessionKey) return false;
    _liveStreamStateBySession.delete(sessionKey);
    _isStreaming = !!state.isStreaming;
    _streamBubble = state.streamBubble || null;
    _streamSessionKey = state.streamSessionKey || sessionKey;
    _streamRaw = state.streamRaw || '';
    _segments = Array.isArray(state.segments) ? state.segments : [];
    _activeTextSeg = state.activeTextSeg || null;
    _activeTextRaw = state.activeTextRaw || '';
    _streamArtifacts = Array.isArray(state.streamArtifacts) ? state.streamArtifacts.slice() : [];
    _lastVisibleStreamEvent = state.lastVisibleStreamEvent || '';
    _streamGeneration = Math.max(_streamGeneration, state.streamGeneration || 0);
    _autoScroll = state.autoScroll !== false;
    _pendingFinalizedAssistantBubble = state.pendingFinalizedAssistantBubble || null;
    _pendingFinalizedAssistantFallbackId = state.pendingFinalizedAssistantFallbackId || '';
    const liveUserAnchor = state.liveUserAnchor || null;
    const routerStrips = Array.isArray(state.routerStrips) ? state.routerStrips : [];
    if (_thread && liveUserAnchor && !liveUserAnchor.isConnected) {
      _thread.appendChild(liveUserAnchor);
    }
    if (_streamBubble) {
      _streamBubble.dataset.sessionKey = sessionKey;
      _streamBubble.dataset.streamSessionKey = sessionKey;
      if (_thread && !_streamBubble.isConnected) _thread.appendChild(_streamBubble);
    }
    if (_lastVisibleStreamEvent !== 'tool_result') _clearAwaitingModelHint();
    if (_thread) {
      routerStrips.forEach((el) => {
        el.dataset.sessionKey = sessionKey;
        if (!el.isConnected) {
          _insertLiveRouterStripForAnchor(el, liveUserAnchor, _streamBubble);
        }
        _routerFxResumeLiveStrip(el);
      });
    }
    if (_thread) _thread.setAttribute('aria-busy', _isStreaming ? 'true' : 'false');
    if (_isStreaming) {
      _applySessionRunState({ run_status: 'running', active_task: { status: 'running' } });
      _resetStreamIdleTimer();
    }
    _updateSendButton();
    _chatDiag('stream.view_state_restored', {
      sessionKey,
      streamRawLen: _streamRaw.length,
      hasStreamBubble: !!_streamBubble,
      hasLiveUserAnchor: !!liveUserAnchor,
      routerStripCount: routerStrips.length,
    });
    return true;
  }

  function _clearViewLocalStreamState(reason) {
    const hadStreamBubble = !!_streamBubble;
    const hadPendingFinalized = !!_pendingFinalizedAssistantBubble;
    const routerStrips = _currentSessionLiveRouterStrips(_streamSessionKey || _sessionKey || '');
    _hideThinkingIndicator();
    _cancelPendingRouterFxScan(reason || 'clear_view_state');
    if (_historySyncTimer) { clearTimeout(_historySyncTimer); _historySyncTimer = null; }
    if (_renderRafId) { cancelAnimationFrame(_renderRafId); _renderRafId = null; }
    _renderDirty = false;
    _clearStreamIdleTimer();
    _streamIdlePausedForApproval = false;
    _approvalPendingForCurrentSession = false;
    if (_streamBubble) _streamBubble.remove();
    routerStrips.forEach((el) => {
      _routerFxPauseScanTimers(el);
      if (el.parentNode) el.remove();
    });
    _clearPendingFinalizedAssistantBubble();
    if (_streamSessionKey) _liveStreamStateBySession.delete(_streamSessionKey);
    _isStreaming = false;
    _streamBubble = null;
    _streamSessionKey = '';
    _streamRaw = '';
    _segments = []; _activeTextSeg = null; _activeTextRaw = '';
    _streamArtifacts = [];
    _lastVisibleStreamEvent = '';
    _streamGeneration += 1;
    if (_thread) _thread.setAttribute('aria-busy', 'false');
    _updateSendButton();
    _chatDiag('stream.view_state_cleared', {
      reason: reason || '',
      hadStreamBubble,
      hadPendingFinalized,
      routerStripCount: routerStrips.length,
    });
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
    _sendBtn.title = _isCompactInFlightForCurrentSession()
      ? 'Send (queues until compaction finishes)'
      : _isStreaming
        ? 'Send (queues for after current response)'
        : 'Send';
    _updateStopButton();
  }

  /* ── Tool Call / Tool Result Display ────────────────────────────────── */

  function _toolInputObject(input) {
    if (!input) return null;
    if (typeof input === 'object') return input;
    if (typeof input !== 'string') return null;
    const trimmed = input.trim();
    if (!trimmed || !trimmed.startsWith('{')) return null;
    try {
      const parsed = JSON.parse(trimmed);
      return parsed && typeof parsed === 'object' ? parsed : null;
    } catch {
      return null;
    }
  }

  function _basename(path) {
    const raw = String(path || '').trim();
    if (!raw) return '';
    const parts = raw.split(/[\\/]+/).filter(Boolean);
    return parts.length ? parts[parts.length - 1] : raw;
  }

  function _publishArtifactTargetName(input) {
    input = _toolInputObject(input);
    if (!input) return '';
    return _basename(input.name || input.path);
  }

  function _toolDisplayName(name, input) {
    if (name === 'publish_artifact') {
      const target = _publishArtifactTargetName(input);
      if (target) return `${name} - ${target}`;
    }
    // Meta-skill step: render as a clean step name (drop the 'meta-step:'
    // prefix and replace underscores with spaces).
    if (name && name.startsWith('meta-step:')) {
      const stepId = name.slice('meta-step:'.length);
      return 'Step · ' + stepId.replace(/_/g, ' ');
    }
    return name || 'tool';
  }

  function _metaStepRunningHint(name) {
    if (!name || !name.startsWith('meta-step:')) return '';
    const stepId = name.slice('meta-step:'.length);
    if (stepId.endsWith('_video')) {
      return '正在生成视频素材，可能需要几分钟。Generating video assets; this may take several minutes.';
    }
    if (stepId.endsWith('_image') || stepId.endsWith('_img_prompt')) {
      return '正在生成视觉素材，可能需要稍等。Generating visual assets; this can take a little while.';
    }
    if (stepId.includes('duration') || stepId.includes('prompt')) {
      return '正在准备这一生成步骤。Preparing this generation step.';
    }
    return '正在运行这个 meta-skill 步骤。Running this meta-skill step.';
  }

  function _isControlPlaneToolName(name) {
    return name === 'router_control';
  }

  function _buildToolCallDOM(name, toolId, input, isRunning) {
    const displayName = _toolDisplayName(name, input);
    const preview = _truncate(
      typeof input === 'string' ? input : JSON.stringify(input || '', null, 2),
      200
    );

    const details = document.createElement('details');
    details.className = 'chat-tools-collapse' + (isRunning ? ' chat-tools-collapse--running' : '');
    // Auto-open meta-skill step cards so the spinner border + body are
    // visible while the step is running. (Generic tools stay collapsed
    // by default to keep the chat tidy.)
    if (name && name.startsWith('meta-step:')) details.setAttribute('open', '');
    if (toolId) details.setAttribute('data-tool-id', toolId);
    details.setAttribute('data-tool-name', name || 'tool');

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
    summary.appendChild(document.createTextNode(' ' + displayName));
    const statusSpan = document.createElement('span');
    statusSpan.className = 'chat-tools-status';
    _applyToolSummaryStatus(statusSpan, isRunning ? 'running' : '');
    summary.appendChild(statusSpan);

    const toolsBody = document.createElement('div');
    toolsBody.className = 'chat-tools-body';

    const runningHint = isRunning ? _metaStepRunningHint(name) : '';
    if (runningHint) {
      const hint = document.createElement('div');
      hint.className = 'chat-meta-step-running-hint';
      hint.textContent = runningHint;
      toolsBody.appendChild(hint);
    }

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

  function _visibleToolSummaryStatus(status) {
    return status === 'running' ? 'running' : '';
  }

  function _applyToolSummaryStatus(statusSpan, status) {
    const visibleStatus = _visibleToolSummaryStatus(status || '');
    statusSpan.dataset.status = status || '';
    statusSpan.textContent = visibleStatus;
    statusSpan.hidden = !visibleStatus;
  }

  function _setToolSummaryStatus(details, status) {
    if (!details) return;
    const summary = details.querySelector('.chat-tools-summary');
    if (!summary) return;
    let statusSpan = summary.querySelector('.chat-tools-status');
    if (!statusSpan) {
      statusSpan = document.createElement('span');
      statusSpan.className = 'chat-tools-status';
      summary.appendChild(statusSpan);
    }
    _applyToolSummaryStatus(statusSpan, status || '');
  }

  function _retitleToolCallDOM(details, name, input) {
    if (!details || !name) return;
    const current = details.getAttribute('data-tool-name') || '';
    if (current === name) return;
    details.setAttribute('data-tool-name', name);
    const summary = details.querySelector('.chat-tools-summary');
    if (!summary) return;
    const providerBadge = summary.querySelector('.chat-tool-provider');
    if (providerBadge) providerBadge.remove();
    const currentStatus = summary.querySelector('.chat-tools-status');
    const statusText = currentStatus?.dataset?.status || currentStatus?.textContent || '';
    summary.textContent = '';
    const iconSpan = document.createElement('span');
    iconSpan.className = 'chat-tools-icon';
    iconSpan.textContent = _toolEmoji(name);
    summary.appendChild(iconSpan);
    summary.appendChild(document.createTextNode(' ' + _toolDisplayName(name, input)));
    const statusSpan = document.createElement('span');
    statusSpan.className = 'chat-tools-status';
    _applyToolSummaryStatus(statusSpan, statusText);
    summary.appendChild(statusSpan);
    if (providerBadge) summary.appendChild(providerBadge);
  }

  function _findToolDetailsById(root, toolId) {
    if (!root || !toolId) return null;
    return Array.from(root.querySelectorAll('[data-tool-id]')).find(
      (el) => el.getAttribute('data-tool-id') === toolId
    ) || null;
  }

  function _findToolResultById(root, toolId) {
    if (!root || !toolId) return null;
    return Array.from(root.querySelectorAll('[data-tool-result-for]')).find(
      (el) => el.getAttribute('data-tool-result-for') === toolId
    ) || null;
  }

  function _settleToolResultCard(payload, isError) {
    const toolId = payload && payload.tool_use_id || '';
    if (!toolId) return null;
    const bubble = _ensureStreamBubble();
    const body = bubble && bubble.querySelector('.msg-body');
    const details = _findToolDetailsById(body, toolId);
    if (!details) return null;
    let toolName = payload.name || payload.tool_name || '';
    if (toolName) _retitleToolCallDOM(details, toolName, payload.arguments || payload.input || '');
    toolName = toolName || details.getAttribute('data-tool-name') || '';
    details.classList.remove('chat-tools-collapse--running');
    details.classList.add(_toolResultStateClass(payload));
    _setToolSummaryStatus(details, isError ? 'error' : 'done');
    const summary = details.querySelector('.chat-tools-summary');
    if (summary) summary.removeAttribute('aria-disabled');
    return details;
  }

  function _clarifyArgsFromHistoricalSegment(seg, details) {
    const input = details && details._opensquillaToolInput;
    if (!input || typeof input !== 'object') return null;
    if (
      input.kind === 'user_input'
      && input.paused === true
      && input.clarify_schema
    ) {
      return input;
    }
    return null;
  }

  function _toolExecutionStatus(payload) {
    const status = payload && (payload.execution_status || payload.executionStatus);
    return status && typeof status === 'object' ? status : null;
  }

  function _toolResultIsError(payload) {
    const status = _toolExecutionStatus(payload);
    if (status && typeof status.status === 'string') {
      return ['error', 'timeout', 'cancelled'].includes(status.status);
    }
    return !!(payload && (payload.is_error || payload.isError || payload.error));
  }

  function _toolResultStateClass(payload) {
    const status = _toolExecutionStatus(payload);
    if (status && status.status === 'success') return 'chat-tools-collapse--success';
    if (status && status.status === 'unknown') return 'chat-tools-collapse--unknown';
    return _toolResultIsError(payload) ? 'chat-tools-collapse--error' : 'chat-tools-collapse--success';
  }

  function _toolResultIsTruncated(payload) {
    const status = _toolExecutionStatus(payload);
    return !!(status && status.truncated);
  }

  function _toolResultContent(payload) {
    if (!payload) return '';
    let raw = '';
    if (Object.prototype.hasOwnProperty.call(payload, 'result')) {
      raw = payload.result;
    } else if (Object.prototype.hasOwnProperty.call(payload, 'content')) {
      raw = payload.content;
    } else if (Object.prototype.hasOwnProperty.call(payload, 'output')) {
      raw = payload.output;
    }
    if (typeof raw === 'string') return raw;
    const rendered = JSON.stringify(raw, null, 2);
    return rendered == null ? '' : rendered;
  }

  function _memorySearchSourceRows(content) {
    if (!content || typeof content !== 'string') return [];
    const rows = [];
    const pattern = /^\[(\d+)\]\s+(.+?)\s+\(source:\s*([^;]+);\s*lines\s+([^;]+);\s*citation:\s*([^;]+);/;
    for (const line of content.split('\n')) {
      const match = line.match(pattern);
      if (!match) continue;
      rows.push({
        index: match[1],
        path: match[2],
        source: match[3],
        lines: match[4],
        citation: match[5],
      });
      if (rows.length >= 6) break;
    }
    return rows;
  }

  function _buildMemorySearchSourceDOM(content) {
    const rows = _memorySearchSourceRows(content);
    if (!rows.length) return null;

    const wrap = document.createElement('div');
    wrap.className = 'chat-memory-sources';
    for (const row of rows) {
      const item = document.createElement('div');
      item.className = 'chat-memory-source';

      const badge = document.createElement('span');
      badge.className = 'chat-memory-source-badge chat-memory-source-badge--' + row.source;
      badge.textContent = row.source;
      item.appendChild(badge);

      const cite = document.createElement('span');
      cite.className = 'chat-memory-source-citation';
      cite.textContent = row.citation || (row.path + '#L' + row.lines);
      item.appendChild(cite);
      wrap.appendChild(item);
    }
    return wrap;
  }

  function _buildToolResultDOM(content, isError, isTruncated = false, toolName = '') {
    const preview = _truncate(content, 200);
    if (!preview || preview.trim() === '') return null;

    const div = document.createElement('div');
    div.className = 'chat-tool-result'
      + (isError ? ' chat-tool-result--error' : '')
      + (isTruncated ? ' chat-tool-result--warn' : '');

    const previewDiv = document.createElement('div');
    previewDiv.className = 'chat-tool-result-preview';
    previewDiv.textContent = preview;
    div.appendChild(previewDiv);

    if (toolName === 'memory_search') {
      const sources = _buildMemorySearchSourceDOM(content);
      if (sources) div.appendChild(sources);
    }

    if (content.length > 200) {
      const viewBtn = document.createElement('button');
      viewBtn.className = 'btn btn--sm btn--ghost chat-tool-view-btn';
      viewBtn.type = 'button';
      viewBtn.textContent = 'View full';
      viewBtn.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        UI.modal('Tool Result', '<pre class="chat-tool-result-full">' + _esc(content) + '</pre>', [
          { label: 'Close', cls: 'btn-secondary' },
        ]);
      });
      div.appendChild(viewBtn);
    }
    return div;
  }

  function _appendToolCall(payload) {
    if (!payload) return;
    _chatDiag('tool_call.append.start', _chatDiagSummarizePayload(payload));
    const name = payload.name || payload.tool_name || 'tool';
    if (_isControlPlaneToolName(name)) {
      _chatDiag('tool_call.append.skip_control_plane', { name });
      return;
    }
    try { if (name && name.startsWith('meta-step:')) console.log('[meta-step] start', name); } catch (e) {}
    const input = typeof payload.input === 'string'
      ? payload.input
      : JSON.stringify(payload.input || payload.arguments || '', null, 2);
    const toolId = payload.tool_use_id || '';

    const bubble = _ensureStreamBubble();
    _markVisibleStreamEvent('tool_use_start');
    const body = bubble.querySelector('.msg-body');
    const existing = _findToolDetailsById(body, toolId);
    if (existing) {
      _chatDiag('tool_call.append.reuse_existing', {
        toolId,
        name,
      });
      if (name === 'web_search' && _searchProvider) {
        _injectProviderBadge(existing.querySelector('.chat-tools-summary'), _searchProvider);
      }
      if (_autoScroll) _scrollToBottom();
      return;
    }

    const details = _buildToolCallDOM(name, toolId, input, true);
    if (name === 'web_search' && _searchProvider) {
      _injectProviderBadge(details.querySelector('.chat-tools-summary'), _searchProvider);
    }
    _flushPendingTextSegment();
    body.appendChild(details);
    _segments.push({ type: 'tool', el: details });

    // Seal the current text segment and start a new one for text after this tool call
    _newTextSegment();

    if (_autoScroll) _scrollToBottom();
    _chatDiag('tool_call.append.done', {
      toolId,
      name,
      details: _chatDiagDescribeElement(details),
    });
  }

  function _appendToolResult(payload) {
    if (!payload) return;
    _chatDiag('tool_result.append.start', _chatDiagSummarizePayload(payload));

    // PR5: meta-skill user_input paused signal — render a clickable form
    // instead of a plain tool-result card. The scheduler emits this with
    // arguments.kind === 'user_input' and arguments.clarify_schema as the
    // surface protocol payload (see clarify_schema.schema_to_protocol).
    const _args = payload && payload.arguments;
    // Diagnostic: log every tool_result event so the form-card branch
    // can be debugged from the browser console.
    try {
      console.log('[clarify-debug] tool_result', {
        tool_name: payload && payload.tool_name,
        args_kind: _args && _args.kind,
        args_paused: _args && _args.paused,
        has_schema: !!(_args && _args.clarify_schema),
        payload: payload,
      });
    } catch (e) {}
    if (
      _args
      && _args.kind === 'user_input'
      && _args.paused === true
      && _args.clarify_schema
    ) {
      try { console.log('[clarify-debug] firing _appendClarifyForm'); } catch (e) {}
      _markVisibleStreamEvent('clarify_form');
      _settleToolResultCard(payload, false);
      _appendClarifyForm(payload, _args);
      _chatDiag('tool_result.append.clarify_form', _chatDiagSummarizePayload(payload));
      return;
    }

    // Skipped user_input step with an inferred-context summary —
    // close the (c)/(d) "trust gap" on the path where the form was
    // auto-suppressed. The scheduler attaches ``clarify_skip_summary``
    // whenever a meta author's ``when:`` expression evaluated false
    // for a user_input step, so the user can still see what the
    // upstream context-extraction inferred and intervene before the
    // DAG continues.
    if (
      _args
      && _args.kind === 'user_input'
      && _args.skipped === true
      && _args.clarify_skip_summary
    ) {
      try { console.log('[clarify-debug] firing _appendClarifySkipSummary'); } catch (e) {}
      _markVisibleStreamEvent('clarify_skip_summary');
      _appendClarifySkipSummary(payload, _args);
      _chatDiag(
        'tool_result.append.clarify_skip_summary',
        _chatDiagSummarizePayload(payload),
      );
      return;
    }

    const content = _toolResultContent(payload);
    const isError = _toolResultIsError(payload);
    const toolId = payload.tool_use_id || '';
    let toolName = payload.name || payload.tool_name || '';
    if (_isControlPlaneToolName(toolName)) {
      _chatDiag('tool_result.append.skip_control_plane', {
        toolId,
        toolName,
      });
      return;
    }

    const bubble = _ensureStreamBubble();
    _markVisibleStreamEvent('tool_result');
    const body = bubble.querySelector('.msg-body');

    // Transition tool container from running → success/error and find target container
    let resultTarget = body; // default: append to msg-body
    if (toolId) {
      const details = _findToolDetailsById(body, toolId);
      if (details) {
        if (toolName) _retitleToolCallDOM(details, toolName, payload.arguments || payload.input || '');
        toolName = toolName || details.getAttribute('data-tool-name') || '';
        details.classList.remove('chat-tools-collapse--running');
        details.classList.add(_toolResultStateClass(payload));
        _setToolSummaryStatus(details, isError ? 'error' : 'done');
        const summary = details.querySelector('.chat-tools-summary');
        if (summary) summary.removeAttribute('aria-disabled');
        const toolsBody = details.querySelector('.chat-tools-body');
        if (toolsBody) resultTarget = toolsBody;

        // web_search: add provider badge to collapsible summary (may already be present from running state)
        if (toolName === 'web_search') {
          const provider = _toolResultProvider(payload, content);
          if (provider) {
            _setSearchProvider(provider, { refreshRunning: false });
            _injectProviderBadge(details.querySelector('.chat-tools-summary'), provider);
          }
        }
      }
    }
    if (toolId && _findToolResultById(resultTarget, toolId)) {
      if (_autoScroll) _scrollToBottom();
      _chatDiag('tool_result.append.skip_duplicate', {
        toolId,
        toolName,
      });
      return;
    }

    // Only show result preview if non-empty
    const resultDiv = _buildToolResultDOM(
      content,
      isError,
      _toolResultIsTruncated(payload),
      toolName
    );
    if (!resultDiv) {
      if (_autoScroll) _scrollToBottom();
      _chatDiag('tool_result.append.skip_empty_result', {
        toolId,
        toolName,
      });
      return;
    }

    if (toolId) resultDiv.setAttribute('data-tool-result-for', toolId);
    resultTarget.appendChild(resultDiv);
    if (_autoScroll) _scrollToBottom();
    _chatDiag('tool_result.append.done', {
      toolId,
      toolName,
      result: _chatDiagDescribeElement(resultDiv),
    });
  }

  // ── PR5: meta-skill user_input form rendering ──

  function _appendClarifyForm(payload, args) {
    const bubble = _ensureStreamBubble();
    const body = bubble.querySelector('.msg-body');
    _appendClarifyFormToBody(body, payload, args);
  }

  function _appendClarifyFormToBody(body, payload, args) {
    if (!body) return;
    // The scheduler payload carries:
    //   args.clarify_schema = { mode, intro, fields, cancel_keywords,
    //                            timeout_hours, nl_extract }
    //   args.run_id         = awaiting run identifier
    //   args.step           = user_input step id
    const schema = args.clarify_schema || {};
    const runId = args.run_id || '';
    const fields = Array.isArray(schema.fields) ? schema.fields : [];
    const schemaCopy = [
      schema.intro || '',
      ...fields.map((field) => field && field.prompt || ''),
    ].join('\n');
    const schemaLang = /[\u4e00-\u9fff]/.test(schemaCopy) ? 'zh' : 'en';
    const clarifyText = (zh, en) => schemaLang === 'zh' ? zh : en;
    const zhChoiceLabels = {
      "en": "英文",
      "zh": "中文",
      "ja": "日文",
      "other": "其他",
      "mixed": "中英混合",
      "YES": "是",
      "NO": "否",
      "LAST_WEEK": "过去一周",
      "LAST_MONTH": "过去一个月",
      "LAST_QUARTER": "过去一个季度",
      "ENTRY": "初级",
      "MID": "中级",
      "SENIOR": "高级",
      "STAFF": "专家级",
      "PRE_K": "学龄前（3-5 岁）",
      "EARLY_GRADE": "小学低年级（6-9 岁）",
      "TWEEN": "小学高年级/初中前（10-12 岁）",
      "TEEN": "青少年（13-17 岁）",
      "SHOESTRING": "低预算",
      "MODEST": "适中预算",
      "COMFORTABLE": "宽裕预算",
      "SOLO": "孩子独立完成",
      "LIGHT": "家长偶尔帮忙",
      "HANDS_ON": "家长全程陪同",
      "budget": "低预算",
      "mid": "中等",
      "premium": "高预算",
      "academic": "学术读者",
      "technical": "技术读者",
      "business": "商业读者",
      "general": "普通读者",
      "FULL_MANUSCRIPT": "完整论文",
      "COMPACT_SKELETON": "快速草稿",
      "REPAIR_EXISTING": "修复已有稿件",
      "COMPILE_ONLY": "仅编译",
      "readable_pdf": "可读取 PDF",
      "inline_excerpts_only": "仅使用粘贴摘录",
      "reference_only": "只有引用/文件名",
    };
    const localizedChoiceLabel = (choice, language) => {
      const raw = String(choice || '');
      if (language === 'zh') return zhChoiceLabels[raw] || raw;
      if (/^[A-Z0-9_-]+$/.test(raw)) {
        const humanized = raw.replace(/[_-]+/g, ' ').toLowerCase();
        return humanized.charAt(0).toUpperCase() + humanized.slice(1);
      }
      return raw;
    };

    const card = document.createElement('div');
    card.className = 'clarify-form chat-tools-collapse';
    card.setAttribute('data-clarify-step', args.step || '');
    card.setAttribute('data-clarify-run', runId);

    const header = document.createElement('div');
    header.className = 'clarify-form-header';
    header.textContent = clarifyText('请确认以下信息', 'Please confirm these details');
    card.appendChild(header);

    // Dual-channel hint (soft-clarify) — tell the user the main chat
    // input still works while the form is open, so they can either
    // type into fields or continue the conversation naturally to
    // supply / refine answers. Without this line users assume the
    // form is the only path forward and avoid the message box.
    const dualChannelHint = document.createElement('div');
    dualChannelHint.className = 'clarify-form-dual-channel-hint';
    dualChannelHint.textContent = clarifyText(
      '✎ 您也可以在下方对话框里继续聊天补充信息，或回复 "开始" 让系统立即执行；说 "算了" 取消。',
      '✎ You can also keep chatting in the message box below to add or refine info, reply "go ahead" to start, or "cancel" to abort.',
    );
    card.appendChild(dualChannelHint);

    if (schema.intro) {
      const intro = document.createElement('div');
      intro.className = 'clarify-form-intro';
      // schema.intro is xml_escape'd server-side; safe as textContent.
      intro.textContent = schema.intro;
      card.appendChild(intro);
    }

    // Step (d) auto-prefill rendering. The server may attach
    // confirmed_fields / ambiguous_fields / unknown_mentions when
    // the prefill scan inferred values from the user's earlier
    // messages. Render a transparency block at the top so the user
    // sees what was detected and can confirm or override; build a
    // lookup map so the field rows below can show inline markers.
    const confirmedFields = Array.isArray(schema.confirmed_fields)
      ? schema.confirmed_fields : [];
    const ambiguousFields = Array.isArray(schema.ambiguous_fields)
      ? schema.ambiguous_fields : [];
    const unknownMentions = Array.isArray(schema.unknown_mentions)
      ? schema.unknown_mentions : [];
    const confirmedByName = {};
    confirmedFields.forEach((entry) => {
      if (entry && typeof entry.name === 'string') {
        confirmedByName[entry.name] = entry;
      }
    });
    const ambiguousByName = {};
    ambiguousFields.forEach((entry) => {
      if (entry && typeof entry.name === 'string') {
        ambiguousByName[entry.name] = entry;
      }
    });

    const requiredFields = fields.filter((field) => field && field.required);
    const confirmedRequiredFields = requiredFields.filter((field) => (
      confirmedByName[field.name] !== undefined
    ));
    const missingRequiredFields = requiredFields.filter((field) => (
      confirmedByName[field.name] === undefined
    ));
    const clarifyFieldPromptText = (field) => {
      if (!field) return '';
      return String(field.prompt || '').replace(/\s+/g, ' ').trim();
    };
    const clarifyFieldDisplayLabel = (field) => {
      if (!field) return '';
      const nameText = String(field.name || '').replace(/[_-]+/g, ' ').trim();
      const promptText = clarifyFieldPromptText(field);
      const promptLower = promptText.toLowerCase();
      const nameLower = nameText.toLowerCase();
      const promptLooksLikeScriptReplyField = (
        (
          promptLower.includes('script draft')
          && promptLower.includes('verbatim reply')
        )
        || (
          promptText.includes('脚本草稿')
          && promptText.includes('原样')
        )
      );
      const looksLikeScriptReplyField = (
        promptLooksLikeScriptReplyField
        || nameLower === 'reply'
        || nameLower === 'reply text'
      );
      if (looksLikeScriptReplyField) {
        return clarifyText('回复内容', 'Reply');
      }
      if (promptText && promptText.length <= 60) return promptText;
      if (nameText) {
        return nameText.replace(/\b[a-z]/g, (char) => char.toUpperCase());
      }
      if (promptText) return promptText.slice(0, 60).trim() + '...';
      return '';
    };

    if (fields.length > 0) {
      const progress = document.createElement('div');
      progress.className = 'clarify-form-progress';

      const metric = document.createElement('div');
      metric.className = 'clarify-form-progress-metric';
      metric.textContent = clarifyText(
        '已收集 ' + confirmedRequiredFields.length + '/' + requiredFields.length + ' 项必填信息',
        'Captured ' + confirmedRequiredFields.length + '/' + requiredFields.length + ' required details',
      );
      progress.appendChild(metric);

      const next = document.createElement('div');
      next.className = 'clarify-form-progress-next';
      if (missingRequiredFields.length > 0) {
        const missingLabels = missingRequiredFields.map(clarifyFieldDisplayLabel).filter(Boolean);
        next.textContent = clarifyText(
          '建议下一步：补充 ' + missingLabels.join('、') + '。可在表单中填写，也可直接继续聊天补充。',
          'Suggested next steps: add ' + missingLabels.join(', ') + '. You can fill the form or keep chatting.',
        );
      } else if (ambiguousFields.length > 0) {
        next.textContent = clarifyText(
          '建议下一步：检查不确定的信息，确认无误后提交。',
          'Suggested next steps: review the unclear details, then submit.',
        );
      } else {
        next.textContent = clarifyText(
          '建议下一步：检查已识别的信息，确认无误后提交。',
          'Suggested next steps: review the captured details, then submit.',
        );
      }
      progress.appendChild(next);
      card.appendChild(progress);
    }

    if (
      confirmedFields.length > 0
      || ambiguousFields.length > 0
      || unknownMentions.length > 0
    ) {
      const prefill = document.createElement('div');
      prefill.className = 'clarify-form-prefill';
      const prefillNote = document.createElement('div');
      prefillNote.className = 'clarify-form-prefill-note';
      prefillNote.textContent = clarifyText(
        '已根据您之前的消息识别出以下信息，请确认或修改：',
        'We noticed details from your earlier messages — please confirm or override below:',
      );
      prefill.appendChild(prefillNote);
      const prefillList = document.createElement('ul');
      prefillList.className = 'clarify-form-prefill-list';
      confirmedFields.forEach((entry) => {
        if (!entry || typeof entry.name !== 'string') return;
        const li = document.createElement('li');
        li.className = 'clarify-form-prefill-confirmed';
        // Field values may be any JSON type — coerce to a stable
        // string the user will recognise. Using textContent keeps
        // angle brackets / quotes safe (server already xml_escaped
        // free-text fields).
        const valueRepr = entry.value === null || entry.value === undefined
          ? ''
          : String(entry.value);
        const sourceLabel = entry.source || 'auto_prefill';
        li.textContent = clarifyText(
          '✓ ' + entry.name + ' = ' + valueRepr + '(来源: ' + sourceLabel + ')',
          '✓ ' + entry.name + ' = ' + valueRepr + ' (source: ' + sourceLabel + ')',
        );
        prefillList.appendChild(li);
      });
      ambiguousFields.forEach((entry) => {
        if (!entry || typeof entry.name !== 'string') return;
        const li = document.createElement('li');
        li.className = 'clarify-form-prefill-ambiguous';
        const reason = entry.reason ? ' — ' + entry.reason : '';
        li.textContent = clarifyText(
          '⚠ ' + entry.name + '：需要您填写' + reason,
          '⚠ ' + entry.name + ': needs your input' + reason,
        );
        prefillList.appendChild(li);
      });
      unknownMentions.forEach((entry) => {
        if (!entry || typeof entry.text !== 'string') return;
        const li = document.createElement('li');
        li.className = 'clarify-form-prefill-unknown';
        const guess = entry.guess
          ? clarifyText('（推测：' + entry.guess + '）', ' (looked like: ' + entry.guess + ')')
          : '';
        li.textContent = clarifyText(
          '· 我们注意到您还提到了：' + entry.text + guess,
          '· we also noticed: ' + entry.text + guess,
        );
        prefillList.appendChild(li);
      });
      prefill.appendChild(prefillList);
      card.appendChild(prefill);
    }

    const form = document.createElement('div');
    form.className = 'clarify-form-fields';
    form.setAttribute('role', 'form');

    fields.forEach((field) => {
      const row = document.createElement('div');
      row.className = 'clarify-form-row';

      const confirmedEntry = confirmedByName[field.name];
      const ambiguousEntry = ambiguousByName[field.name];

      const label = document.createElement('label');
      label.className = 'clarify-form-label';
      const requiredFlag = field.required ? ' *' : '';
      const fieldPromptText = clarifyFieldPromptText(field);
      label.textContent = clarifyFieldDisplayLabel(field) + requiredFlag;
      label.setAttribute('for', 'clarify-' + field.name);
      row.appendChild(label);

      if (field.prompt && clarifyFieldDisplayLabel(field) !== fieldPromptText) {
        const help = document.createElement('details');
        help.className = 'clarify-form-field-help';
        const helpSummary = document.createElement('summary');
        helpSummary.className = 'clarify-form-field-help-summary';
        helpSummary.textContent = clarifyText('填写要求', 'Requirements');
        help.appendChild(helpSummary);
        const helpBody = document.createElement('div');
        helpBody.className = 'clarify-form-field-help-body';
        helpBody.textContent = fieldPromptText;
        help.appendChild(helpBody);
        row.appendChild(help);
      }

      let input;
      if (field.type === 'enum' && Array.isArray(field.choices)) {
        input = document.createElement('select');
        const optionByValue = new Map();
        if (Array.isArray(field.options)) {
          field.options.forEach((option) => {
            if (!option || typeof option !== 'object') return;
            const value = option.value != null ? String(option.value) : '';
            if (!value) return;
            optionByValue.set(value, option.label != null ? String(option.label) : value);
          });
        }
        if (!field.required) {
          const blank = document.createElement('option');
          blank.value = '';
          const defaultLabel = optionByValue.get(String(field.default)) || field.default;
          blank.textContent = field.default
            ? clarifyText('(默认: ' + defaultLabel + ')', '(default: ' + defaultLabel + ')')
            : clarifyText('(可选)', '(optional)');
          input.appendChild(blank);
        }
        field.choices.forEach((choice) => {
          const choiceValue = String(choice);
          const opt = document.createElement('option');
          opt.value = choiceValue;
          opt.textContent = optionByValue.get(choiceValue)
            || localizedChoiceLabel(choiceValue, schemaLang);
          if (field.default === choice) opt.selected = true;
          input.appendChild(opt);
        });
      } else if (field.type === 'bool') {
        input = document.createElement('select');
        ['', 'true', 'false'].forEach((v) => {
          const opt = document.createElement('option');
          opt.value = v;
          opt.textContent = v === '' ? clarifyText('(未选)', '(not selected)') : v;
          if (field.default === (v === 'true')) opt.selected = true;
          input.appendChild(opt);
        });
      } else if (field.type === 'int') {
        input = document.createElement('input');
        input.type = 'number';
        if (field.min !== undefined && field.min !== null) input.min = String(field.min);
        if (field.max !== undefined && field.max !== null) input.max = String(field.max);
        if (field.default !== undefined && field.default !== null) {
          input.value = String(field.default);
        }
      } else {
        input = document.createElement('input');
        input.type = 'text';
        if (field.max_chars) input.maxLength = field.max_chars;
        if (field.default) input.value = String(field.default);
      }
      input.className = 'clarify-form-input';
      input.id = 'clarify-' + field.name;
      input.setAttribute('data-clarify-field', field.name);
      input.setAttribute('data-clarify-type', field.type);
      if (field.required) input.setAttribute('data-clarify-required', '1');

      // Auto-prefill: a confirmed value from the prefill scan wins over
      // any author-supplied default. Mark the field so the user sees
      // it's a system inference (CSS hook + data attribute) and a
      // future submit handler could distinguish "user-typed" from
      // "auto-confirmed". The user can still edit/replace as normal.
      if (confirmedEntry !== undefined) {
        const confirmedValue = confirmedEntry.value;
        if (confirmedValue !== null && confirmedValue !== undefined) {
          if (field.type === 'bool') {
            const boolStr = (confirmedValue === true || confirmedValue === 'true')
              ? 'true' : 'false';
            input.value = boolStr;
          } else {
            input.value = String(confirmedValue);
          }
        }
        input.classList.add('clarify-form-input-confirmed');
        input.setAttribute('data-clarify-confirmed', '1');
        input.setAttribute(
          'data-clarify-source', String(confirmedEntry.source || 'auto_prefill'),
        );
      }

      row.appendChild(input);

      // Inline marker line below the input — the per-row hint that
      // tells the user "we filled this from earlier context, edit
      // freely if it's wrong" or "we noticed something here but
      // couldn't pin it down".
      if (confirmedEntry !== undefined) {
        const marker = document.createElement('div');
        marker.className = 'clarify-form-row-marker clarify-form-row-marker-confirmed';
        marker.textContent = clarifyText(
          '✓ 已自动识别，可编辑修改',
          '✓ auto-detected from earlier — edit if needed',
        );
        row.appendChild(marker);
      } else if (ambiguousEntry !== undefined) {
        const marker = document.createElement('div');
        marker.className = 'clarify-form-row-marker clarify-form-row-marker-ambiguous';
        const reason = ambiguousEntry.reason
          ? clarifyText('（' + ambiguousEntry.reason + '）', ' (' + ambiguousEntry.reason + ')')
          : '';
        marker.textContent = clarifyText(
          '⚠ 不太确定，请填写' + reason,
          '⚠ unclear, please specify' + reason,
        );
        row.appendChild(marker);
      }

      form.appendChild(row);
    });

    const actions = document.createElement('div');
    actions.className = 'clarify-form-actions';

    const submitBtn = document.createElement('button');
    submitBtn.type = 'button';
    submitBtn.className = 'clarify-form-submit';
    submitBtn.textContent = clarifyText('提交', 'Submit');
    actions.appendChild(submitBtn);

    const cancelKeyword = (
      Array.isArray(schema.cancel_keywords) && schema.cancel_keywords.length > 0
        ? schema.cancel_keywords[0]
        : ''
    );
    let cancelBtn = null;
    if (cancelKeyword) {
      cancelBtn = document.createElement('button');
      cancelBtn.type = 'button';
      cancelBtn.className = 'clarify-form-cancel';
      cancelBtn.textContent = clarifyText('取消', 'Cancel');
      cancelBtn.addEventListener('click', () => {
        const sessionKey = _currentSessionKey();
        _rpc.call('chat.send', {
          message: cancelKeyword,
          sessionKey: sessionKey,
          intent: 'clarify_cancel',
        }).catch((err) => {
          UI.toast(clarifyText('取消失败: ', 'Cancel failed: ') + (err && err.message || err), 'error');
        });
        submitBtn.disabled = true;
        cancelBtn.disabled = true;
      });
      actions.appendChild(cancelBtn);
    }
    form.appendChild(actions);

    const submitStatus = document.createElement('div');
    submitStatus.className = 'clarify-form-submit-status';
    submitStatus.hidden = true;
    form.appendChild(submitStatus);

    let clarifySubmitInFlight = false;
    const waitForClarifySubmitConnection = () => Promise.race([
      _rpc.waitForConnection(),
      new Promise((_, reject) => {
        setTimeout(() => reject(new Error(clarifyText(
          '连接超时，请刷新页面后重试。',
          'Connection timed out; refresh the page and retry.',
        ))), 10000);
      }),
    ]);
    const submitClarifyForm = () => {
      if (clarifySubmitInFlight) return;
      const collected = {};
      let firstErrorEl = null;
      form.querySelectorAll('[data-clarify-field]').forEach((el) => {
        const name = el.getAttribute('data-clarify-field');
        const type = el.getAttribute('data-clarify-type');
        const required = el.getAttribute('data-clarify-required') === '1';
        let value = el.value;
        if (typeof value === 'string') value = value.trim();
        if (value === '' || value === null) {
          if (required && !firstErrorEl) firstErrorEl = el;
          return; // omit empty (RPC handler skips empties)
        }
        if (type === 'int') {
          const parsed = parseInt(value, 10);
          if (Number.isNaN(parsed)) {
            if (!firstErrorEl) firstErrorEl = el;
            return;
          }
          collected[name] = parsed;
        } else if (type === 'bool') {
          collected[name] = (value === 'true');
        } else {
          collected[name] = value;
        }
      });
      if (firstErrorEl) {
        firstErrorEl.focus();
        UI.toast(clarifyText('请检查必填字段', 'Please check required fields'), 'warn');
        return;
      }
      if (Object.keys(collected).length === 0) {
        UI.toast(clarifyText('请至少填写一个字段', 'Please fill in at least one field'), 'warn');
        return;
      }
      clarifySubmitInFlight = true;
      submitBtn.disabled = true;
      if (cancelBtn) cancelBtn.disabled = true;
      card.classList.add('clarify-form--submitting');
      submitStatus.hidden = false;
      submitStatus.textContent = clarifyText(
        '正在提交；如果连接刚恢复，会自动继续。',
        'Submitting; if the connection just recovered, this will continue automatically.',
      );
      const sessionKey = _currentSessionKey();
      waitForClarifySubmitConnection()
        .then(() => _rpc.call('chat.clarify_submit', {
          sessionKey: sessionKey,
          run_id: runId,
          fields: collected,
        }))
        .then(() => {
          clarifySubmitInFlight = false;
          card.classList.remove('clarify-form--submitting');
          card.classList.add('clarify-form--submitted');
          submitStatus.textContent = clarifyText(
            '已提交，正在继续流程...',
            'Submitted, continuing...',
          );
          UI.toast(clarifyText('已提交，正在继续流程', 'Submitted, continuing'), 'info');
        })
        .catch((err) => {
          clarifySubmitInFlight = false;
          submitBtn.disabled = false;
          if (cancelBtn) cancelBtn.disabled = false;
          card.classList.remove('clarify-form--submitting');
          submitStatus.hidden = true;
          submitStatus.textContent = '';
          UI.toast(clarifyText('提交失败: ', 'Submit failed: ') + (err && err.message || err), 'error');
        });
    };

    submitBtn.addEventListener('click', (evt) => {
      evt.preventDefault();
      submitClarifyForm();
    });
    form.addEventListener('keydown', (evt) => {
      if (evt.key !== 'Enter' || evt.shiftKey || evt.altKey || evt.ctrlKey || evt.metaKey) {
        return;
      }
      if (evt.target && evt.target.tagName === 'TEXTAREA') return;
      evt.preventDefault();
      submitClarifyForm();
    });

    card.appendChild(form);
    body.appendChild(card);
    if (_autoScroll) _scrollToBottom();
  }

  function _appendClarifySkipSummary(payload, args) {
    // Render a lightweight "trust gap" card for a user_input step
    // that was auto-skipped by its ``when:`` expression. The user
    // sees what the system inferred without the form being forced
    // back open, but still gets a clear way to undo if the
    // inference was wrong.
    const summary = args.clarify_skip_summary || {};
    const stepId = String(summary.step_id || args.skill || '');
    const fields = Array.isArray(summary.fields) ? summary.fields : [];
    const inferredFrom = Array.isArray(summary.inferred_from) ? summary.inferred_from : [];
    const trigger = String(summary.trigger_message || '');
    const label = String(summary.label || '');

    // Localise the default label when the page is Chinese.
    const pageLang = /[一-鿿]/.test(
      (trigger + ' ' + label + ' ' + (fields[0] && fields[0].prompt || '')),
    ) ? 'zh' : 'en';
    const localized = (zh, en) => pageLang === 'zh' ? zh : en;

    const bubble = _ensureStreamBubble();
    const body = bubble.querySelector('.msg-body');

    const card = document.createElement('div');
    card.className = 'clarify-skip-summary chat-tools-collapse';
    card.setAttribute('data-clarify-skip-step', stepId);

    const header = document.createElement('div');
    header.className = 'clarify-skip-summary-header';
    header.textContent = localized(
      '系统已从对话上下文中推断了答案 (' + stepId + ')',
      'System inferred answers from conversation context (' + stepId + ')',
    );
    card.appendChild(header);

    if (label) {
      const note = document.createElement('div');
      note.className = 'clarify-skip-summary-note';
      // ``label`` is server-generated copy, not user content — safe as textContent.
      note.textContent = label;
      card.appendChild(note);
    }

    if (trigger) {
      const triggerEl = document.createElement('div');
      triggerEl.className = 'clarify-skip-summary-trigger';
      triggerEl.textContent = localized('您说: ', 'You said: ') + trigger;
      card.appendChild(triggerEl);
    }

    if (fields.length > 0) {
      const fieldsHeader = document.createElement('div');
      fieldsHeader.className = 'clarify-skip-summary-fields-header';
      fieldsHeader.textContent = localized(
        '系统本可询问以下字段，但已根据上下文推断：',
        'Fields the system would have asked for, now inferred from context:',
      );
      card.appendChild(fieldsHeader);
      const fieldList = document.createElement('ul');
      fieldList.className = 'clarify-skip-summary-fields';
      fields.forEach((field) => {
        if (!field || typeof field.name !== 'string') return;
        const li = document.createElement('li');
        const requiredFlag = field.required
          ? ' ' + localized('（必填）', '(required)')
          : '';
        li.textContent = field.name + requiredFlag + (field.prompt ? ' — ' + field.prompt : '');
        fieldList.appendChild(li);
      });
      card.appendChild(fieldList);
    }

    if (inferredFrom.length > 0) {
      const inferHeader = document.createElement('div');
      inferHeader.className = 'clarify-skip-summary-inferred-header';
      inferHeader.textContent = localized(
        '推断依据：',
        'Inferred from:',
      );
      card.appendChild(inferHeader);
      inferredFrom.forEach((entry) => {
        if (!entry || typeof entry.excerpt !== 'string') return;
        const block = document.createElement('div');
        block.className = 'clarify-skip-summary-inferred-entry';
        const stepLabel = document.createElement('span');
        stepLabel.className = 'clarify-skip-summary-inferred-step';
        stepLabel.textContent = '[' + (entry.step || '') + '] ';
        block.appendChild(stepLabel);
        const excerpt = document.createElement('span');
        excerpt.className = 'clarify-skip-summary-inferred-excerpt';
        excerpt.textContent = entry.excerpt;
        block.appendChild(excerpt);
        card.appendChild(block);
      });
    }

    const hint = document.createElement('div');
    hint.className = 'clarify-skip-summary-hint';
    hint.textContent = localized(
      '若发现理解有误，请直接回复 "修改 <字段名>" 或重新描述需求。',
      'If anything looks wrong, reply "change <field>" or restate your request.',
    );
    card.appendChild(hint);

    body.appendChild(card);
    _maybeScrollToBottom();
  }

  function _currentSessionKey() {
    // Read the module-private _sessionKey populated at chat init / nav
    // (see ~line 12, 890, 933). Fallback to the documented WebChat
    // default if not yet set (rare race during very first paint).
    return _sessionKey || 'default';
  }

  function _appendArtifact(payload) {
    if (!payload) return;
    _chatDiag('artifact.append.start', _chatDiagSummarizePayload(payload));
    _streamArtifacts.push(payload);
    const bubble = _ensureStreamBubble();
    _markVisibleStreamEvent('artifact');
    const body = bubble.querySelector('.msg-body');
    body.insertAdjacentHTML('beforeend', _renderArtifacts([payload]));
    if (_autoScroll) _scrollToBottom();
    _chatDiag('artifact.append.done', _chatDiagSummarizePayload(payload));
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

  const ARTIFACT_MIME_CATEGORIES = {
    'application/json': 'data',
    'application/ndjson': 'data',
    'application/pdf': 'document',
    'application/x-ndjson': 'data',
    'text/csv': 'data',
    'text/html': 'document',
    'text/markdown': 'document',
    'text/plain': 'document',
    'text/tab-separated-values': 'data',
  };

  const ARTIFACT_EXTENSION_CATEGORIES = {
    csv: 'data',
    htm: 'document',
    html: 'document',
    ipynb: 'data',
    json: 'data',
    jsonl: 'data',
    log: 'document',
    markdown: 'document',
    md: 'document',
    ndjson: 'data',
    pdf: 'document',
    sql: 'code',
    tsv: 'data',
    txt: 'document',
  };

  function _artifactMime(artifact) {
    return artifact && artifact.mime ? String(artifact.mime).toLowerCase() : '';
  }

  function _artifactName(artifact) {
    return artifact && artifact.name ? String(artifact.name) : 'artifact';
  }

  function _artifactExtension(name) {
    const trimmed = String(name || '').trim().toLowerCase();
    const idx = trimmed.lastIndexOf('.');
    if (idx < 0 || idx === trimmed.length - 1) return '';
    return trimmed.slice(idx + 1);
  }

  function _artifactCategory(artifact) {
    const mime = _artifactMime(artifact);
    if (mime.startsWith('image/')) return 'visual';
    if (mime.startsWith('audio/')) return 'audio';
    if (ARTIFACT_MIME_CATEGORIES[mime]) return ARTIFACT_MIME_CATEGORIES[mime];
    if (!mime || mime === 'application/octet-stream' || mime === 'artifact') {
      const ext = _artifactExtension(_artifactName(artifact));
      if (['mp3', 'wav', 'm4a', 'aac', 'ogg', 'oga', 'opus', 'flac', 'webm'].includes(ext)) return 'audio';
      if (ARTIFACT_EXTENSION_CATEGORIES[ext]) return ARTIFACT_EXTENSION_CATEGORIES[ext];
    }
    return 'file';
  }

  function _artifactCategoryLabel(category) {
    switch (category) {
      case 'data': return 'data';
      case 'document': return 'doc';
      case 'code': return 'code';
      case 'audio': return 'audio';
      default: return 'file';
    }
  }

  function _isImageArtifact(artifact) {
    return _artifactCategory(artifact) === 'visual';
  }

  function _isAudioArtifact(artifact) {
    return _artifactCategory(artifact) === 'audio';
  }

  function _artifactPreviewUrl(artifact) {
    const raw = _artifactDownloadUrl(artifact);
    if (!raw) return '';
    try {
      const url = new URL(raw, window.location.origin);
      if (_sessionKey) url.searchParams.set('sessionKey', _sessionKey);
      const token = (App.getAuthToken && App.getAuthToken()) || '';
      if (token) url.searchParams.set('token', token);
      return url.pathname + url.search + url.hash;
    } catch {
      return raw;
    }
  }

  function _artifactAuthenticatedDownloadUrl(raw, token) {
    if (!raw) return '';
    try {
      const url = new URL(raw, window.location.origin);
      if (_sessionKey) url.searchParams.set('sessionKey', _sessionKey);
      if (token) url.searchParams.set('token', token);
      return url.pathname + url.search + url.hash;
    } catch {
      return raw;
    }
  }

  function _renderArtifacts(artifacts) {
    if (!Array.isArray(artifacts) || artifacts.length === 0) return '';
    if (window.ArtifactCard && typeof window.ArtifactCard.renderArtifacts === 'function') {
      return window.ArtifactCard.renderArtifacts(artifacts, {
        origin: window.location.origin,
        sessionKey: _sessionKey,
        token: (App.getAuthToken && App.getAuthToken()) || '',
      });
    }
    let html = '<div class="msg-artifacts">';
    let openGroup = '';
    const token = (App.getAuthToken && App.getAuthToken()) || '';
    const closeGroup = () => {
      if (!openGroup) return;
      html += '</div>';
      openGroup = '';
    };
    artifacts.forEach((artifact) => {
      const category = _artifactCategory(artifact);
      const groupKind = category === 'visual' ? 'visual' : 'file';
      if (groupKind !== openGroup) {
        closeGroup();
        html += groupKind === 'visual'
          ? '<div class="msg-artifact-gallery">'
          : '<div class="msg-artifact-files">';
        openGroup = groupKind;
      }
      const name = _artifactName(artifact);
      const mime = artifact && artifact.mime ? String(artifact.mime) : 'artifact';
      const size = artifact && artifact.size ? `${Math.max(1, Math.round(Number(artifact.size) / 1024))} KB` : '';
      const downloadUrl = _artifactDownloadUrl(artifact || {});
      const downloadHref = _artifactAuthenticatedDownloadUrl(downloadUrl, token);
      const meta = [mime, size].filter(Boolean).join(' · ');
      if (_isImageArtifact(artifact)) {
        const previewUrl = _artifactPreviewUrl(artifact || {});
        html += `<a class="msg-artifact-card msg-artifact-card--image" href="${_escAttr(downloadHref)}" download="${_escAttr(name)}" data-artifact-category="${_escAttr(category)}" data-artifact-download="${_escAttr(downloadUrl)}" data-artifact-id="${_escAttr(artifact?.id || '')}" data-artifact-name="${_escAttr(name)}" title="Download ${_escAttr(name)}">
          ${previewUrl ? `<img class="msg-artifact-preview" src="${_esc(previewUrl)}" alt="${_esc(name)}" loading="lazy">` : '<span class="msg-artifact-preview msg-artifact-preview--empty" aria-hidden="true"></span>'}
          <span class="msg-artifact-card__body">
            <span class="msg-artifact-card__name">${_esc(name)}</span>
            <span class="msg-artifact-card__meta">${_esc(meta)}</span>
          </span>
          <span class="msg-artifact-card__action" aria-hidden="true">Download</span>
        </a>`;
      } else if (_isAudioArtifact(artifact)) {
        html += `<div class="msg-artifact-card msg-artifact-card--audio" data-artifact-category="${_escAttr(category)}" data-artifact-id="${_escAttr(artifact?.id || '')}" data-artifact-name="${_escAttr(name)}">
          <audio class="msg-artifact-audio" controls preload="metadata" src="${_escAttr(downloadHref)}"></audio>
          <span class="msg-artifact-card__body">
            <span class="msg-artifact-card__name">${_esc(name)}</span>
            <span class="msg-artifact-card__meta">${_esc(meta)}</span>
          </span>
          <a class="msg-artifact-card__action" href="${_escAttr(downloadHref)}" download="${_escAttr(name)}" data-artifact-download="${_escAttr(downloadUrl)}">Download</a>
        </div>`;
      } else {
        html += `<a class="msg-artifact-chip" href="${_escAttr(downloadHref)}" download="${_escAttr(name)}" data-artifact-category="${_escAttr(category)}" data-artifact-download="${_escAttr(downloadUrl)}" data-artifact-id="${_escAttr(artifact?.id || '')}" data-artifact-name="${_escAttr(name)}" title="${_escAttr(name)}">
          <span class="msg-file-chip__icon" aria-hidden="true">${_esc(_artifactCategoryLabel(category))}</span>
          <span class="msg-file-chip__name">${_esc(name)}</span>
          <span class="msg-file-chip__meta">${_esc(meta)}</span>
        </a>`;
      }
    });
    closeGroup();
    html += '</div>';
    return html;
  }

  async function _downloadArtifact(artifact) {
    let downloadUrl = _artifactDownloadUrl(artifact);
    if (!downloadUrl) return;
    const headers = {};
    const token = (App.getAuthToken && App.getAuthToken()) || '';
    if (token) headers['Authorization'] = `Bearer ${token}`;
    if (_sessionKey) headers['x-opensquilla-session-key'] = _sessionKey;
    downloadUrl = _artifactAuthenticatedDownloadUrl(downloadUrl, token);
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
      const _toolInputById = {};
      for (const seg of segments) {
        if (seg.type === 'tool_use' && seg.tool_use_id) {
          _toolNameById[seg.tool_use_id] = seg.name || 'tool';
          _toolInputById[seg.tool_use_id] = seg.input || null;
        }
      }

      for (const seg of segments) {
        if (seg.type === 'text') {
          const text = _stripDirectiveTags(_stripProtocolTextLeak(seg.text || '')).trim();
          if (!text) continue;
          const textDiv = document.createElement('div');
          textDiv.className = 'msg-text-seg';
          textDiv.innerHTML = Markdown.render(text);  // eslint-disable-line no-unsanitized/property
          Markdown.bindCopy(textDiv);
          Markdown.bindHighlight(textDiv);
          body.appendChild(textDiv);
        } else if (seg.type === 'tool_use') {
          if (_isControlPlaneToolName(seg.name || '')) continue;
          if (_findToolDetailsById(body, seg.tool_use_id || '')) continue;
          const details = _buildToolCallDOM(seg.name || 'tool', seg.tool_use_id || '', seg.input || '', false);
          details._opensquillaToolInput = seg.input || null;
          body.appendChild(details);
        } else if (seg.type === 'tool_result') {
          const toolId = seg.tool_use_id || '';
          const isError = _toolResultIsError(seg);
          const content = _toolResultContent(seg);
          const resultToolName = seg.name || _toolNameById[toolId] || '';
          if (_isControlPlaneToolName(resultToolName)) continue;

          if (toolId) {
            const details = _findToolDetailsById(body, toolId);
            if (details) {
              _retitleToolCallDOM(details, resultToolName, seg.input || '');
              details._opensquillaToolInput = details._opensquillaToolInput || _toolInputById[toolId] || null;
              details.classList.remove('chat-tools-collapse--running');
              details.classList.add(_toolResultStateClass(seg));
              const toolsBody = details.querySelector('.chat-tools-body');
              const resultTarget = toolsBody || details;
              if (_findToolResultById(resultTarget, toolId)) continue;
              const clarifyArgs = _clarifyArgsFromHistoricalSegment(seg, details);
              if (clarifyArgs) {
                _appendClarifyFormToBody(body, seg, clarifyArgs);
                continue;
              }
              const resultDiv = _buildToolResultDOM(
                content,
                isError,
                _toolResultIsTruncated(seg),
                resultToolName
              );
              if (resultDiv) {
                resultDiv.setAttribute('data-tool-result-for', toolId);
                resultTarget.appendChild(resultDiv);
              }

              // web_search: inject provider badge and seed _searchProvider from persisted result
              if (resultToolName === 'web_search' && content) {
                const provider = _toolResultProvider(seg, content);
                if (provider) {
                  _setSearchProvider(provider, { refreshRunning: false });
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

    const roleText = _displayRoleLabel(displayRole);

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
      header.innerHTML = `<span class="role-label">${_esc(roleText)}</span>${_renderMessageTags(options)}<span class="msg-time">${_esc(timeStr)}</span>`;
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
    const visibleText = role === 'assistant' ? _stripGeneratedArtifactMarkers(text) : text;
    body.className = 'msg-body';
    body.textContent = '';
    if (role === 'assistant' && visibleText) {
      body.innerHTML = Markdown.render(_stripProtocolTextLeak(_stripDirectiveTags(visibleText)));
      Markdown.bindCopy(body);
      Markdown.bindHighlight(body);
    } else if (isSubagentCompletion) {
      body.appendChild(_renderSubagentDisclosure(visibleText));
    } else if (role === 'system' && visibleText) {
      body.textContent = visibleText;
    } else if (visibleText) {
      body.textContent = role === 'user' ? _stripTimePrefix(visibleText) : visibleText;
    }
  }

  function _scrollToBottom() {
    if (_thread) {
      _thread.scrollTop = _thread.scrollHeight;
    }
  }

  /* ── Attachments ────────────────────────────────────────────────────── */

  function _estimateTextTokens(text) {
    return text ? Math.max(1, Math.floor(text.length / 4)) : 0;
  }

  function _pageDumpMarkerScore(text) {
    const lowered = String(text || '').toLowerCase();
    return PAGE_DUMP_MARKERS.reduce((score, marker) => (
      lowered.includes(marker.toLowerCase()) ? score + 1 : score
    ), 0);
  }

  function _bytesToBase64(bytes) {
    const chunkSize = 0x8000;
    const chunks = [];
    for (let i = 0; i < bytes.length; i += chunkSize) {
      chunks.push(String.fromCharCode(...bytes.subarray(i, i + chunkSize)));
    }
    return btoa(chunks.join(''));
  }

  function _largePasteAttachmentName(kind) {
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').replace('T', '-').replace('Z', '');
    return `${kind === 'page_dump' ? 'webchat-page-dump' : 'webchat-paste'}-${stamp}.txt`;
  }

  function _nonNegativeInteger(value) {
    const number = Number(value);
    if (!Number.isFinite(number) || number < 0) return 0;
    return Math.floor(number);
  }

  function _inputNormalizationProvenanceFromAttachments(attachments) {
    const generated = (attachments || [])
      .filter((a) => a && a.generated === true && a.inputNormalization);
    if (!generated.length) return null;
    const meta = generated[0].inputNormalization || {};
    return {
      kind: 'web_message',
      source: 'WebChat',
      input_normalization: {
        source: 'input_normalization',
        original_chars: _nonNegativeInteger(meta.originalChars),
        material_estimated_tokens: _nonNegativeInteger(meta.materialEstimatedTokens),
        marker_score: _nonNegativeInteger(meta.markerScore),
        generated_attachment_count: generated.length,
        guard_action: meta.guardAction || 'generated_text_attachment',
      },
    };
  }

  async function _normalizeOutgoingComposerPayload(text, attachments, options = {}) {
    const raw = String(text || '');
    const markerScore = _pageDumpMarkerScore(raw);
    const isPageDump = raw.length >= PAGE_DUMP_CHARS && markerScore >= PAGE_DUMP_MARKER_MIN_SCORE;
    const isLargePaste = raw.length >= LARGE_PASTE_CHARS;
    if (options.allowSlashCommand && raw.startsWith('/')) {
      return {
        text: raw,
        displayText: raw,
        attachments: attachments.map((a) => ({ ...a })),
        normalized: null,
      };
    }
    if (!isPageDump && !isLargePaste) {
      return {
        text: raw,
        displayText: raw,
        attachments: attachments.map((a) => ({ ...a })),
        normalized: null,
      };
    }

    const kind = isPageDump ? 'page_dump' : 'large_paste';
    const bytes = new TextEncoder().encode(raw);
    const materialEstimatedTokens = _estimateTextTokens(raw);
    if (bytes.length > ATTACHMENT_TEXT_HARD_CAP_BYTES) {
      UI.toast(
        `Pasted text is too large to attach directly (${Math.round(bytes.length / 1000 / 1000)} MB). Save it as a file or send a shorter summary.`,
        'warn',
        6000,
      );
      return null;
    }

    const encoded = _bytesToBase64(bytes);
    const generatedAttachment = {
      kind: 'inline',
      local_id: _nextAttachmentId++,
      name: _largePasteAttachmentName(kind),
      mime: 'text/plain',
      size: bytes.length,
      data: encoded,
      dataUrl: `data:text/plain;base64,${encoded}`,
      generated: true,
      normalizationKind: kind,
      inputNormalization: {
        kind,
        originalChars: raw.length,
        markerScore,
        materialEstimatedTokens,
        guardAction: 'generated_text_attachment',
      },
    };
    const message = kind === 'page_dump'
      ? 'Please process the attached WebChat page dump.'
      : 'Please process the attached pasted text.';
    UI.toast('Large pasted text was attached as a .txt file.', 'info', 2500);
    return {
      text: message,
      displayText: message,
      attachments: [...attachments.map((a) => ({ ...a })), generatedAttachment],
      normalized: {
        kind,
        originalChars: raw.length,
        markerScore,
        materialEstimatedTokens,
      },
    };
  }

  function _addAttachment(file) {
    const mime = _resolveAttachmentMime(file);
    if (!_isAllowedAttachmentMime(mime)) {
      UI.toast(`Unsupported file: ${file.name || 'attachment'} (${mime}). Allowed: ${ATTACHMENT_ALLOWED_LABEL}`, 'warn', 4500);
      return false;
    }
    const hardCap = _attachmentHardCapBytes(mime);
    if (file.size > hardCap) {
      UI.toast(`File too large: ${file.name || 'attachment'} (max ${Math.round(hardCap / 1024 / 1024)} MB)`, 'warn');
      return false;
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
      return true;
    }

    if (!_canStageAttachmentMime(mime)) {
      UI.toast(
        `File too large: ${file.name || 'attachment'} (text-family attachments are limited to ${Math.round(ATTACHMENT_TEXT_HARD_CAP_BYTES / 1000 / 1000)} MB)`,
        'warn',
        4500,
      );
      return false;
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
    return true;
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

  async function _onVoiceInputToggle() {
    if (_voiceInputBusy) return;
    if (_mediaRecorder && _mediaRecorder.state === 'recording') {
      _mediaRecorder.stop();
      return;
    }
    await _startVoiceInputRecording();
  }

  async function _startVoiceInputRecording() {
    if (!window.isSecureContext && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
      UI.toast('Voice input requires HTTPS on public URLs.', 'warn', 4500);
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || typeof MediaRecorder === 'undefined') {
      UI.toast('Voice input is not available in this browser.', 'warn', 3500);
      return;
    }
    try {
      _voiceInputBusy = true;
      _setVoiceInputState('requesting');
      _recordedAudioChunks = [];
      _recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported('audio/webm')
        ? 'audio/webm'
        : '';
      _mediaRecorder = mimeType
        ? new MediaRecorder(_recordingStream, { mimeType })
        : new MediaRecorder(_recordingStream);
      _mediaRecorder.addEventListener('dataavailable', (event) => {
        if (event.data && event.data.size > 0) _recordedAudioChunks.push(event.data);
      });
      _mediaRecorder.addEventListener('stop', () => {
        _finishVoiceInputRecording().catch((err) => {
          UI.toast(`Voice transcription failed: ${err && err.message || err}`, 'warn', 4500);
          _setVoiceInputState('idle');
        });
      }, { once: true });
      _mediaRecorder.start();
      _setVoiceInputState('recording');
      UI.toast('Recording voice input...', 'info', 1600);
    } catch (err) {
      UI.toast(`Could not start voice input: ${err && err.message || err}`, 'warn', 4500);
      _stopVoiceInputTracks();
      _setVoiceInputState('idle');
    } finally {
      _voiceInputBusy = false;
    }
  }

  async function _finishVoiceInputRecording() {
    _stopVoiceInputTracks();
    const mime = (_mediaRecorder && _mediaRecorder.mimeType) || 'audio/webm';
    _mediaRecorder = null;
    if (!_recordedAudioChunks.length) {
      _setVoiceInputState('idle');
      UI.toast('No voice audio was recorded.', 'warn', 2500);
      return;
    }
    _setVoiceInputState('transcribing');
    _voiceInputBusy = true;
    try {
      const blob = new Blob(_recordedAudioChunks, { type: mime });
      const text = await _transcribeVoiceInput(blob, mime);
      if (!text) {
        UI.toast('Voice transcription returned no text.', 'warn', 3000);
        return;
      }
      _appendTranscribedText(text);
      UI.toast('Voice input transcribed.', 'info', 2200);
    } finally {
      _recordedAudioChunks = [];
      _voiceInputBusy = false;
      _setVoiceInputState('idle');
    }
  }

  async function _transcribeVoiceInput(blob, mime) {
    const ext = mime.includes('mp4') ? 'm4a' : mime.includes('wav') ? 'wav' : 'webm';
    const form = new FormData();
    form.append('file', blob, `voice_input.${ext}`);
    const headers = {};
    const token = (App.getAuthToken && App.getAuthToken()) || '';
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const response = await fetch('/api/audio/transcribe', {
      method: 'POST',
      body: form,
      headers: headers,
      credentials: 'same-origin',
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    return String(payload.text || '').trim();
  }

  function _appendTranscribedText(text) {
    if (!_textarea) return;
    const current = _textarea.value.trim();
    const next = current ? `${current}\n${text}` : text;
    _textarea.value = next;
    _textarea.dispatchEvent(new Event('input', { bubbles: true }));
    _textarea.focus();
    _textarea.setSelectionRange(next.length, next.length);
  }

  function _setVoiceInputState(state) {
    if (!_micBtn) return;
    const recording = state === 'recording';
    const busy = state === 'requesting' || state === 'transcribing';
    _micBtn.classList.toggle('chat-mic-recording', recording);
    _micBtn.disabled = busy;
    _micBtn.title = recording
      ? 'Stop recording'
      : state === 'transcribing'
        ? 'Transcribing voice input'
        : 'Record voice input';
    _micBtn.setAttribute('aria-label', recording ? 'Stop recording voice input' : 'Record voice input');
  }

  function _stopVoiceInputTracks() {
    if (_recordingStream && _recordingStream.getTracks) {
      _recordingStream.getTracks().forEach((track) => track.stop());
    }
    _recordingStream = null;
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

  function _attachmentDownloadName(att) {
    const raw = String(att && att.name || 'attachment').trim();
    return raw || 'attachment';
  }

  function _attachmentDownloadHref(att, mime) {
    if (!att) return '';
    if (att.dataUrl) {
      const dataUrl = String(att.dataUrl).trim();
      return /^javascript:/i.test(dataUrl) ? '' : dataUrl;
    }
    if (att.data) {
      return `data:${_escAttr(mime || 'application/octet-stream')};base64,${String(att.data)}`;
    }
    const url = String(att.url || att.download_url || att.downloadUrl || '').trim();
    if (url && !/^javascript:/i.test(url)) return url;
    return '';
  }

  function _renderMessageAttachmentHtml(att) {
    const mime = att.type || att.mime || '';
    const name = att.name || 'attachment';
    if ((mime || '').startsWith('image/') && (att.dataUrl || att.data)) {
      const src = att.dataUrl || `data:${_esc(mime || 'image/png')};base64,${att.data}`;
      return `<img class="msg-thumb" src="${src}" alt="${_esc(name)}">`;
    }
    const downloadName = _attachmentDownloadName(att);
    const downloadHref = _attachmentDownloadHref(att, mime);
    const inner = `
      <span class="msg-file-chip__icon" aria-hidden="true">file</span>
      <span class="msg-file-chip__name">${_esc(name)}</span>
      <span class="msg-file-chip__meta">${_esc(mime || 'attachment')}</span>`;
    if (downloadHref) {
      return `<a class="msg-file-chip msg-file-chip--download" title="${_escAttr(name)}" href="${_escAttr(downloadHref)}" download="${_escAttr(downloadName)}">${inner}</a>`;
    }
    return `<span class="msg-file-chip msg-file-chip--disabled" title="${_escAttr(name)}">${inner}</span>`;
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
          <button class="attachment-remove" data-idx="${i}" aria-label="Remove attachment ${_esc(att.name)}">&times;</button>
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
          <button class="attachment-remove" data-idx="${i}" title="Remove" aria-label="Remove attachment ${_esc(att.name)}">&times;</button>
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
      const role = _displayRoleLabel(msg.role) || msg.role;
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

  /* ── Pending Queue ──────────────────────────────────────────────────── */

  function _onStop(source = 'webui_stop_button') {
    if (!_isStreaming) return;
    if (typeof source !== 'string' || !source) source = 'webui_stop_button';
    _stopRequestedByUser = true;
    _aborted = true;
    _rpc.call('chat.abort', { sessionKey: _sessionKey, source }).catch(() => {});
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
      _clearPendingDrainAfterTerminalTimer();
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
      const raw = p.displayText || p.text || (p.attachments && p.attachments.length ? '(attachment only)' : '');
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

  function _enqueuePendingInput(
    text,
    toastMessage = null,
    waitReason = 'the current response',
    attachmentsOverride = null,
    displayTextOverride = null,
    intentOverride = undefined,
    preserveComposer = false,
  ) {
    if (_pendingQueue.length >= _MAX_PENDING) {
      UI.toast(
        `Pending queue full (${_MAX_PENDING}). Wait for ${waitReason} or clear.`,
        'warning',
        3000,
      );
      return false;
    }
    const queuedAttachments = attachmentsOverride || _pendingAttachments;
    _pendingQueue.push({
      text,
      displayText: displayTextOverride,
      attachments: queuedAttachments.map((a) => ({ ...a })),
      intent: intentOverride === undefined ? _pendingSessionIntent : intentOverride,
      hiddenControl: preserveComposer === true,
    });
    if (!preserveComposer) {
      _textarea.value = '';
      _pendingAttachments = [];
      if (intentOverride === undefined) _pendingSessionIntent = null;
      _renderAttachmentPreview();
      _autoResizeTextarea();
    }
    _renderPendingQueue();
    UI.toast(toastMessage || `Queued (${_pendingQueue.length}/${_MAX_PENDING})`, 'info', 1500);
    return true;
  }

  function _drainQueueHead() {
    // Only called on natural (non-aborted) turn completion.
    _clearPendingDrainAfterTerminalTimer();
    if (_pendingQueue.length === 0) return;
    const head = _pendingQueue.shift();
    _renderPendingQueue();
    setTimeout(() => {
      const draftText = _textarea.value;
      const draftAttachments = _pendingAttachments.map(att => ({ ...att }));
      const draftIntent = _pendingSessionIntent;
      if (head.hiddenControl) {
        _sendTextOverride = head.text || '';
        _sendDisplayTextOverride = typeof head.displayText === 'string' ? head.displayText : null;
        _onSend();
      } else {
        _textarea.value = head.text || '';
        _sendDisplayTextOverride = typeof head.displayText === 'string' ? head.displayText : null;
        _pendingAttachments = head.attachments || [];
        _pendingSessionIntent = head.intent || null;
        _renderAttachmentPreview();
        _onSend();
      }
      if (draftText.trim() || draftAttachments.length || draftIntent) {
        _textarea.value = draftText;
        _pendingAttachments = draftAttachments;
        _pendingSessionIntent = draftIntent;
        _renderAttachmentPreview();
        _autoResizeTextarea();
      }
    }, 0);
  }

  function _popPendingTail() {
    if (_pendingQueue.length === 0) return false;
    const tail = _pendingQueue.pop();
    _textarea.value = tail.hiddenControl
      ? (tail.displayText || '')
      : (tail.text || '');
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
  // Queued texts join the
  // current textarea content with newlines (FIFO), attachments stack into
  // _pendingAttachments, and the queue is cleared. The caller decides
  // whether to send — recovery never auto-fires. Returns true when the
  // queue had something to recover.
  function _popAllPendingIntoComposer() {
    _clearPendingDrainAfterTerminalTimer();
    if (!_textarea || _pendingQueue.length === 0) return false;
    const queuedTexts = _pendingQueue
      .map((p) => {
        if (typeof p.displayText === 'string') return p.displayText;
        return typeof p.text === 'string' ? p.text : '';
      })
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

  function _recoverPendingAfterTerminal(status = 'failed') {
    const recovered = _popAllPendingIntoComposer();
    if (recovered) {
      const label = _runStatusLabel(_normalizeRunStatus(status)).toLowerCase();
      UI.toast(`Pending message recovered after ${label}`, 'warn', 2500);
    }
    return recovered;
  }

  function _clearPendingDrainAfterTerminalTimer() {
    if (_pendingDrainAfterTerminalTimer) {
      clearTimeout(_pendingDrainAfterTerminalTimer);
      _pendingDrainAfterTerminalTimer = null;
    }
  }

  function _schedulePendingDrainAfterTerminal() {
    if (_pendingQueue.length === 0) return;
    _clearPendingDrainAfterTerminalTimer();
    _pendingDrainAfterTerminalTimer = setTimeout(() => {
      _pendingDrainAfterTerminalTimer = null;
      if (_isStreaming || _isCompactInFlightForCurrentSession() || _pendingQueue.length === 0) return;
      _drainQueueHead();
    }, 50);
  }

  function _setCompactInFlight(active, key = _sessionKey) {
    _compactInFlight = !!active;
    _compactInFlightKey = active ? String(key || _sessionKey || '') : '';
    _updateSendButton();
  }

  function _isCompactInFlightForCurrentSession() {
    if (!_compactInFlight) return false;
    return !_compactInFlightKey || _compactInFlightKey === _sessionKey;
  }

  function _settleCompactInFlight(payload = {}, options = {}) {
    const key = String(payload && payload.key || _compactInFlightKey || _sessionKey || '');
    if (!_compactInFlight || (_compactInFlightKey && key && key !== _compactInFlightKey)) {
      return false;
    }
    _setCompactInFlight(false);
    const status = String(payload && payload.status || '').toLowerCase();
    const compactedFlag = payload && Object.prototype.hasOwnProperty.call(payload, 'compacted')
      ? !!payload.compacted
      : null;
    let recovered = false;
    if (
      status === 'completed' ||
      status === 'skipped' ||
      (status === '' && compactedFlag !== null)
    ) {
      _schedulePendingDrainAfterTerminal();
    } else if (options && options.preservePending) {
      recovered = _pendingQueue.length > 0;
    } else if (options && options.recoverPending) {
      recovered = _popAllPendingIntoComposer();
    }
    if (_isStreaming && !_streamBubble) _showThinkingIndicator();
    return recovered;
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
  async function _enqueueCurrentInput() {
    let text = _textarea.value.trim();
    let hasPayload = text || _pendingAttachments.length > 0;
    let isLiteralSlash = false;
    if (text.startsWith('//')) {
      isLiteralSlash = true;
      text = text.slice(1);
      hasPayload = text || _pendingAttachments.length > 0;
    }
    const isSlashCommand = !isLiteralSlash && text.startsWith('/')
      && !!(await _lookupSlashCommand(text));
    if (!hasPayload) return false;
    const normalized = await _normalizeOutgoingComposerPayload(
      text,
      _pendingAttachments,
      { allowSlashCommand: isSlashCommand },
    );
    if (!normalized) return false;
    text = normalized.text;
    _pendingAttachments = normalized.attachments;
    return _enqueuePendingInput(text, null, 'the current response', normalized.attachments);
  }

  function _updateStopButton() {
    if (!_stopBtn) return;
    _stopBtn.classList.toggle('hidden', !_isStreaming);
  }

  /* ── Destroy ────────────────────────────────────────────────────────── */

  function destroy() {
    if (App.clearTopbarCenter) App.clearTopbarCenter();
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
    _clearStreamActiveMarkReveal();
    _hideThinkingIndicator();
    _cancelPendingRouterFxScan('destroy');
    if (_renderRafId) { cancelAnimationFrame(_renderRafId); _renderRafId = null; }
    _renderDirty = false;
    _closeSlashMenu();
    _clearPendingDrainAfterTerminalTimer();
    _setCompactInFlight(false);
    _hideCompactionSeparator();
    _pendingAttachments = [];
    _pendingQueue = [];
    _stopRequestedByUser = false;
    _messages = [];
    _clearContextStatus();
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
    _runModeControl = null;
    _sandboxSetupBanner = null;
    _composer = null;
    _streamBubble = null;
    _streamSessionKey = '';
    _streamRaw = '';
    _segments = []; _activeTextSeg = null; _activeTextRaw = '';
    _streamArtifacts = [];
    _lastVisibleStreamEvent = '';
    _liveStreamStateBySession.clear();
    _streamSeqBySession.clear();
    _lastStreamSeq = 0;
    _el = null;
    _rpc = null;
  }

  return { render, destroy };
})();

window.ChatView = ChatView;
