(function () {
  'use strict';

  const scripts = new Map();
  const styles = new Map();

  function loadScript(url, globalName) {
    if (globalName && window[globalName]) return Promise.resolve(window[globalName]);
    if (!url) return Promise.reject(new Error('Asset URL is unavailable.'));
    if (scripts.has(url)) return scripts.get(url);
    const promise = new Promise(function (resolve, reject) {
      const element = document.createElement('script');
      element.src = url;
      element.async = true;
      element.onload = function () { resolve(globalName ? window[globalName] : true); };
      element.onerror = function () { scripts.delete(url); reject(new Error('Could not load the requested interface asset.')); };
      document.head.appendChild(element);
    });
    scripts.set(url, promise);
    return promise;
  }

  function loadStyle(url) {
    if (!url) return Promise.reject(new Error('Stylesheet URL is unavailable.'));
    if (styles.has(url)) return styles.get(url);
    const promise = new Promise(function (resolve, reject) {
      const element = document.createElement('link');
      element.rel = 'stylesheet';
      element.href = url;
      element.onload = function () { resolve(true); };
      element.onerror = function () { styles.delete(url); reject(new Error('Could not load the requested interface styles.')); };
      document.head.appendChild(element);
    });
    styles.set(url, promise);
    return promise;
  }

  function loadLeaflet() {
    const config = window.PORTAL_CONFIG || {};
    return Promise.all([
      loadStyle(config.leafletStyles),
      loadScript(config.leafletScript, 'L'),
    ]).then(function () { return window.L; });
  }

  window.MiniAppAssetLoader = Object.freeze({ loadScript: loadScript, loadStyle: loadStyle, loadLeaflet: loadLeaflet });
})();
