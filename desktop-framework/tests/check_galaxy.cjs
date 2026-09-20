// Run from repository root after installing playwright in artifacts/graph-tests.
const {chromium}=require('../../artifacts/graph-tests/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const runtime=JSON.parse(fs.readFileSync(process.argv[2]||'desktop-framework/evidence/galaxy-test-data/runtime.json'));
 const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true,args:['--enable-unsafe-swiftshader']});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:940}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=400&&!r.url().endsWith('/favicon.ico'))errors.push(r.status()+' '+r.url())});
 await page.goto(runtime.url+'/#graph');await page.waitForSelector('#galaxy-canvas');await page.waitForTimeout(2500);
 assert.equal(await page.locator('main>header').isVisible(),false);
 assert.equal(await page.locator('.graph-settings').getAttribute('open'),null);
 const box=await page.locator('#galaxy-canvas').boundingBox();assert.equal(box.y,0);assert.equal(box.height,940);
 await page.locator('.graph-settings>summary').click();await page.locator('[data-setting=rotate]').uncheck();await page.locator('.graph-settings>summary').click();
 // Hit a real rendered node in the dense center, not a fabricated DOM node.
 for(let dx=-12;dx<=12;dx+=6){await page.mouse.click(box.x+box.width/2+dx,box.height/2);await page.waitForTimeout(150);if(await page.locator('#g-detail h2').count())break}
 await page.waitForSelector('#g-detail h2');const title=await page.locator('#g-detail h2').textContent();
 const original=await page.locator('#g-detail').innerHTML();await page.screenshot({path:'desktop-framework/evidence/galaxy-detail.png'});
 await page.locator('.graph-settings>summary').click();await page.locator('[data-setting=enabled]').uncheck();await page.waitForSelector('#graph-canvas',{state:'visible'});assert.equal(await page.locator('#g-detail').innerHTML(),original);
 await page.locator('[data-setting=enabled]').check();await page.waitForSelector('#galaxy-canvas');assert.equal(await page.locator('#g-detail').innerHTML(),original);
 for(const [key,value] of [['size','1.6'],['links','0.5'],['bloom','0.8'],['repel','60'],['distance','90'],['flatten','0.2']]){
 await page.locator(`[data-setting=${key}]`).fill(value);assert.equal(await page.locator(`[data-value=${key}]`).textContent(),value);
 }
 await page.locator('[data-setting=stars]').uncheck();await page.locator('#g-fit').click();assert.equal(await page.locator('#g-detail').innerHTML(),original);
 await page.reload();await page.waitForSelector('#galaxy-canvas');await page.locator('.graph-settings>summary').click();assert.equal(await page.locator('[data-setting=size]').inputValue(),'1.6');assert.equal(await page.locator('[data-setting=stars]').isChecked(),false);
 await page.locator('#g-reset').click();assert.equal(await page.locator('[data-setting=size]').inputValue(),'1');await page.locator('.graph-settings>summary').click();
 await page.locator('[data-go=home]').first().click();await page.waitForSelector('.hero');await page.waitForTimeout(200);assert.equal(page.workers().length,0);
 await page.locator('[data-go=graph]').first().click();await page.waitForSelector('#galaxy-canvas');await page.waitForTimeout(2000);await page.screenshot({path:'desktop-framework/evidence/galaxy-full.png'});
 assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,nodes:await page.locator('#galaxy-canvas').getAttribute('data-nodes'),detailTitle:title,checks:['full pane','folded settings','real node click','unchanged details across 2D/3D','all sliders','persistent preferences','reset','worker cleanup','reentry','no script/resource errors']}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
