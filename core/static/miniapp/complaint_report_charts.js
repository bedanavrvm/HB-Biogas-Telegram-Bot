/* Read-only report charts. All drill-downs use the same server filters as XLSX. */
(function () {
  'use strict';
  let charts = [];
  const chosenTypes = {};
  const hours = value => value == null ? '—' : value < 24 ? `${Number(value.toFixed(1))}h` : `${Number((value / 24).toFixed(1))}d`;
  const readableHours = value => value == null ? 'Unavailable' : `${Number(Number(value).toFixed(2))} hrs (${Number((value / 24).toFixed(1))} days)`;
  function period(label, grouping) {
    const start = new Date(`${label.length === 4 ? label + '-01-01' : label.length === 7 ? label + '-01' : label}T00:00:00Z`);
    const end = new Date(start);
    if (grouping === 'year') end.setUTCFullYear(end.getUTCFullYear() + 1);
    else if (grouping === 'month') end.setUTCMonth(end.getUTCMonth() + 1);
    else end.setUTCDate(end.getUTCDate() + (grouping === 'week' ? 7 : 1));
    end.setUTCDate(end.getUTCDate() - 1);
    return {date_from: start.toISOString().slice(0, 10), date_to: end.toISOString().slice(0, 10)};
  }
  function state(message) {
    document.querySelectorAll('[data-complaint-chart-slide]').forEach(slide => {
      slide.querySelector('canvas').hidden = !!message;
      const note = slide.querySelector('.chart-state'); note.textContent = message; note.hidden = !message;
      slide.querySelector('.chart-drill-controls')?.remove();
    });
  }
  function render(summary, options) {
    const {categoryType = 'bar', onSelect, formatPeriod} = options;
    charts.forEach(chart => chart.destroy()); charts = [];
    if (!window.Chart) { state('Charts unavailable. Use the report table below.'); return; }
    const root = getComputedStyle(document.documentElement);
    const color = (token, fallback) => root.getPropertyValue(token).trim() || fallback;
    const text = color('--muted', '#667085'), grid = color('--line', '#e2e8f0');
    const green = '#168354', red = '#d14343', blue = '#2481cc';
    const activity = summary.reported_outcomes || [], timing = summary.timing || {};
    const grouping = summary.time_granularity || 'month';
    const specifications = [
      {key:'activity', rows:activity, type:'line', datasets:[
        {label:'Closed (+ve)',data:activity.map(row=>row.closed),borderColor:green},
        {label:'Open & Reopened (−ve)',data:activity.map(row=>row.open),borderColor:red}],
        select:(row, dataset)=>({...period(row.label, grouping),date_basis:'reported',metric:dataset ? 'reported_open':'reported_closed'}),
        help:'Grouped by reporting date. Each complaint appears once, under its current status.'},
      {key:'age',rows:summary.open_age || [],horizontal:true,
        select:row=>({date_basis:'reported',metric:'open_age',metric_value:row.key}),note:timing.age_unavailable ? `${timing.age_unavailable} Complaint(s) without timing` : ''},
      {key:'resolution',rows:summary.resolution_trend || [],type:'line',hours:true,
        select:row=>({...period(row.label,grouping),date_basis:'resolved',metric:'resolution'}),help:'Median elapsed time from reporting to final closure, grouped by closure date.',note:timing.resolution_excluded ? `${timing.resolution_excluded} Complaint(s) without timing` : ''},
      {key:'target',rows:[{label:'On time',count:timing.on_time || 0},{label:'Late',count:timing.late || 0}],colors:[green,red],
        select:row=>({date_basis:'resolved',metric:row.label==='On time'?'on_time':'late'}),note:timing.target_unavailable ? `${timing.target_unavailable} Complaint(s) without a target` : ''},
      {key:'category',rows:summary.by_category || [],horizontal:categoryType!=='pie',type:categoryType,
        select:row=>({category:row.label,date_basis:'reported'}),help:'Complaint(s) reported in the selected dates, grouped by type.'},
      {key:'category_time',rows:summary.resolution_by_category || [],hours:true,horizontal:true,
        select:row=>({category:row.label,date_basis:'resolved',metric:'resolution'}),help:'Median elapsed time for Complaint(s) closed in the selected dates.'},
      {key:'response',rows:summary.response_trend || [],hours:true,type:'line',
        select:row=>({...period(row.label,grouping),date_basis:'response',metric:'hb_response'}),help:'Median time to the first saved HB comment or closure, grouped by that response date.',note:timing.response_unavailable ? `${timing.response_unavailable} Complaint(s) without an HB response` : ''},
      {key:'reopened',rows:summary.reopenings || [],type:'line',
        select:row=>({...period(row.label,grouping),date_basis:'reopened',metric:'reopened'}),help:'Grouped by reopening date. Each complaint counts once per period.'},
    ];
    for (const spec of specifications) {
      const slide = document.querySelector(`[data-complaint-chart="${spec.key}"]`);
      if (!slide) continue;
      const canvas = slide.querySelector('canvas'), status = slide.querySelector('.chart-state');
      const temporal = spec.type === 'line';
      const presentation = window.MiniAppReportControls.chartPresentation({ id: spec.key, temporal,
        composition: spec.key === 'target', count: spec.rows.length });
      const types = spec.key === 'category' && spec.rows.length <= 8 ? ['bar', 'doughnut', 'pie'] : presentation.allowedTypes;
      const requested = chosenTypes[spec.key] || (spec.key === 'category' ? categoryType : presentation.defaultType);
      spec.type = types.includes(requested) ? requested : presentation.defaultType;
      const pie = ['pie', 'doughnut'].includes(spec.type);
      spec.horizontal = !pie && (spec.horizontal || spec.key === 'category');
      const head = slide.querySelector('.report-chart-head');
      let menu = head.querySelector('.miniapp-chart-options');
      if (!menu) {
        menu = document.createElement('details'); menu.className = 'miniapp-chart-options';
        const toggle = document.createElement('summary'); toggle.innerHTML = window.MiniAppReportControls.chartOptionsIcon; toggle.setAttribute('aria-label', 'Chart options');
        menu.appendChild(toggle); head.appendChild(menu);
        head.querySelector('.chart-toggle')?.remove();
        const grouping = head.querySelector('.chart-granularity'); if (grouping) menu.appendChild(grouping);
      }
      menu.querySelector('.miniapp-chart-types')?.remove();
      const typeGroup = document.createElement('div'); typeGroup.className = 'miniapp-chart-types';
      types.forEach(type => {
        const choice = document.createElement('button'); choice.type = 'button';
        const label = type[0].toUpperCase() + type.slice(1) + ' chart';
        choice.innerHTML = window.MiniAppReportControls.chartTypeIcon(type);
        choice.setAttribute('aria-label', label); choice.title = label;
        choice.setAttribute('aria-pressed', String(type === spec.type));
        choice.addEventListener('click', () => { chosenTypes[spec.key] = type; menu.open = false; render(summary, options); });
        typeGroup.appendChild(choice);
      });
      menu.appendChild(typeGroup);
      window.MiniAppReportControls.prepareChartMenu(menu);
      window.MiniAppReportControls.setChartHelp(slide.querySelector('.chart-context'),
        `${spec.help || (spec.key === 'age' ? 'Current age of open Complaint(s), grouped by reporting date.' : 'Closed Complaint(s) compared with their recorded resolution target.')} Select a point or an option below to filter the table.`, spec.note || '');
      canvas.setAttribute('role','img'); canvas.setAttribute('aria-label',slide.querySelector('h3').textContent);
      slide.querySelector('.chart-drill-controls')?.remove();
      const hasData = spec.rows.some(row => spec.hours ? row.hours != null : (row.count || row.closed || row.open));
      canvas.hidden = !hasData; status.hidden = hasData;
      status.textContent = spec.hours ? 'Timing unavailable for this period.' : 'No matching complaints.';
      if (!hasData) continue;
      const rows = spec.horizontal ? spec.rows.slice(0,10) : spec.rows;
      const timeChart = temporal;
      const datasets = spec.datasets || [{label:spec.hours?'Hours':'Complaint(s)',data:rows.map(row=>spec.hours?row.hours:row.count),
        backgroundColor:spec.colors || rows.map((_row,i)=>`hsl(${(i*137.508)%360} 60% 42%)`),borderColor:spec.type==='line'?blue:(spec.colors || rows.map((_row,i)=>`hsl(${(i*137.508)%360} 60% 42%)`)),borderWidth:spec.type==='line'?2:0,pointBackgroundColor:blue,pointRadius:2,tension:.2}];
      datasets.forEach(dataset => {
        dataset.borderWidth = spec.type === 'line' ? 2 : 0;
        if (!dataset.backgroundColor) dataset.backgroundColor = dataset.borderColor;
        if (!dataset.pointBackgroundColor) dataset.pointBackgroundColor = dataset.borderColor;
      });
      const choices = document.createElement('div'); choices.className='chart-drill-controls';
      const select = document.createElement('select'); select.setAttribute('aria-label',`Select ${slide.querySelector('h3').textContent} cases`);
      const placeholder=document.createElement('option'); placeholder.textContent='Choose cases…'; placeholder.value=''; select.appendChild(placeholder);
      spec.rows.forEach((row,index)=>{
        const option=document.createElement('option'); option.value=String(index);
        option.textContent=`${timeChart ? formatPeriod(row.label,grouping) : row.label}${row.hours != null ? ` · ${readableHours(row.hours)} · ${row.count} Complaint(s)` : ''}`;
        option.title = option.textContent;
        select.appendChild(option);
      });
      const applySelection = () => {
        if (select.value === '') return;
        const series = choices.querySelector('[aria-label="Activity type"]');
        onSelect(spec.select(spec.rows[Number(select.value)],Number(series?.value || 0)),`${series?.selectedOptions[0].textContent || slide.querySelector('h3').textContent} · ${select.selectedOptions[0].textContent}`);
      };
      select.addEventListener('change', applySelection);
      choices.append(select); slide.appendChild(choices);
      // Activity has two populations. Provide a keyboard-accessible selector.
      if(spec.key==='activity') {
        const series=document.createElement('select'); series.setAttribute('aria-label','Activity type');
        spec.datasets.forEach((dataset,index)=>{const option=document.createElement('option'); option.value=String(index);option.textContent=dataset.label;series.appendChild(option);});
        series.addEventListener('change', applySelection);
        choices.prepend(series);
      }
      const chartOptions = window.MiniAppReportControls.applyChartMeasurement({responsive:true,maintainAspectRatio:false,animation:false,indexAxis:spec.horizontal?'y':'x',
        onClick:(event,elements,chart)=>{
          const hit = chart.getElementsAtEventForMode(event, 'nearest', {intersect:true}, false)[0] || elements[0];
          if (!hit) return;
          select.value = String(hit.index);
          const series = choices.querySelector('[aria-label="Activity type"]');
          if (series) series.value = String(hit.datasetIndex);
          applySelection();
        },
        plugins:{legend:{display:!!spec.datasets || pie,position:'bottom',labels:{color:text,boxWidth:10}},
          tooltip:{callbacks:{title:items=>items.length?(timeChart?formatPeriod(rows[items[0].dataIndex].label,grouping):rows[items[0].dataIndex].label):'',afterLabel:context=>spec.hours?`${rows[context.dataIndex].count} Complaint(s)`:''}}},
        scales:pie?{}:{x:{beginAtZero:true,ticks:{color:text,maxRotation:0,autoSkip:true,maxTicksLimit:innerWidth<480?4:8},grid:{color:grid}},y:{beginAtZero:true,ticks:{color:text,precision:spec.hours?undefined:0},grid:{color:grid}}},
      }, {unit:spec.hours?'hours':'complaints', label:spec.hours?'Hours':'Complaint(s)', horizontal:spec.horizontal, color:text});
      chartOptions.plugins.tooltip.callbacks.label = context => spec.hours ? readableHours(context.raw)
        : `${context.dataset.label}: ${new Intl.NumberFormat('en-KE').format(context.raw)} Complaint(s)`;
      charts.push(new window.Chart(canvas,{
        type:spec.type || 'bar',data:{labels:rows.map(row=>{
          if(timeChart)return formatPeriod(row.label,grouping);
          const limit=innerWidth<480?20:32;
          return row.label.length>limit?row.label.slice(0,limit-1)+'…':row.label;
        }),datasets},
        options:chartOptions,
      }));
    }
  }
  window.ComplaintReportCharts = {render,state,hours,readableHours,resize:()=>charts.forEach(chart=>chart.resize())};
})();
