/** OpenSquilla Web UI — Main application entry point. */

// Feature flags. Defaults are baked in here; future surfaces can flip individual
// keys before app.js loads to override. tokenViz controls the floating token
// widget + per-turn savings chip. SavingsFX (popup) is independent of this flag.
window.OPENSQUILLA_FEATURES = Object.assign(
  { tokenViz: false },
  window.OPENSQUILLA_FEATURES || {}
);

const App = (() => {
  const WS_URL_KEY = 'opensquilla.wsUrl';
  const WS_TOKEN_KEY = 'opensquilla.wsToken';
  let rpc = null;

  function _basePath() {
    return document.getElementById('opensquilla-data')?.dataset.basePath || '/control';
  }

  function init() {
    Theme.init();
    rpc = new RpcClient();

    _buildLayout();
    if (window.ApprovalMonitor) ApprovalMonitor.start();
    _bindNav();
    _bindThemeToggle();
    _bindSidebarToggle();
    _bindConnectionState();

    Router.register('/overview', (el) => OverviewView.render(el), () => OverviewView.destroy());
    Router.register('/health', (el) => HealthView.render(el), () => HealthView.destroy());
    Router.register('/chat', (el) => ChatView.render(el), () => ChatView.destroy());
    Router.register('/sessions', (el) => SessionsView.render(el), () => SessionsView.destroy());
    Router.register('/agents', (el) => AgentsView.render(el), () => AgentsView.destroy());
    Router.register('/cron', (el) => CronView.render(el), () => CronView.destroy());
    Router.register('/usage', (el) => UsageView.render(el), () => UsageView.destroy());
    Router.register('/config', (el) => ConfigView.render(el), () => ConfigView.destroy());
    Router.register('/setup', (el) => SetupView.render(el), () => SetupView.destroy());
    Router.register('/channels', (el) => ChannelsView.render(el), () => ChannelsView.destroy());
    Router.register('/approvals', (el) => ApprovalsView.render(el), () => ApprovalsView.destroy());
    Router.register('/skills', (el) => SkillsView.render(el), () => SkillsView.destroy());
    Router.register('/logs', (el) => LogsView.render(el), () => LogsView.destroy());

    Router.init(_basePath(), document.getElementById('content'));

    _autoConnect();
  }

  function _buildLayout() {
    const app = document.getElementById('app');
    const basePath = _basePath();
    app.innerHTML = `
      <nav class="sidebar" id="sidebar-nav" aria-label="Primary">
        <div class="nav-brand"><img class="brand-mark" src="${basePath}/static/img/opensquilla-mark.png" alt="" aria-hidden="true"> OpenSquilla</div>
        <div class="nav-group-label">Chat</div>
        <a class="nav-item" href="#" data-path="/chat">${icons.chat()} Chat</a>
        <div class="nav-group-label">Control</div>
        <a class="nav-item" href="#" data-path="/overview">${icons.home()} Overview</a>
        <a class="nav-item" href="#" data-path="/health">${icons.logs()} Health</a>
        <a class="nav-item" href="#" data-path="/channels">${icons.channels()} Channels</a>
        <a class="nav-item" href="#" data-path="/skills">${icons.skills()} Skills</a>
        <a class="nav-item" href="#" data-path="/sessions">${icons.sessions()} Sessions</a>
        <a class="nav-item" href="#" data-path="/agents">${icons.agents()} Agents</a>
        <a class="nav-item" href="#" data-path="/usage">${icons.usage()} Usage</a>
        <a class="nav-item" href="#" data-path="/cron">${icons.cron()} Cron</a>
        <div class="nav-group-label">Settings</div>
        <a class="nav-item" href="#" data-path="/config">${icons.config()} Config</a>
        <a class="nav-item" href="#" data-path="/logs">${icons.logs()} Logs</a>
        <a class="nav-item" href="#" data-path="/approvals">${icons.approvals()} Approvals <span class="nav-badge hidden" id="approval-count">0</span></a>
      </nav>
      <div class="main">
        <header class="topbar">
          <div class="topbar-left">
            <button class="btn btn--icon btn--ghost sidebar-toggle" id="sidebar-toggle" title="Toggle menu" aria-controls="sidebar-nav" aria-expanded="false">${icons.menu()}</button>
            <span class="conn-pill err" id="conn-pill">Disconnected</span>
          </div>
          <div class="topbar-right">
            <button class="approval-inline hidden" id="approval-inline" title="Open approvals">Approval required</button>
            <button class="btn btn--icon btn--ghost" id="theme-toggle" title="Toggle theme">${icons.sun()}</button>
          </div>
        </header>
        <main class="content" id="content"></main>
      </div>`;
  }

  function _bindNav() {
    document.querySelectorAll('.nav-item[data-path]').forEach(el => {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        Router.navigate(el.dataset.path);
      });
    });
  }

  function _bindThemeToggle() {
    document.getElementById('theme-toggle')?.addEventListener('click', () => Theme.cycle());
  }

  function _bindSidebarToggle() {
    const toggle = document.getElementById('sidebar-toggle');
    const sidebar = document.querySelector('.sidebar');
    if (!toggle || !sidebar) return;
    const mobileQuery = window.matchMedia('(max-width: 768px)');

    const setSidebarOpen = (open) => {
      sidebar.classList.toggle('open', open);
      _syncSidebarAccessibility(sidebar, toggle, mobileQuery);
    };

    _syncSidebarAccessibility(sidebar, toggle, mobileQuery);
    if (mobileQuery.addEventListener) {
      mobileQuery.addEventListener('change', () => _syncSidebarAccessibility(sidebar, toggle, mobileQuery));
    } else if (mobileQuery.addListener) {
      mobileQuery.addListener(() => _syncSidebarAccessibility(sidebar, toggle, mobileQuery));
    }

    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      setSidebarOpen(!sidebar.classList.contains('open'));
    });
    sidebar.addEventListener('click', (e) => {
      if (e.target.closest('.nav-item')) setSidebarOpen(false);
    });
    // Click outside the sidebar (and not on the toggle) closes the drawer.
    // The CSS backdrop is a pseudo-element that can't receive pointer events,
    // so we rely on a document-level handler instead.
    document.addEventListener('click', (e) => {
      if (!sidebar.classList.contains('open')) return;
      if (sidebar.contains(e.target) || toggle.contains(e.target)) return;
      setSidebarOpen(false);
    });
    // Esc closes the drawer for keyboard users.
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && sidebar.classList.contains('open')) {
        setSidebarOpen(false);
      }
    });
  }

  function _syncSidebarAccessibility(sidebar, toggle, mobileQuery) {
    const isOpen = sidebar.classList.contains('open');
    const isHiddenDrawer = mobileQuery.matches && !isOpen;
    toggle.setAttribute('aria-expanded', String(isOpen));
    if (isHiddenDrawer) {
      sidebar.setAttribute('aria-hidden', 'true');
      sidebar.setAttribute('inert', '');
      return;
    }
    sidebar.removeAttribute('aria-hidden');
    sidebar.removeAttribute('inert');
  }

  function _bindConnectionState() {
    const VARIANT = { connected: 'ok', connecting: 'warn', disconnected: 'err' };
    rpc.on('_state', (state) => {
      const pill = document.getElementById('conn-pill');
      if (!pill) return;
      pill.className = `conn-pill ${VARIANT[state] || 'err'}`;
      pill.textContent = state.charAt(0).toUpperCase() + state.slice(1);
    });
  }

  function _autoConnect() {
    if (!rpc || rpc.state !== 'disconnected') return;
    const { url, token } = loadConnectionSettings();
    rpc.connect(url, token || undefined);
  }

  function getDefaultRpcUrl() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${location.host}/ws`;
  }

  function loadConnectionSettings() {
    let url = getDefaultRpcUrl();
    let token = '';
    try { url = localStorage.getItem(WS_URL_KEY) || url; } catch {}
    try { token = sessionStorage.getItem(WS_TOKEN_KEY) || ''; } catch {}
    return { url, token };
  }

  function getAuthToken() {
    return loadConnectionSettings().token || '';
  }

  function saveConnectionSettings(url, token) {
    try { localStorage.setItem(WS_URL_KEY, url || getDefaultRpcUrl()); } catch {}
    try {
      if (token) sessionStorage.setItem(WS_TOKEN_KEY, token);
      else sessionStorage.removeItem(WS_TOKEN_KEY);
    } catch {}
  }

  function getRpc() { return rpc; }

  return { init, getRpc, getDefaultRpcUrl, loadConnectionSettings, getAuthToken, saveConnectionSettings };
})();

document.addEventListener('DOMContentLoaded', () => App.init());
