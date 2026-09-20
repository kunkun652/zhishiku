import {AggregateRenderer,WorkerForceLayout,seedPosition,seedRadius,OrbitControls,Color} from './plugins/galaxy-view/galaxy-core.js';

export function mountGalaxy(host,{nodes,edges,onSelect,onOpen,onError,settings,selected,paths}){
 const radius=Math.max(80,seedRadius(nodes.length)*1.6),positions=new Float32Array(nodes.length*3);
 nodes.forEach((n,i)=>positions.set(seedPosition(n.id,radius),i*3));
 const data={nodes:nodes.map(n=>({...n,name:n.title,folderTop:n.type,inDegree:0,outDegree:0,fileSize:0,tags:[],unresolved:false,tag:false})),links:edges.map(e=>({source:e.source.index,target:e.target.index}))};
 const renderer=new AggregateRenderer(host,radius),layout=new WorkerForceLayout();
 const canvas=renderer.renderer.domElement;canvas.id='galaxy-canvas';canvas.tabIndex=0;canvas.setAttribute('aria-label','Galaxy View 三维知识图谱：左键旋转，右键平移，滚轮缩放，点击查看详情');
 canvas.dataset.nodes=nodes.length;canvas.dataset.edges=edges.length;
 renderer.setColorFn(n=>new Color(n.degree?['#71d9e8','#ae91ff','#f2c78a','#7fd1b1'][Math.abs([...n.type].reduce((s,c)=>s+c.charCodeAt(0),0))%4]:'#c4ccdf'));
 renderer.setData(data,positions);
 const controls=new OrbitControls(renderer.camera,canvas);controls.enableDamping=true;controls.autoRotateSpeed=.35;
 const tag=document.createElement('span');tag.className='galaxy-label';host.append(tag);
 let alive=true,frame=0,last=performance.now(),down=null,hover=-1,current=selected,width=1,height=1;
 function params(){return {charge:-settings.repel,linkDistance:settings.distance,linkStrength:1,centerPull:.025,flatten:settings.flatten,coreGravity:0,spiral:0,velocityDecay:.4}}
 function apply(){renderer.setNodeScale(settings.size);renderer.setLinkOpacity(settings.links);renderer.setBloomStrength(settings.bloom);renderer.setStarfieldEnabled(settings.stars);controls.autoRotate=settings.rotate&&!current;layout.updateParams(params())}
 function fit(){renderer.camera.position.set(radius*2,radius*1.2,radius*14);controls.target.set(0,0,0);controls.update()}
 function select(id){current=id;const index=nodes.findIndex(n=>n.id===id),near=new Set([index]);const chosen=[];data.links.forEach((e,i)=>{if(e.source===index||e.target===index){near.add(e.source);near.add(e.target);chosen.push(i)}else if(paths.has(edges[i].id))chosen.push(i)});renderer.setFocus(index<0?null:i=>near.has(i)?1:.25);renderer.setSelectedLinks(chosen,[]);controls.autoRotate=settings.rotate&&!id}
 function hit(e){const r=canvas.getBoundingClientRect();return renderer.pickNearest(e.clientX-r.left,e.clientY-r.top,width,height,10)}
 canvas.onpointerdown=e=>{down={x:e.clientX,y:e.clientY,button:e.button}};
 canvas.onpointerup=e=>{if(down?.button===0&&Math.hypot(e.clientX-down.x,e.clientY-down.y)<5){const i=hit(e);onSelect(i<0?null:nodes[i].id)}down=null};
 canvas.onpointercancel=()=>{down=null};
 canvas.onpointermove=e=>{if(!e.buttons){hover=hit(e);canvas.style.cursor=hover<0?'grab':'pointer'}};
 canvas.onpointerleave=()=>{hover=-1};canvas.ondblclick=e=>{const i=hit(e);if(i>=0)onOpen(nodes[i].id)};
 canvas.onkeydown=e=>{if(e.key==='Escape')onSelect(null);if(e.key.toLowerCase()==='f')fit()};
 canvas.addEventListener('webglcontextlost',lost);
 function lost(e){e.preventDefault();onError('三维显示上下文丢失，可在设置中切回二维图谱。')}
 const resize=new ResizeObserver(()=>{width=host.clientWidth;height=host.clientHeight;renderer.resize(width,height)});resize.observe(host);
 function draw(now){if(!alive)return;const dt=Math.min((now-last)/1000,.05);last=now;if(layout.step())renderer.updatePositions();controls.update(dt);renderer.render(dt);const i=hover>=0?hover:nodes.findIndex(n=>n.id===current);tag.hidden=i<0;if(i>=0){const p=renderer.projectNode(i,width,height);tag.hidden=p.behind;tag.textContent=nodes[i].title;tag.style.left=p.x+'px';tag.style.top=p.y+'px'}frame=requestAnimationFrame(draw)}
 layout.init(data,positions,params());apply();fit();select(selected);frame=requestAnimationFrame(draw);
 return {apply,select,fit,dispose(){alive=false;cancelAnimationFrame(frame);resize.disconnect();controls.dispose();layout.dispose();canvas.removeEventListener('webglcontextlost',lost);renderer.dispose();canvas.remove();tag.remove()}};
}
