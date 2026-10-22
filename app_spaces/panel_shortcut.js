/* Small aaPanel navigation hook. No polling or framework/bundle patching. */
(function(){
  'use strict';
  if(window.__appSpacesShortcut)return;window.__appSpacesShortcut=true;
  let scheduled=false;
  function open(){
    const child=window.open('/app-spaces','aaPanel-App-Spaces');
    if(!child)return;
    const token=document.querySelector('#request_token_head')?.getAttribute('token');
    if(token){
      try{if(child.location.origin===location.origin||child.location.href==='about:blank')child.sessionStorage.setItem('app-spaces-csrf',token);}catch(e){}
      const send=e=>{if(e.origin===location.origin&&e.source===child&&e.data?.type==='APP_SPACES_READY'){child.postMessage({type:'APP_SPACES_BOOTSTRAP',csrf:token},location.origin);window.removeEventListener('message',send);}};
      window.addEventListener('message',send);setTimeout(()=>window.removeEventListener('message',send),15000);
      child.postMessage({type:'APP_SPACES_BOOTSTRAP',csrf:token},location.origin);
    }
  }
  function mount(){
    scheduled=false;
    // Scope to the exact Supervisor control, never container links or table cells.
    for(const supervisor of document.querySelectorAll('button,[role="button"]')){
      if(supervisor.textContent.trim()!=='Supervisor'||supervisor.closest('dialog,.layui-layer'))continue;
      if(supervisor.parentElement.querySelector('[data-app-spaces-shortcut]'))continue;
      const button=document.createElement('button');button.type='button';button.dataset.appSpacesShortcut='true';
      button.textContent='App Spaces ↗';button.title='Manage systemd and Docker services in a new tab';
      button.className=supervisor.className;button.style.cssText='margin-left:8px;padding:0 12px;min-height:32px;border:1px solid #3b4149;border-radius:4px;background:transparent;color:#20a6dc;cursor:pointer;font:inherit';
      button.onclick=open;supervisor.after(button);
    }
  }
  const observer=new MutationObserver(records=>{if(!scheduled&&records.some(r=>r.addedNodes.length)){scheduled=true;requestAnimationFrame(mount);}});
  observer.observe(document.body,{childList:true,subtree:true});mount();
}());
