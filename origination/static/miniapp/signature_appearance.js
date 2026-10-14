/* One typed-mark control for officer, TEST and remote signing. Images stay in memory. */
(() => {
  'use strict';
  const fonts = [['caveat', 'Caveat'], ['dancing_script', 'Dancing Script'],
    ['yellowtail', 'Yellowtail'], ['nothing_you_could_do', 'Nothing You Could Do']];
  window.OriginationSignatureAppearance = {
    mount({input, container, request, onChange = () => {}}) {
      container.innerHTML = '<fieldset class="signature-styles"><legend>Style</legend>' +
        fonts.map(([key, label], index) => `<label><input type="radio" name="signature-style" value="${key}" ${index ? '' : 'checked'}><span>${label}</span></label>`).join('') +
        '</fieldset><div class="typed-mark-frame"><img alt="Your signature preview" hidden><span role="status" aria-live="polite">Type your name to preview</span></div>';
      const image = container.querySelector('img');
      const status = container.querySelector('[role="status"]');
      let sequence = 0, timer, preview = null, disposed = false;
      const values = () => ({name: input.value.trim(), font: container.querySelector('input:checked').value});
      const update = () => {
        const ticket = ++sequence;
        preview = null; image.hidden = true;
        clearTimeout(timer); onChange();
        if (values().name.length < 2) { status.textContent = 'Type your name to preview'; return; }
        status.textContent = 'Preparing preview…';
        timer = setTimeout(async () => {
          try {
            const result = await request(values());
            if (disposed || ticket !== sequence) return;
            if (!result?.sha256 || !result?.image_url?.startsWith('data:image/png;base64,')) throw new Error(result?.error || 'Could not load preview. Edit your name or style to retry.');
            preview = {...values(), appearance_version: 2, preview_sha256: result.sha256};
            image.src = result.image_url; image.hidden = false; status.textContent = '';
          } catch (error) { if (!disposed && ticket === sequence) status.textContent = error.message; }
        }, 300);
      };
      input.addEventListener('input', update);
      container.addEventListener('change', update);
      update();
      return {
        capture() {
          if (!preview) throw new Error('Wait for your signature preview, then try again.');
          return {method: 'typed', ...preview};
        },
        dispose() { disposed = true; ++sequence; clearTimeout(timer); input.removeEventListener('input', update); container.removeEventListener('change', update); },
      };
    },
  };
})();
