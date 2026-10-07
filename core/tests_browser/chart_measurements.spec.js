'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('playwright/test');
const asset = name => path.resolve(__dirname, '../static/miniapp', name);
const source = fs.readFileSync(asset('tat_tracker.js'), 'utf8');
const renderer = source.slice(source.indexOf('  function renderTatReportCharts('), source.indexOf('  async function ', source.indexOf('  function renderTatReportCharts(')));

test('TAT duration, percentage and count graphs label the numeric axis in every orientation', async ({page}) => {
  const keys = {trend:'tatTrend',case_progression:'tatProgression',backlog_age:'tatBacklog',sla_compliance:'tatSla',tat_percentiles:'tatPercentiles',stage_target:'tatTarget',explorer:'tatExplorer'};
  await page.setContent(Object.values(keys).map(prefix=>`<article id="${prefix}Panel"><h3 id="${prefix}Title"></h3><p id="${prefix}Basis"></p><canvas id="${prefix}Chart"></canvas><p id="${prefix}Empty"></p></article>`).join(''));
  await page.addScriptTag({path:asset('components.js')});
  await page.addScriptTag({content:`
    const $ = id => document.getElementById(id);
    const state = {report:{charts:{},insightPayloads:{},view:'performance'}};
    const showTatChartHelp = () => {}, renderExplorerDetails = () => {}, syncTatChartDisplay = () => {}, syncTatReportChartTypeToggles = () => {};
    const formatReportDate = value => value, compactTatReportLabel = value => value;
    const chartColors = () => ['#2481cc'];
    let requestedType = 'bar';
    const tatReportChartType = () => requestedType;
    window.Chart = class {constructor(canvas, config) {this.config=config;this.canvas=canvas;}destroy(){}};
    ${renderer}
    window.renderUnits = (key, payload, type) => {requestedType=type;renderTatReportCharts({response_mode:'focused_v1',charts:{[key]:payload}});return state.report.charts[key].config;};
  `});
  for (const type of ['bar','line','doughnut']) {
    for (const [key, unit, metric] of [['trend','actions'],['case_progression','minutes'],['tat_percentiles','minutes'],['sla_compliance','percent'],['stage_target','percent'],['explorer','cases_per_assignee','load_per_assignee']]) {
      const output = await page.evaluate(({key,unit,metric,type}) => {
        const {options} = window.renderUnits(key,{title:'Synthetic metric',unit,metric,labels:['Training stage'],sample_count:1,series:[{key:'sample',label:'Sample',values:[90]}]},type);
        const axis=options.scales?.[options.indexAxis==='y'?'x':'y'];
        return {label:axis?.title.text || options.plugins.subtitle.text,
          tooltip:options.plugins.tooltip.callbacks.label({dataset:{label:'Sample'},raw:90}),
          categoryFormatter:options.scales?.[options.indexAxis==='y'?'y':'x'].ticks.callback};
      }, {key,unit,metric,type});
      expect(output.label).toBe({actions:'Actions',minutes:'Minutes',percent:'Percentage (%)',cases_per_assignee:'Cases per assignee'}[unit]);
      expect(output.tooltip).toContain(unit==='percent'?'90%':unit==='cases_per_assignee'?'90 cases per assignee':`90 ${unit}`);
      expect(output.categoryFormatter).toBeUndefined();
    }
  }
});
