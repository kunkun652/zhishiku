// Original-source reader. Page numbers come from registered source pages, not IDs.
let closeCurrent = () => {};
// pywebview opens target=_blank in the system browser, which deliberately has
// no owner cookie. Keep original-file navigation inside the authenticated app.
document.addEventListener('click',event=>{
 if(event.defaultPrevented)return;
 const link=event.target.closest('a[href]');if(!link)return;
 const url=new URL(link.href,location.href);
 if(url.origin!==location.origin||!/^\/api\/model-assets\/[^/]+\/file$/.test(url.pathname))return;
 event.preventDefault();
 const dialog=document.createElement('dialog');dialog.className='original-viewer';
 const head=document.createElement('div');head.className='reader-head';
 const title=document.createElement('strong');title.textContent='原始文件 · 本机阅读';
 const close=document.createElement('button');close.textContent='关闭原件';close.onclick=()=>dialog.close();
 head.append(title,close);const frame=document.createElement('iframe');frame.title='原始文件';frame.src=url.href;
 dialog.append(head,frame);document.body.append(dialog);dialog.addEventListener('close',()=>dialog.remove());dialog.showModal();
});
export function closeReader(){closeCurrent()}
export async function openReader(fileId,{api,esc,page=null,query=''}={}){
 closeCurrent();let disposed=false,sequence=0,current=null,offset=0;
 const key='zh-reader:'+fileId;
 let saved={};try{saved=JSON.parse(localStorage.getItem(key)||'{}')}catch{}
 const drawer=document.createElement('section');drawer.className='source-drawer';drawer.setAttribute('aria-label','原文阅读侧栏');document.body.append(drawer);
 const remember=()=>{if(current)try{localStorage.setItem(key,JSON.stringify({hash:current.file_hash,page:current.page,offset,scroll:drawer.querySelector('.reader-body')?.scrollTop||0}))}catch{}};
 const close=()=>{remember();disposed=true;++sequence;drawer.remove();document.removeEventListener('keydown',onKey)};
 const onKey=e=>{if(e.key==='Escape')close()};document.addEventListener('keydown',onKey);closeCurrent=close;
 const highlight=text=>{if(!query)return esc(text);const parts=String(text).split(new RegExp('('+query.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+')','ig'));return parts.map((p,i)=>i%2?`<mark>${esc(p)}</mark>`:esc(p)).join('')};
 async function load(target,restore=false){
  const n=++sequence;drawer.innerHTML='<div class="reader-head"><strong>正在读取原文…</strong><button data-close>关闭</button></div>';drawer.querySelector('[data-close]').onclick=close;
  try{
   const r=await api('/api/library/files/'+encodeURIComponent(fileId)+'/read?'+new URLSearchParams({page:target||0,offset}));if(disposed||n!==sequence)return;current=r;
   if(restore&&saved.hash&&saved.hash!==r.file_hash){saved={};offset=0;return load(0)}
   const ix=r.pages.indexOf(r.page);
   drawer.innerHTML=`<div class="reader-head"><div><small>原始资料 · 版本 ${esc(r.file_hash.slice(0,8))}</small><h2>${esc(r.name)}</h2></div><button data-close aria-label="关闭原文侧栏">×</button></div><div class="reader-toolbar"><button data-prev ${ix<=0?'disabled':''}>上一页</button><label>页码 <select data-page>${r.pages.map(p=>`<option ${p===r.page?'selected':''}>${p}</option>`).join('')}</select></label><button data-next ${ix<0||ix>=r.pages.length-1?'disabled':''}>下一页</button><a href="${r.url}#page=${r.page}" target="_blank" rel="noopener">打开原件 ↗</a></div><div class="reader-body"><p class="hint">${esc(r.order_note||'原文逐字显示，不以 AI 摘要代替。')}${restore&&saved.page?' · 已恢复阅读位置':''}</p>${r.blocks.map(b=>`<article class="reader-block">${highlight(b.text)}</article>`).join('')||'<p>此文件暂无已解析正文，请打开原件阅读。</p>'}<div class="actions"><button data-block-prev ${offset===0?'disabled':''}>前一组片段</button><span>${r.total_blocks} 个同页片段</span><button data-block-next ${offset+30>=r.total_blocks?'disabled':''}>后一组片段</button></div>${r.pdf?`<details class="reader-pdf"><summary>在侧栏查看 PDF 原件</summary><iframe title="PDF 原件" loading="lazy" data-src="${r.url}#page=${r.page}"></iframe></details>`:''}<details class="reader-policy"><summary>资料使用范围 · ${r.outbound_allowed?'允许用于远端问答':'仅限本机'}</summary><p>授权仅对这个文件的当前版本有效。远端问答只发送命中的引文，不上传整个文件。变更版本后需重新确认。</p><label><input type="checkbox" data-outbound ${r.outbound_allowed?'checked':''}>允许当前版本的引用片段发送给已配置的远端模型</label><button data-policy-save>保存使用范围</button><p data-policy-result role="status"></p></details></div>`;
   drawer.querySelector('[data-close]').onclick=close;
   const navigate=p=>{remember();offset=0;load(p)};
   drawer.querySelector('[data-prev]').onclick=()=>navigate(r.pages[ix-1]);drawer.querySelector('[data-next]').onclick=()=>navigate(r.pages[ix+1]);drawer.querySelector('[data-page]').onchange=e=>navigate(Number(e.target.value));
   drawer.querySelector('[data-block-prev]').onclick=()=>{offset=Math.max(0,offset-30);load(r.page)};drawer.querySelector('[data-block-next]').onclick=()=>{offset+=30;load(r.page)};
   drawer.querySelector('[data-policy-save]').onclick=async()=>{try{const v=await api('/api/library/files/'+encodeURIComponent(fileId)+'/policy',{method:'POST',body:JSON.stringify({allowed:drawer.querySelector('[data-outbound]').checked,file_hash:r.file_hash})});if(!disposed)drawer.querySelector('[data-policy-result]').textContent=v.allowed?'已授权当前版本':'已恢复仅限本机'}catch(e){if(!disposed)drawer.querySelector('[data-policy-result]').textContent=e.message}};
   const pdf=drawer.querySelector('.reader-pdf');if(pdf)pdf.ontoggle=()=>{const frame=pdf.querySelector('iframe');if(pdf.open&&!frame.src)frame.src=frame.dataset.src};
   if(restore)drawer.querySelector('.reader-body').scrollTop=saved.scroll||0;
  }catch(e){if(!disposed&&n===sequence){drawer.innerHTML=`<div class="reader-head"><p>${esc(e.message)}</p><button data-close>关闭</button></div>`;drawer.querySelector('[data-close]').onclick=close}}
 }
 offset=page===null?(saved.offset||0):0;await load(page===null?saved.page:page,page===null);
}
