const $ = (id) => document.getElementById(id);
let chart;
let quotePrice = null;
let refreshTimer;

function money(value) { return new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'}).format(value); }
function dateLabel(value) { return new Date(`${value}T12:00:00`).toLocaleDateString('en-US',{month:'short',day:'numeric'}); }
function showToast(message, error=false) {
  const el=$('toast'); el.textContent=message; el.classList.toggle('error',error); el.classList.add('show');
  clearTimeout(showToast.timer); showToast.timer=setTimeout(()=>el.classList.remove('show'),3400);
}
async function api(url, options={}) {
  const response=await fetch(url,options); const data=await response.json();
  if(!response.ok) throw new Error(data.error||'Something went wrong.'); return data;
}
function renderChart(history) {
  const ctx=$('equityChart').getContext('2d'); const values=history.map(p=>p.equity);
  const up=(values.at(-1)||0)>=(values[0]||0); const color=up?'#a8ed6c':'#ff8279';
  const gradient=ctx.createLinearGradient(0,0,0,220); gradient.addColorStop(0,up?'rgba(168,237,108,.18)':'rgba(255,130,121,.16)'); gradient.addColorStop(1,'rgba(168,237,108,0)');
  if(chart) chart.destroy();
  chart=new Chart(ctx,{type:'line',data:{labels:history.map(p=>p.date),datasets:[{data:values,borderColor:color,borderWidth:2,fill:true,backgroundColor:gradient,tension:.33,pointRadius:0,pointHoverRadius:4,pointHoverBackgroundColor:color,pointHoverBorderColor:'#171e1b'}]},options:{responsive:true,maintainAspectRatio:false,interaction:{intersect:false,mode:'index'},plugins:{legend:{display:false},tooltip:{backgroundColor:'#222d27',borderColor:'#394a3e',borderWidth:1,titleColor:'#9aa79f',bodyColor:'#f1f4f2',padding:10,displayColors:false,callbacks:{title:items=>dateLabel(items[0].label),label:item=>money(item.raw)}}},scales:{x:{grid:{display:false},border:{display:false},ticks:{color:'#748078',font:{family:'DM Mono',size:9},maxTicksLimit:6,maxRotation:0,callback:(v,i)=>dateLabel(history[i].date)}},y:{grid:{color:'rgba(135,147,140,.11)'},border:{display:false,dash:[3,4]},ticks:{color:'#748078',font:{family:'DM Mono',size:9},maxTicksLimit:4,callback:v=>'$'+Number(v).toLocaleString('en-US',{notation:'compact',maximumFractionDigits:1})}}}}});
}
function render(data) {
  $('equity').textContent=money(data.equity); $('cash').textContent=money(data.cash);
  const first=data.history[0]?.equity||data.equity, diff=data.equity-first, pct=first?diff/first*100:0;
  $('equity-change').textContent=`${diff>=0?'+':'−'}${money(Math.abs(diff))} (${diff>=0?'+':'−'}${Math.abs(pct).toFixed(2)}%)`;
  $('equity-change').className=diff>=0?'positive':'negative'; $('chartRange').textContent=`${dateLabel(data.history[0].date)} — ${dateLabel(data.history.at(-1).date)}`;
  renderChart(data.history);
  $('holdings').innerHTML=data.holdings.length?data.holdings.map(h=>`<div class="holding-row"><div><span class="holding-name">${h.symbol}</span><span class="holding-meta">${h.quantity.toLocaleString('en-US',{maximumFractionDigits:4})} shares · ${money(h.price)}</span></div><div><div class="holding-value">${money(h.value)}</div><div class="holding-change">market value</div></div></div>`).join(''):'<div class="empty-state">Your investments will show up here.</div>';
  $('holdingCount').textContent=data.holdings.length;
  $('activity').innerHTML=data.trades.length?data.trades.map(t=>`<div class="activity-row"><div class="activity-symbol">${t.symbol.slice(0,3)}</div><div><div class="activity-title"><strong>${t.side.toUpperCase()}</strong> ${Number(t.quantity).toLocaleString('en-US',{maximumFractionDigits:4})} ${t.symbol} <span style="color:#87938c">@ ${money(t.price)}</span></div><div class="activity-date">${dateLabel(t.date)}</div></div><div class="activity-amount ${t.side}">${t.side==='buy'?'−':'+'}${money(t.quantity*t.price)}</div></div>`).join(''):'<div class="empty-state">Your trades will show up here.</div>';
  $('chartLoading').classList.add('hidden');
}
async function refresh() { try { render(await api('/api/dashboard')); } catch(e) { $('chartLoading').textContent=e.message; showToast(e.message,true); } }
async function lookup() {
  const symbol=$('ticker').value.trim().toUpperCase(); if(!symbol) return;
  $('quoteResult').textContent='Looking up market price…';
  try {const q=await api(`/api/quote/${encodeURIComponent(symbol)}`);quotePrice=q.price;$('ticker').value=q.symbol;$('quoteResult').innerHTML=`${q.name} <strong>${money(q.price)}</strong> <span class="${q.change>=0?'positive':'negative'}">${q.change>=0?'+':''}${q.change_percent.toFixed(2)}%</span>`;updateEstimate();}
  catch(e){quotePrice=null;$('quoteResult').textContent=e.message;updateEstimate();}
}
function updateEstimate(){const qty=Number($('quantity').value);$('orderEstimate').textContent=quotePrice&&qty?money(quotePrice*qty):'Enter a stock and shares';}
$('lookupBtn').addEventListener('click',lookup);$('ticker').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();lookup();}});$('ticker').addEventListener('change',lookup);$('quantity').addEventListener('input',updateEstimate);
$('tradeDate').max=new Date().toISOString().slice(0,10);$('tradeDate').min=new Date(Date.now()-30*86400000).toISOString().slice(0,10);$('tradeDate').value=$('tradeDate').max;
$('tradeForm').addEventListener('submit',async e=>{e.preventDefault();const side=e.submitter.value;const payload={symbol:$('ticker').value,quantity:$('quantity').value,date:$('tradeDate').value,side};try{const result=await api('/api/trades',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});showToast(result.message);$('quantity').value='';updateEstimate();await refresh();}catch(error){showToast(error.message,true);}});
refresh();refreshTimer=setInterval(refresh,60000);
