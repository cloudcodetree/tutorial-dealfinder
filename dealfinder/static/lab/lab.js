const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const money = n => "$" + Number(n).toFixed(2);
// Offer links come from third-party sources. Only http(s) URLs become links, so a
// javascript: URL can never run in a page that holds a sign-in token.
function safeHref(u){
  try{ const p = new URL(u, location.href); return /^https?:$/.test(p.protocol) ? esc(p.href) : '#'; }
  catch(e){ return '#'; }
}
// Behind the deals Worker every backend route sits under /api. Served directly on
// :8000 it is the bare path. The server writes the base into the page.
const API = document.querySelector('meta[name="api-base"]').content;
const LAB = '/lab/';   // the lab's own files, at the same path in both places
// Off in production until a store key exists. The modes that need live store data say so.
const LIVE = document.querySelector('meta[name="live-data"]').content === 'on';
const LIVE_OFF = 'Live store data is off until DealFinder has a Best Buy API key.';
const NEEDS_LIVE = {deals:'#results', stream:'#streamResults', watchlist:'#wlBody'};
let state = { mode:"deals", q:"noise cancelling headphones" };
let rankedThr = 0.70;   // suspicious-residual threshold; the backend sends the real value
// Real sign-in: Supabase Auth in the browser. The backend verifies the access
// token against the project's JWKS; no header can claim an identity.
let sb = null;          // the Supabase client, once /config.json says sign-in is configured
let session = null;     // the current Supabase session (null when signed out)
let lastResults = [];   // the current deals, so a card's "watch" button can find its item
const authHeaders = () => session ? {Authorization: 'Bearer ' + session.access_token} : {};
const signedIn = () => !!session;
function renderAcct(){
  const b = document.getElementById('acct'); if(!b) return;
  if(!sb){ b.textContent = 'Sign-in not configured'; b.disabled = true; return; }
  b.disabled = false;
  b.textContent = session ? ('Sign out · ' + (session.user.email || 'account')) : 'Sign in';
}
function onAuthChange(){
  renderAcct(); refreshWlCount();
  loaded.watchlist = false;
  if(state.mode === 'watchlist') loadWatchlist();
}
function openSignin(){
  if(!sb) return;
  document.getElementById('signin').hidden = false;
  document.getElementById('signinAddr').focus();
}
async function toggleAcct(){
  if(!sb) return;
  if(session){ await sb.auth.signOut(); return; }
  const panel = document.getElementById('signin');
  if(panel.hidden) openSignin(); else panel.hidden = true;
}
const returnTo = () => location.origin + location.pathname;
async function initAuth(){
  let cfg = {};
  try{ cfg = await (await fetch(API + '/config.json')).json(); }catch(e){}
  if(cfg.supabaseUrl && cfg.supabasePublishableKey && window.supabase){
    sb = window.supabase.createClient(cfg.supabaseUrl, cfg.supabasePublishableKey);
    session = (await sb.auth.getSession()).data.session;
    sb.auth.onAuthStateChange((_event, s) => { session = s; onAuthChange(); });
  }
  document.getElementById('signinEmail').addEventListener('submit', async ev => {
    ev.preventDefault();
    const msg = document.getElementById('signinMsg');
    const {error} = await sb.auth.signInWithOtp({email: document.getElementById('signinAddr').value.trim(),
                                                  options: {emailRedirectTo: returnTo()}});
    msg.textContent = error ? ('Could not send the link: ' + error.message) : 'Check your email for the sign-in link.';
  });
  document.querySelectorAll('#signin [data-provider]').forEach(b => b.addEventListener('click', () =>
    sb.auth.signInWithOAuth({provider: b.dataset.provider, options: {redirectTo: returnTo()}})));
  onAuthChange();
}
async function refreshWlCount(){
  const el = document.getElementById('wlCount');
  if(!signedIn()){ if(el) el.textContent=''; return; }
  try{ const d = await (await fetch(API + '/watchlist', {headers: authHeaders()})).json(); if(el) el.textContent = d.count || ''; }catch(e){}
}
const loaded = {};
const BESPOKE = ['snapshot','deals','stream','pipeline','evals','models','tracking','semantic','ask','watchlist'];
const GENERIC = {
  context:{ep:'/context',q:true,kicker:'Part 16 · context engineering',title:'The window as a token budget',sub:'What fits and what gets evicted — live from /context.'},
  review:{ep:'/review',q:true,kicker:'Part 17 · writer / reviewer',title:'Draft, critique, revise',sub:'A second-opinion agent gates the answer — live from /review.'},
  dataset:{ep:'/dataset',q:false,kicker:'Part 19 · dataset engineering',title:'The labeled training set',sub:'Class balance, weights, leakage-safe split — live from /dataset.'},
  mlops:{ep:'/mlops',q:false,kicker:'Part 24 · the MLOps loop',title:'Drift → retrain → gate → promote',sub:'The full closed loop — live from /mlops.'},
  safety:{ep:'/safety',q:false,kicker:'Part 25 · safety & governance',title:'The guardrail stack',sub:'Injection, PII, spec, audit, tool-trust — live from /safety.'},
  inference:{ep:'/inference',q:false,kicker:'Part 27 · inference optimization',title:'Cache, batch, speed',sub:'The four cost/latency levers — live from /inference.'},
  ops:{ep:'/ops',q:false,kicker:'Part 30 · cost & drift',title:'FinOps + drift',sub:'Spend, budget, drift — live from /ops.'},
  auth:{ep:'/auth',q:false,kicker:'Part 32 · auth & accounts',title:'Every JWT verdict',sub:'The real verifier over 8 scenarios — live from /auth.'},
  suggestions:{ep:'/suggestions',q:true,kicker:'Part 33 · suggestions worker',title:'The saved-search diff loop',sub:'What changed since last run — live from /suggestions.'},
  billing:{ep:'/billing',q:false,kicker:'Part 34 · payments & SaaS',title:'Plans, quota, webhooks',sub:'Stripe mechanics — live from /billing.'},
  compliance:{ep:'/compliance',q:false,kicker:'Part 35 · compliance at scale',title:'Rate limit, GDPR, abuse',sub:'The at-scale guardrails — live from /compliance.'},
};

/* ── mode switching ──────────────────────────────────────────────────── */
document.querySelectorAll('.rail-item[data-mode]').forEach(b=>{
  b.addEventListener('click',()=>setMode(b.dataset.mode));
});
function setMode(m){
  state.mode = m;
  // The ready flag marks a finished render (Plan 6's screenshots wait on it). A switch clears it.
  document.querySelectorAll('.rail-item[data-mode]').forEach(b=>{ b.classList.toggle('active',b.dataset.mode===m); delete b.dataset.ready; });
  const view = BESPOKE.includes(m) ? m : 'generic';
  ['snapshot','deals','stream','pipeline','evals','models','tracking','semantic','ask','watchlist','generic'].forEach(v=>$('#view-'+v).classList.toggle('hidden',v!==view));
  $('#trapRow').hidden = m !== 'review';
  if(m !== 'stream' && stream){ stream.close(); stream = null; loaded.stream = false; }
  const load = (!LIVE && NEEDS_LIVE[m]) ? (()=>liveOff(m)) :
    ({snapshot:loadSnapshot,deals:loadDeals,stream:loadStream,pipeline:loadPipeline,evals:loadEvals,models:loadModels,tracking:loadTracking,semantic:loadSemantic,ask:loadAsk,watchlist:loadWatchlist}[m] || (()=>loadGeneric(m)));
  Promise.resolve(load()).finally(()=>{
    const b = document.querySelector(`.rail-item[data-mode="${m}"]`);
    if(b && state.mode === m) b.dataset.ready = 'true';
  });
}
function liveOff(m){
  $(NEEDS_LIVE[m]).innerHTML = `<div class="loading">${LIVE_OFF} <a class="link-sm" href="/">Check a deal instead →</a></div>`;
  $('#meta').innerHTML = '';
}

const mlHint = ep => `<div class="statcard"><div class="k" style="color:var(--color-neutral-500);">unavailable</div><div class="muted" style="font-size:13px;">This mode needs the full-ML profile. Start it with<br><span class="mono" style="font-size:11px;">docker compose -f docker-compose.yml -f docker-compose.full.yml up</span><br>then reopen this mode.</div></div>`;

async function loadModels(){
  if(loaded.models) return; loaded.models=true;
  try{
    const r = await fetch(API + '/models'); if(!r.ok) throw new Error('needs full-ML profile');
    const d = await r.json(); const f=d.full, t=d.torch_mlp;
    const stat=(k,num,meta,accent)=>`<div class="statcard"><div class="k">${k}</div><div class="num"${accent?' style="color:var(--color-accent-400);"':''}>${num}</div><div class="muted" style="font-size:11px;">${meta}</div></div>`;
    $('#modelCards').innerHTML =
      stat('linear baseline', '$'+f.linear_mae, 'MAE · from-scratch model') +
      stat('GBDT + embeddings', '$'+f.gbdt_mae, `MAE · R² ${f.gbdt_r2}`, true) +
      stat('improvement', '+'+f.improvement_pct+'%', 'GBDT vs linear MAE') +
      stat('Torch MLP', '$'+t.mae, `real=${t.real} · loss ${t.final_loss}`);
    $('#modelNote').textContent = `Boosting with PCA-compressed title embeddings cuts MAE ${f.improvement_pct}% below the linear baseline; the PyTorch MLP is a real trained model (final loss ${t.final_loss}).`;
  }catch(e){ $('#modelCards').innerHTML=mlHint('/models'); $('#modelNote').textContent=''; loaded.models=false; }
}

async function loadTracking(){
  if(loaded.tracking) return; loaded.tracking=true;
  try{
    const r = await fetch(API + '/tracking'); if(!r.ok) throw new Error('needs full-ML profile');
    const d = await r.json();
    if(!d.mlflow_available){ $('#trackCards').innerHTML=mlHint('/tracking'); $('#trackTable').innerHTML=''; loaded.tracking=false; return; }
    $('#trackCards').innerHTML =
      `<div class="statcard"><div class="k">registered winner</div><div class="num" style="color:var(--color-accent-400);">${esc(d.winner)}</div><div class="muted" style="font-size:11px;">${esc(d.registered_model||'model registry')}</div></div>`+
      `<div class="statcard"><div class="k">winner MAE</div><div class="num">$${d.winner_mae}</div><div class="muted" style="font-size:11px;">best selectable run</div></div>`+
      `<div class="statcard"><div class="k">runs logged</div><div class="num">${d.runs.length}</div><div class="muted" style="font-size:11px;">experiment: ${esc(d.experiment||'—')}</div></div>`;
    $('#trackTable').innerHTML = `<h5 style="margin:0 0 var(--space-3);">Run ledger</h5>`+
      d.runs.map(run=>`<div class="toprow"><span class="nm">${esc(run.name)}</span><span class="mono" style="font-size:12px;">MAE $${run.mae}</span><span class="mono" style="font-size:12px;color:var(--color-neutral-500);">R² ${run.r2}</span>${run.selectable?'<span class="tag tag-deal">selectable</span>':'<span class="tag tag-fair">baseline</span>'}</div>`).join('');
  }catch(e){ $('#trackCards').innerHTML=mlHint('/tracking'); $('#trackTable').innerHTML=''; loaded.tracking=false; }
}

/* ── DEALS (1b) ──────────────────────────────────────────────────────── */
$('#go').addEventListener('click',()=>{ state.q=$('#q').value.trim()||state.q; Object.keys(loaded).forEach(k=>delete loaded[k]); setMode(state.mode); });
$('#q').addEventListener('keydown',e=>{ if(e.key==='Enter'){$('#go').click();} });

async function loadDeals(){
  if(loaded.deals) return; loaded.deals=true;
  $('#results').innerHTML='<div class="loading">Loading real offers…</div>';
  try{
    const d = await (await fetch(API + `/ranked?q=${encodeURIComponent(state.q)}&k=8`)).json();
    rankedThr = d.residual_threshold ?? rankedThr;
    $('#dealsCount').textContent = d.count;
    $('#meta').innerHTML = `<span class="mono">${d.count} offers · ${d.median_price==null ? 'ratings off' : 'median '+money(d.median_price)} · two-signal ranked</span>`;
    lastResults = d.results;
    const held = d.results.filter(r=>r.verdict==='suspicious').length;
    $('#results').innerHTML = d.results.map(cardHTML).join('') +
      `<button class="btn btn-secondary btn-block" style="min-height:44px;">Ranked by value · ${held} held back as too-good-to-be-true</button>`;
    wireWhy();
  }catch(e){ $('#results').innerHTML=`<div class="loading">Could not reach /ranked — ${esc(e.message)}</div>`; }
}

function tagFor(v){
  if(v==='deal') return '<span class="tag tag-deal">DEAL</span>';
  if(v==='suspicious') return '<span class="tag tag-susp">HELD BACK · SUSPICIOUS</span>';
  if(v==='overpriced') return '<span class="tag tag-over">OVERPRICED</span>';
  if(v==='fair') return '<span class="tag tag-fair">FAIR</span>';
  return '<span class="tag tag-fair">VALUE</span>';   // no price model for this category
}
function cardHTML(r,i){
  const pct = r.pct_under_median;
  const under = pct==null ? 'not rated' : pct>=0 ? `▼ ${pct}% under` : `▲ ${Math.abs(pct)}% over`;
  const thumb = r.image_url ? `<img class="thumb" src="${esc(r.image_url)}" alt="" referrerpolicy="no-referrer">` : `<div class="thumb"></div>`;
  const src = `<span class="mono" style="font-size:10px;color:var(--color-neutral-600);">${esc(r.source||'')}</span>`;
  const est = r.basis==='peers';       // fair price estimated from peers, not a trained model
  const noBasis = r.basis==null;       // too few offers to compare → value-only
  const estChip = est ? '<span class="mono" style="font-size:9px;color:var(--color-neutral-600);">· est. from similar offers</span>' : '';
  const sig2 = est ? 'Signal 2 · peer residual' : 'Signal 2 · model residual';
  const thrPct = Math.round(rankedThr*100);
  if(r.verdict==='suspicious'){
    const residPct = Math.max(0,Math.min(100,Math.round((r.residual_frac||0)*100)));
    return `<div class="card held">
      <div class="cardline">
        ${thumb}
        <div class="card-body">
          <div class="card-head">${tagFor(r.verdict)} ${src}${estChip}</div>
          <div class="title dim">${esc(r.title)}</div>
        </div>
        <div class="signal">
          <div class="bar-track" style="background:var(--color-neutral-900);"><div class="bar-fill hatch" style="width:${Math.min(100,Math.abs(pct))}%"></div></div>
          <span class="sig-note">${under} claimed</span>
          <span class="sig-note accent">residual ${r.residual_frac} &gt; ${rankedThr}</span>
        </div>
        <div class="priceblock">
          <div class="price dim">${money(r.price)}</div>
          <button class="linkbtn why-toggle" data-i="${i}">why held? →</button>
        </div>
      </div>
      <div class="why hidden" id="why-${i}">
        <div class="col">
          <div><div class="lab"><span class="muted">Signal 1 · under median</span><span class="mono" style="color:var(--color-accent-400);">${(pct/100).toFixed(2)}</span></div>
            <div class="track6"><div class="bar-fill" style="width:${Math.min(100,Math.abs(pct))}%"></div></div></div>
          <div><div class="lab"><span class="muted">${sig2}</span><span class="mono">${r.residual_frac}</span></div>
            <div class="track6"><div class="bar-fill hatch" style="width:${residPct}%"></div><div class="tick" style="left:${thrPct}%"></div></div>
            <div class="sig-note" style="margin-top:4px;">threshold ${rankedThr} — tripped · ${est?'peers ≈':'fair'} ${money(r.fair)}</div></div>
        </div>
        <p>${esc(r.reason||'')}</p>
      </div>
    </div>`;
  }
  const isDeal = r.verdict==='deal';
  const fairNote = r.fair!=null ? (est?`≈ ${money(r.fair)} (similar offers)`:`fair price ${money(r.fair)}`) : (noBasis?'value only':'');
  return `<div class="card ${i===0&&isDeal?'top':''}">
    ${thumb}
    <div class="card-body">
      <div class="card-head">${tagFor(r.verdict)} ${src}${estChip}</div>
      <div class="title">${esc(r.title)}</div>
      <div class="reason">${esc(r.reason||'')}</div>
    </div>
    <div class="signal">
      <div class="bar-track"><div class="bar-fill" style="width:${Math.max(0,Math.min(100,pct))}%"></div></div>
      <span class="sig-note ${isDeal?'accent':''}">${under}</span>
      <span class="sig-note">${fairNote}</span>
    </div>
    <div class="priceblock">
      <div class="price">${money(r.price)}</div>
      <div style="display:flex;gap:var(--space-3);align-items:center;">
        ${r.url?`<a class="link-sm" href="${safeHref(r.url)}" target="_blank" rel="noopener noreferrer">open offer →</a>`:''}
        <button class="linkbtn watch-btn" data-idx="${i}">＋ watch</button>
      </div>
    </div>
  </div>`;
}
async function addWatch(r, btn){
  if(!r) return;
  if(!signedIn()){ openSignin(); return; }
  try{
    // Only which offer and a target: the server fills in the title and price from its catalog.
    const body = {offer_id:r.id, target_price:r.price};
    const res = await fetch(API + '/watchlist', {method:'POST', headers:{'Content-Type':'application/json', ...authHeaders()}, body:JSON.stringify(body)});
    if(res.ok && btn){ btn.textContent='watching ✓'; btn.disabled=true; btn.style.color='var(--color-neutral-500)'; }
    else if(btn){ btn.textContent = res.status === 404 ? 'search again to watch' : 'could not watch'; }
    refreshWlCount();
  }catch(e){}
}
function wireWhy(){
  document.querySelectorAll('.watch-btn').forEach(b=>b.onclick=()=>addWatch(lastResults[b.dataset.idx], b));
  document.querySelectorAll('.why-toggle').forEach(b=>b.addEventListener('click',()=>{
    const el=$('#why-'+b.dataset.i); const open=!el.classList.contains('hidden');
    el.classList.toggle('hidden'); b.textContent = open?'why held? →':'hide ↑';
  }));
}

/* ── SNAPSHOT (Part 1 · the data layer) ──────────────────────────────── */
async function loadSnapshot(){
  if(loaded.snapshot) return; loaded.snapshot=true;
  const body = $('#snapBody');
  try{
    const d = await (await fetch(API + `/snapshot?q=${encodeURIComponent(state.q)}&limit=50`)).json();
    $('#snapMeta').innerHTML = `<span class="mono">${d.count} of ${d.total} rows shown · ${d.retailer_polluted} of ${d.total} carry a retailer in their brand field</span>`;
    if(!d.rows.length){ body.innerHTML = `<div class="loading">No snapshot title contains “${esc(state.q)}”.</div>`; return; }
    const differs = r => (r.raw_brand||'').toLowerCase() !== (r.brand||'').toLowerCase();
    body.innerHTML = `<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:12.5px;">
      <tr>${['title','raw brand','brand from title','price','source'].map(c=>`<th style="text-align:left;padding:var(--space-2);color:var(--color-neutral-500);font-weight:500;border-bottom:1px solid var(--color-divider);">${c}</th>`).join('')}</tr>
      ${d.rows.map(r=>`<tr${differs(r)?' data-row-polluted="true"':''}>
        <td style="padding:var(--space-2);">${esc(r.title)}</td>
        <td class="raw-brand mono" style="padding:var(--space-2);${differs(r)?'color:var(--warn);':''}">${esc(r.raw_brand||'—')}</td>
        <td class="mono" style="padding:var(--space-2);">${esc(r.brand||'—')}</td>
        <td class="mono" style="padding:var(--space-2);">${money(r.price)}</td>
        <td class="mono" style="padding:var(--space-2);color:var(--color-neutral-500);">${esc(r.source||'')}</td></tr>`).join('')}
    </table></div>`;
  }catch(e){ body.innerHTML=`<div class="loading">Could not reach /snapshot — ${esc(e.message)}</div>`; loaded.snapshot=false; }
}

/* ── STREAM (Part 18 · server-sent events) ───────────────────────────── */
let stream = null;   // the open EventSource, closed by a new search or a mode switch
function loadStream(){
  if(loaded.stream) return; loaded.stream=true;
  const box = $('#streamResults'); box.innerHTML = '';
  if(stream) stream.close();
  let n = 0; const srcs = [];
  return new Promise(resolve => {
    const es = stream = new EventSource(API + `/search/stream?q=${encodeURIComponent(state.q)}`);
    es.addEventListener('results', e => {
      const d = JSON.parse(e.data);
      if(d.source && !srcs.includes(d.source)) srcs.push(d.source);
      (d.results||[]).forEach(r => { box.insertAdjacentHTML('beforeend', semCard(r)); n++; });
      $('#meta').innerHTML = `<span class="mono">streaming… ${n} offers · sources: ${esc(srcs.join(', '))}</span>`;
    });
    es.addEventListener('source_error', e => {
      const d = JSON.parse(e.data); if(d.source && !srcs.includes(d.source)) srcs.push(d.source + ' ✗');
    });
    es.addEventListener('done', e => {
      const d = JSON.parse(e.data);
      $('#meta').innerHTML = `<span class="mono">${n} offers streamed · sources: ${esc(srcs.join(', ') || 'none')} · ${d.median_price==null ? 'ratings off' : 'median '+money(d.median_price)}</span>`;
      if(!n) box.innerHTML = '<div class="loading">No results.</div>';
      es.close(); resolve();
    });
    // EventSource reports 'error' when the stream drops. Closing stops the browser's
    // automatic reconnect, which would run the search again.
    es.addEventListener('error', () => {
      es.close(); loaded.stream = false;
      if(!n) box.innerHTML = '<div class="loading">Could not reach /search/stream.</div>';
      resolve();
    });
  });
}

/* ── PIPELINE (1c) ───────────────────────────────────────────────────── */
async function loadPipeline(){
  if(loaded.pipeline) return; loaded.pipeline=true;
  try{
    const d = await (await fetch(API + '/pipeline?q='+encodeURIComponent(state.q))).json();
    const nums = { ingest:d.contract.total, normalize:d.contract.total, 'quality-gate':`${d.contract.valid}/${d.contract.total}`,
                   label:d.contract.total, 'good_deals model':d.good_deals };
    $('#stages').innerHTML = d.stages.map((s,i)=>`
      ${i>0?'<div class="arrow">→</div>':''}
      <div class="stage">
        <div class="k">${esc(s.name)}</div>
        <div class="big">${esc(String(nums[s.name]??''))}</div>
        <div class="d">${esc(s.detail)}</div>
      </div>`).join('');
    const dist=d.label_distribution, tot=Object.values(dist).reduce((a,b)=>a+b,0);
    const colors={deal:'var(--color-accent)',fair:'var(--color-neutral-600)',suspicious:'var(--color-accent-600)',overpriced:'var(--color-neutral-800)'};
    const order=['deal','fair','suspicious','overpriced'];
    $('#dist').innerHTML = order.map(k=>`<span style="width:${(dist[k]/tot*100).toFixed(1)}%;background:${colors[k]};" title="${k}: ${dist[k]}"></span>`).join('');
    $('#distLegend').innerHTML = order.map(k=>`<span><i style="background:${colors[k]}"></i>${k} · ${dist[k]}</span>`).join('');
  }catch(e){ $('#stages').innerHTML=`<div class="loading">Could not reach /pipeline — ${esc(e.message)}</div>`; }
}

/* ── EVALS (1c inspector) ────────────────────────────────────────────── */
async function loadEvals(){
  if(loaded.evals) return; loaded.evals=true;
  try{
    const d = await (await fetch(API + '/evals')).json();
    $('#evalCards').innerHTML = `
      <div class="statcard"><div class="k">two_signal</div>
        <div style="display:flex;align-items:baseline;gap:var(--space-3);"><span class="num" style="color:var(--color-accent-400);">${d.two_signal.precision_at_5.toFixed(2)}</span><span class="tag tag-deal">gate pass</span></div>
        <div class="muted" style="font-size:11px;">precision@5 · gate ≥ ${d.gate.toFixed(2)}</div></div>
      <div class="statcard"><div class="k" style="color:var(--color-neutral-500);">median_only</div>
        <div style="display:flex;align-items:baseline;gap:var(--space-3);"><span class="num" style="color:var(--color-neutral-500);">${d.median_only.precision_at_5.toFixed(2)}</span><span class="tag tag-susp">gate fail</span></div>
        <div class="muted" style="font-size:11px;">precision@5 · gate ≥ ${d.gate.toFixed(2)}</div></div>
      <div class="statcard"><div class="k">A/B delta</div>
        <div class="num">+${d.ab.delta.toFixed(2)}</div>
        <div class="muted" style="font-size:11px;">winner: ${esc(d.ab.winner)} · the number you paste into the PR</div></div>`;
    const col = (title,rows,dim)=>`<div><h5 style="margin:0 0 var(--space-3);${dim?'color:var(--color-neutral-500);':''}">${title}</h5>
      ${rows.map((r,i)=>`<div class="toprow"><span class="rk">${i+1}</span><span class="nm ${dim&&r.label!=='deal'?'muted':''}">${esc(r.title)}</span>${r.label==='deal'?'<span class="tag tag-deal">deal</span>':'<span class="tag tag-susp">'+esc(r.label)+'</span>'}</div>`).join('')}</div>`;
    $('#evalTop').innerHTML = col('two_signal · top 5', d.two_signal.top5, false) + col('median_only · top 5', d.median_only.top5, true);
    $('#evalNote').textContent = `The naive ranker's top-5 are salted with traps that read as huge discounts; adding the model residual as a second signal moves ${d.median_only.precision_at_5.toFixed(2)} to ${d.two_signal.precision_at_5.toFixed(2)} — same listings, same labels, different ordering.`;
  }catch(e){ $('#evalCards').innerHTML=`<div class="loading">Could not reach /evals — ${esc(e.message)}</div>`; }
}

/* ── BY MEANING (semantic) ───────────────────────────────────────────── */
async function loadSemantic(){
  if(loaded.semantic) return; loaded.semantic=true;
  $('#semResults').innerHTML='<div class="loading">Loading…</div>';
  try{
    const d=await (await fetch(API + `/semantic?q=${encodeURIComponent(state.q)}&k=8`)).json();
    $('#semResults').innerHTML = d.results.map(semCard).join('') || '<div class="loading">No matches.</div>';
  }catch(e){ $('#semResults').innerHTML=`<div class="loading">Could not reach /semantic — ${esc(e.message)}</div>`; loaded.semantic=false; }
}
function semCard(r){
  const sim = r.similarity!=null ? Math.round(r.similarity*100)+'% match' : (r.verdict||'');
  const thumb = r.image_url?`<img class="thumb" src="${esc(r.image_url)}" referrerpolicy="no-referrer" alt="">`:`<div class="thumb"></div>`;
  return `<div class="card">${thumb}
    <div class="card-body"><div class="card-head"><span class="mono" style="font-size:10px;color:var(--color-neutral-600);">${esc(r.source||'')}</span></div>
      <div class="title">${esc(r.title)}</div></div>
    <div class="signal"><span class="sig-note accent">${esc(sim)}</span></div>
    <div class="priceblock"><div class="price">${r.price!=null?money(r.price):''}</div>${r.url?`<a class="link-sm" href="${safeHref(r.url)}" target="_blank" rel="noopener noreferrer">open offer →</a>`:''}</div>
  </div>`;
}

/* ── ASK (RAG) ───────────────────────────────────────────────────────── */
async function loadAsk(){
  if(loaded.ask) return; loaded.ask=true;
  $('#askBody').innerHTML='<div class="loading">Loading…</div>';
  try{
    const ep = $('#agentic').checked ? '/ask_agentic' : '/ask';
    const d=await (await fetch(API + ep + `?q=${encodeURIComponent(state.q)}`)).json();
    const badge = d.grounded?'<span class="tag tag-deal">grounded ✓</span>':'<span class="tag tag-susp">ungrounded</span>';
    $('#askBody').innerHTML = `
      <div class="card" style="flex-direction:column;align-items:stretch;gap:var(--space-3);">
        <div style="display:flex;gap:var(--space-3);align-items:center;flex-wrap:wrap;">${badge}<span class="tag tag-fair">${d.ai_written?'AI-written':'deterministic'}</span><span class="mono" style="font-size:11px;color:var(--color-neutral-600);margin-left:auto;">${d.sources.length} sources</span></div>
        <div style="white-space:pre-wrap;font-size:14px;line-height:1.6;">${esc(d.answer)}</div>
        ${d.hops ? `<ol class="mono" style="font-size:11px;color:var(--color-neutral-500);margin:0;padding-left:var(--space-6);">${d.hops.map(h=>`<li>${esc(h.query)} · ${h.sufficient?'enough evidence':'too thin'} · ${esc(h.reason)}</li>`).join('')}</ol>` : ''}
        <div style="display:flex;flex-wrap:wrap;gap:var(--space-2);">${d.sources.map(s=>`<span class="mono" style="font-size:10px;color:var(--color-neutral-600);border:1px solid var(--color-neutral-800);border-radius:5px;padding:2px 7px;">${esc(s)}</span>`).join('')}</div>
      </div>`;
  }catch(e){ $('#askBody').innerHTML=`<div class="loading">Could not reach /ask — ${esc(e.message)}</div>`; loaded.ask=false; }
}

/* ── GENERIC INSPECTOR ───────────────────────────────────────────────── */
async function loadGeneric(m){
  const cfg=GENERIC[m]; if(!cfg) return;
  const lesson = LESSONS[m];
  if(lesson && lesson.live && lesson.slug) $('#genKicker').innerHTML = kickerLink(cfg.kicker, lesson.slug);
  else $('#genKicker').textContent = cfg.kicker;
  $('#genTitle').textContent=cfg.title; $('#genSub').textContent=cfg.sub;
  if(loaded[m]) return; loaded[m]=true;
  $('#genBody').innerHTML='<div class="loading">Loading…</div>';
  try{
    const url = cfg.ep + (cfg.q?`?q=${encodeURIComponent(state.q)}`:'') +
      (m==='review' ? '&trap=' + ($('#trap').checked ? 'true' : 'false') : '');
    const r=await fetch(API + url); if(!r.ok) throw new Error('unavailable');
    $('#genBody').innerHTML = renderInspector(await r.json());
  }catch(e){ $('#genBody').innerHTML=mlHint(cfg.ep); loaded[m]=false; }
}
const isScalar = v => v===null || ['string','number','boolean'].includes(typeof v);
const fmtV = v => v===null?'—':(typeof v==='boolean'?(v?'✓ true':'✗ false'):esc(String(v)));
function kvRows(o){
  return Object.entries(o).map(([k,v])=>{
    let val;
    if(isScalar(v)) val=fmtV(v);
    else if(Array.isArray(v)) val=`<span class="muted">[${v.length}]</span>`+(v.length&&isScalar(v[0])?' '+v.slice(0,6).map(x=>`<span class="mono" style="font-size:10px;background:var(--color-neutral-900);border-radius:4px;padding:1px 6px;">${fmtV(x)}</span>`).join(' '):'');
    else val=`<span class="muted">{${esc(Object.keys(v).join(', ').slice(0,60))}}</span>`;
    return `<div style="display:flex;gap:var(--space-4);padding:var(--space-2) 0;font-size:13px;background:linear-gradient(to right,var(--color-divider),var(--color-divider)) no-repeat bottom/100% 1px;"><span class="muted" style="flex:0 0 42%;">${esc(k)}</span><span class="mono" style="flex:1;min-width:0;">${val}</span></div>`;
  }).join('');
}
function renderInspector(d){
  if(isScalar(d)) return `<div class="statcard"><div class="num" style="font-size:26px;">${fmtV(d)}</div></div>`;
  const E=Object.entries(d);
  const scalars=E.filter(([,v])=>isScalar(v)), objects=E.filter(([,v])=>v&&!Array.isArray(v)&&typeof v==='object'), arrays=E.filter(([,v])=>Array.isArray(v));
  let h='';
  if(scalars.length) h+=`<div class="gridcards" style="margin-bottom:var(--space-6);">`+scalars.map(([k,v])=>{
    const long = typeof v==='string' && v.length>16;
    return `<div class="statcard"><div class="k">${esc(k)}</div><div class="${long?'':'num'}" style="${long?'font-size:14px;line-height:1.45;':'font-size:24px;'}overflow-wrap:anywhere;">${fmtV(v)}</div></div>`;
  }).join('')+`</div>`;
  for(const [k,v] of objects) h+=`<div class="statcard" style="margin-bottom:var(--space-4);gap:0;"><div class="k" style="margin-bottom:var(--space-2);">${esc(k)}</div>${kvRows(v)}</div>`;
  for(const [k,v] of arrays){
    h+=`<div style="margin-bottom:var(--space-6);"><h5 style="margin:0 0 var(--space-3);">${esc(k)} <span class="muted mono" style="font-size:11px;">[${v.length}]</span></h5>`;
    if(v.length && typeof v[0]==='object' && !Array.isArray(v[0])){
      const cols=[...new Set(v.flatMap(o=>Object.keys(o)))].slice(0,6);
      h+=`<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:12.5px;"><tr>${cols.map(c=>`<th style="text-align:left;padding:var(--space-2);color:var(--color-neutral-500);font-weight:500;border-bottom:1px solid var(--color-divider);">${esc(c)}</th>`).join('')}</tr>`+
        v.slice(0,12).map(o=>`<tr>${cols.map(c=>`<td style="padding:var(--space-2);border-bottom:1px solid var(--color-neutral-900);" class="mono">${isScalar(o[c])?fmtV(o[c]):`<span class="muted">${o[c]==null?'—':(Array.isArray(o[c])?'['+o[c].length+']':'{…}')}</span>`}</td>`).join('')}</tr>`).join('')+`</table></div>`;
    } else {
      h+=`<div style="display:flex;flex-wrap:wrap;gap:var(--space-2);">`+v.slice(0,20).map(x=>`<span class="mono" style="font-size:11px;background:var(--color-neutral-900);border-radius:5px;padding:2px 8px;">${isScalar(x)?fmtV(x):esc(JSON.stringify(x).slice(0,40))}</span>`).join('')+`</div>`;
    }
    h+=`</div>`;
  }
  return h || '<div class="loading">No data.</div>';
}

/* ── WATCHLIST (P1 consumer core) ─────────────────────────────────────── */
async function loadWatchlist(){
  const body = $('#wlBody');
  if(!signedIn()){
    loaded.watchlist = false;
    body.innerHTML = '<div class="loading">Sign in to save items and get price-drop alerts — use the “Sign in” button, top-right.</div>';
    $('#wlCount').textContent = '';
    return;
  }
  if(loaded.watchlist) return; loaded.watchlist = true;
  body.innerHTML = '<div class="loading">Loading…</div>';
  try{
    const d = await (await fetch(API + '/watchlist', {headers: authHeaders()})).json();
    $('#wlCount').textContent = d.count || '';
    if(!d.items.length){ body.innerHTML = '<div class="loading">Nothing watched yet — add items from Live deals with “＋ watch”.</div>'; return; }
    body.innerHTML = d.items.map(wlCard).join('');
    document.querySelectorAll('.wl-remove').forEach(b=>b.onclick=async()=>{
      await fetch(API + '/watchlist/' + encodeURIComponent(b.dataset.id), {method:'DELETE', headers: authHeaders()});
      loaded.watchlist = false; loadWatchlist();
    });
  }catch(e){ body.innerHTML = `<div class="loading">Could not load watchlist — ${esc(e.message)}</div>`; loaded.watchlist = false; }
}
function wlCard(it){
  const thumb = it.image_url ? `<img class="thumb" src="${esc(it.image_url)}" referrerpolicy="no-referrer" alt="">` : `<div class="thumb"></div>`;
  const tag = it.hit ? '<span class="tag tag-deal">PRICE DROP</span>' : '<span class="tag tag-fair">WATCHING</span>';
  return `<div class="card ${it.hit?'top':''}">${thumb}
    <div class="card-body">
      <div class="card-head">${tag} <span class="mono" style="font-size:10px;color:var(--color-neutral-600);">${esc(it.source||'')}</span></div>
      <div class="title">${esc(it.title)}</div>
      <div class="reason">target ${it.target_price!=null?money(it.target_price):'—'} · last seen ${it.last_price!=null?money(it.last_price):'—'}</div>
    </div>
    <div class="priceblock">
      <div class="price">${it.last_price!=null?money(it.last_price):''}</div>
      <div style="display:flex;gap:var(--space-3);align-items:center;">
        ${it.url?`<a class="link-sm" href="${safeHref(it.url)}" target="_blank" rel="noopener noreferrer">open →</a>`:''}
        <button class="linkbtn wl-remove" data-id="${esc(it.offer_id)}">remove</button>
      </div>
    </div>
  </div>`;
}

/* ── lessons, sources, start-up ──────────────────────────────────────── */
// Each mode's "Part N" kicker links to its lesson once that lesson is published.
let LESSONS = {};
const kickerLink = (text, slug) => `<a href="${safeHref('https://cloudcodetree.com/tutorials/' + slug + '/')}">${esc(text)}</a>`;
async function loadLessons(){
  try{ LESSONS = await (await fetch(LAB + 'lessons.json')).json(); }catch(e){ return; }
  for(const [m, v] of Object.entries(LESSONS)){
    const h = document.querySelector(`#view-${m} .section-head h6`);
    if(h && v.live && v.slug) h.innerHTML = kickerLink(h.textContent, v.slug);
  }
}
async function loadSources(){
  try{
    const s = await (await fetch(API + '/sources')).json();
    const on = Object.entries(s).filter(([,v])=>v).map(([k])=>k);
    $('#sourcesLine').innerHTML = `<span class="mono">free-tier sources on: ${esc(on.join(', ') || 'none')} · metered sources (Amazon, Apify, Firecrawl) stay off unless DEALFINDER_ENABLE_PAID_SOURCES=1</span>`;
  }catch(e){}
}
$('#agentic').addEventListener('change', ()=>{ loaded.ask = false; if(state.mode==='ask') setMode('ask'); });
$('#trap').addEventListener('change', ()=>{ loaded.review = false; if(state.mode==='review') setMode('review'); });
if(LIVE){ document.getElementById('acct').addEventListener('click', toggleAcct); initAuth(); }
else document.getElementById('acct').hidden = true;   // nothing to sign in for without live data
loadLessons(); loadSources();
// Deep links (Plan 6's screenshot manifests): ?mode=<id>&q=<query> opens that mode and runs it.
const params = new URLSearchParams(location.search);
const startQ = (params.get('q') || '').trim();
if(startQ){ state.q = startQ; $('#q').value = startQ; }
const startMode = params.get('mode');
setMode(document.querySelector(`.rail-item[data-mode="${CSS.escape(startMode || '')}"]`) ? startMode : 'deals');
