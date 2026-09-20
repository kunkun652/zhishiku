// First clone the pinned upstream into artifacts/galaxy-view-upstream and run npm ci there.
import path from 'node:path';
import fs from 'node:fs';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';
const here=path.dirname(fileURLToPath(import.meta.url));
const upstream=path.resolve(here,'../../artifacts/galaxy-view-upstream');
const revision='b49b60cb04687783153f24ff7f9b0a0af59334af';
if(execFileSync('git',['-C',upstream,'rev-parse','HEAD'],{encoding:'utf8'}).trim()!==revision)throw Error('Unexpected Galaxy View revision');
const {build}=await import(pathToFileURL(path.join(upstream,'node_modules/esbuild/lib/main.js')).href);
const out=path.resolve(here,'../src/static/plugins/galaxy-view');
fs.mkdirSync(out,{recursive:true});
await build({entryPoints:[path.join(here,'entry.js')],bundle:true,format:'esm',target:'es2021',minify:true,
 outfile:path.join(out,'galaxy-core.js'),nodePaths:[path.join(upstream,'node_modules')],
 alias:{'galaxy-source':path.join(upstream,'src')},legalComments:'eof',plugins:[{
 name:'inline-worker',setup(b){
  b.onResolve({filter:/^worker:/},a=>({path:path.resolve(path.dirname(a.importer),a.path.slice(7)),namespace:'inline-worker'}));
  b.onLoad({filter:/.*/,namespace:'inline-worker'},async a=>{const r=await build({entryPoints:[a.path],bundle:true,write:false,format:'iife',target:'es2021',minify:true});return {contents:r.outputFiles[0].text,loader:'text'}});
 }}]});
for(const [name,file] of [['Galaxy-View',path.join(upstream,'LICENSE')],['Three',path.join(upstream,'node_modules/three/LICENSE')],...['d3-force-3d','d3-dispatch','d3-timer','d3-binarytree','d3-quadtree','d3-octree'].map(n=>[n,path.join(upstream,'node_modules',n,'LICENSE')])])fs.copyFileSync(file,path.join(out,name+'-LICENSE.txt'));
console.log('Galaxy View core built from '+revision);
