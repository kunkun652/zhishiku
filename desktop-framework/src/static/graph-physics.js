/* Force calculations stay off the UI thread, also while a node is selected. */
importScripts('/static/vendor/d3/d3.min.js');
let simulation,nodes=[],timer;
function chargeGroup(connected,strength){
 const force=d3.forceManyBody().strength(strength).theta(.8);
 const tick=alpha=>force(alpha);
 tick.initialize=(all,random)=>force.initialize(all.filter(n=>Boolean(n.degree)===connected),random);
 return tick;
}
function publish(){const positions=new Float32Array(nodes.length*2);nodes.forEach((n,i)=>{positions[i*2]=n.x;positions[i*2+1]=n.y});postMessage(positions,[positions.buffer])}
onmessage=({data})=>{
 if(data.type==='init'){
  clearInterval(timer);simulation?.stop();nodes=data.nodes;nodes.forEach(n=>{n.anchorX=n.x;n.anchorY=n.y});
  simulation=d3.forceSimulation(nodes).stop().alphaDecay(.035).alphaTarget(.025).velocityDecay(.36)
   .force('connected-charge',chargeGroup(true,-35))
   .force('orphan-charge',chargeGroup(false,-3))
   .force('link',d3.forceLink(data.edges).id(n=>n.id).distance(150))
   .force('x',d3.forceX(n=>n.degree?0:n.anchorX).strength(n=>n.degree?.035:.03))
   .force('y',d3.forceY(n=>n.degree?0:n.anchorY).strength(n=>n.degree?.035:.03))
   .force('collide',d3.forceCollide(n=>n.degree?12:0).iterations(1));
  publish();timer=setInterval(()=>{simulation.tick();publish()},40);
 }else if(data.type==='pause'){clearInterval(timer);timer=null;
 }else if(data.type==='resume'){if(!timer&&simulation)timer=setInterval(()=>{simulation.tick();publish()},40);
 }else if(data.type==='drag'){
  const n=nodes[data.index];n.fx=data.x;n.fy=data.y;n.x=data.x;n.y=data.y;simulation.alpha(Math.max(simulation.alpha(),.18));publish();
 }else if(data.type==='release'){
  nodes[data.index].fx=null;nodes[data.index].fy=null;simulation.alpha(Math.max(simulation.alpha(),.18));
 }else if(data.type==='wake')simulation.alpha(Math.max(simulation.alpha(),.12));
};
