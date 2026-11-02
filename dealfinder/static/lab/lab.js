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
let state = { mode:"snapshot", q:"noise cancelling headphones" };
const loaded = {};

/* ── mode switching ──────────────────────────────────────────────────── */
document.querySelectorAll('.rail-item[data-mode]').forEach(b=>{
  b.addEventListener('click',()=>setMode(b.dataset.mode));
});
function setMode(m){
  state.mode = m;
  // The ready flag marks a finished render (Plan 6's screenshots wait on it). A switch clears it.
  document.querySelectorAll('.rail-item[data-mode]').forEach(b=>{ b.classList.toggle('active',b.dataset.mode===m); delete b.dataset.ready; });
  ['snapshot'].forEach(v=>$('#view-'+v).classList.toggle('hidden',v!==m));
  // A loader returns false when all it could draw is an error, which never counts as ready.
  Promise.resolve({snapshot:loadSnapshot}[m]()).catch(()=>false).then(ok=>{
    const b = document.querySelector(`.rail-item[data-mode="${m}"]`);
    if(ok !== false && b && state.mode === m) b.dataset.ready = 'true';
  });
}
$('#go').addEventListener('click',()=>{ state.q=$('#q').value.trim()||state.q; Object.keys(loaded).forEach(k=>delete loaded[k]); setMode(state.mode); });

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
  }catch(e){ body.innerHTML=`<div class="loading">Could not reach /snapshot — ${esc(e.message)}</div>`; loaded.snapshot=false; return false; }
}

/* ── lessons, start-up ───────────────────────────────────────────────── */
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
loadLessons();
// Deep links (Plan 6's screenshot manifests): ?mode=<id>&q=<query> opens that mode and runs it.
const params = new URLSearchParams(location.search);
const startQ = (params.get('q') || '').trim();
if(startQ){ state.q = startQ; $('#q').value = startQ; }
const startMode = params.get('mode');
setMode(document.querySelector(`.rail-item[data-mode="${CSS.escape(startMode || '')}"]`) ? startMode : 'snapshot');
