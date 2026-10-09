(() => {
  'use strict';
  const forms=[...document.querySelectorAll('[data-osw-autosave]')], feedback=document.querySelector('[data-save-feedback]');
  let dirty=false,timer,inFlight,failed=false,generation=0,pending;
  const notice=text => {if(feedback) feedback.textContent=text;};
  const apply=data => {
    document.querySelectorAll('input[name="expected_tokens"]').forEach(i => {i.value=JSON.stringify(data.expected_tokens);});
    const documentList=document.querySelector('[data-selected-documents]');
    if(documentList && !dirty && typeof data.documents_html==='string') documentList.innerHTML=data.documents_html;
    const publishForm=document.querySelector('[data-product-publish]');
    if(publishForm) {
      publishForm.dataset.stopNew=String(Boolean(data.stop_new_applications));
      publishForm.querySelectorAll('input[name="templates"]').forEach(i => i.remove());
      for(const id of data.selected_document_ids || []) {const i=document.createElement('input');i.type='hidden';i.name='templates';i.value=id;publishForm.append(i);}
      const token=publishForm.elements.namedItem('maintenance_token');if(token) token.value=data.maintenance_token;
    }
    for(const task of data.tasks) {
      const row=document.querySelector(`[data-task="${task.key}"]`);
      if(row) {row.classList.toggle('complete',task.valid);row.querySelector('[data-task-status]').textContent=task.status_label;row.querySelector('[data-task-detail]').textContent=task.detail;}
    }
    const count=document.querySelector('[data-outstanding]');if(count) count.textContent=data.outstanding_count ? `${data.outstanding_count} things left` : 'Ready';
    const publish=document.querySelector('[data-product-publish] button');if(publish) publish.disabled=!data.can_publish || dirty || failed;
  };
  async function save() {
    clearTimeout(timer);
    if(inFlight) {await inFlight;if(dirty && !failed) return save();return;}
    if(!dirty || !pending) return;
    const form=pending,captured=generation,body=new FormData(form);body.set('intent','stay');
    form._retry ||= {generation:captured,key:crypto.randomUUID()};
    if(form._retry.generation!==captured) form._retry={generation:captured,key:crypto.randomUUID()};
    body.set('request_id',form._retry.key);notice('Saving…');
    inFlight=(async () => {
      try {
        const response=await fetch(form.getAttribute('action') || location.href,{method:'POST',body,headers:{'X-Requested-With':'XMLHttpRequest'}}),result=await response.json();
        form.querySelectorAll('[data-autosave-error]').forEach(e => e.remove());
        if(!response.ok || !result.ok) {
          failed=true;
          for(const [key,errors] of Object.entries(result.errors || {})) {
            const control=form.elements.namedItem(key);
            if(control instanceof Element && Array.isArray(errors)) {
              const error=document.createElement('small');error.dataset.autosaveError='';error.className='errorlist';error.id=`${control.id}-save-error`;error.textContent=errors.map(e => e.message).join(' ');
              control.setAttribute('aria-invalid','true');control.setAttribute('aria-describedby',`${control.getAttribute('aria-describedby') || ''} ${error.id}`.trim());control.after(error);
            }
          }
          notice(result.error || 'Couldn’t save. Check the highlighted fields.');
        } else {
          failed=false;dirty=captured!==generation;delete form._retry;
          form.querySelectorAll('[aria-invalid="true"]').forEach(c => {c.removeAttribute('aria-invalid');const ids=(c.getAttribute('aria-describedby') || '').split(' ').filter(id => id!==`${c.id}-save-error`);if(ids.length) c.setAttribute('aria-describedby',ids.join(' '));else c.removeAttribute('aria-describedby');});notice(dirty ? 'Unsaved changes' : 'Saved');
        }
        if(result.data && response.status!==409) apply(result.data);
      } catch(error) {failed=true;notice('Not saved · tap to retry. Your input is still here.');}
      finally {inFlight=null;}
    })();
    await inFlight;if(dirty && !failed) return save();
  }
  feedback?.addEventListener('click',() => {if(failed) {failed=false;save();}});
  for(const form of forms) {
    const changed=() => {pending=form;dirty=true;failed=false;generation++;notice('Unsaved changes');clearTimeout(timer);timer=setTimeout(save,650);document.querySelector('[data-product-publish] button')?.setAttribute('disabled','');};
    form.addEventListener('input',changed);form.addEventListener('change',changed);form.addEventListener('submit',e => {e.preventDefault();save();});
    form.querySelectorAll('[data-add-row]').forEach(b => b.addEventListener('click',changed));
  }
  document.addEventListener('click',async e => {
    const link=e.target.closest('a');if(!link || !dirty || link.target || e.ctrlKey || e.metaKey) return;
    e.preventDefault();await save();if(!dirty && !failed) location.assign(link.href);
  });
  document.querySelector('[data-product-publish]')?.addEventListener('submit',async e => {
    e.preventDefault();const form=e.currentTarget;await save();if(dirty || failed) return;
    const body=new FormData(form);
    if(form.dataset.stopNew==='true') {
      if(!window.confirm('Remove the last Main LAF? This stops new applications. Existing applications stay unchanged.')) return;
      body.set('allow_unavailable','yes');
    }
    const button=form.querySelector('button');button.disabled=true;notice('Publishing…');
    try {
      const response=await fetch(form.getAttribute('action'),{method:'POST',body,headers:{'X-Requested-With':'XMLHttpRequest'}}),result=await response.json();
      if(!response.ok || !result.ok) {notice(result.error || 'Couldn’t publish. Open the tasks needing attention.');button.disabled=false;return;}
      dirty=false;location.reload();
    } catch(error) {notice('Couldn’t confirm publication. Retry safely.');button.disabled=false;}
  });
  window.addEventListener('beforeunload',e => {if(dirty) {e.preventDefault();e.returnValue='';}});
})();
