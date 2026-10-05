(function () {
  'use strict';
  function mount(host, request) {
    if (!host || host.dataset.emailMounted) return;
    host.dataset.emailMounted = 'true';
    host.classList.add('report-email-settings');
    let data = {}, editing = null, busy = false;
    const keys = new Map();
    const node = (tag, text, className) => { const n = document.createElement(tag); if (text) n.textContent = text; if (className) n.className = className; return n; };
    const icon = path => { const n = document.createElementNS('http://www.w3.org/2000/svg','svg'); n.setAttribute('viewBox','0 0 24 24'); n.setAttribute('fill','none'); n.setAttribute('stroke','currentColor'); n.setAttribute('stroke-width','2'); n.setAttribute('aria-hidden','true'); const p=document.createElementNS(n.namespaceURI,'path'); p.setAttribute('d',path); n.append(p); return n; };
    const button = (label, action, path) => { const b=node('button', path ? '' : label, path ? 'report-email-icon' : ''); b.type='button'; b.setAttribute('aria-label',label); b.title=label; if(path)b.append(icon(path)); b.addEventListener('click',action); return b; };
    const uuid = () => window.crypto.randomUUID ? window.crypto.randomUUID() : '10000000-1000-4000-8000-100000000000'.replace(/[018]/g,c=>(Number(c)^window.crypto.getRandomValues(new Uint8Array(1))[0]&15>>Number(c)/4).toString(16));
    const head=node('div','', 'report-email-head'); head.append(node('h3',host.id==='portal-report-email-manager'?'Schedules':'Email reports'));
    const manage=button('Manage reports',load); head.append(manage);
    const content=node('div'); content.hidden=true;
    const status=node('p','', 'report-email-status'); status.setAttribute('role','status'); status.setAttribute('aria-live','polite');
    host.append(head,status,content);
    async function call(payload) {
      if(busy)return null;
      busy=true; const controls=[...host.querySelectorAll('button')].map(b=>[b,b.disabled]); controls.forEach(([b])=>b.disabled=true);
      try { const response=await request(payload); return response.data || response; }
      catch(error) { status.textContent=error.message || 'Could not save report settings. Try again.'; return null; }
      finally { busy=false; controls.forEach(([b,disabled])=>b.disabled=disabled); }
    }
    async function load() { const result=await call({action:'list'}); if(!result)return; data=result; content.hidden=false; manage.textContent='Refresh'; render(); }
    async function send(s) {
      if(!window.confirm(`Send ${s.title} to its approved recipients now?`))return;
      if(!keys.has(s.id))keys.set(s.id,uuid());
      const result=await call({action:'send',id:s.id,client_request_id:keys.get(s.id)});
      if(result){keys.delete(s.id);status.textContent=result.message; window.MiniAppRuntime?.showToast(result.message,{tone:'success'});}
    }
    function render() {
      content.replaceChildren(); status.textContent=data.enabled ? 'Approved recipients only. Sending runs in the background.' : 'Email delivery is not configured. You can save schedules now.';
      for(const s of data.schedules || []) { const row=node('div','', 'report-email-row'); const copy=node('div','', 'report-email-copy'); copy.append(node('strong',s.title),node('small',`${s.active?'Active':'Paused'} · ${s.frequency} · ${s.recipients.length} recipient(s)`)); row.append(copy,button(`Edit ${s.title}`,()=>edit(s),'M16 3l5 5-12 12H4v-5L16 3z')); const sendButton=button(`Send ${s.title}`,()=>send(s),'M22 2L9 15M22 2l-7 20-6-7-7-6L22 2z'); sendButton.disabled=!data.enabled; row.append(sendButton); content.append(row); }
      content.append(button('Add report',()=>edit(null)));
      if(editing)renderForm();
    }
    function edit(s) { editing=s ? {...s} : {id:uuid(),revision:0,send_time:'08:00',frequency:'daily',recipients:[],preset:data.presets[0],group_configuration:data.groups[0]?.id}; render(); }
    function renderForm() {
      const form=node('form','', 'report-email-form');
      function field(key,label,options,type) { const wrap=node('label',label,key==='recipients'?'report-email-wide':''); const input=node(key==='recipients'?'textarea':options?'select':'input'); input.name=key; if(options)for(const [value,text] of options){const o=node('option',text);o.value=value;input.append(o);} else if(type)input.type=type; if(key==='recipients'){input.rows=3;input.placeholder='One email address per line';} input.value=key==='recipients'?editing.recipients.join('\n'):(editing[key] || ''); if(['title','group_configuration','recipients'].includes(key))input.required=true; wrap.append(input);form.append(wrap); }
      field('title','Report name',null,'text'); field('group_configuration','Group',data.groups.map(g=>[g.id,g.label]));
      field('preset','Report',data.presets.map(p=>[p,p==='tat'?'TAT outcomes':p==='complaints'?'Complaints overview':p[0].toUpperCase()+p.slice(1)]));
      field('frequency','Frequency',['daily','weekly','monthly','quarterly'].map(v=>[v,v[0].toUpperCase()+v.slice(1)])); field('send_time','Time (Nairobi)',null,'time');
      field('branch','Branch (blank = all)',null,'text');
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
    }
  }
  window.MiniAppReportEmailSettings={mount};
})();
