import * as THREE from 'three';
import {OrbitControls} from '/static/vendor/three/OrbitControls.js';

export function mountViewer(host, asset) {
  host.innerHTML = `<div class="viewer-tools"><button data-action="fit">适应窗口</button><button data-action="solid">实体</button><button data-action="wire">实体＋网格</button><button data-action="lines">线框</button><span>左键旋转 · 右键平移 · 滚轮缩放</span></div><div class="viewer-stage"></div><div class="viewer-status">正在读取模型…</div>`;
  const stage = host.querySelector('.viewer-stage'), status = host.querySelector('.viewer-status');
  const renderer = new THREE.WebGLRenderer({antialias:true, alpha:false});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setClearColor(0xf1f5f9);
  stage.appendChild(renderer.domElement);
  const scene = new THREE.Scene(), root = new THREE.Group();
  const camera = new THREE.PerspectiveCamera(40, 1, 0.01, 100000);
  camera.up.set(0,0,1);
  const controls = new OrbitControls(camera, renderer.domElement);
  scene.add(root, new THREE.HemisphereLight(0xffffff, 0x64748b, 2.5));
  const light = new THREE.DirectionalLight(0xffffff, 2.5); light.position.set(1,2,3); scene.add(light);
  let disposed = false, worker, extent = 1, radius = 1;
  const abort = new AbortController(), solids = [], lines = [];
  const render = () => { if (!disposed) renderer.render(scene,camera); };
  controls.addEventListener('change', render);
  function resize() {
    const w=stage.clientWidth, h=stage.clientHeight;
    if (!w || !h || disposed) return;
    renderer.setSize(w,h); camera.aspect=w/h; camera.updateProjectionMatrix(); render();
  }
  const observer = new ResizeObserver(resize); observer.observe(stage);
  function fit() {
    const halfFov=Math.atan(Math.tan(THREE.MathUtils.degToRad(camera.fov/2))*Math.min(1,camera.aspect));
    const distance=radius*1.05/Math.sin(halfFov);
    camera.position.copy(new THREE.Vector3(1,-1.2,0.85).normalize().multiplyScalar(distance));
    camera.near=Math.max(extent/10000,1e-6); camera.far=extent*100;
    camera.updateProjectionMatrix(); controls.target.set(0,0,0); controls.update(); render();
  }
  function addGeometry(positions, indices, color, edges) {
    const g=new THREE.BufferGeometry();
    g.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));
    if (indices?.length) {
      g.setIndex(indices); g.computeVertexNormals();
      const mesh=new THREE.Mesh(g,new THREE.MeshStandardMaterial({color,side:THREE.DoubleSide,roughness:0.72,metalness:0.12,polygonOffset:true,polygonOffsetFactor:1,polygonOffsetUnits:1}));
      root.add(mesh); solids.push(mesh);
    } else {
      const points=new THREE.Points(g,new THREE.PointsMaterial({color,size:2,sizeAttenuation:false})); root.add(points); solids.push(points);
    }
    let eg;
    if (edges?.length) { eg=new THREE.BufferGeometry();eg.setAttribute('position',g.getAttribute('position').clone());eg.setIndex(edges); }
    else if(indices?.length) eg=new THREE.EdgesGeometry(g,25);
    if(eg){const line=new THREE.LineSegments(eg,new THREE.LineBasicMaterial({color:0x334155,transparent:true,opacity:0.65}));root.add(line);lines.push(line);}
  }
  function finish(message) {
    if (disposed) return;
    const box=new THREE.Box3().setFromObject(root), size=box.getSize(new THREE.Vector3());
    if(box.isEmpty()) throw new Error('模型没有可显示的几何');
    root.position.sub(box.getCenter(new THREE.Vector3())); extent=Math.max(size.x,size.y,size.z,0.001);radius=Math.max(size.length()/2,0.001);
    scene.add(new THREE.AxesHelper(extent*0.18)); resize(); fit(); status.textContent=message;
  }
  host.querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>{
    if(b.dataset.action==='fit') return fit();
    solids.forEach(x=>x.visible=b.dataset.action!=='lines');lines.forEach(x=>x.visible=b.dataset.action!=='solid');render();
  });
  async function load() {
    const fmt=asset.format.toLowerCase(), url='/api/model-assets/'+encodeURIComponent(asset.asset_id);
    if(['step','stp','iges','igs','brep'].includes(fmt)) {
      worker=new Worker('/static/cad-worker.js');
      worker.onerror=e=>{status.textContent='CAD 解析失败：'+e.message;worker.terminate();};
      worker.onmessage=({data})=>{
        if(disposed)return;
        if(data.progress){status.textContent=data.progress;return;}
        if(data.error){status.textContent=data.error;worker.terminate();return;}
        try {
          let triangles=0;
          for(const m of data.result.meshes){triangles+=m.index.array.length/3;addGeometry(m.attributes.position.array,m.index.array,m.color?new THREE.Color(...m.color):0x83a7c9);}
          finish(`${data.result.meshes.length} 个曲面网格 · ${triangles.toLocaleString()} 个显示三角形 · ${fmt==='brep'?'BREP 单位待确认':'CAD 显示坐标转换为 mm'} · 仅几何预览`);
        }catch(e){status.textContent='显示失败：'+e.message;}
        worker.terminate();
      };
      worker.postMessage({url:url+'/file',format:fmt});
    } else {
      const r=await fetch(url+'/mesh',{signal:abort.signal}); const data=await r.json();
      if(!r.ok)throw new Error(data.detail||'网格读取失败');
      if(disposed)return;
      addGeometry(data.positions,data.triangles,0x83a7c9,data.edges);
      finish(`${data.node_count.toLocaleString()} 节点 · ${data.element_count.toLocaleString()} 单元 · ${data.units}。${data.warnings.join(' ')}`);
    }
  }
  load().catch(e=>{if(!disposed)status.textContent=e.message;});
  return ()=>{disposed=true;abort.abort();worker?.terminate();observer.disconnect();controls.dispose();scene.traverse(x=>{x.geometry?.dispose();if(x.material)for(const m of [].concat(x.material))m.dispose();});renderer.dispose();renderer.forceContextLoss();};
}
