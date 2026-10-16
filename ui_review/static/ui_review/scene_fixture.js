/* Synthetic I/O only. Application renderers and their styles remain original. */
(function () {
  'use strict';
  const config = JSON.parse(document.getElementById('ui-scene-config').textContent);
  const calls = []; const gaps = [];
  window.UI_SCENE = {config, calls, gaps, ready: false};
  // srcdoc has an opaque about: URL. Keep the app's normal relative-URL I/O
  // semantics without granting the frame same-origin access to its host.
  const NativeURL = window.URL;
  window.URL = class SceneURL extends NativeURL {
    constructor(value, base) {
      super(value, base && (base==='null'||/^(about:|blob:)/.test(base)) ? document.baseURI : base);
    }
  };
  const record = method => (...args) => {calls.push({method, arguments: args.map(value => typeof value)});};
  const noNavigation=()=>{calls.push({method:'page-navigation-blocked'});gaps.push('Page navigation captured; open the intended journey as its own source scene.');};
  window.UI_SCENE.navigation={assign:noNavigation,replace:noNavigation,reload:noNavigation,set href(_value){noNavigation();}};
  const handlers = new Map();
  const button = name => ({show: record(name+'.show'), hide: record(name+'.hide'), setText: record(name+'.setText'),
    enable(){}, disable(){}, showProgress(){}, hideProgress(){}, setParams(){}, onClick: callback => handlers.set(name, callback), offClick: () => handlers.delete(name)});
  window.Telegram = {WebApp: {initData: 'synthetic-only-not-valid-auth', initDataUnsafe: {}, platform:'unknown', version:'8.0',
    colorScheme:'light',themeParams:{}, ready:record('ready'),expand:record('expand'),onEvent:(key,fn)=>handlers.set(key,fn),offEvent:key=>handlers.delete(key),
    enableClosingConfirmation:record('enableClosingConfirmation'),disableClosingConfirmation:record('disableClosingConfirmation'),
    enableVerticalSwipes(){},disableVerticalSwipes(){}, setHeaderColor(){},setBackgroundColor(){},setBottomBarColor(){},isVersionAtLeast:()=>true,
    BackButton:button('BackButton'),MainButton:button('MainButton'),HapticFeedback:{impactOccurred:record('haptic.impact'),notificationOccurred:record('haptic.notification'),selectionChanged:record('haptic.selection')},
    openLink:record('openLink'),openTelegramLink:record('openTelegramLink'),downloadFile:record('downloadFile'),close:record('close')}};
  window.addEventListener('message',event=>{
    if(event.source!==window.parent || event.data?.type!=='ui-lab-theme')return;
    const dark=event.data.mode==='dark';const app=window.Telegram.WebApp;app.colorScheme=dark?'dark':'light';
    const colors=dark?{bg_color:'#17171e',secondary_bg_color:'#20202c',text_color:'#ffffff',hint_color:'#a8a8b3',button_color:'#72bff4',button_text_color:'#102331'}:{bg_color:'#f5f7f8',secondary_bg_color:'#ffffff',text_color:'#17212b',hint_color:'#6d7a86',button_color:'#176ca5',button_text_color:'#ffffff'};
    app.themeParams=colors;for(const [key,value]of Object.entries(colors))document.documentElement.style.setProperty('--tg-theme-'+key.replaceAll('_','-'),value);
    document.documentElement.dataset.miniappColorScheme=app.colorScheme;document.documentElement.dataset.telegramTheme=app.colorScheme;handlers.get('themeChanged')?.();
  });
  window.open = record('window.open');
  navigator.sendBeacon = () => false;
  if (navigator.mediaDevices) navigator.mediaDevices.getUserMedia = async () => {throw new Error('Camera and microphone are disabled in synthetic scenes.');};
  const count = config.state === 'empty' ? 0 : config.state === 'many' ? 20 : 1;
  const name = config.state === 'long' ? 'Synthetic Wanjiku Mwangi-Kamau With A Deliberately Long Applicant Name' : 'Synthetic Wanjiku Mwangi';
  const now = '2026-10-16T09:00:00+03:00';
  const rows = Array.from({length:count}, (_, index) => ({id:`00000000-0000-0000-0000-${String(index+1).padStart(12,'0')}`,
    case_id:`UI-TRAIN-${index+1}`, reference_number:`TRAIN-${index+1}`,name,client_name:name,customer_name:name,applicant_name:name,
    national_id:'00000000',customer_id:'00000000',primary_phone:'0700000000',customer_phone:'0700000000',phone:'0700000000',
    branch:'Training branch',branch_region:'Training branch',product:'Training product',product_key:'training',product_name:'Training product',
    amount:'85000',amount_display:'KES 85,000',status:'Active',status_label:'Active',stage:'BM analysis approval',next_stage:'BM analysis approval',
    category:'Synthetic system issue',age_label:'2 days open',created_at:now,updated_at:now,reported_at:now,workflow_revision:1,
    applicant_summary:{name,national_id:'00000000',phone:'0700000000'}}));
  const pagination = {page:1,pages:config.state==='many'?3:1,total:count,offset:0,page_size:10};
  const allCaps = ['tat.case.view','tat.case.create','tat.case.correct','tat.case.search','tat.reports.view','tat.recognition.view',
    'complaint.queue.view','complaint.case.create','complaint.reports.view','complaint.case.export','complaint.case.comment',
    'portal.dashboard.view','portal.jbl_queue.view','portal.jbl_visit.view','portal.jbl_visit.log','portal.case.view','portal.settings.view',
    'portal.performance.view','portal.reports.view','portal.document_history.view','portal.credit_queue.view','portal.payment.view'];
  const caps = config.role === 'staff' ? allCaps.filter(value => !/reports|settings|performance|recognition|export/.test(value)) : allCaps;
  const actor = {id:1,user_id:1,name:'Synthetic reviewer',roles:[config.role.toUpperCase()],role:config.role.toUpperCase(),capabilities:caps};
  const products = [{key:'training',label:'Training product',name:'Training product',value:'training',id:'training'}];
  const home = {queue:'role',items:rows,metrics:{total:count,role:count},pagination,visibility:{},action_required:rows,recent:rows};
  const summary = {total:count,pending:count,resolved:0,by_category:[{label:'Synthetic system issue',count}],by_branch:[{label:'Training branch',count}],
    time_granularity:'month',filter_options:{branches:[{label:'Training branch',count}],categories:[{label:'Synthetic system issue',count}]},
    activity:[{label:'2026-10',received:count,resolved:0}],reported_outcomes:[{label:'2026-10',closed:0,open:count}],
    open_age:[{key:'under_3',label:'Under 3 days',count}],timing:{median_resolution_hours:null,on_time_percent:null,resolution_count:0},
    resolution_trend:[],response_trend:[],resolution_by_category:[],reopenings:[]};
  function payload(path) {
    if (path.startsWith('/api/portal/')) {
      if (path.endsWith('/meta/')) return {ok:true,actor,capabilities:caps,branches:['Training branch'],counties:['Training county'],business_date:'2026-10-16',
        access_policy_version:'synthetic',jbl_visit_statuses:['Pending','Visited'],credit_decisions:[],final_decisions:[],approval_reasons:[],
        location_catalog:{branches:[],counties:[],sub_counties:[]},voice_input:{enabled:false}};
      if (path.endsWith('/dashboard/')) return {ok:true,counts:{},calculated_at:now,home:{actions:[],queues:[],shortcuts:[],system_health:[]}};
      if (path.includes('/fragment/')) throw new Error('Synthetic JSON renderer fallback; HTML fragment is not modelled.');
      if (path.includes('queue') || path.endsWith('/farmers/')) return {ok:true,farmers:rows,pagination,filter_options:{branches:['Training branch'],counties:['Training county']}};
      if (path.endsWith('/pump/')) return {ok:true,changed:false,poll_after_seconds:600};
      return {ok:true,items:[],results:[],records:[],rows:[],settings:{},data:{},pagination};
    }
    if (path.startsWith('/api/tat-tracker/')) {
      if (path.endsWith('/bootstrap/')) return {ok:true,data:{...home,authorized:true,user:actor,products,branches:['Training branch'],statuses:['Active','Stalled','Declined','Disbursed'],bro_users:[{id:'1',name:'Synthetic officer',username:'synthetic-officer'}],personal:{},task_inbox:{items:[]}}};
      if (path.endsWith('/home/')) return {ok:true,data:home};
      if (path.endsWith('/tasks/')) return {ok:true,data:{items:[],pagination}};
      if (path.includes('/draft')) return {ok:true,data:{draft:null}};
      gaps.push('TAT journey not modelled: '+path); return {ok:false,error:'This journey has not been modelled in the lab yet.'};
    }
    if (path.startsWith('/api/complaints/')) {
      if (path.endsWith('/bootstrap/')) return {ok:true,data:{actor,counts:{pending:count,total:count,resolved:0},branches:['Training branch'],
        categories:['Synthetic system issue'],category_catalogue:[],location_options:{counties:[],sub_counties:[]},voice_input:{enabled:false}}};
      if (path.endsWith('/cases/')) return {ok:true,cases:rows.map(row=>({...row,status:'Pending'})),pagination,start_index:1};
      if (path.endsWith('/summary/')) return {ok:true,...summary};
      if (path.endsWith('/data/')) return {ok:true,results:rows,count,page:1,page_size:50};
      if (path.includes('/draft')) return {ok:true,data:{draft:null}};
      gaps.push('Complaints journey not modelled: '+path); return {ok:false,error:'This journey has not been modelled in the lab yet.'};
    }
    if (path.startsWith('/api/origination/api/')) {
      if (path.endsWith('/products/')) return {ok:true,products,branches:['Training branch'],capabilities:{can_create:true,user_id:1}};
      if (path.endsWith('/applications/')) return {ok:true,applications:rows.map(row=>({...row,status:'draft',status_label:'Draft',next_action:'Continue application'})),
        tab_counts:{action:count,applications:count},status_options:[{value:'draft',label:'Draft'},{value:'completed',label:'Completed'}],
        filter_options:{products},capabilities:{can_create:true,user_id:1},pagination,applications_label:'My applications'};
      gaps.push('Origination journey not modelled: '+path); return {ok:false,error:'This journey has not been modelled in the lab yet.'};
    }
    if (path.includes('draft') || path.includes('diagnostics')) return {ok:true,data:{draft:null}};
    gaps.push('Unmodelled request: '+path); return {ok:false,error:'This request is not modelled in the lab.'};
  }
  const reads = /\/(bootstrap|home|tasks|cases|summary|data|products|applications|meta|dashboard|settings|drafts|pump)\/$|queue\/|\/farmers\//;
  window.fetch = async function (input, options = {}) {
    const url = new URL(typeof input === 'string' ? input : input.url, document.baseURI);
    const method = String(options.method || 'GET').toUpperCase();
    calls.push({method:'fetch',path:url.pathname,verb:method});
    if (url.origin !== new URL(document.baseURI).origin) throw new Error('External requests are disabled.');
    if (method !== 'GET' && !(method==='POST' && reads.test(url.pathname))) {
      return new Response(JSON.stringify({ok:false,error:'Business writes are disabled in the Design Lab.'}),{status:403});
    }
    if (config.state === 'loading') return new Promise(()=>{});
    if (config.state === 'error' || config.state === 'denied') return new Response(JSON.stringify({ok:false,error:config.state==='denied'?'Synthetic access denied.':'Synthetic connection failure. Try again.'}),{status:config.state==='denied'?403:503});
    if(url.pathname==='/api/portal/queues/jbl/fragment/')return new Response(config.portal_fragment,{status:200,headers:{'Content-Type':'text/html'}});
    const value = payload(url.pathname);
    return new Response(JSON.stringify(value),{status:value.ok===false?422:200,headers:{'Content-Type':'application/json'}});
  };
  XMLHttpRequest.prototype.open = function (method, url) {this.uiMethod=String(method).toUpperCase();this.uiUrl=new URL(url,document.baseURI);};
  XMLHttpRequest.prototype.setRequestHeader = function () {};
  XMLHttpRequest.prototype.send = function () {
    const known=this.uiMethod==='GET' && this.uiUrl.pathname==='/api/portal/navigation/';
    if(!known){gaps.push('Unmodelled XHR blocked.');this.dispatchEvent(new Event('error'));return;}
    const text=config.portal_navigation||'';
    for(const [key,value]of Object.entries({status:200,readyState:4,responseText:text,response:text,responseURL:this.uiUrl.href}))Object.defineProperty(this,key,{value,configurable:true});
    this.getAllResponseHeaders=()=> 'Content-Type: text/html';this.getResponseHeader=()=>null;
    setTimeout(()=>{this.dispatchEvent(new Event('load'));this.dispatchEvent(new Event('loadend'));},0);
  };
  document.addEventListener('click',event=>{if(event.target.closest?.('a[href]')){event.preventDefault();calls.push({method:'link-navigation-blocked'});}},true);
  document.addEventListener('submit',event=>{event.preventDefault();},true);
})();
