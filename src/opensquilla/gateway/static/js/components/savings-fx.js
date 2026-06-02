/** OpenSquilla — Savings FX: viewport-centered particle burst for squilla-router & prompt-cache signals. */

const SavingsFX = (() => {
  /* ── Device helpers ──────────────────────────────────────────────────── */
  const _isMobile  = () => window.innerWidth < 480;
  const _isTablet  = () => window.innerWidth < 1024;
  const _reducedMotion = () =>
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ── Enabled preference (persisted, DEFAULT ON) ──────────────────────── */
  const _PREF_KEY = 'opensquilla.savingsFx';
  let _enabled = (() => {
    try { return window.localStorage.getItem(_PREF_KEY) !== '0'; } catch { return true; }
  })();
  function isEnabled() { return _enabled; }
  function setEnabled(on) {
    _enabled = !!on;
    try { window.localStorage.setItem(_PREF_KEY, _enabled ? '1' : '0'); } catch {}
  }

  // Density multiplier — keeps small screens legible without starving them
  // of particles (the prior 0.35 looked like "no effect at all" on phones).
  function _deviceMult() {
    if (_isMobile())  return 0.55;
    if (_isTablet())  return 0.78;
    return 1.0;
  }

  // Speed multiplier scaling with the smaller viewport dimension. A 320px
  // phone and a 2560px monitor should both produce a burst that *fills*
  // a meaningful share of the screen rather than a fixed pixel radius.
  function _speedScale() {
    return Math.min(window.innerWidth, window.innerHeight) / 280;
  }

  /* ── Session state ───────────────────────────────────────────────────── */
  let _streak    = 0;
  let _maxStreak = 0;
  let _streakIdentity = '';
  const _active  = new Set(); // live canvases
  const _labels = new Set();

  /* ── Savings score 0–1 ───────────────────────────────────────────────── */
  // savings_usd scales with actual token count -> big context = more particles.
  // savings_pct anchors the base intensity (cheaper tier = bigger burst).
  // confidence tilts up when ML is certain about the routing.
  function _score(u) {
    u = u || {};
    const savingsUsd = (typeof u.total_savings_usd === 'number')
      ? u.total_savings_usd
      : (u.savings_usd || 0);
    const rawPct = (typeof u.total_savings_pct === 'number' && u.total_savings_pct > 0)
      ? u.total_savings_pct
      : (u.savings_pct || 0);
    const savingsPct = rawPct / 100;                    // normalize to 0-1
    const usdComponent = Math.min(1, savingsUsd / 0.05); // $0.05 = full score
    const conf = typeof u.routing_confidence === 'number' ? u.routing_confidence : 0.5;
    const blended = usdComponent * 0.55 + savingsPct * 0.35 + conf * 0.10;
    return Math.max(0.25, Math.min(1, blended));
  }

  /* ── Estimated label ─────────────────────────────────────────────────── */
  function _savingsLabel(savePct) {
    if (!savePct || savePct < 1) return 'Cost optimized';
    return `Saved ~${Math.round(savePct)}%`;
  }

  /* ── Floating label — centered on the viewport ──────────────────────── */
  // The centered label is the savings *percentage*, always. The streak/
  // combo lives in the per-turn meta footer beneath the bubble. The label
  // keeps the headline tied to the actual savings story, not
  // the run length. Position is owned by CSS (top:50%; left:50%); the
  // translate keyframe does the rise.
  function _showSavingsLabel(u) {
    const savePct = (typeof u.total_savings_pct === 'number' && u.total_savings_pct > 0)
      ? u.total_savings_pct
      : 0;
    const el = document.createElement('div');
    el.className = 'savings-float';
    if (savePct >= 65) el.classList.add('savings-float--peak');
    el.setAttribute('aria-hidden', 'true');
    const main = document.createElement('span');
    main.className = 'savings-float__main';
    main.textContent = _savingsLabel(savePct);
    el.appendChild(main);
    const sub = document.createElement('span');
    sub.className = 'savings-float__sub';
    sub.textContent = 'this turn';
    el.appendChild(sub);
    document.body.appendChild(el);
    _labels.add(el);
    // Keyframe runs 2.4s; add a 200ms grace so we never yank mid-fade-out.
    setTimeout(() => {
      try { el.remove(); } catch (_) {}
      _labels.delete(el);
    }, 2600);
  }

  /* ── Public API ──────────────────────────────────────────────────────── */
  function _turnIdentity(u) {
    const model = u?.routed_model || u?.model || '';
    return model ? `${model}|${u?.routed_tier || ''}` : '';
  }

  function _isComboTier(tier) {
    const value = String(tier || '').trim().toLowerCase();
    const numeric = /^c(\d+)$/.exec(value) || /^t(\d+)$/.exec(value);
    if (numeric) return Number(numeric[1]) < 3;
    return value !== 'highest' && value !== 'top' && value !== 'flagship';
  }

  function _canVibrate() {
    if (!navigator.vibrate) return false;
    const activation = navigator.userActivation;
    return !activation || activation.hasBeenActive || activation.isActive;
  }

  // noteTurn owns the streak: every chat.done turn calls it. Only real
  // non-top-tier squilla-router routed savings turns with the same model/tier
  // identity increment; every other turn resets to 0.
  // fire() does visuals only; the caller decides when (and which bubble) to
  // fire against, gated by product rules in chat.js.
  function noteTurn(u) {
    const hasTier  = !!(u && u.routed_tier && u.routing_source && u.routing_source !== 'none');
    const savePct = (typeof u?.total_savings_pct === 'number' && u.total_savings_pct > 0)
      ? u.total_savings_pct
      : 0;
    const identity = _turnIdentity(u);
    if (hasTier && savePct > 0 && identity && _isComboTier(u.routed_tier)) {
      _streak = (_streakIdentity === identity) ? _streak + 1 : 1;
      _streakIdentity = identity;
      if (_streak > _maxStreak) _maxStreak = _streak;
    } else if (_streak !== 0 || _streakIdentity) {
      _streak = 0;
      _streakIdentity = '';
    }
  }

  function fire(bubble, u) {
    if (!_enabled) return;          // Savings FX toggle (default on)
    /* Haptic (mobile) — vibration pattern scales with streak */
    if (_canVibrate()) {
      if (_streak >= 5)      navigator.vibrate([40, 20, 60, 20, 40]);
      else if (_streak >= 3) navigator.vibrate([40, 20, 60]);
      else                   navigator.vibrate(30);
    }

    const score = _score(u);
    const conf  = typeof u.routing_confidence === 'number' ? u.routing_confidence : 0.5;

    /* Reduced-motion path: border pulse + label only */
    if (_reducedMotion()) {
      _pulseBorder(bubble, '#fbbf24');
      _showSavingsLabel(u);
      return;
    }

    /* Main burst — viewport-centered */
    _burst(score, conf);

    /* Savings label — appears slightly after the burst peaks */
    setTimeout(() => _showSavingsLabel(u), 180);

    /* Streak milestone bonus burst (independent of the centered burst) */
    if (_streak === 3 || _streak === 5 || (_streak >= 10 && _streak % 5 === 0)) {
      setTimeout(() => _streakBurst(_streak), 360);
    }
  }

  function resetStreak() {
    _streak = 0;
    _streakIdentity = '';
  }

  function getStreak() { return { current: _streak, max: _maxStreak }; }

  function cleanup() {
    for (const c of _active) { try { c.remove(); } catch (_) {} }
    _active.clear();
    for (const el of _labels) { try { el.remove(); } catch (_) {} }
    _labels.clear();
  }

  /* ── Border pulse (reduced-motion fallback) ──────────────────────────── */
  function _pulseBorder(bubble, color) {
    if (!bubble?.isConnected) return;
    const body = bubble.querySelector('.msg-body');
    if (!body) return;
    const was = body.style.transition;
    body.style.transition = 'box-shadow 0.25s ease';
    body.style.boxShadow  = `0 0 0 2px ${color}88`;
    setTimeout(() => {
      body.style.boxShadow  = '';
      body.style.transition = was;
    }, 550);
  }

  /* ── Main burst — emanates from viewport center ──────────────────────── */
  function _burst(score, conf) {
    const dm         = _deviceMult();
    const streakMult = Math.min(2.6, 1 + (_streak - 1) * 0.30);
    const count      = Math.max(28, Math.min(180, Math.round(score * 90 * dm * streakMult)));
    // Duration scales with score and viewport diagonal (bigger screen ⇒
    // longer flight before exit). Floor of 1800ms; ceiling around 3.6s.
    const vpDiag     = Math.hypot(window.innerWidth, window.innerHeight);
    const duration   = Math.min(3600, 1800 + score * 1500 + vpDiag * 0.18);
    const ox = window.innerWidth  / 2;
    const oy = window.innerHeight * 0.45; // slightly above geometric center
    _spawnCanvas(ox, oy, count, duration, conf, false);
  }

  /* ── Streak bonus burst (full-radial, gold) ─────────────────────────── */
  function _streakBurst(streak) {
    const dm    = _deviceMult();
    const count = Math.min(140, Math.round((28 + streak * 5) * dm));
    const ox    = window.innerWidth  / 2;
    const oy    = window.innerHeight * 0.45;
    _spawnCanvas(ox, oy, count, 3000, 1.0, true);
  }

  /* ── Canvas lifecycle ────────────────────────────────────────────────── */
  function _spawnCanvas(ox, oy, count, duration, conf, isStreak) {
    const canvas = document.createElement('canvas');
    canvas.style.cssText =
      'position:fixed;top:0;left:0;width:100vw;height:100vh;' +
      'pointer-events:none;z-index:9998;';
    const dpr = Math.max(1, Math.min(2, window.devicePixelRatio || 1));
    canvas.width  = window.innerWidth  * dpr;
    canvas.height = window.innerHeight * dpr;
    document.body.appendChild(canvas);
    _active.add(canvas);

    const ctx2d = canvas.getContext('2d');
    ctx2d.scale(dpr, dpr);
    const ps    = _makeParticles(ox, oy, count, conf, isStreak);
    const t0    = performance.now();

    function frame(now) {
      if ((now - t0) / duration >= 1) { canvas.remove(); _active.delete(canvas); return; }

      ctx2d.clearRect(0, 0, canvas.width, canvas.height);

      let alive = false;
      for (const p of ps) {
        p.x  += p.vx;
        p.y  += p.vy;
        p.vy += p.gravity;
        p.vx *= 0.991;
        p.life -= p.decay;
        if (p.life <= 0) continue;
        alive = true;

        ctx2d.globalAlpha = p.life * p.life;
        ctx2d.fillStyle   = p.color;

        if (p.isStar) {
          _star(ctx2d, p.x, p.y, p.size);
        } else {
          ctx2d.beginPath();
          ctx2d.arc(p.x, p.y, p.size, 0, 6.2832);
          ctx2d.fill();
        }
      }

      ctx2d.globalAlpha = 1;
      if (!alive) { canvas.remove(); _active.delete(canvas); return; }
      requestAnimationFrame(frame);
    }

    requestAnimationFrame(frame);
  }

  /* ── Particle factory ────────────────────────────────────────────────── */
  // Centered burst → full radial spread. ML high-conf (≥0.78) → gold stars;
  // heuristic → amber circles. Streak → rainbow gold burst.
  function _makeParticles(ox, oy, count, conf, isStreak) {
    const sScale = _speedScale();

    return Array.from({ length: count }, (_, i) => {
      let color;
      if (isStreak) {
        color = `hsl(${30 + (i / count) * 50},94%,62%)`;
      } else {
        color = `hsl(${33 + Math.random() * 22},92%,${55 + Math.random() * 14}%)`;
      }

      const isStar = isStreak || conf >= 0.78;
      // Full 2π spread — burst radiates outward in every direction.
      const angle  = Math.random() * Math.PI * 2;
      const speed  = (1.6 + Math.random() * 5.2) * sScale * 0.95;

      return {
        x: ox, y: oy,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        // Light gravity so particles drift downward gracefully without
        // falling out of frame too fast.
        gravity: 0.045 + Math.random() * 0.04,
        size:    isStreak ? 3.5 + Math.random() * 3.5 : 1.8 + Math.random() * 2.8,
        life:    0.85 + Math.random() * 0.15,
        // Slower decay extends visible life to match the longer canvas
        // duration. Particles now linger ~2.5×–3× as long as before.
        decay:   0.0035 + Math.random() * 0.008,
        color,
        isStar,
      };
    });
  }

  /* ── Star shape ──────────────────────────────────────────────────────── */
  function _star(ctx2d, x, y, r) {
    const inner = r * 0.42;
    const step  = Math.PI / 5;
    ctx2d.beginPath();
    for (let i = 0; i < 10; i++) {
      const angle = i * step - Math.PI / 2;
      const rr    = i % 2 === 0 ? r : inner;
      i === 0
        ? ctx2d.moveTo(x + Math.cos(angle) * rr, y + Math.sin(angle) * rr)
        : ctx2d.lineTo(x + Math.cos(angle) * rr, y + Math.sin(angle) * rr);
    }
    ctx2d.closePath();
    ctx2d.fill();
  }

  function savingsLabel(savePct) { return _savingsLabel(savePct); }

  return { fire, noteTurn, resetStreak, getStreak, savingsLabel, cleanup, isEnabled, setEnabled };
})();

window.SavingsFX = SavingsFX;
