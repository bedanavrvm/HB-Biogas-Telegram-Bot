/* Read-only report charts. All drill-downs use the same server filters as XLSX. */
(function () {
  'use strict';
  let charts = [];
  const hours = value => value == null ? '—' : value < 24 ? `${Number(value.toFixed(1))}h` : `${Number((value / 24).toFixed(1))}d`;
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
  function render(summary, {categoryType = 'bar', onSelect, formatPeriod}) {
    charts.forEach(chart => chart.destroy()); charts = [];
    if (!window.Chart) { state('Charts unavailable. Use the report table below.'); return; }
    const root = getComputedStyle(document.documentElement);
    const color = (token, fallback) => root.getPropertyValue(token).trim() || fallback;
    const text = color('--muted', '#667085'), grid = color('--line', '#e2e8f0');
    const green = '#168354', red = '#d14343', blue = '#2481cc';
    const activity = summary.activity || [], timing = summary.timing || {};
    const grouping = summary.time_granularity || 'month';
    const specifications = [
      {key:'activity', rows:activity, type:'line', datasets:[
        {label:'Received',data:activity.map(row=>row.received),borderColor:blue},
        {label:'Resolved',data:activity.map(row=>row.resolved),borderColor:green}],
        select:(row, dataset)=>({...period(row.label, grouping),date_basis:dataset ? 'closures':'reported',metric:dataset ? 'closures':'received'}),
        note:'Includes repeat closures.'},
      {key:'age',rows:summary.open_age || [],horizontal:true,
        select:row=>({date_basis:'reported',metric:'open_age',metric_value:row.key}),note:timing.age_unavailable ? `${timing.age_unavailable} timing unavailable` : ''},
      {key:'resolution',rows:summary.resolution_trend || [],type:'line',hours:true,
        select:row=>({...period(row.label,grouping),date_basis:'resolved',metric:'resolution'}),note:`${timing.resolution_count || 0} closed${timing.resolution_excluded ? ` · ${timing.resolution_excluded} timing unavailable` : ''}`},
      {key:'target',rows:[{label:'On time',count:timing.on_time || 0},{label:'Late',count:timing.late || 0}],colors:[green,red],
        select:row=>({date_basis:'resolved',metric:row.label==='On time'?'on_time':'late'}),note:timing.target_unavailable ? `${timing.target_unavailable} target unavailable` : ''},
      {key:'category',rows:summary.by_category || [],horizontal:categoryType!=='pie',type:categoryType,
        select:row=>({category:row.label}),note:''},
      {key:'category_time',rows:summary.resolution_by_category || [],hours:true,horizontal:true,
        select:row=>({category:row.label,date_basis:'resolved',metric:'resolution'}),note:'Median · closed complaints'},
      {key:'response',rows:summary.response_trend || [],hours:true,type:'line',
        select:row=>({...period(row.label,grouping),date_basis:'response',metric:'hb_response'}),note:`${timing.response_count || 0} responses · ${timing.response_unavailable || 0} reported cases without recorded HB response`},
      {key:'reopened',rows:summary.reopenings || [],type:'line',
        select:row=>({...period(row.label,grouping),date_basis:'reopened',metric:'reopened'}),note:'Each complaint counts once per period.'},
    ];
    for (const spec of specifications) {
      const slide = document.querySelector(`[data-complaint-chart="${spec.key}"]`);
      if (!slide) continue;
      const canvas = slide.querySelector('canvas'), status = slide.querySelector('.chart-state');
      canvas.setAttribute('role','img'); canvas.setAttribute('aria-label',slide.querySelector('h3').textContent);
      slide.querySelector('.chart-drill-controls')?.remove();
      const hasData = spec.rows.some(row => spec.hours ? row.hours != null : (row.count || row.received || row.resolved));
      canvas.hidden = !hasData; status.hidden = hasData;
      status.textContent = spec.hours ? 'Timing unavailable for this period.' : 'No matching complaints.';
      slide.querySelector('.chart-context').textContent = spec.note;
      if (!hasData) continue;
      const rows = spec.horizontal ? spec.rows.slice(0,10) : spec.rows;
      const timeChart = spec.type === 'line';
      const datasets = spec.datasets || [{label:spec.hours?'Hours':'Complaints',data:rows.map(row=>spec.hours?row.hours:row.count),
        backgroundColor:spec.colors || rows.map((_row,i)=>`hsl(${(i*137.508)%360} 60% 42%)`),borderColor:blue,borderWidth:spec.type==='line'?2:0,pointBackgroundColor:blue,pointRadius:2,tension:.2}];
      const choices = document.createElement('div'); choices.className='chart-drill-controls';
      const select = document.createElement('select'); select.setAttribute('aria-label',`Select ${slide.querySelector('h3').textContent} cases`);
      const placeholder=document.createElement('option'); placeholder.textContent='Choose cases…'; placeholder.value=''; select.appendChild(placeholder);
      spec.rows.forEach((row,index)=>{
        const option=document.createElement('option'); option.value=String(index);
        option.textContent=`${timeChart ? formatPeriod(row.label,grouping) : row.label}${row.hours != null ? ` · ${hours(row.hours)} (${row.count})` : ''}`;
        select.appendChild(option);
      });
      const button=document.createElement('button'); button.type='button'; button.textContent='Show cases'; button.disabled=true;
      select.addEventListener('change',()=>{button.disabled=select.value==='';});
      button.addEventListener('click',()=>{
        const series = choices.querySelector('[aria-label="Activity type"]');
        onSelect(spec.select(spec.rows[Number(select.value)],Number(series?.value || 0)),`${series?.selectedOptions[0].textContent || slide.querySelector('h3').textContent} · ${select.selectedOptions[0].textContent}`);
      });
      choices.append(select,button); slide.appendChild(choices);
      // Activity has two populations. Provide a keyboard-accessible selector.
      if(spec.key==='activity') {
        const series=document.createElement('select'); series.setAttribute('aria-label','Activity type');
        ['Received','Resolved'].forEach((label,index)=>{const option=document.createElement('option'); option.value=String(index);option.textContent=label;series.appendChild(option);});
        choices.prepend(series);
      }
      charts.push(new window.Chart(canvas,{
        type:spec.type || 'bar',data:{labels:rows.map(row=>{
          if(timeChart)return formatPeriod(row.label,grouping);
          const limit=innerWidth<480?20:32;
          return row.label.length>limit?row.label.slice(0,limit-1)+'…':row.label;
        }),datasets},
        options:{responsive:true,maintainAspectRatio:false,animation:false,indexAxis:spec.horizontal?'y':'x',
          onClick:(_event,elements)=>{if(elements.length){const item=elements[0];onSelect(spec.select(rows[item.index],item.datasetIndex),`${slide.querySelector('h3').textContent} · ${rows[item.index].label}`);}},
          plugins:{legend:{display:!!spec.datasets || spec.type==='pie',position:'bottom',labels:{color:text,boxWidth:10}},
            tooltip:{callbacks:{title:items=>items.length?rows[items[0].dataIndex].label:'',label:context=>`${context.dataset.label || context.label}: ${spec.hours?hours(context.raw):context.raw}${spec.hours?` · ${rows[context.dataIndex].count} cases`:''}`}}},
          scales:spec.type==='pie'?{}:{x:{beginAtZero:true,ticks:{color:text,maxRotation:0,autoSkip:true,maxTicksLimit:innerWidth<480?4:8},grid:{color:grid}},y:{beginAtZero:true,ticks:{color:text,precision:0},grid:{color:grid}}},
        },
      }));
    }
  }
  window.ComplaintReportCharts = {render,state,hours,resize:()=>charts.forEach(chart=>chart.resize())};
})();
