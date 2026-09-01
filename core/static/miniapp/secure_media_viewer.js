(function () {
  'use strict';

  async function fetchAuthorizedBlob(url, options) {
    const settings = options || {};
    const response = await fetch(url, {
      method: settings.method || 'GET',
      headers: { ...(settings.headers || {}) },
      body: settings.body,
      cache: 'no-store',
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || payload.message || 'The evidence could not be opened.');
    }
    const blob = await response.blob();
    if (!blob.size) throw new Error('The evidence file was empty.');
    return blob;
  }

  function renderBlob(container, blob, options) {
    const settings = options || {};
    const objectUrl = URL.createObjectURL(blob);
    const mimeType = String(blob.type || settings.mimeType || '').toLowerCase();
    container.replaceChildren();
    if (mimeType.startsWith('image/')) {
      const image = document.createElement('img');
      image.className = settings.imageClass || 'media-viewer-image';
      image.src = objectUrl;
      image.alt = settings.name || 'Evidence preview';
      container.appendChild(image);
    } else {
      const frame = document.createElement('iframe');
      frame.className = settings.documentClass || 'media-viewer-document';
      frame.src = objectUrl;
      frame.title = settings.name || 'Evidence preview';
      frame.setAttribute('sandbox', '');
      container.appendChild(frame);
    }
    return objectUrl;
  }

  function revoke(objectUrl) {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  }

  window.SecureMediaViewer = { fetchAuthorizedBlob, renderBlob, revoke };
}());
