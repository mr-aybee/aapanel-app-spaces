const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),path=require('path'),http=require('http');
(async()=>{
 const base=path.resolve(__dirname,'..');let metrics=0,inventory=0;const times=[],headers=[];
 const service={id:'api',name:'API',namespace:'demo',native:'demo.service',source:'demo.service',runtime:'systemd',state:'Running',endpoints:[],proxies:[],instances:[],capabilities:{lifecycle:false,config:false},cpu:null,memory:null,uptime:60};
 const server=http.createServer(async(req,res)=>{
  if(req.url.startsWith('/plugin?')){let body='';for await(const c of req)body+=c;const p=JSON.parse(new URLSearchParams(body).get('payload'));headers.push(req.headers['x-http-token']);if(req.headers['x-http-token']!=='fixture-token'){res.writeHead(403);return res.end('{}');}
   let data={};if(p.operation==='inventory'){inventory++;data={namespaces:[{slug:'demo',description:'Demo',environment:'Test'}],services:[service],warnings:[],at:new Date().toISOString()};}if(p.operation==='metrics'){times.push(Date.now());metrics++;data={services:[{id:'api',cpu:metrics,memory:104857600,status:'ok'}]};}if(p.operation==='bootstrap')data={csrf:'fixture-token'};res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({status:true,data}));
  }
  if(req.url.startsWith('/app-spaces')||req.url.startsWith('/static/app_spaces/index.html')){res.setHeader('Content-Type','text/html');return res.end(fs.readFileSync(path.join(base,'app_spaces/workspace.html')));}
  if(req.url.startsWith('/static/app_spaces/panel_shortcut.js')){res.setHeader('Content-Type','text/javascript');return res.end(fs.readFileSync(path.join(base,'app_spaces/panel_shortcut.js')));}
  res.setHeader('Content-Type','text/html');res.end('<!doctype html><body><a id="request_token_head" token="fixture-token"></a><main><button id="supervisor">Supervisor</button></main><script src="/static/app_spaces/panel_shortcut.js"></script></body>');
 });await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({headless:true,channel:process.env.BROWSER_CHANNEL||undefined});const context=await browser.newContext();const panel=await context.newPage();const errors=[];panel.on('pageerror',e=>errors.push(e.message));
 await panel.goto(origin);const shortcut=panel.locator('[data-app-spaces-shortcut]');await shortcut.waitFor();if(await shortcut.evaluate(e=>e.previousElementSibling.id)!=='supervisor')throw Error('Shortcut is not beside Supervisor');
 const popupPromise=context.waitForEvent('page');await shortcut.click();const child=await popupPromise;child.on('pageerror',e=>errors.push(e.message));await child.locator('[data-metric="api"]').waitFor();await child.waitForFunction(()=>document.querySelector('[data-metric="api"]').textContent.includes('100 MB'));
 if(!child.url().startsWith(origin+'/app-spaces'))throw Error('Not a separate tab');if(child.url().includes('token'))throw Error('Token exposed in URL');
 await child.evaluate(()=>{window.dispatchEvent(new MessageEvent('message',{origin:'https://attacker.invalid',source:window.opener,data:{type:'APP_SPACES_BOOTSTRAP',csrf:'bad'}}));window.dispatchEvent(new MessageEvent('message',{origin:location.origin,source:window,data:{type:'APP_SPACES_BOOTSTRAP',csrf:'bad'}}));});
 await child.waitForFunction(()=>document.querySelector('[data-metric="api"]').textContent.startsWith('2.0%'),null,{timeout:8000});if(inventory!==1)throw Error('Metrics rescanned inventory');if(times[1]-times[0]<4500||times[1]-times[0]>6500)throw Error('Not polling every5s');
 await child.reload();await child.locator('[data-open="api"]').first().waitFor();
 if(!child.url().endsWith('/app-spaces'))throw Error('Reload lost canonical workspace route');
 await child.goto(origin+'/static/app_spaces/index.html?v=0.3.0');await child.locator('[data-open="api"]').first().waitFor();if(!child.url().endsWith('/app-spaces'))throw Error('Legacy link was not canonicalized');
 if(await child.locator('.more svg circle').count()!==3)throw Error('Missing SVG action menu');if(await child.locator('.collapse svg').count()<2)throw Error('Missing SVG namespace controls');if(/[\u00c2\u00c3]|\u00e2[\u20ac\u2020\u2039]/.test(await child.locator('body').innerText()))throw Error('Corrupted UTF-8 glyphs');if(headers.some(x=>x!=='fixture-token'))throw Error('Token validation failed');
 await panel.evaluate(()=>{document.querySelector('main').innerHTML='<button id="supervisor">Supervisor</button>';});await shortcut.waitFor();if(await shortcut.count()!==1)throw Error('Duplicate shortcuts after navigation');
 if(errors.length)throw Error(errors.join('\n'));console.log('PASS: Proxy Project shortcut, separate-tab auth, origin/source rejection, reload auth, native fetch, 5s independent metrics and no repeated inventory.');
 await browser.close();await new Promise(r=>server.close(r));
})().catch(e=>{console.error(e);process.exit(1)});
