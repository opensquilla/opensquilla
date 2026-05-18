/** OpenSquilla Web UI — shared compile-time constants.
 *
 * Loaded as a plain <script> via the index.html template, before any view code.
 * Exposes `window.SquillaConstants` as the single source of truth so values
 * like the CNY exchange rate don't drift across overview, usage, and token
 * widget views.
 *
 * Add new constants conservatively: anything user-visible should live here
 * with a brief comment explaining provenance.
 */

(function () {
  // CNY/USD exchange rate baked in at release time. Intentionally a constant
  // (not fetched live) so historical CSV exports and on-screen totals stay
  // reproducible for accounting. Surface the "baked-in" disclosure to users
  // alongside any CNY value derived from this rate.
  const CNY_RATE = 7.25;

  // ISO 8601 date string indicating when CNY_RATE was last reviewed.
  // Update this whenever CNY_RATE changes so disclosure copy can reference it.
  const CNY_RATE_SET_AT = '2026-05-13';

  window.SquillaConstants = Object.freeze({
    CNY_RATE: CNY_RATE,
    CNY_RATE_SET_AT: CNY_RATE_SET_AT,
  });
})();
