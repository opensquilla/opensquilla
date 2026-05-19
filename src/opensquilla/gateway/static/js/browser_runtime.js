/** OpenSquilla Web UI - browser runtime contract helpers. */

const OpenSquillaBrowserRuntime = (() => {
  const CORE_GLOBALS = Object.freeze([
    'RpcClient',
    'WebUiRpc',
    'WebUiHttp',
    'Router',
  ]);
  const APP_GLOBALS = Object.freeze([
    'App',
  ]);

  function _globalObject() {
    return typeof window !== 'undefined' ? window : globalThis;
  }

  function _resolveGlobal(name) {
    if (name === 'App' && typeof App !== 'undefined') return App;
    const global = _globalObject();
    return global ? global[name] : undefined;
  }

  function availableGlobals(names = [...CORE_GLOBALS, ...APP_GLOBALS]) {
    const available = {};
    names.forEach((name) => {
      available[name] = !!_resolveGlobal(name);
    });
    return available;
  }

  function requireGlobals(names = CORE_GLOBALS) {
    const missing = names.filter((name) => !_resolveGlobal(name));
    if (missing.length) {
      throw new Error('OpenSquilla browser runtime missing: ' + missing.join(', '));
    }
    return true;
  }

  function coreContract() {
    requireGlobals(CORE_GLOBALS);
    return {
      RpcClient: _resolveGlobal('RpcClient'),
      WebUiRpc: _resolveGlobal('WebUiRpc'),
      WebUiHttp: _resolveGlobal('WebUiHttp'),
      Router: _resolveGlobal('Router'),
    };
  }

  function appContract() {
    requireGlobals([...CORE_GLOBALS, ...APP_GLOBALS]);
    return {
      ...coreContract(),
      App: _resolveGlobal('App'),
    };
  }

  return {
    coreGlobals: CORE_GLOBALS,
    appGlobals: APP_GLOBALS,
    availableGlobals,
    requireGlobals,
    coreContract,
    appContract,
  };
})();

window.OpenSquillaBrowserRuntime = OpenSquillaBrowserRuntime;
