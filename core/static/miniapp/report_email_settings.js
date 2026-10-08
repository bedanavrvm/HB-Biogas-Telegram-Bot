(function () {
  'use strict';
  function mount(host, request) {
    if (!host || host.dataset.emailMounted) return;
    host.dataset.emailMounted = 'true';
    host.classList.add('report-email-settings');
    let data = {}, editing = null, busy = false;
    const keys = new Map();
    const sending = new Set();
    let watchVersion = 0;
    const node = (tag, text, className) => { const n = document.createElement(tag); if (text) n.textContent = text; if (className) n.className = className; return n; };
    const icon = path => { const n = document.createElementNS('http://www.w3.org/2000/svg','svg'); n.setAttribute('viewBox','0 0 24 24'); n.setAttribute('fill','none'); n.setAttribute('stroke','currentColor'); n.setAttribute('stroke-width','2'); n.setAttribute('aria-hidden','true'); const p=document.createElementNS(n.namespaceURI,'path'); p.setAttribute('d',path); n.append(p); return n; };
    const button = (label, action, path) => { const b=node('button', path ? '' : label, path ? 'report-email-icon miniapp-compact-icon' : ''); b.type='button'; b.setAttribute('aria-label',label); b.title=label; if(path)b.append(icon(path)); b.addEventListener('click',action); return b; };
    // These are idempotency identifiers, not authentication tokens. Older
    // WebViews must still be able to open the editor without crypto helpers.
    const uuid = () => {
      try {
        if(typeof window.crypto?.randomUUID === 'function')return window.crypto.randomUUID();
        if(typeof window.crypto?.getRandomValues === 'function')return '10000000-1000-4000-8000-100000000000'.replace(/[018]/g,c=>(Number(c)^window.crypto.getRandomValues(new Uint8Array(1))[0]&15>>Number(c)/4).toString(16));
      } catch(error) { /* Restricted WebView: use a non-security request key. */ }
      return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{const r=Math.floor(Math.random()*16);return(c==='x'?r:(r&3)|8).toString(16);});
    };
    const head=node('div','', 'report-email-head'); head.append(node('h3',host.id==='portal-report-email-manager'?'Schedules':'Email reports'));
    const manage=button('Manage reports',load); head.append(manage);
    const content=node('div'); content.hidden=true;
    const status=node('p','', 'report-email-status'); status.setAttribute('role','status'); status.setAttribute('aria-live','polite');
    host.append(head,status,content);
    const deliveryMessage = rows => {
      const counts={};rows.forEach(r=>counts[r.status]=(counts[r.status]||0)+1);
      const parts=[];
      if(counts.delivered)parts.push(`${counts.delivered} delivered`);
      if(counts.accepted)parts.push(`${counts.accepted} accepted by email provider`);
      if(counts.skipped)parts.push(`${counts.skipped} skipped: no matching data`);
      const issues=[...new Set(rows.filter(r=>['failed','blocked','uncertain','bounced','complained'].includes(r.status)).map(r=>r.issue||'Delivery failed. Check report deliveries in Admin.'))];
      parts.push(...issues);
      if(counts.retry)parts.push('Retry pending; check again shortly.');
      if(counts.queued||counts.processing)parts.push('Sending report…');
      return parts.join(' · ') || 'Checking report delivery…';
    };
    async function watchDeliveries(ids, scheduleId, version, pass=0) {
      if(!ids?.length)return;
      try {
        const response=await request({action:'status',delivery_ids:ids});
        const rows=(response.data||response).deliveries||[];
        if(version===watchVersion)status.textContent=deliveryMessage(rows);
        if(rows.length && rows.every(r=>!['queued','processing','retry'].includes(r.status))){
          sending.delete(scheduleId);
          if(rows.every(r=>['accepted','delivered','skipped'].includes(r.status)))keys.delete(scheduleId);
          host.querySelectorAll('[data-report-send]').forEach(b=>b.disabled=!data.enabled||sending.has(b.dataset.reportSend));
          return;
        }
        if(pass<20)window.setTimeout(()=>watchDeliveries(ids,scheduleId,version,pass+1),3000);
        else {sending.delete(scheduleId);status.textContent+=' Refresh to check progress.';host.querySelectorAll('[data-report-send]').forEach(b=>b.disabled=!data.enabled||sending.has(b.dataset.reportSend));}
      } catch(error) {
        sending.delete(scheduleId);status.textContent='Delivery status could not be checked. Refresh to check progress; do not send a new copy.';
        host.querySelectorAll('[data-report-send]').forEach(b=>b.disabled=!data.enabled||sending.has(b.dataset.reportSend));
      }
    }
    async function call(payload) {
      if(busy)return null;
      busy=true; const controls=[...host.querySelectorAll('button')].map(b=>[b,b.disabled]); controls.forEach(([b])=>b.disabled=true);
      try { const response=await request(payload); return response.data || response; }
      catch(error) { status.textContent=error.message || 'Could not save report settings. Try again.'; return null; }
      finally { busy=false; controls.forEach(([b,disabled])=>b.disabled=disabled); }
    }
    async function load() { const result=await call({action:'list'}); if(!result)return; data=result; content.hidden=false; manage.textContent='Refresh'; render();if(data.pending_delivery_ids?.length)watchDeliveries(data.pending_delivery_ids,'',++watchVersion); }
    async function send(s) {
      if(sending.has(s.id))return;
      if(!window.confirm(`Send ${s.title} to its approved recipients now?`))return;
      if(!keys.has(s.id))keys.set(s.id,uuid());
      const result=await call({action:'send',id:s.id,client_request_id:keys.get(s.id)});
      if(result){status.textContent=result.message; window.MiniAppRuntime?.showToast(result.message,{tone:'success'});if(result.delivery_ids?.length){sending.add(s.id);host.querySelectorAll('[data-report-send]').forEach(b=>b.disabled=!data.enabled||sending.has(b.dataset.reportSend));watchDeliveries(result.delivery_ids,s.id,++watchVersion);}else keys.delete(s.id);}
    }
    function render() {
      content.replaceChildren(); status.textContent=data.enabled ? 'Approved recipients only. Sending runs in the background.' : 'Email delivery is not configured. You can save schedules now.';
      for(const s of data.schedules || []) { const row=node('div','', 'report-email-row'); const copy=node('div','', 'report-email-copy'); copy.append(node('strong',s.title),node('small',`${s.active?'Active':'Paused'} · ${s.frequency} · ${s.recipients.length} recipient(s)`)); row.append(copy,button(`Edit ${s.title}`,()=>edit(s),'M16 3l5 5-12 12H4v-5L16 3z')); const sendButton=button(`Send ${s.title}`,()=>send(s),'M22 2L9 15M22 2l-7 20-6-7-7-6L22 2z'); sendButton.dataset.reportSend=s.id;sendButton.disabled=!data.enabled||sending.has(s.id); row.append(sendButton); content.append(row); }
      content.append(button('Add report',()=>edit(null)));
      if(editing)renderForm();
    }
    function edit(s) {
      try {
        editing=s ? {...s} : {id:uuid(),revision:0,send_time:'08:00',frequency:'daily',recipients:[],preset:data.presets[0],group_configuration:data.groups[0]?.id};
        render();
        const first=content.querySelector('input[name="title"]');
        first?.scrollIntoView({block:'center'});
        first?.focus({preventScroll:true});
      } catch(error) {
        status.textContent='Could not open report settings. Refresh and try again.';
      }
    }
    function renderForm() {
      const form=node('form','', 'report-email-form miniapp-report-filter-fields');
      function field(key,label,options,type) { const wrap=node('label',label,key==='recipients'?'report-email-wide':''); const input=node(key==='recipients'?'textarea':options?'select':'input'); input.name=key; if(options)for(const [value,text] of options){const o=node('option',text);o.value=value;input.append(o);} else if(type)input.type=type; if(key==='recipients'){input.rows=3;input.placeholder='One email address per line';} input.value=key==='recipients'?editing.recipients.join('\n'):(editing[key] || ''); if(['title','group_configuration','recipients'].includes(key))input.required=true; wrap.append(input);form.append(wrap); }
      field('title','Report name',null,'text');
      const group=node('input');group.type='hidden';group.name='group_configuration';group.value=editing.group_configuration || '';form.append(group);
      field('preset','Report',data.presets.map(p=>[p,p==='tat'?'TAT outcomes':p==='complaints'?'Complaints overview':p[0].toUpperCase()+p.slice(1)]));
      field('frequency','Frequency',['daily','weekly','monthly','quarterly'].map(v=>[v,v[0].toUpperCase()+v.slice(1)])); field('send_time','Time (Nairobi)',null,'time');
      const branches=(data.branches_by_group?.[String(editing.group_configuration)] || [{value:'',label:'All branches'}]).map(b=>[b.value,b.label]);
      if(editing.branch && !branches.some(b=>b[0]===editing.branch))branches.push([editing.branch,editing.branch]);
      field('branch','Branch',branches);
      if(!data.presets.includes('complaints'))field('product','Product code (blank = all)',null,'text');
      if(data.presets.includes('pipeline'))field('county','County (optional)',null,'text');
      field('recipients','Recipients');
      for(const [key,label] of [['active','Active'],['skip_empty','Skip empty reports']]){ const wrap=node('label',label,'report-email-check');const input=node('input');input.type='checkbox';input.name=key;input.checked=!!editing[key];wrap.prepend(input);form.append(wrap); }
      const actions=node('div','', 'report-email-actions report-email-wide'); const save=node('button','Save');save.type='submit'; actions.append(save,button('Cancel',()=>{editing=null;render();}));form.append(actions);
      form.addEventListener('submit',async event=>{event.preventDefault();if(!form.reportValidity()||busy)return;
        if(!window.confirm('Approve these recipients to receive this report and its selected scope?'))return;
        const values=Object.fromEntries(new FormData(form));values.active=form.elements.active.checked;values.skip_empty=form.elements.skip_empty.checked;values.recipients=values.recipients.split(/[\n,;]+/).map(v=>v.trim()).filter(Boolean);
        const result=await call({...values,action:'save',id:editing.id,revision:editing.revision});if(result){data=result;editing=null;render();status.textContent='Report settings saved.';}
      }); content.append(form);
      window.MiniAppUtils?.bindAccessibleForm?.(form, {validators: {
        recipients: value => {
          const emails = String(value).split(/[\n,;]+/).map(item => item.trim()).filter(Boolean);
          return emails.length && emails.every(email => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) ? '' : 'Enter a valid email address for each recipient.';
        },
      }});
    }
  }
  window.MiniAppReportEmailSettings={mount};
})();
