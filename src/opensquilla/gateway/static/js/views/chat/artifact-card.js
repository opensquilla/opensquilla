// Artifact cards for chat history and live stream artifact events.
// Pure renderer; chat.js owns placement, auth context, and click handling.

(function (root) {
  'use strict';

  const MIME_CATEGORIES = {
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

  const EXTENSION_CATEGORIES = {
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

  function renderArtifacts(artifacts, options) {
    if (!Array.isArray(artifacts) || artifacts.length === 0) return '';
    const opts = options || {};
    let html = '<div class="msg-artifacts">';
    let openGroup = '';
    const closeGroup = () => {
      if (!openGroup) return;
      html += '</div>';
      openGroup = '';
    };

    artifacts.forEach((artifact) => {
      const category = artifactCategory(artifact);
      const groupKind = category === 'visual' ? 'visual' : 'file';
      if (groupKind !== openGroup) {
        closeGroup();
        html += groupKind === 'visual'
          ? '<div class="msg-artifact-gallery">'
          : '<div class="msg-artifact-files">';
        openGroup = groupKind;
      }
      html += renderArtifactCard(artifact || {}, category, opts);
    });

    closeGroup();
    html += '</div>';
    return html;
  }

  function renderArtifactCard(artifact, category, options) {
    const name = artifactName(artifact);
    const mime = artifact.mime ? String(artifact.mime) : 'artifact';
    const size = artifact.size ? `${Math.max(1, Math.round(Number(artifact.size) / 1024))} KB` : '';
    const meta = [mime, size].filter(Boolean).join(' / ');
    const rawDownloadUrl = artifactDownloadUrl(artifact, options);
    const href = authenticatedDownloadUrl(rawDownloadUrl, options);
    const previewUrl = category === 'visual' ? authenticatedDownloadUrl(rawDownloadUrl, options) : '';
    const cardClass = [
      'msg-artifact-card',
      category === 'visual' ? 'msg-artifact-card--image' : '',
      category === 'audio' ? 'msg-artifact-card--audio' : '',
    ].filter(Boolean).join(' ');

    const media = category === 'visual'
      ? (
        previewUrl
          ? `<img class="msg-artifact-preview" src="${escapeAttr(previewUrl)}" alt="${escapeHtml(name)}" loading="lazy">`
          : '<span class="msg-artifact-preview msg-artifact-preview--empty" aria-hidden="true"></span>'
      )
      : '';
    const audio = category === 'audio' && href
      ? `<audio class="msg-artifact-audio" controls preload="metadata" src="${escapeAttr(href)}"></audio>`
      : '';
    const openAction = href
      ? `<a class="msg-artifact-card__action" href="${escapeAttr(href)}" target="_blank" rel="noopener" data-artifact-download="${escapeAttr(rawDownloadUrl)}" data-artifact-id="${escapeAttr(artifact.id || '')}" data-artifact-name="${escapeAttr(name)}">Open</a>`
      : '<span class="msg-artifact-card__action" aria-disabled="true">Open</span>';
    const downloadAction = href
      ? `<a class="msg-artifact-card__action" href="${escapeAttr(href)}" download="${escapeAttr(name)}" data-artifact-download="${escapeAttr(rawDownloadUrl)}" data-artifact-id="${escapeAttr(artifact.id || '')}" data-artifact-name="${escapeAttr(name)}">Download</a>`
      : '<span class="msg-artifact-card__action" aria-disabled="true">Download</span>';

    return `<div class="${escapeAttr(cardClass)}" data-artifact-category="${escapeAttr(category)}" data-artifact-id="${escapeAttr(artifact.id || '')}" data-artifact-name="${escapeAttr(name)}">
      ${media}
      ${audio}
      <span class="msg-artifact-card__body">
        <span class="msg-artifact-card__name">${escapeHtml(name)}</span>
        <span class="msg-artifact-card__meta">${escapeHtml(meta)}</span>
      </span>
      <span class="msg-artifact-card__actions">${openAction}${downloadAction}</span>
    </div>`;
  }

  function artifactDownloadUrl(artifact, options) {
    let raw = artifact && artifact.download_url ? String(artifact.download_url) : '';
    if (!raw && artifact && artifact.id) raw = `/api/v1/artifacts/${encodeURIComponent(artifact.id)}`;
    if (!raw) return '';
    try {
      const url = new URL(raw, (options && options.origin) || root.location.origin);
      url.searchParams.delete('sessionKey');
      url.searchParams.delete('session_key');
      url.searchParams.delete('token');
      return url.pathname + url.search + url.hash;
    } catch {
      return raw;
    }
  }

  function authenticatedDownloadUrl(raw, options) {
    if (!raw) return '';
    try {
      const url = new URL(raw, (options && options.origin) || root.location.origin);
      const sessionKey = options && options.sessionKey ? String(options.sessionKey) : '';
      const token = options && options.token ? String(options.token) : '';
      if (sessionKey) url.searchParams.set('sessionKey', sessionKey);
      if (token) url.searchParams.set('token', token);
      return url.pathname + url.search + url.hash;
    } catch {
      return raw;
    }
  }

  function artifactName(artifact) {
    return artifact && artifact.name ? String(artifact.name) : 'artifact';
  }

  function artifactMime(artifact) {
    return artifact && artifact.mime ? String(artifact.mime).toLowerCase() : '';
  }

  function artifactExtension(name) {
    const trimmed = String(name || '').trim().toLowerCase();
    const idx = trimmed.lastIndexOf('.');
    if (idx < 0 || idx === trimmed.length - 1) return '';
    return trimmed.slice(idx + 1);
  }

  function artifactCategory(artifact) {
    const mime = artifactMime(artifact);
    if (mime.startsWith('image/')) return 'visual';
    if (mime.startsWith('audio/')) return 'audio';
    if (MIME_CATEGORIES[mime]) return MIME_CATEGORIES[mime];
    if (!mime || mime === 'application/octet-stream' || mime === 'artifact') {
      const ext = artifactExtension(artifactName(artifact));
      if (['mp3', 'wav', 'm4a', 'aac', 'ogg', 'oga', 'opus', 'flac', 'webm'].includes(ext)) return 'audio';
      if (EXTENSION_CATEGORIES[ext]) return EXTENSION_CATEGORIES[ext];
    }
    return 'file';
  }

  function escapeHtml(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, '&#39;');
  }

  root.ArtifactCard = {
    renderArtifacts,
  };
}(typeof window !== 'undefined' ? window : globalThis));
