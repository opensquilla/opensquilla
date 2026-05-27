/** OpenSquilla Web UI — Usage Analytics view (FE-006). */

const UsageView = (() => {
  let _el = null;
  let _rpc = null;
  let _unsubs = [];
  let _intervals = [];

  // State
  let _currency = localStorage.getItem('opensquilla-currency') || 'USD';
  let _sessions = [];
  let _sortCol = 'updated_at';
  let _sortAsc = false;
  let _chartMode = 'tokens';  // 'tokens' | 'cost'
  let _range = _normalizeRange(localStorage.getItem('opensquilla-usage-range'));

  // Single source of truth: window.SquillaConstants.CNY_RATE (constants.js).
  // Captured into a local for hot paths so we don't dereference globals per row.
  const CNY_RATE = (window.SquillaConstants && window.SquillaConstants.CNY_RATE) || 7.25;
  const USAGE_SESSION_TABLE_COLUMNS = [
    { key: 'session', label: 'Session' },
    { key: 'updated_at', label: 'Modified' },
    { key: 'input_tokens', label: 'Input' },
    { key: 'output_tokens', label: 'Output' },
    { key: 'cache_read_tokens', label: 'Cache R' },
    { key: 'cache_write_tokens', label: 'Cache W' },
    { key: 'cost_usd', label: 'Cost' },
    { key: 'cost_source', label: 'Source' },
    { key: 'model', label: 'Model' },
  ];

  function render(el) {
    _el = el;
    _rpc = App.getRpc();

    _el.innerHTML = `
      <div class="usage-stage">
        <header class="usage-stage__header">
          <div class="usage-stage__title-block">
            <span class="usage-stage__eyebrow">Control · Analytics</span>
            <h2 class="usage-stage__title">Usage</h2>
            <p class="usage-stage__subtitle">Tokens, cost, and per-model spend across every session.</p>
            <!-- Surface the undated/legacy filter notice in the page toolbar instead of
                 burying it in the chart legend — it applies to the whole view's filtered set. -->
            <small class="usage-range-notice" id="usage-range-hint" aria-live="polite"></small>
          </div>
          <div class="usage-stage__actions mobile-action-strip">
            <div class="usage-currency mobile-action-strip__item" role="group" aria-label="Currency">
              <button class="usage-currency__btn" data-cur="USD" title="US Dollar">$ USD</button>
              <button class="usage-currency__btn" data-cur="CNY" title="Chinese Yuan">¥ CNY</button>
            </div>
            <button class="btn btn--ghost mobile-action-strip__button" id="usage-export" title="Download CSV">
              ${icons.download()}<span class="mobile-action-strip__label">Export</span>
            </button>
            <button class="btn btn--ghost mobile-action-strip__button" id="usage-refresh" title="Refresh">
              ${icons.refresh()}<span class="mobile-action-strip__label">Refresh</span>
            </button>
          </div>
        </header>

        <section class="stat-row" id="usage-metrics">
          <div class="stat stat--hero">
            <div class="stat-label">Total tokens</div>
            <div class="stat-value" id="usage-total-tokens">—</div>
            <div class="stat-hint" id="usage-tokens-breakdown"></div>
          </div>
          <div class="stat">
            <div class="stat-label">Total cost</div>
            <div class="stat-value mono" id="usage-total-cost">—</div>
            <div class="stat-hint" id="usage-cost-hint"></div>
          </div>
          <div class="stat">
            <div class="stat-label">Sessions</div>
            <div class="stat-value" id="usage-session-count">—</div>
            <div class="stat-hint" id="usage-sessions-hint">across all models</div>
          </div>
          <div class="stat">
            <div class="stat-label">Avg cost / session</div>
            <div class="stat-value mono" id="usage-avg-cost">—</div>
            <div class="stat-hint">running average</div>
          </div>
        </section>

        <section class="usage-chart">
          <div class="usage-chart__head">
            <div class="usage-segs" role="tablist" aria-label="Chart metric">
              <button class="usage-seg is-active" data-mode="tokens" role="tab">Tokens</button>
              <button class="usage-seg" data-mode="cost" role="tab">Cost</button>
            </div>
            <div class="usage-range" role="tablist" aria-label="Date range">
              <button class="usage-range__btn${_range === 'all' ? ' is-active' : ''}" data-range="all" role="tab">All</button>
              <button class="usage-range__btn${_range === '7' ? ' is-active' : ''}" data-range="7" role="tab">7d</button>
              <button class="usage-range__btn${_range === '14' ? ' is-active' : ''}" data-range="14" role="tab">14d</button>
              <button class="usage-range__btn${_range === '30' ? ' is-active' : ''}" data-range="30" role="tab">30d</button>
            </div>
          </div>
          <div class="usage-chart__legend" id="usage-bar-legend">
            <span class="usage-chart__legend-item"><span class="usage-chart__swatch usage-chart__swatch--input"></span>Input</span>
            <span class="usage-chart__legend-item"><span class="usage-chart__swatch usage-chart__swatch--output"></span>Output</span>
            <span class="usage-chart__legend-spacer"></span>
            <span class="usage-chart__caption" id="usage-chart-caption">Top sessions by total tokens</span>
          </div>
          <div id="usage-chart" class="usage-bars"></div>
        </section>

        <section class="usage-models">
          <div class="usage-section-head">
            <h3 class="usage-section-title">By model</h3>
            <span class="usage-section-meta" id="usage-models-meta">—</span>
          </div>
          <div id="usage-model-grid" class="usage-model-grid"></div>
        </section>

        <section class="usage-sessions">
          <div class="usage-section-head">
            <h3 class="usage-section-title">Sessions</h3>
            <span class="usage-section-meta" id="usage-sessions-meta">—</span>
          </div>
          <div id="usage-table-wrap" class="usage-table-wrap"></div>
        </section>
      </div>`;

    _el.querySelector('#usage-refresh').addEventListener('click', _loadData);
    _el.querySelector('#usage-export').addEventListener('click', _exportCsv);
    _el.querySelectorAll('.usage-currency__btn').forEach(btn => {
      btn.addEventListener('click', () => _setCurrency(btn.dataset.cur));
    });

    _el.querySelectorAll('.usage-seg').forEach(btn => {
      btn.addEventListener('click', () => {
        _chartMode = btn.dataset.mode;
        _el.querySelectorAll('.usage-seg').forEach(b => b.classList.toggle('is-active', b === btn));
        _renderChart();
        _renderChartCaption();
      });
    });

    _el.querySelectorAll('.usage-range__btn').forEach(btn => {
      btn.addEventListener('click', () => {
        _range = _normalizeRange(btn.dataset.range);
        localStorage.setItem('opensquilla-usage-range', _range);
        _updateRangeBtns();
        _renderUsageSections();
      });
    });

    _updateCurrencyBtns();
    _updateRangeBtns();
    _renderChartCaption();
    _renderRangeHint();
    _loadData();

    const id = setInterval(_loadData, 60000);
    _intervals.push(id);

    // Resume immediately when the tab becomes visible, instead of waiting up
    // to 60s for the next interval. The polling early-return inside _loadData
    // skips fetches while hidden; this listener pairs with that to make the
    // pause/resume cycle feel instantaneous to the user.
    if (typeof document !== 'undefined') {
      _onVisibilityChange = () => {
        if (document.visibilityState === 'visible') _loadData();
      };
      document.addEventListener('visibilitychange', _onVisibilityChange);
    }
  }

  function destroy() {
    _unsubs.forEach(fn => fn());
    _unsubs = [];
    _intervals.forEach(id => clearInterval(id));
    _intervals = [];
    if (_onVisibilityChange && typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', _onVisibilityChange);
    }
    _onVisibilityChange = null;
    _sessions = [];
    _el = null;
    _rpc = null;
  }

  function _setCurrency(cur) {
    if (cur !== 'USD' && cur !== 'CNY') return;
    _currency = cur;
    localStorage.setItem('opensquilla-currency', _currency);
    _updateCurrencyBtns();
    _renderUsageSections();
  }

  function _updateCurrencyBtns() {
    if (!_el) return;
    _el.querySelectorAll('.usage-currency__btn').forEach(btn => {
      btn.classList.toggle('is-active', btn.dataset.cur === _currency);
    });
  }

  function _normalizeRange(range) {
    const value = String(range || '7');
    return ['all', '7', '14', '30'].includes(value) ? value : '7';
  }

  function _updateRangeBtns() {
    if (!_el) return;
    _el.querySelectorAll('.usage-range__btn').forEach(btn => {
      btn.classList.toggle('is-active', btn.dataset.range === _range);
    });
  }

  function _fmtCost(usd, opts) {
    if (usd == null) return '—';
    const n = Number(usd);
    const decimals = (opts && opts.decimals != null) ? opts.decimals : 4;
    if (_currency === 'CNY') {
      return '¥' + (n * CNY_RATE).toFixed(decimals);
    }
    return '$' + n.toFixed(decimals);
  }

  function _rowVal(row, ...keys) {
    for (const key of keys) {
      if (row[key] != null) return row[key];
    }
    return null;
  }

  function _numericRowVal(row, ...keys) {
    const value = _rowVal(row, ...keys);
    if (value == null || value === '') return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function _sessionTimestamp(row) {
    for (const key of ['endedAt', 'ended_at', 'updatedAt', 'updated_at', 'startedAt', 'started_at', 'createdAt', 'created_at']) {
      const value = _numericRowVal(row, key);
      if (value != null) return value;
    }
    return null;
  }

  function _rangeCutoffMs(range) {
    const activeRange = _normalizeRange(range || _range);
    if (activeRange === 'all') return null;
    return Date.now() - (Number(activeRange) * 86400000);
  }

  // Per-render cache: _renderUsageSections sets this once at the top so that
  // _renderMetrics / _renderTable / _renderChart / _renderModelBreakdown all
  // share one filtered array instead of recomputing the filter 5 times.
  // Cleared at the end of the render pass — outside that window we always
  // recompute from _sessions to avoid stale reads.
  let _visibleCache = null;
  function _visibleSessions() {
    if (_visibleCache !== null) return _visibleCache;
    const cutoff = _rangeCutoffMs(_range);
    if (cutoff == null) return _sessions;
    return _sessions.filter(row => {
      const timestamp = _sessionTimestamp(row);
      return timestamp != null && timestamp >= cutoff;
    });
  }

  function _undatedHiddenCount() {
    if (_range === 'all') return 0;
    return _sessions.filter(row => _sessionTimestamp(row) == null).length;
  }

  function _usageTotals(rows) {
    return rows.reduce((acc, row) => {
      acc.input += Number(_rowVal(row, 'input_tokens', 'inputTokens') || 0);
      acc.output += Number(_rowVal(row, 'output_tokens', 'outputTokens') || 0);
      acc.cost += Number(_rowVal(row, 'cost_usd', 'costUsd') || 0);
      acc.cacheRead += Number(_rowVal(row, 'cache_read_tokens', 'cacheReadTokens') || 0);
      acc.cacheWrite += Number(_rowVal(row, 'cache_write_tokens', 'cacheWriteTokens') || 0);
      return acc;
    }, { input: 0, output: 0, cost: 0, cacheRead: 0, cacheWrite: 0, sessions: rows.length });
  }

  function _rangeHiddenHint() {
    const hidden = _undatedHiddenCount();
    if (hidden <= 0) return '';
    return `${hidden} undated legacy session${hidden === 1 ? '' : 's'} hidden`;
  }

  function _renderRangeHint() {
    const hint = _el && _el.querySelector('#usage-range-hint');
    if (!hint) return;
    hint.textContent = _rangeHiddenHint();
  }

  function _costSource(row) {
    return String(_rowVal(row, 'cost_source', 'costSource') || 'none');
  }

  function _costSourceClass(source) {
    const known = ['provider_billed', 'provider_billed_prorated', 'opensquilla_estimate', 'mixed', 'unavailable', 'none'];
    if (known.includes(source)) return source;
    return 'none';
  }

  function _costSourceLabel(source, ephemeral) {
    if (ephemeral) return 'Ephemeral';
    switch (source) {
      case 'provider_billed': return 'Actual';
      // Same "Actual" label: the total is still the real billed amount; only
      // the per-model split is estimated. The badge stays visually distinct
      // via .usage-source--provider_billed_prorated (dashed border) and the
      // tooltip explains the nuance.
      case 'provider_billed_prorated': return 'Actual';
      case 'opensquilla_estimate': return 'Estimated';
      case 'mixed': return 'Mixed';
      case 'unavailable': return 'Unpriced';
      default: return 'None';
    }
  }

  function _costSourceTooltip(source, ephemeral) {
    if (ephemeral) return 'Ephemeral session — cost not yet persisted';
    switch (source) {
      case 'provider_billed': return 'Actual — cost billed by the provider';
      case 'provider_billed_prorated': return 'Total is real billed; per-model split is estimated.';
      case 'opensquilla_estimate': return 'Estimated — derived locally from token counts';
      case 'mixed': return 'Mixed — partial billing data, rest estimated';
      case 'unavailable': return 'Unpriced — no pricing table entry for this model';
      default: return 'No cost recorded';
    }
  }

  function _renderCostSourceBadge(row) {
    const source = _costSource(row);
    const ephemeral = Boolean(_rowVal(row, 'cost_ephemeral', 'costEphemeral'));
    const label = _costSourceLabel(source, ephemeral);
    const tooltip = _costSourceTooltip(source, ephemeral);
    return `<span class="usage-source usage-source--${_costSourceClass(source)}${ephemeral ? ' usage-source--ephemeral' : ''}" title="${_esc(tooltip)}">${_esc(label)}</span>`;
  }

  function _sourceCompositionHint(rows) {
    const counts = { Actual: 0, Estimated: 0, Mixed: 0, Unpriced: 0, Ephemeral: 0 };
    rows.forEach(row => {
      const label = _costSourceLabel(_costSource(row), Boolean(_rowVal(row, 'cost_ephemeral', 'costEphemeral')));
      if (counts[label] != null) counts[label] += 1;
    });
    return Object.entries(counts)
      .filter(([, n]) => n > 0)
      .map(([label, n]) => `${label.toLowerCase()} ${n}`)
      .join(' · ');
  }

  function _sortVal(row, key) {
    switch (key) {
      case 'session':
        return _rowVal(row, 'session', 'sessionKey', 'key') || '';
      case 'updated_at':
        return _sessionTimestamp(row) || 0;
      case 'input_tokens':
        return Number(_rowVal(row, 'input_tokens', 'inputTokens') || 0);
      case 'output_tokens':
        return Number(_rowVal(row, 'output_tokens', 'outputTokens') || 0);
      case 'cache_read_tokens':
        return Number(_rowVal(row, 'cache_read_tokens', 'cacheReadTokens') || 0);
      case 'cache_write_tokens':
        return Number(_rowVal(row, 'cache_write_tokens', 'cacheWriteTokens') || 0);
      case 'cost_usd':
        return Number(_rowVal(row, 'cost_usd', 'costUsd') || 0);
      default:
        return _rowVal(row, key) || '';
    }
  }

  // Cache last data for currency re-render
  let _lastStatus = null;
  // visibilitychange listener handle so destroy() can detach cleanly.
  let _onVisibilityChange = null;

  async function _loadData() {
    if (!_el) return;
    // Skip polling while the tab is hidden. The 60s interval still fires but
    // costs ~nothing; we resume on visibilitychange via the listener below.
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
    await _rpc.waitForConnection();

    // usage.cost is a backend RPC still consumed by CLI / chat slash / HTTP /api/usage,
    // but this view derives every visible metric from usage.status.sessions. Calling
    // both used to double the polling cost for no rendering benefit.
    _rpc.call('usage.status').then(status => {
      if (!_el) return;
      _lastStatus = status;
      _sessions = status.sessions || [];
      _renderUsageSections();
    }).catch(err => UI.toast('Failed to load usage: ' + err.message, 'err'));
  }

  function _renderUsageSections() {
    // Cache the filtered session list once per render batch so the 5 leaf
    // renderers don't each recompute it. See note on `_visibleCache` above.
    _visibleCache = null;
    _visibleCache = _visibleSessions();
    try {
      _renderMetrics(_lastStatus);
      _renderTable();
      _renderChart();
      _renderChartCaption();
      _renderRangeHint();
      _renderModelBreakdown();
    } finally {
      _visibleCache = null;
    }
  }

  function _renderMetrics(status) {
    if (!_el) return;

    const visibleRows = _visibleSessions();
    const totals = _usageTotals(visibleRows);
    const totalIn = totals.input;
    const totalOut = totals.output;
    const totalCache = totals.cacheRead;
    const totalWrite = totals.cacheWrite;
    const totalTokens = totalIn + totalOut;
    const totalCostUsd = totals.cost;
    const sessionCount = totals.sessions;
    const avgCost = sessionCount > 0 ? totalCostUsd / sessionCount : null;

    const tokEl = _el.querySelector('#usage-total-tokens');
    const costEl = _el.querySelector('#usage-total-cost');
    const sessEl = _el.querySelector('#usage-session-count');
    const brkEl = _el.querySelector('#usage-tokens-breakdown');
    const costHintEl = _el.querySelector('#usage-cost-hint');
    const avgEl = _el.querySelector('#usage-avg-cost');

    if (tokEl) tokEl.textContent = totalTokens != null ? totalTokens.toLocaleString() : '—';
    if (costEl) costEl.textContent = _fmtCost(totalCostUsd, { decimals: 4 });
    if (sessEl) sessEl.textContent = sessionCount != null ? String(sessionCount) : '—';
    if (avgEl) avgEl.textContent = avgCost != null ? _fmtCost(avgCost, { decimals: 4 }) : '—';

    if (brkEl) {
      const parts = [];
      if (totalIn != null) parts.push(`<span><em>In</em> ${totalIn.toLocaleString()}</span>`);
      if (totalOut != null) parts.push(`<span><em>Out</em> ${totalOut.toLocaleString()}</span>`);
      if (totalCache) parts.push(`<span><em>Cache R</em> ${totalCache.toLocaleString()}</span>`);
      if (totalWrite) parts.push(`<span><em>Cache W</em> ${totalWrite.toLocaleString()}</span>`);
      brkEl.innerHTML = parts.join('<span>·</span>');
    }

    if (costHintEl) {
      const sourceHint = _sourceCompositionHint(visibleRows);
      let currencyHint = '';
      if (_currency === 'CNY') {
        currencyHint = `≈ ${('$' + Number(totalCostUsd).toFixed(4))} USD`;
      } else if (_currency === 'USD') {
        currencyHint = `≈ ¥${(Number(totalCostUsd) * CNY_RATE).toFixed(4)} CNY`;
      }
      costHintEl.textContent = [currencyHint, sourceHint].filter(Boolean).join(' · ');
      // Disclose that CNY values use a baked-in rate so users don't mistake
      // the estimate for live FX. Source: static/js/constants.js (CNY_RATE).
      const rateSetAt = (window.SquillaConstants && window.SquillaConstants.CNY_RATE_SET_AT) || '';
      costHintEl.title = `CNY values use baked-in rate ${CNY_RATE}` +
        (rateSetAt ? ` (set ${rateSetAt}). ` : '. ') +
        'Verify against current FX for accounting use.';
    }
  }

  function _renderTable() {
    const wrap = _el && _el.querySelector('#usage-table-wrap');
    const meta = _el && _el.querySelector('#usage-sessions-meta');
    if (!wrap) return;

    const visibleRows = _visibleSessions();
    const sorted = [...visibleRows].sort((a, b) => {
      let va = _sortVal(a, _sortCol);
      let vb = _sortVal(b, _sortCol);
      if (typeof va === 'string') va = va.toLowerCase();
      if (typeof vb === 'string') vb = vb.toLowerCase();
      const cmp = va < vb ? -1 : va > vb ? 1 : 0;
      return _sortAsc ? cmp : -cmp;
    });

    if (meta) {
      meta.textContent = [`${sorted.length} session${sorted.length === 1 ? '' : 's'}`, _rangeHiddenHint()]
        .filter(Boolean)
        .join(' · ');
    }

    const sortable = ['session', 'updated_at', 'input_tokens', 'output_tokens', 'cost_usd', 'model'];

    let html = '<table class="usage-table"><thead><tr>';
    USAGE_SESSION_TABLE_COLUMNS.forEach(col => {
      if (sortable.includes(col.key)) {
        const arrow = _sortCol === col.key ? (_sortAsc ? ' ▲' : ' ▼') : '';
        html += `<th class="usage-th-sort" data-sort="${col.key}">${col.label}<span class="usage-table__arrow">${arrow}</span></th>`;
      } else {
        html += `<th>${col.label}</th>`;
      }
    });
    html += '</tr></thead><tbody>';

    if (sorted.length === 0) {
      html += `<tr><td colspan="${USAGE_SESSION_TABLE_COLUMNS.length}" class="usage-empty-row">
        <div class="state">
          <div class="state-icon">${icons.usage()}</div>
          <div class="state-title">No usage data yet</div>
          <p class="state-text">Run a session and token spend will appear here automatically.</p>
        </div>
      </td></tr>`;
    } else {
      sorted.forEach(row => {
        const sessionKey = _rowVal(row, 'session', 'sessionKey', 'key') || '';
        const sessionLink = sessionKey
          ? `<a href="#" class="usage-sess-link" data-key="${_esc(sessionKey)}" title="Open chat for ${_esc(sessionKey)}">${_esc(sessionKey)}</a>`
          : '—';
        const cost = _rowVal(row, 'cost_usd', 'costUsd');
        const timestamp = _sessionTimestamp(row);
        const modified = timestamp != null ? UI.relTime(timestamp) : '—';
        html += `<tr>
          <td data-label="Session">${sessionLink}</td>
          <td data-label="Modified" class="usage-mono usage-dim">${_esc(modified)}</td>
          <td data-label="Input" class="usage-mono">${_rowVal(row, 'input_tokens', 'inputTokens') != null ? Number(_rowVal(row, 'input_tokens', 'inputTokens')).toLocaleString() : '—'}</td>
          <td data-label="Output" class="usage-mono">${_rowVal(row, 'output_tokens', 'outputTokens') != null ? Number(_rowVal(row, 'output_tokens', 'outputTokens')).toLocaleString() : '—'}</td>
          <td data-label="Cache R" class="usage-mono usage-dim">${_rowVal(row, 'cache_read_tokens', 'cacheReadTokens') != null ? Number(_rowVal(row, 'cache_read_tokens', 'cacheReadTokens')).toLocaleString() : '—'}</td>
          <td data-label="Cache W" class="usage-mono usage-dim">${_rowVal(row, 'cache_write_tokens', 'cacheWriteTokens') != null ? Number(_rowVal(row, 'cache_write_tokens', 'cacheWriteTokens')).toLocaleString() : '—'}</td>
          <td data-label="Cost" class="usage-mono usage-cost">${_fmtCost(cost)}</td>
          <td data-label="Source">${_renderCostSourceBadge(row)}</td>
          <td data-label="Model">${_renderModelCell(row)}</td>
        </tr>`;
      });
    }
    html += '</tbody></table>';
    wrap.innerHTML = html;

    _bindModelToggles(wrap);

    wrap.querySelectorAll('.usage-sess-link').forEach(a => {
      a.addEventListener('click', (e) => {
        e.preventDefault();
        Router.navigate('/chat?session=' + encodeURIComponent(a.dataset.key));
      });
    });

    wrap.querySelectorAll('th.usage-th-sort').forEach(th => {
      th.addEventListener('click', () => {
        const col = th.dataset.sort;
        if (_sortCol === col) {
          _sortAsc = !_sortAsc;
        } else {
          _sortCol = col;
          _sortAsc = false;
        }
        _renderTable();
      });
    });
  }

  function _fmtNum(n) {
    if (n == null) return '—';
    const v = Number(n);
    if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + 'M';
    if (v >= 1_000) return (v / 1_000).toFixed(1) + 'K';
    return String(v);
  }

  function _renderChartCaption() {
    const cap = _el && _el.querySelector('#usage-chart-caption');
    if (!cap) return;
    // N = pool the chart actually plots (visible + non-zero token rows). Without
    // this, users with 25+ sessions couldn't tell that 5+ were silently dropped.
    const pool = _visibleSessions().filter(r => {
      const inp = Number(_rowVal(r, 'input_tokens', 'inputTokens') || 0);
      const out = Number(_rowVal(r, 'output_tokens', 'outputTokens') || 0);
      return (inp + out) > 0;
    });
    const shown = Math.min(20, pool.length);
    const suffix = pool.length > shown ? ` · showing ${shown} of ${pool.length}` : '';
    cap.textContent = (_chartMode === 'cost'
      ? 'Top sessions by cost'
      : 'Top sessions by total tokens') + suffix;
  }

  function _renderChart() {
    const el = _el && _el.querySelector('#usage-chart');
    const legend = _el && _el.querySelector('#usage-bar-legend');
    if (!el) return;
    const visibleRows = _visibleSessions();

    if (legend) {
      const showOutput = _chartMode === 'tokens';
      legend.querySelectorAll('.usage-chart__legend-item').forEach((item, i) => {
        // Hide the "Output" legend in cost mode (single-segment bar)
        if (i === 1) item.style.display = showOutput ? '' : 'none';
      });
    }

    // Filter out sessions with zero tokens (unknown/placeholder rows), then sort and take top 20
    const sorted = [...visibleRows].filter(r => {
      const inp = Number(_rowVal(r, 'input_tokens', 'inputTokens') || 0);
      const out = Number(_rowVal(r, 'output_tokens', 'outputTokens') || 0);
      return (inp + out) > 0;
    }).sort((a, b) => {
      if (_chartMode === 'cost') {
        return (Number(_rowVal(b, 'cost_usd', 'costUsd') || 0)) - (Number(_rowVal(a, 'cost_usd', 'costUsd') || 0));
      }
      const totalA = (Number(_rowVal(a, 'input_tokens', 'inputTokens') || 0)) + (Number(_rowVal(a, 'output_tokens', 'outputTokens') || 0));
      const totalB = (Number(_rowVal(b, 'input_tokens', 'inputTokens') || 0)) + (Number(_rowVal(b, 'output_tokens', 'outputTokens') || 0));
      return totalB - totalA;
    }).slice(0, 20);

    if (sorted.length === 0) {
      el.innerHTML = `<div class="usage-bars__empty">
        <div class="usage-bars__empty-icon">${icons.usage()}</div>
        <div>No data in the selected window.</div>
      </div>`;
      return;
    }

    let maxVal = 0;
    if (_chartMode === 'cost') {
      maxVal = Math.max(...sorted.map(r => Number(_rowVal(r, 'cost_usd', 'costUsd') || 0)));
    } else {
      maxVal = Math.max(...sorted.map(r =>
        (Number(_rowVal(r, 'input_tokens', 'inputTokens') || 0)) + (Number(_rowVal(r, 'output_tokens', 'outputTokens') || 0))
      ));
    }
    if (maxVal === 0) maxVal = 1;

    let html = '';
    sorted.forEach((row, i) => {
      const fullLabel = (_rowVal(row, 'session', 'sessionKey', 'key') || '—');
      const label = fullLabel.length > 26 ? fullLabel.slice(0, 24) + '…' : fullLabel;
      let valueLabel, inputPct, outputPct, totalPct;
      if (_chartMode === 'cost') {
        const cost = Number(_rowVal(row, 'cost_usd', 'costUsd') || 0);
        const pct = (cost / maxVal) * 100;
        inputPct = pct;
        outputPct = 0;
        totalPct = pct;
        valueLabel = _fmtCost(cost);
      } else {
        const inp = Number(_rowVal(row, 'input_tokens', 'inputTokens') || 0);
        const out = Number(_rowVal(row, 'output_tokens', 'outputTokens') || 0);
        const total = inp + out;
        inputPct = (inp / maxVal) * 100;
        outputPct = (out / maxVal) * 100;
        totalPct = inputPct + outputPct;
        valueLabel = _fmtNum(total);
      }
      const sessionKey = _esc(fullLabel);
      html += `<button class="usage-bar-row" type="button" data-session="${sessionKey}" title="Open ${sessionKey}" style="--i:${i}">
        <span class="usage-bar-row__label">${_esc(label)}</span>
        <span class="usage-bar-row__track">
          <span class="usage-bar-row__fill usage-bar-row__fill--input" style="width:${inputPct.toFixed(1)}%"></span>
          ${outputPct > 0 ? `<span class="usage-bar-row__fill usage-bar-row__fill--output" style="width:${outputPct.toFixed(1)}%"></span>` : ''}
          <span class="usage-bar-row__cap" style="left:${Math.min(100, totalPct).toFixed(1)}%"></span>
        </span>
        <span class="usage-bar-row__value usage-mono">${_esc(valueLabel)}</span>
      </button>`;
    });
    el.innerHTML = html;

    // Click a bar → jump to chat for that session
    el.querySelectorAll('[data-session]').forEach(btn => {
      btn.addEventListener('click', () => {
        const key = btn.dataset.session;
        if (key && key !== '—') Router.navigate('/chat?session=' + encodeURIComponent(key));
      });
    });
  }

  function _modelDisplayLabel(row) {
    const bd = row.modelBreakdown;
    if (Array.isArray(bd) && bd.length > 0) {
      return bd.length > 1 ? `auto · ${bd.length} models` : (bd[0].model || row.model || '—');
    }
    return row.model || '—';
  }

  function _renderModelCell(row) {
    const bd = row.modelBreakdown;
    const label = _modelDisplayLabel(row);
    const sessionKey = _rowVal(row, 'session', 'sessionKey', 'key') || '';
    // Only show the expand caret when there is meaningful breakdown to reveal.
    // A single-model breakdown duplicates the visible row, so the caret was noise.
    if (bd && bd.length > 1) {
      return `<button class="usage-model-toggle" data-session="${_esc(sessionKey)}">
        <span>${_esc(label)}</span><span class="usage-model-caret">▾</span>
      </button>`;
    }
    return `<span class="usage-model-text">${_esc(label)}</span>`;
  }

  function _buildExpandedContent(row) {
    const bd = row.modelBreakdown || [];
    const totalCost = bd.reduce((acc, m) => acc + (Number(m.costUsd) || 0), 0);
    const totalTokens = bd.reduce(
      (acc, m) => acc + (Number(m.inputTokens) || 0) + (Number(m.outputTokens) || 0),
      0,
    );
    // Detect when the backend pro-rated the per-model costs so we can surface
    // a single disclosure at the top of the breakdown instead of one badge per
    // row only (badges still appear per row for hover detail).
    const anyProrated = bd.some(m => {
      const src = String(m.costSource || m.cost_source || '');
      return src === 'provider_billed_prorated';
    });

    const container = document.createElement('div');
    container.className = 'usage-expand';

    const head = document.createElement('div');
    head.className = 'usage-expand__head';
    head.innerHTML = `
      <span class="usage-expand__connector" aria-hidden="true"></span>
      <span class="usage-expand__eyebrow">Model breakdown</span>
      <span class="usage-expand__count">${bd.length} model${bd.length === 1 ? '' : 's'}</span>
      <span class="usage-expand__spacer"></span>
      <span class="usage-expand__total">${totalTokens.toLocaleString()} tokens · ${_fmtCost(totalCost)}</span>
    `;
    container.appendChild(head);

    if (anyProrated) {
      const notice = document.createElement('div');
      notice.className = 'usage-expand__notice';
      notice.setAttribute('role', 'note');
      notice.textContent =
        'Per-model split is estimated; total is the actual billed amount.';
      container.appendChild(notice);
    }

    const list = document.createElement('div');
    list.className = 'usage-expand__list';
    list.setAttribute('role', 'table');
    list.setAttribute('aria-label', 'Model breakdown');

    bd.forEach((m, i) => {
      const tokens = (Number(m.inputTokens) || 0) + (Number(m.outputTokens) || 0);
      const cost = Number(m.costUsd) || 0;
      const share = totalCost > 0 ? (cost / totalCost) * 100 : 0;
      const provider = (m.model || '').split('/')[0] || '';
      const name = (m.model || '').split('/').slice(1).join('/') || m.model || 'unknown';

      const rowEl = document.createElement('div');
      rowEl.className = 'usage-expand__row';
      rowEl.style.setProperty('--i', String(i));
      rowEl.setAttribute('role', 'row');
      rowEl.innerHTML = `
        <div class="usage-expand__model" role="cell" title="${_esc(m.model)}">
          ${provider ? `<span class="usage-expand__provider">${_esc(provider)}/</span>` : ''}<span class="usage-expand__name">${_esc(name)}</span>
        </div>
        <div class="usage-expand__share" role="cell">
          <span class="usage-expand__share-track">
            <span class="usage-expand__share-fill" style="width:${share.toFixed(2)}%"></span>
          </span>
          <span class="usage-expand__share-pct">${share.toFixed(1)}%</span>
        </div>
        <div class="usage-expand__tokens" role="cell">${tokens.toLocaleString()}</div>
        <div class="usage-expand__cost" role="cell">${_fmtCost(cost)}</div>
        <div class="usage-expand__source" role="cell">${_renderCostSourceBadge(m)}</div>
      `;
      list.appendChild(rowEl);
    });

    container.appendChild(list);
    return container;
  }

  function _bindModelToggles(wrap) {
    wrap.querySelectorAll('.usage-model-toggle').forEach(btn => {
      btn.addEventListener('click', () => {
        const sessionKey = btn.dataset.session;
        const tr = btn.closest('tr');
        const next = tr.nextElementSibling;
        if (next && next.classList.contains('usage-expand-row')) {
          next.remove();
          btn.classList.remove('open');
          return;
        }
        const row = _visibleSessions().find(r => (_rowVal(r, 'session', 'sessionKey', 'key') || '') === sessionKey);
        if (!row) return;
        const expandTr = document.createElement('tr');
        expandTr.className = 'usage-expand-row';
        const td = document.createElement('td');
        td.className = 'usage-expand-cell';
        td.colSpan = USAGE_SESSION_TABLE_COLUMNS.length;
        td.appendChild(_buildExpandedContent(row));
        expandTr.appendChild(td);
        tr.after(expandTr);
        btn.classList.add('open');
      });
    });
  }

  function _renderModelBreakdown() {
    const el = _el && _el.querySelector('#usage-model-grid');
    const meta = _el && _el.querySelector('#usage-models-meta');
    if (!el) return;
    const visibleRows = _visibleSessions();

    // Group by actual per-model usage when available. Squilla router can route
    // different turns in the same session to different models, while row.model
    // represents only the current/latest session model.
    const map = {};
    visibleRows.forEach(row => {
      const breakdown = Array.isArray(row.modelBreakdown) ? row.modelBreakdown : [];
      const items = breakdown.length > 0 ? breakdown : [{
        model: row.model || 'unknown',
        inputTokens: Number(_rowVal(row, 'input_tokens', 'inputTokens') || 0),
        outputTokens: Number(_rowVal(row, 'output_tokens', 'outputTokens') || 0),
        cacheReadTokens: Number(_rowVal(row, 'cache_read_tokens', 'cacheReadTokens') || 0),
        cacheWriteTokens: Number(_rowVal(row, 'cache_write_tokens', 'cacheWriteTokens') || 0),
        costUsd: Number(_rowVal(row, 'cost_usd', 'costUsd') || 0),
      }];
      const modelsSeenInSession = new Set();
      items.forEach(item => {
        const model = item.model || row.model || 'unknown';
        if (!map[model]) {
          map[model] = { model, inputTokens: 0, outputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0, costUsd: 0, sessions: 0 };
        }
        map[model].inputTokens += Number(_rowVal(item, 'input_tokens', 'inputTokens') || 0);
        map[model].outputTokens += Number(_rowVal(item, 'output_tokens', 'outputTokens') || 0);
        map[model].cacheReadTokens += Number(_rowVal(item, 'cache_read_tokens', 'cacheReadTokens') || 0);
        map[model].cacheWriteTokens += Number(_rowVal(item, 'cache_write_tokens', 'cacheWriteTokens') || 0);
        map[model].costUsd += Number(_rowVal(item, 'cost_usd', 'costUsd') || 0);
        if (!modelsSeenInSession.has(model)) {
          map[model].sessions += 1;
          modelsSeenInSession.add(model);
        }
      });
    });

    const models = Object.values(map).sort((a, b) => b.costUsd - a.costUsd);
    const totalCost = models.reduce((acc, m) => acc + m.costUsd, 0);

    if (meta) meta.textContent = `${models.length} model${models.length === 1 ? '' : 's'}`;

    if (models.length === 0) {
      el.innerHTML = `<div class="usage-models__empty">No model usage yet.</div>`;
      return;
    }

    let html = '';
    models.forEach((m, i) => {
      const share = totalCost > 0 ? (m.costUsd / totalCost) * 100 : 0;
      const provider = (m.model || '').split('/')[0] || '';
      const name = (m.model || '').split('/').slice(1).join('/') || m.model || 'unknown';
      const totalTokens = m.inputTokens + m.outputTokens;
      html += `<article class="usage-model-card" style="--i:${i}">
        <header class="usage-model-card__head">
          <div class="usage-model-card__id">
            ${provider ? `<span class="usage-model-card__provider">${_esc(provider)}</span>` : ''}
            <span class="usage-model-card__name" title="${_esc(m.model)}">${_esc(name)}</span>
          </div>
          <span class="usage-model-card__share" title="Share of total cost">${share.toFixed(1)}%</span>
        </header>
        <div class="usage-model-card__share-bar">
          <span class="usage-model-card__share-fill" style="width:${share.toFixed(1)}%"></span>
        </div>
        <dl class="usage-model-card__rows">
          <div><dt>Tokens</dt><dd class="usage-mono">${totalTokens.toLocaleString()}</dd></div>
          <div><dt>Input</dt><dd class="usage-mono usage-dim">${m.inputTokens.toLocaleString()}</dd></div>
          <div><dt>Output</dt><dd class="usage-mono usage-dim">${m.outputTokens.toLocaleString()}</dd></div>
          ${m.cacheReadTokens > 0 ? `<div><dt>Cache R</dt><dd class="usage-mono usage-dim">${m.cacheReadTokens.toLocaleString()}</dd></div>` : ''}
          ${m.cacheWriteTokens > 0 ? `<div><dt>Cache W</dt><dd class="usage-mono usage-dim">${m.cacheWriteTokens.toLocaleString()}</dd></div>` : ''}
          <div><dt>Sessions</dt><dd>${m.sessions}</dd></div>
          <div class="usage-model-card__cost-row"><dt>Cost</dt><dd class="usage-mono usage-cost">${_fmtCost(m.costUsd)}</dd></div>
        </dl>
      </article>`;
    });
    el.innerHTML = html;
  }

  function _exportCsv() {
    const headers = [
      'session',
      'input_tokens',
      'output_tokens',
      'cache_read_tokens',
      'cache_write_tokens',
      'cost_usd',
      'cost_cny',
      'billed_cost_usd',
      'estimated_cost_usd',
      'cost_source',
      'missing_cost_entries',
      'cost_ephemeral',
      'model'
    ];
    const visibleRows = _visibleSessions();
    const rows = visibleRows.map(row => [
      _rowVal(row, 'session', 'sessionKey', 'key') || '',
      _rowVal(row, 'input_tokens', 'inputTokens') ?? '',
      _rowVal(row, 'output_tokens', 'outputTokens') ?? '',
      _rowVal(row, 'cache_read_tokens', 'cacheReadTokens') ?? '',
      _rowVal(row, 'cache_write_tokens', 'cacheWriteTokens') ?? '',
      _rowVal(row, 'cost_usd', 'costUsd') != null ? Number(_rowVal(row, 'cost_usd', 'costUsd')).toFixed(6) : '',
      _rowVal(row, 'cost_usd', 'costUsd') != null ? (Number(_rowVal(row, 'cost_usd', 'costUsd')) * CNY_RATE).toFixed(6) : '',
      _rowVal(row, 'billed_cost_usd', 'billedCostUsd') != null ? Number(_rowVal(row, 'billed_cost_usd', 'billedCostUsd')).toFixed(6) : '',
      _rowVal(row, 'estimated_cost_usd', 'estimatedCostUsd') != null ? Number(_rowVal(row, 'estimated_cost_usd', 'estimatedCostUsd')).toFixed(6) : '',
      _costSource(row),
      _rowVal(row, 'missing_cost_entries', 'missingCostEntries') ?? '',
      _rowVal(row, 'cost_ephemeral', 'costEphemeral') ? 'true' : 'false',
      row.model || '',
    ]);
    const csv = [headers, ...rows].map(r => r.map(v => '"' + String(v).replace(/"/g, '""') + '"').join(',')).join('\n');
    // Filename embeds the baked-in CNY rate so the cost_cny column is
    // self-describing if the file outlives the conversation it came from.
    const suffix = _range === 'all' ? 'all' : `${_range}d`;
    _download(`opensquilla-usage-${suffix}-cny${CNY_RATE}.csv`, 'text/csv', csv);
  }

  function _download(filename, mime, content) {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  function _esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  return { render, destroy };
})();

window.UsageView = UsageView;
