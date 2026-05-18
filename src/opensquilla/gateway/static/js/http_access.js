/** OpenSquilla Web UI - browser HTTP access boundary. */

const WebUiHttp = (() => {
  function _app() {
    return typeof App !== 'undefined' ? App : window.App;
  }

  function _authToken() {
    const app = _app();
    return (app && typeof app.getAuthToken === 'function' && app.getAuthToken()) || '';
  }

  function _mergeHeaders(...sources) {
    const headers = {};
    sources.forEach((source) => {
      if (!source) return;
      if (typeof Headers !== 'undefined' && source instanceof Headers) {
        source.forEach((value, key) => { headers[key] = value; });
        return;
      }
      Object.entries(source).forEach(([key, value]) => {
        if (value === undefined || value === null) return;
        headers[key] = value;
      });
    });
    return headers;
  }

  function _withAuth(source) {
    const headers = _mergeHeaders(source);
    const hasAuth = Object.keys(headers).some((key) => key.toLowerCase() === 'authorization');
    const token = _authToken();
    if (token && !hasAuth) headers['Authorization'] = `Bearer ${token}`;
    return headers;
  }

  function request(url, options = {}) {
    const { auth = false, headers, ...fetchOptions } = options;
    return fetch(url, {
      ...fetchOptions,
      headers: auth ? _withAuth(headers) : _mergeHeaders(headers),
    });
  }

  async function json(response) {
    if (!response.ok) throw new Error('HTTP ' + response.status);
    return response.json();
  }

  async function getJson(url, options = {}) {
    return json(await request(url, options));
  }

  function postJsonResponse(url, body, options = {}) {
    return request(url, {
      ...options,
      method: 'POST',
      headers: _mergeHeaders({ 'Content-Type': 'application/json' }, options.headers),
      body: JSON.stringify(body),
    });
  }

  async function postJson(url, body, options = {}) {
    return json(await postJsonResponse(url, body, options));
  }

  function download(url, options = {}) {
    return request(url, {
      ...options,
      method: 'GET',
      auth: true,
      credentials: 'same-origin',
    });
  }

  function upload(url, form, options = {}) {
    return request(url, {
      ...options,
      method: 'POST',
      body: form,
      auth: true,
      credentials: 'same-origin',
    });
  }

  function getPendingApprovals() {
    return getJson('/api/approvals', { cache: 'no-store' });
  }

  function resolveApproval(body) {
    return postJson('/api/approvals/resolve', body);
  }

  return {
    request,
    getJson,
    postJsonResponse,
    postJson,
    download,
    upload,
    getPendingApprovals,
    resolveApproval,
  };
})();

window.WebUiHttp = WebUiHttp;
