// ABSI Audio Cloud: Worker handles Cloudflare R2 audio and a scheduled Blogger feed scan.
const BLOG = 'https://www.absi.cc';
const DIAG_KEY = 'system/last-scan.json';
const PILOT_URL = 'https://www.absi.cc/2026/11/bawndi.html';
async function saveDiagnostic(env, data) {
  const record = {checkedAt: new Date().toISOString(), ...data};
  try { await env.AUDIO_BUCKET.put(DIAG_KEY, JSON.stringify(record), {httpMetadata: {contentType:'application/json', cacheControl:'no-store'}}); }
  catch (error) { console.error('Diagnostic write failed:', String(error)); }
  return record;
}

function audioKey(articleUrl) {
  let u;
  try { u = new URL(articleUrl); } catch { return null; }
  if (u.protocol !== 'https:' || !['www.absi.cc', 'absi.cc'].includes(u.hostname)) return null;
  const m = u.pathname.match(/^\/20(\d{2})\/(0[1-9]|1[0-2])\/([A-Za-z0-9_-]+)\.html$/);
  return m ? `articles/20${m[1]}/${m[2]}/${m[3]}.mp3` : null;
}
function cors(origin) {
  const ok = [BLOG, "https://absi.cc"].includes(origin);
  return ok ? { "Access-Control-Allow-Origin": origin, "Vary": "Origin" } : { "Vary": "Origin" };
}
async function scan(env) {
  if (!env.RENDER_URL || !env.WORKER_SHARED_SECRET) { await saveDiagnostic(env,{status:'missing_configuration'}); throw new Error('Render URL or shared secret missing'); }
  const response = await fetch(`${BLOG}/feeds/posts/default?alt=json&max-results=100`);
  if (!response.ok) { await saveDiagnostic(env,{status:'blogger_feed_error',httpStatus:response.status}); throw new Error(`Blogger feed returned ${response.status}`); }
  const feed = await response.json();
  const entries = [...(feed.feed?.entry || [])];
  const pilotIndex = entries.findIndex(e => (e.link || []).some(l => l.rel === 'alternate' && audioKey(l.href) === audioKey(PILOT_URL)));
  if (pilotIndex > 0) entries.unshift(entries.splice(pilotIndex, 1)[0]);
  let lastValidationError = null;
  for (const entry of entries) {
    const link = (entry.link || []).find(x => x.rel === 'alternate' && x.type === 'text/html')?.href;
    if (!link) continue;
    const key = audioKey(link);
    if (!key || await env.AUDIO_BUCKET.head(key)) continue;
    const html = entry.content?.$t || '';
    if (!html) continue;
    const res = await fetch(`${env.RENDER_URL.replace(/\/$/, '')}/generate`, {
      method: 'POST', headers: {'Content-Type':'application/json','Authorization':`Bearer ${env.WORKER_SHARED_SECRET}`},
      body: JSON.stringify({url: link, html})
    });
    if (!res.ok) {
      const failure = {status:'generation_http_error',httpStatus:res.status,article:link};
      await saveDiagnostic(env, failure);
      console.error('Generation failed', failure);
      if (res.status === 422 || res.status === 400) { lastValidationError = failure; continue; }
      throw new Error(`Piper service returned ${res.status}`);
    }
    const outcome = await res.json();
    await saveDiagnostic(env,{status:outcome.status || 'created',article:link});
    return outcome;
  }
  if (lastValidationError) return lastValidationError;
  const done = {status:'nothing_to_do',feedItems:entries.length};
  await saveDiagnostic(env,done);
  return done;
}
export default {
  async scheduled(event, env, ctx) { ctx.waitUntil(scan(env)); },
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === 'OPTIONS') return new Response(null, {status:204,headers:{...cors(request.headers.get('Origin')),'Access-Control-Allow-Methods':'GET,HEAD,OPTIONS'}});
    if (request.method !== 'GET' && request.method !== 'HEAD') return new Response('Method not allowed', {status:405});
    if (url.pathname === '/health') return Response.json({ok: true, service:'ABSI Audio Cloud'});
    if (url.pathname === '/diagnostics') {
      const stored = await env.AUDIO_BUCKET.get(DIAG_KEY);
      return Response.json(stored ? JSON.parse(await stored.text()) : {status:'not_run_since_diagnostics_enabled'},
        {headers:{...cors(request.headers.get('Origin')),'Cache-Control':'no-store'}});
    }
    if (url.pathname === '/status') {
      const articleUrl=url.searchParams.get('url') || '';
      const key = audioKey(articleUrl);
      if (!key) return Response.json({ready:false},{status:400,headers:cors(request.headers.get('Origin'))});
      const meta = await env.AUDIO_BUCKET.head(key);
      return Response.json({ready:!!meta,audioUrl:meta?`${url.origin}/play?url=${encodeURIComponent(articleUrl)}`:null},
        {headers:{...cors(request.headers.get('Origin')),'Cache-Control':'public,max-age=60'}});
    }
    if (url.pathname === '/play') {
      const key = audioKey(url.searchParams.get('url') || '');
      if (!key) return new Response('Bad article URL', {status:400});
      const range = request.headers.get('Range');
      const object = await env.AUDIO_BUCKET.get(key, range ? {range:request.headers} : {});
      if (!object) return new Response('Audio not ready', {status:404});
      const headers = new Headers({'Content-Type':'audio/mpeg','Cache-Control':'public,max-age=86400','Accept-Ranges':'bytes',...cors(request.headers.get('Origin'))});
      const size=object.size, offset=object.range?.offset, length=object.range?.length;
      if (range && offset !== undefined && length !== undefined) {
        headers.set('Content-Range', `bytes ${offset}-${offset+length-1}/${size}`);
        headers.set('Content-Length', String(length));
        return new Response(request.method === 'HEAD' ? null : object.body, {status:206,headers});
      }
      headers.set('Content-Length', String(size));
      return new Response(request.method === 'HEAD' ? null : object.body,{headers});
    }
    return new Response('Not found',{status:404});
  }
};
