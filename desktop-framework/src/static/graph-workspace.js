const saved={selected:null,transform:null,positions:new Map(),backend:'authority',pathEdges:[]};
export function focusGraph(id,paths=[],backend='authority'){
 saved.selected=id;saved.pathEdges=paths.flat().map(e=>e.id);
 if(saved.backend!==backend){saved.positions.clear();saved.transform=null;}saved.backend=backend;
}
export async function mountGraph(host,{api,esc,showDetail,catalog,openSlices}){
 host.innerHTML=`<div class="live-graph"><div class="live-scene"><canvas id="graph-canvas" aria-label="全库知识图谱，可拖动节点、拖动空白平移、滚轮缩放" tabindex="0"></canvas><p id="g-status" role="status">正在加载全部知识与连接…</p><span class="graph-help">拖动节点 · 拖动空白平移 · 滚轮缩放 · 点击查看 · 双击打开原信息</span></div><section id="g-detail" class="live-details" hidden></section></div>`;
 const $=s=>host.querySelector(s),canvas=$('#graph-canvas'),ctx=canvas.getContext('2d'),panel=$('#g-detail');
 let alive=true,nodes=[],edges=[],byid=new Map(),adj=new Map(),snapshot='',request=0,selected=saved.selected,hover=null,gesture=null,frame=0,width=1,height=1,tree,autoFit=!saved.transform,ticks=0;
 let transform=saved.transform?{...saved.transform}:{x:0,y:0,k:1};
 const backend=saved.backend,paths=new Set(saved.pathEdges),worker=new Worker('/static/graph-physics.js');
 const label=type=>catalog.templates.find(t=>t.type===type)?.label||type;
 function schedule(){if(alive&&!frame)frame=requestAnimationFrame(draw)}
 function fit(){
  if(!nodes.length)return;
  const [x0,x1]=d3.extent(nodes,n=>n.x),[y0,y1]=d3.extent(nodes,n=>n.y);
  const k=Math.min(1.6,(width-90)/(x1-x0+40),(height-90)/(y1-y0+40));
  transform={k,x:width/2-(x0+x1)*k/2,y:height/2-(y0+y1)*k/2};
 }
 function draw(){
  frame=0;ctx.clearRect(0,0,width,height);
  const active=hover||selected,near=adj.get(active)||new Set(),k=transform.k;
  const point=n=>[n.x*k+transform.x,n.y*k+transform.y];
  ctx.lineWidth=.65;ctx.strokeStyle=active?'#dcdce590':'#afb0bd99';ctx.beginPath();
  for(const e of edges)if(!e.stale){ctx.moveTo(...point(e.source));ctx.lineTo(...point(e.target))}ctx.stroke();
  ctx.setLineDash([3,3]);ctx.beginPath();for(const e of edges)if(e.stale){ctx.moveTo(...point(e.source));ctx.lineTo(...point(e.target))}ctx.stroke();ctx.setLineDash([]);
  if(active||paths.size){ctx.lineWidth=1.35;ctx.strokeStyle='#9473d8';ctx.beginPath();for(const e of edges)if(e.source.id===active||e.target.id===active||paths.has(e.id)){ctx.moveTo(...point(e.source));ctx.lineTo(...point(e.target))}ctx.stroke()}
  const visible=[];
  for(const n of nodes){const [x,y]=point(n);if(x< -20||x>width+20||y< -20||y>height+20)continue;const related=near.has(n.id),chosen=n.id===active;
   const r=chosen?6:Math.max(1.35,Math.min(5,(2.7+Math.log1p(n.degree)*.45)*Math.sqrt(k)));
   ctx.fillStyle=chosen?'#8b5cf6':related?'#aa8bcc':active?'#d0d0d9':n.degree?'#9293a4':'#c9c9d2';ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();
   visible.push({n,x,y,r,priority:chosen?3:related?2:n.degree?1:0});
  }
  // Only labels are thinned; every node remains drawn and hit-testable.
  visible.sort((a,b)=>b.priority-a.priority||b.n.degree-a.n.degree);const occupied=new Set();ctx.font='12px "Microsoft YaHei", sans-serif';ctx.textAlign='center';let count=0;
  for(const {n,x,y,r,priority} of visible){if(priority<2&&k<.55&&n.degree<2)continue;if(priority<2&&count>Math.max(12,width*height/13000))continue;
   const text=n.title.length>22?n.title.slice(0,22)+'…':n.title,w=ctx.measureText(text).width+12,yy=y+r+16,keys=[];
   for(let cx=Math.floor((x-w/2)/32);cx<=Math.floor((x+w/2)/32);cx++)for(let cy=Math.floor((yy-12)/18);cy<=Math.floor((yy+3)/18);cy++)keys.push(cx+','+cy);
   if(priority!==3&&keys.some(c=>occupied.has(c)))continue;keys.forEach(c=>occupied.add(c));
   ctx.lineWidth=3;ctx.strokeStyle='#fcfcfe';ctx.strokeText(text,x,yy);ctx.fillStyle=priority===3?'#292333':priority===2?'#756087':'#8e8d9c';ctx.fillText(text,x,yy);count++;
  }
  canvas.dataset.transform=JSON.stringify(transform);
 }
 function rebuildTree(){tree=d3.quadtree(nodes,n=>n.x,n=>n.y)}
 worker.onmessage=({data})=>{if(!alive)return;nodes.forEach((n,i)=>{if(gesture?.node===n&&gesture.moved)return;n.x=data[i*2];n.y=data[i*2+1]});ticks++;rebuildTree();if(autoFit)fit();if(ticks>90)autoFit=false;schedule()};
 worker.onerror=()=>{$('#g-status').textContent='动态布局加载失败，请重新进入图谱。'};
 function local(event){const r=canvas.getBoundingClientRect();return [event.clientX-r.left,event.clientY-r.top]}
 function hit(x,y){return tree?.find((x-transform.x)/transform.k,(y-transform.y)/transform.k,9/transform.k)}
 canvas.onpointerdown=e=>{if(e.button!==0)return;autoFit=false;const [x,y]=local(e);gesture={id:e.pointerId,x,y,lastX:x,lastY:y,node:hit(x,y),moved:false};canvas.setPointerCapture(e.pointerId)};
 canvas.onpointermove=e=>{
  const [x,y]=local(e);
  if(gesture){if(Math.hypot(x-gesture.x,y-gesture.y)>4)gesture.moved=true;if(gesture.moved){
   if(gesture.node){const n=gesture.node;n.x=(x-transform.x)/transform.k;n.y=(y-transform.y)/transform.k;worker.postMessage({type:'drag',index:n.index,x:n.x,y:n.y});rebuildTree()}
   else{transform.x+=x-gesture.lastX;transform.y+=y-gesture.lastY}schedule();
  }gesture.lastX=x;gesture.lastY=y;canvas.style.cursor='grabbing';return;}
  const n=hit(x,y);hover=n?.id||null;canvas.title=n?.title||'';canvas.style.cursor=n?'pointer':'grab';schedule();
 };
 function release(e,cancel=false){if(!gesture||gesture.id!==e.pointerId)return;const g=gesture;gesture=null;if(g.node&&g.moved)worker.postMessage({type:'release',index:g.node.index});if(canvas.hasPointerCapture(e.pointerId))canvas.releasePointerCapture(e.pointerId);canvas.style.cursor='grab';if(!cancel&&!g.moved){if(g.node)detail(g.node.id);else closeDetail()}schedule()}
 canvas.onpointerup=e=>release(e);canvas.onpointercancel=e=>release(e,true);canvas.onlostpointercapture=e=>release(e,true);
 canvas.onpointerleave=()=>{hover=null;schedule()};
 canvas.ondblclick=e=>{const n=hit(...local(e));if(n)showDetail(n.id)};
 canvas.onwheel=e=>{e.preventDefault();autoFit=false;const [x,y]=local(e),old=transform.k,k=Math.max(.025,Math.min(10,old*Math.exp(-e.deltaY*.0015)));transform={k,x:x-(x-transform.x)*k/old,y:y-(y-transform.y)*k/old};schedule()};
 canvas.onkeydown=e=>{if(e.key==='Escape')closeDetail()};
 function closeDetail(){++request;selected=saved.selected=null;panel.hidden=true;schedule()}
 async function detail(oid){
  const token=++request;selected=saved.selected=oid;hover=null;autoFit=false;panel.hidden=false;panel.innerHTML='<p>正在读取原信息与连接…</p>';worker.postMessage({type:'wake'});schedule();
  try{
   const params={backend,snapshot,limit:100};const g=await api('/api/graph-node/'+encodeURIComponent(oid)+'?'+new URLSearchParams(params));if(!alive||token!==request)return;
   const relations=[...g.relations];for(let offset=relations.length;offset<g.total;offset+=100){const page=await api('/api/graph-node/'+encodeURIComponent(oid)+'?'+new URLSearchParams({...params,offset}));if(!alive||token!==request)return;relations.push(...page.relations);Object.assign(g.neighbors,page.neighbors)}
   const n=g.node,template=catalog.templates.find(t=>t.type===n.type),files=await api('/api/objects/'+encodeURIComponent(oid)+'/files');if(!alive||token!==request)return;
   panel.innerHTML=`<button class="graph-close" aria-label="关闭详情">×</button><span class="hint">${esc(label(n.type))} · v${n.version}${backend==='semantica'?' · 派生快照':''}</span><h2>${esc(n.title)}</h2><p class="hint">${esc(({candidate:'候选 · 待复核',reviewed:'已复核',retired:'停用',conflict:'冲突'})[n.status]||n.status)}</p><div class="actions"><button id="g-open">打开原信息</button><button id="g-slices">查看原文</button></div><p class="graph-summary">${esc(n.data.summary||n.data.definition||'')}</p>${files.length?'<h3>'+(backend==='semantica'?'当前主库原文件':'原文件')+'</h3>'+files.map(f=>`<p><a href="/api/model-assets/${encodeURIComponent(f.id)}/file" target="_blank">${esc(f.name)}</a></p>`).join(''):''}${n.data.source?`<h3>来源位置</h3><p>${esc(n.data.source)}</p>`:''}<h3>连接 · ${g.total}</h3>${relations.map(e=>{const other=e.source===oid?e.target:e.source;return `<article class="graph-relation"><button data-neighbor="${esc(other)}">${esc(g.neighbors[other]?.title||other)}</button><small>${e.source===oid?'→':'←'} ${esc(e.type)}${e.stale?' · 端点版本待复核':''}</small><p class="hint">${esc(e.evidence)}</p></article>`}).join('')||'<p class="hint">此对象尚未登记连接。</p>'}<details><summary>完整记录字段</summary>${(template?.fields||[]).filter(f=>f.key!=='original_record'&&n.data[f.key]).map(f=>`<div class="detail-field"><strong>${esc(f.label)}</strong><div>${esc(typeof n.data[f.key]==='object'?JSON.stringify(n.data[f.key],null,2):n.data[f.key])}</div></div>`).join('')}</details>`;
   panel.querySelector('.graph-close').onclick=closeDetail;$('#g-open').onclick=()=>showDetail(oid);$('#g-slices').onclick=()=>openSlices(oid);panel.querySelectorAll('[data-neighbor]').forEach(b=>b.onclick=()=>detail(b.dataset.neighbor));
  }catch(e){if(alive&&token===request){panel.innerHTML=`<button class="graph-close" aria-label="关闭详情">×</button><p>${esc(e.message)}</p>`;panel.querySelector('.graph-close').onclick=closeDetail}}
 }
 const resize=new ResizeObserver(()=>{width=canvas.clientWidth;height=canvas.clientHeight;const dpr=Math.min(2,window.devicePixelRatio||1);canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);if(autoFit)fit();schedule()});resize.observe(canvas);
 try{
  const g=await api('/api/graph?'+new URLSearchParams({full:true,backend}));if(!host.isConnected){dispose();return dispose}snapshot=g.snapshot;
  nodes=g.nodes.map((n,index)=>{const p=saved.positions.get(n.id),a=Math.random()*Math.PI*2,r=Math.sqrt(Math.random())*Math.sqrt(g.nodes.length)*8;return {...n,index,x:p?.x??Math.cos(a)*r,y:p?.y??Math.sin(a)*r,degree:0}});byid=new Map(nodes.map(n=>[n.id,n]));adj=new Map(nodes.map(n=>[n.id,new Set()]));
  edges=g.edges.map(e=>({...e,source:byid.get(e.source),target:byid.get(e.target)}));for(const e of edges){e.source.degree++;e.target.degree++;adj.get(e.source.id).add(e.target.id);adj.get(e.target.id).add(e.source.id)}
  canvas.dataset.nodes=nodes.length;canvas.dataset.edges=edges.length;rebuildTree();if(autoFit)fit();schedule();
  $('#g-status').textContent=`全部 ${nodes.length.toLocaleString()} 个对象 · ${edges.length.toLocaleString()} 条连接${g.invalid_edges?' · '+g.invalid_edges+' 条连接端点缺失':''}`;$('#g-status').title=`${g.isolated_nodes} 个对象尚未登记连接；显示已有真实关系。`;
  worker.postMessage({type:'init',nodes:nodes.map(({id,x,y,degree})=>({id,x,y,degree})),edges:g.edges.map(({source,target})=>({source,target}))});if(selected&&byid.has(selected))detail(selected);
 }catch(e){if(alive)$('#g-status').textContent='加载失败：'+e.message}
 function dispose(){alive=false;++request;worker.terminate();resize.disconnect();cancelAnimationFrame(frame);saved.transform={...transform};saved.positions=new Map(nodes.map(n=>[n.id,{x:n.x,y:n.y}]));}
 return dispose;
}

