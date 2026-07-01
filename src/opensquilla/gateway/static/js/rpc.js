/** OpenSquilla Web UI — WebSocket RPC client. */

class RpcClient {
  constructor() {
    this._ws = null;
    this._reqId = 0;
    this._pending = new Map();
    this._listeners = new Map();
    this._state = 'disconnected';
    this._url = '';
    this._token = null;
    this._reconnectTimer = null;
    this._reconnectDelay = 800;
    this._maxReconnectDelay = 15000;
    this._reconnectFactor = 1.7;
    this._autoReconnect = true;
    this._pingTimer = null;
    this._pingInterval = 55000; // 55s — safely under server's 120s keepalive
    this._policy = null;
    this._lastSeq = 0;
    this._lastFrameAt = 0;
    this._tickWatchTimer = null;
    this._tickTimeoutMs = 60000;
  }

  connect(url, token) {
    this._url = url;
    this._token = token || null;
    this._autoReconnect = true;
    this._doConnect();
  }

  disconnect() {
    this._autoReconnect = false;
    clearTimeout(this._reconnectTimer);
    this._stopPing();
    this._stopTickWatch();
    if (this._ws) {
      this._ws.close();
      this._ws = null;
    }
    this._setState('disconnected');
  }

  call(method, params = {}) {
    return new Promise((resolve, reject) => {
      if (!this._ws || this._ws.readyState !== WebSocket.OPEN) {
        reject(new Error('Not connected'));
        return;
      }
      const id = String(++this._reqId);
      this._pending.set(id, { resolve, reject });
      this._ws.send(JSON.stringify({ type: 'req', id, method, params }));
    });
  }

  on(event, handler) {
    if (!this._listeners.has(event)) this._listeners.set(event, new Set());
    this._listeners.get(event).add(handler);
    return () => this._listeners.get(event)?.delete(handler);
  }

  get state() { return this._state; }
  get policy() { return this._policy || {}; }

  waitForConnection() {
    if (this._state === 'connected') return Promise.resolve();
    return new Promise((resolve) => {
      const unsub = this.on('_state', (s) => {
        if (s === 'connected') { unsub(); resolve(); }
      });
    });
  }

  _doConnect() {
    this._setState('connecting');
    this._lastSeq = 0;
    this._lastFrameAt = Date.now();
    this._stopTickWatch();
    try {
      this._ws = new WebSocket(this._url);
    } catch {
      this._scheduleReconnect();
      return;
    }

    this._ws.onopen = () => {
      this._reconnectDelay = 800;
      // Don't send connect yet — wait for connect.challenge from server
    };

    this._ws.onmessage = (ev) => {
      let data;
      try { data = JSON.parse(ev.data); } catch { return; }
      if (!this._noteIncomingFrame(data)) return;

      // Handshake: server sends connect.challenge, we reply with connect request
      if (data.type === 'event' && data.event === 'connect.challenge') {
        const authParams = this._token ? { auth: { token: this._token } } : {};
        const id = String(++this._reqId);
        this._pending.set(id, {
          resolve: () => {},  // HelloOk is not a res frame, handled below
          reject: (err) => { this._ws?.close(); this._setState('disconnected'); }
        });
        this._ws.send(JSON.stringify({
          type: 'req', id, method: 'connect',
          params: { minProtocol: 3, maxProtocol: 3, client: { name: 'opensquilla-web' }, ...authParams }
        }));
        return;
      }

      // Handshake: HelloOk frame (has "protocol" field, no "type":"res")
      if (data.protocol !== undefined && this._state === 'connecting') {
        this._policy = data.policy || null;
        // Resolve any pending connect request
        for (const [id, p] of this._pending) {
          this._pending.delete(id);
          p.resolve(data);
          break;
        }
        this._setState('connected');
        const helloHandlers = this._listeners.get('_hello');
        if (helloHandlers) helloHandlers.forEach(h => h(data));
        this._startPing();
        this._startTickWatch();
        return;
      }

      if (data.type === 'res') {
        const p = this._pending.get(data.id);
        if (p) {
          this._pending.delete(data.id);
          if (data.ok) {
            p.resolve(data.payload);
          } else {
            const err = data.error;
            const message = typeof err === 'string'
              ? err
              : (err && (err.message || err.code)) || 'RPC error';
            const error = new Error(message);
            if (err && typeof err === 'object') {
              error.code = err.code;
              error.details = err.details;
            }
            p.reject(error);
          }
        }
      } else if (data.type === 'event') {
        const meta = data.meta || {};
        const handlers = this._listeners.get(data.event);
        if (handlers) handlers.forEach(h => h(data.payload, meta));
        const wild = this._listeners.get('*');
        if (wild) wild.forEach(h => h(data.event, data.payload, meta));
      }
    };

    this._ws.onclose = () => {
      this._stopPing();
      this._stopTickWatch();
      for (const [, p] of this._pending) p.reject(new Error('Connection closed'));
      this._pending.clear();
      this._ws = null;
      if (this._state !== 'disconnected') {
        this._setState('disconnected');
        this._scheduleReconnect();
      }
    };

    this._ws.onerror = () => {};
  }

  _startPing() {
    this._stopPing();
    this._pingTimer = setInterval(() => {
      if (this._ws && this._ws.readyState === WebSocket.OPEN) {
        this._ws.send('{"type":"ping"}');
      }
    }, this._pingInterval);
  }

  _stopPing() {
    if (this._pingTimer !== null) {
      clearInterval(this._pingTimer);
      this._pingTimer = null;
    }
  }

  _noteIncomingFrame(data) {
    this._lastFrameAt = Date.now();
    if (!data || data.type !== 'event' || typeof data.seq !== 'number') return true;

    const seq = data.seq;
    if (this._lastSeq > 0 && seq !== this._lastSeq + 1) {
      const detail = { expected: this._lastSeq + 1, actual: seq, event: data.event };
      const handlers = this._listeners.get('_gap');
      if (handlers) handlers.forEach(h => h(detail));
      try { this._ws?.close(); } catch {}
      return false;
    }
    this._lastSeq = seq;
    return true;
  }

  _startTickWatch() {
    this._stopTickWatch();
    const tickMs = this._policy?.tick_interval_ms || 30000;
    this._tickTimeoutMs = Math.max(10000, tickMs * 2.5);
    this._lastFrameAt = Date.now();
    this._tickWatchTimer = setInterval(() => {
      if (!this._ws || this._ws.readyState !== WebSocket.OPEN) return;
      const idleMs = Date.now() - this._lastFrameAt;
      if (idleMs <= this._tickTimeoutMs) return;
      const handlers = this._listeners.get('_gap');
      if (handlers) handlers.forEach(h => h({ reason: 'tick_timeout', idleMs }));
      try { this._ws.close(); } catch {}
    }, Math.min(tickMs, 10000));
  }

  _stopTickWatch() {
    if (this._tickWatchTimer !== null) {
      clearInterval(this._tickWatchTimer);
      this._tickWatchTimer = null;
    }
  }

  _scheduleReconnect() {
    if (!this._autoReconnect) return;
    clearTimeout(this._reconnectTimer);
    this._reconnectTimer = setTimeout(() => this._doConnect(), this._reconnectDelay);
    this._reconnectDelay = Math.min(this._reconnectDelay * this._reconnectFactor, this._maxReconnectDelay);
  }

  _setState(s) {
    if (this._state === s) return;
    this._state = s;
    const handlers = this._listeners.get('_state');
    if (handlers) handlers.forEach(h => h(s));
  }
}

window.RpcClient = RpcClient;
