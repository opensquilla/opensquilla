/** OpenSquilla Web UI - view-facing RPC access boundary. */

const WebUiRpc = (() => {
  function client() {
    const app = typeof App !== 'undefined' ? App : window.App;
    if (!app || typeof app.getRpc !== 'function') {
      throw new Error('OpenSquilla RPC client is not initialized');
    }
    return app.getRpc();
  }

  function call(method, params = {}) {
    return client().call(method, params);
  }

  function waitForConnection() {
    return client().waitForConnection();
  }

  function on(event, handler) {
    return client().on(event, handler);
  }

  function policy() {
    return client()?.policy || {};
  }

  return { client, call, waitForConnection, on, policy };
})();

window.WebUiRpc = WebUiRpc;
