/* Shared signing surface. Owning apps supply authorized preview and commit callbacks. */
(() => {
  'use strict';

  const escape = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[ch]);
  window.DocumentSigning = {
    async open({
      title,
      pageCount,
      loadPage,
      previewSignature,
      commit,
      external = false,
      readOnly = false,
      stamps = [],
      needsStamp = false
    }) {
      const dialog = document.createElement('dialog');
      dialog.className = 'portal-laf-dialog';
      dialog.innerHTML = `<header><h2>${escape(title)}</h2><button type="button" data-close aria-label="Close signing">Close</button></header>
        <div class="laf-pages" aria-label="Document pages"></div><p data-page-status role="status">Review every page before signing.</p>
        <section class="laf-signature"><h3>Your signature</h3><label>Type your full name<input data-name autocomplete="name" maxlength="120"></label><div data-mark></div>
        <details><summary>Draw signature instead</summary><canvas width="560" height="180" aria-label="Draw your signature" tabindex="0"></canvas><button type="button" data-clear>Clear drawing</button></details>
        <label class="laf-consent"><input type="checkbox" data-consent> I have reviewed this LAF and agree to sign it${external ? ' personally on this officer’s device' : ''}.</label>
        ${external ? '<label class="laf-consent"><input type="checkbox" data-witness> Officer: I confirm this person signed in my presence.</label>' : ''}
        <p role="alert" data-error></p><button class="btn btn-primary" type="button" data-sign disabled>Confirm signature</button></section>`;
      document.body.append(dialog);
      dialog.showModal();
      if (needsStamp) dialog.querySelector('.laf-signature').insertAdjacentHTML('afterbegin', `<label>Stamp<select data-stamp><option value="">Select stamp</option>${stamps.map(s => `<option value="${escape(s.id)}">${escape(s.name)}</option>`).join('')}</select></label>`);
      if (readOnly) dialog.querySelector('.laf-signature').hidden = true;
      const urls = [],
        reviewed = new Set(),
        loaded = new Set();
      const error = dialog.querySelector('[data-error]'),
        button = dialog.querySelector('[data-sign]');
      let busy = false,
        strokes = [],
        current = null;
      const mark = window.DocumentSigningSignature.mount({
        input: dialog.querySelector('[data-name]'),
        container: dialog.querySelector('[data-mark]'),
        request: previewSignature
      });
      const canvas = dialog.querySelector('canvas'),
        ctx = canvas.getContext('2d');
      ctx.lineWidth = 2;
      ctx.strokeStyle = '#172b4d';
      ctx.lineCap = 'round';
      const point = event => {
        const box = canvas.getBoundingClientRect();
        return [Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)), Math.min(1, Math.max(0, (event.clientY - box.top) / box.height))];
      };
      canvas.onpointerdown = event => {
        canvas.setPointerCapture(event.pointerId);
        current = [point(event)];
        strokes.push(current);
      };
      canvas.onpointermove = event => {
        if (!current) return;
        const p = point(event),
          last = current.at(-1);
        ctx.beginPath();
        ctx.moveTo(last[0] * 560, last[1] * 180);
        ctx.lineTo(p[0] * 560, p[1] * 180);
        ctx.stroke();
        current.push(p);
      };
      canvas.onpointerup = () => {
        current = null;
      };
      dialog.querySelector('[data-clear]').onclick = () => {
        strokes = [];
        ctx.clearRect(0, 0, 560, 180);
      };
      const update = () => {
        button.disabled = busy || reviewed.size !== pageCount || !dialog.querySelector('[data-consent]').checked || external && !dialog.querySelector('[data-witness]').checked;
        dialog.querySelector('[data-page-status]').textContent = `${reviewed.size} / ${pageCount} pages reviewed`;
      };
      const observer = new IntersectionObserver(entries => {
        entries.forEach(entry => {
          const page = Number(entry.target.dataset.page);
          if (entry.isIntersecting && loaded.has(page)) reviewed.add(page);
        });
        update();
      }, {
        root: dialog,
        threshold: .15
      });
      const close = () => {
        if (busy) return;
        mark.dispose();
        observer.disconnect();
        urls.forEach(URL.revokeObjectURL);
        dialog.close();
        dialog.remove();
      };
      dialog.querySelector('[data-close]').onclick = close;
      dialog.addEventListener('cancel', event => {
        event.preventDefault();
        close();
      });
      dialog.querySelector('[data-consent]').onchange = update;
      if (external) dialog.querySelector('[data-witness]').onchange = update;
      for (let page = 1; page <= pageCount; page++) {
        const image = document.createElement('img');
        image.alt = `LAF page ${page}`;
        image.dataset.page = page;
        dialog.querySelector('.laf-pages').append(image);
        try {
          const blob = await loadPage(page);
          if (!dialog.isConnected) break;
          const url = URL.createObjectURL(blob);
          urls.push(url);
          image.onload = () => {
            loaded.add(page);
            observer.observe(image);
          };
          image.src = url;
        } catch (exc) {
          error.textContent = exc.message || 'Could not load this page. Close and reopen signing.';
        }
      }
      const run = async fn => {
        if (busy) return;
        busy = true;
        update();
        error.textContent = '';
        try {
          await fn();
        } catch (exc) {
          error.textContent = exc.message;
        } finally {
          busy = false;
          update();
        }
      };
      button.onclick = () => run(async () => {
        const capture = strokes.some(s => s.length > 1) ? {
          method: 'drawn',
          strokes: strokes.filter(s => s.length > 1)
        } : mark.capture();
        await commit({
          capture,
          consent: true,
          ...(external ? {
            signing_mode: 'in_person',
            witnessed: dialog.querySelector('[data-witness]').checked
          } : {}),
          reviewed_pages: [...reviewed].sort((a, b) => a - b),
          stamp_id: dialog.querySelector('[data-stamp]')?.value
        });
        busy = false;
        close();
      });
    }
  };
})();
