const $ = id => document.getElementById(id);
let jobId = '', timer = null, fileOffset = 0, candidateOffset = 0;
const json = value => JSON.stringify(value, null, 2);
function message(text) { $('message').textContent = text; $('message').style.display = 'block'; setTimeout(() => { $('message').style.display = 'none'; }, 7000); }
async function api(path, body) {
  const options = body === undefined ? {} : body instanceof FormData ? {method:'POST',body} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)};
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : json(data));
  return data;
}
function bind(id, fn) { $(id).addEventListener('click', async () => { $(id).disabled = true; try { await fn(); } catch (e) { message(e.message); } finally { $(id).disabled = false; } }); }
async function status(probe=false) { $('status').textContent = json(await api('/api/pipeline/status'+(probe?'?probe=true':''))); }
async function files(reset=false) {
  if(reset){fileOffset=0;$('files').replaceChildren();}
  const result=await api(`/api/pipeline/files?offset=${fileOffset}&limit=50`);
  for(const file of result.items){const option=document.createElement('option');option.value=file.id;option.textContent=`${file.name} (${file.size} bytes)`;$('files').append(option);}
  fileOffset+=result.items.length;$('more-files').hidden=fileOffset>=result.total;
}
async function candidates(reset=false) {
  if(reset)candidateOffset=0;
  const result=await api(`/api/pipeline/candidates?job_id=${encodeURIComponent(jobId)}&offset=${candidateOffset}&limit=50`);
  $('candidate-count').textContent=`共 ${result.total} 项，当前显示 ${result.total?candidateOffset+1:0}–${candidateOffset+result.items.length} 项`;
  $('candidates').replaceChildren();$('next-candidates').hidden=candidateOffset+result.items.length>=result.total;
  for(const item of result.items){
    const card=document.createElement('div');card.className='candidate';
    const label=document.createElement('label'),check=document.createElement('input'),title=document.createElement('strong');
    check.type='checkbox';check.value=item.id;check.dataset.status=item.status;
    title.textContent=`${item.payload.title} · ${item.payload.kind} · ${item.status}`;label.append(check,title);card.append(label);
    const proof=document.createElement('blockquote');proof.textContent=item.evidence.quote;card.append(proof);
    const meta=document.createElement('p');meta.textContent=`${item.evidence.locator}，字符 ${item.evidence.parent_start}–${item.evidence.parent_end}；Semantica ${item.payload.engine} / ${item.payload.mode}；置信概率未校准`;card.append(meta);
    if(item.conflicts.length){const warning=document.createElement('p');warning.className='warning';warning.textContent=item.conflicts.map(c=>`${c.kind}: ${c.detail} [${c.status}]`).join('；');card.append(warning);}
    const link=document.createElement('a');link.href=`/api/model-assets/${encodeURIComponent(item.evidence.file_id)}/file`;link.target='_blank';link.rel='noopener';link.textContent='打开受管原件';card.append(link);$('candidates').append(card);
  }
}
async function poll(){
  if(!jobId)return;
  const job=await api('/api/pipeline/jobs/'+encodeURIComponent(jobId));$('job').textContent=json(job);
  if(['queued','parsing','extracting'].includes(job.state)){timer=setTimeout(()=>poll().catch(e=>message(e.message)),2000);}
  else{await candidates(true);await status();if(job.state==='failed')message(job.error);}
}
async function review(action){
  const ids=[...$('candidates').querySelectorAll('input:checked')].map(n=>n.value);
  if(!ids.length)throw new Error('请先勾选候选');
  if(action==='revoke'&&!confirm('撤销会停用本流程创建且尚未被再次编辑的对象。继续吗？'))return;
  await api('/api/pipeline/review',{ids,action,reviewer:$('reviewer').value,note:$('note').value,conflict_note:$('conflict-note').value});await candidates();await status();message('审核已记录；采纳不是工程验收。');
}
async function query(agent){
  const result=await api(agent?'/api/agent/ask':'/api/retrieve',{query:$('query').value,top_k:10});
  $('trace').textContent=json(result);$('answer').replaceChildren();
  const label=document.createElement('p');label.textContent=`运行状态：${result.status}`;$('answer').append(label);
  for(const claim of result.claims||[]){const node=document.createElement('div');node.className='claim';node.textContent=claim.text+' '+claim.citations.map(c=>'['+c.id+']').join(' ');$('answer').append(node);}
  for(const gap of result.gaps||[]){const node=document.createElement('p');node.className='warning';node.textContent=gap;$('answer').append(node);}
  const pack=result.evidence_pack||result;
  for(const e of pack.evidence||[]){const box=document.createElement('div');box.className='evidence';const title=document.createElement('strong');title.textContent=`[${e.id}] ${e.title} · ${e.kind}`;const quote=document.createElement('p');quote.textContent=e.quote;box.append(title,quote);if(e.url&&e.url.startsWith('/api/')){const link=document.createElement('a');link.href=e.url;link.target='_blank';link.rel='noopener';link.textContent='查看依据';box.append(link);}$('answer').append(box);}
}
bind('probe',()=>status(true));bind('more-files',()=>files());
bind('upload',async()=>{const file=$('file').files[0];if(!file)throw new Error('请选择文件');const form=new FormData();form.append('file',file);const result=await api('/api/pipeline/upload',form);await files(true);if(![...$('files').options].some(o=>o.value===result.id)){const option=document.createElement('option');option.value=result.id;option.textContent=result.name;$('files').append(option);}$('files').value=result.id;message(result.reused?'已复用登记记录':'原件已登记，尚未开始抽取');});
bind('start',async()=>{if(!$('files').value)throw new Error('请选择已登记资料');clearTimeout(timer);const result=await api('/api/pipeline/jobs',{file_id:$('files').value,mode:$('mode').value});jobId=result.id;await poll();});
bind('accept',()=>review('accept'));bind('reject',()=>review('reject'));bind('revoke',()=>review('revoke'));
bind('reload-candidates',()=>candidates(true));bind('next-candidates',()=>{candidateOffset+=50;return candidates();});
bind('refresh-index',async()=>{$('indexes').textContent=json(await api('/api/pipeline/indexes/refresh',{}));});
bind('check-index',async()=>{$('indexes').textContent=json(await api('/api/pipeline/indexes'));});
bind('activate-index',async()=>{$('indexes').textContent=json(await api('/api/pipeline/indexes/activate',{}));await status();});
bind('retrieve',()=>query(false));bind('ask',()=>query(true));
window.addEventListener('beforeunload',()=>clearTimeout(timer));
Promise.all([status(),files(true),candidates(true)]).catch(e=>message(e.message));
