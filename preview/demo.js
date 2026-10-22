/* Explicit standalone fixtures. This file is excluded from the installed plugin. */

window.APP_SPACES_DEMO = true;

(function () {

  const namespaces=[{slug:'orbyn-production',description:'Orbyn Web',environment:'Production'},{slug:'shared-infrastructure',description:'Shared platform services',environment:'Shared'},{slug:'genie-staging',description:'Genie preview',environment:'Staging'}];

  const base=(id,namespace,name,runtime,source,port,domain,state='Running')=>({id,namespace,name,runtime,source,native:runtime==='systemd'?source:'compose:demo/'+name,state,endpoints:port?[{host:'127.0.0.1',port,protocol:'tcp',...(runtime==='docker'?{container_port:8080}:{})}]:[],cpu:null,memory:runtime==='systemd'?186*1048576:null,uptime:12*86400,instances:runtime==='docker'?[{id:'a'.repeat(64),name,state,health:'healthy'}]:[],capabilities:{lifecycle:true,config:runtime==='systemd'},config_supported:runtime==='systemd',proxies:domain?[{project:domain,domains:[domain],location:'/',target:'http://127.0.0.1:'+port,file:domain+'.conf',confidence:'inferred-local-port',origin:'nginx-config'}]:[]});

  const services=[base('1','orbyn-production','orbyn-api','systemd','web-orbynweb-api.service',9810,'api.orbyntech.com'),base('2','orbyn-production','orbyn-portal','systemd','web-orbynweb-portal.service',9811,'orbyntech.com'),base('3','orbyn-production','orbyn-admin','systemd','web-orbynweb-admin.service',9812,'admin.orbyntech.com'),base('4','shared-infrastructure','object-storage','docker','rustfs/rustfs:latest',7000,'s3.example.net'),base('5','shared-infrastructure','seq','docker','datalust/seq:2026.1',9091,'seq.example.net'),base('6','shared-infrastructure','redis','systemd','redis-server.service',6379,''),base('7','genie-staging','genie-api','docker','ghcr.io/orbyn/genie-api:preview',9820,'preview-api.example.com','Failed'),base('8','genie-staging','genie-worker','systemd','web-genie-worker.service',null,'','Stopped')];

  const audit=[], config={}; let nextId=20;let pendingCreation=null;

  window.appSpacesDemoRequest=async(operation,p)=>{

    await new Promise(resolve=>setTimeout(resolve,60)); const s=services.find(x=>x.id===p.id);

    if(operation==='inventory')return structuredClone({namespaces,services,warnings:[],at:new Date().toISOString()});

    if(operation==='creation_preview'){

      const spec=p.spec;if(!spec.name||!spec.namespace)throw Error('Name and namespace are required.');

      if(spec.runtime==='systemd'&&(!spec.executable.startsWith('/')||!spec.working_directory.startsWith('/')||!spec.user))throw Error('Provide absolute Linux paths and a Linux user.');

      if(spec.runtime==='docker'&&!spec.image)throw Error('Provide an image name/tag.');

      pendingCreation=structuredClone(spec);const native='appspaces-'+spec.namespace+'-'+spec.name;

      const env=Object.keys(spec.environment).map(k=>spec.runtime==='systemd'?'Environment="'+k+'=[hidden]"':'      '+k+': "[hidden]"').join('\n');

      return {token:'demo-creation',identity:spec.runtime==='systemd'?native+'.service':'compose:'+native+'/'+spec.name,note:'Local preview only: validation and creation are simulated. No server is contacted.',content:spec.runtime==='systemd'?'[Unit]\nDescription='+spec.description+'\nAfter=network-online.target\n\n[Service]\nUser='+spec.user+'\nWorkingDirectory='+spec.working_directory+'\nExecStart=:'+spec.executable+' '+spec.arguments.map(x=>JSON.stringify(x)).join(' ')+'\n'+env+'\nRestart='+spec.restart+'\n\n[Install]\nWantedBy=multi-user.target':'services:\n  '+spec.name+':\n    image: '+spec.image+'\n    restart: '+spec.restart+'\n    environment:\n'+env+'\n    ports:\n'+spec.ports.map(x=>'      - "'+x.host+':'+x.published+':'+x.target+'/'+x.protocol+'"').join('\n')+'\n    # Advanced options are validated by the real backend.'};

    }

    if(operation==='create_service'){

      if(!pendingCreation||p.token!=='demo-creation')throw Error('Preview has expired.');

      const spec=pendingCreation;pendingCreation=null;const native='appspaces-'+spec.namespace+'-'+spec.name;

      const item=base(String(nextId++),spec.namespace,spec.name,spec.runtime,spec.runtime==='systemd'?native+'.service':spec.image,spec.ports?.[0]?.published||null,'',p.start?'Running':spec.runtime==='docker'?'Defined':'Stopped');

      item.native=spec.runtime==='systemd'?native+'.service':'compose:'+native+'/'+spec.name;item.managed=true;item.capabilities={lifecycle:true,config:spec.runtime==='systemd'};services.push(item);

      audit.unshift({at:new Date().toISOString(),operation:'create_service',target:spec.name,outcome:'demo-only'});

      return {id:item.id,identity:item.native,created:true,started:!!p.start,state:item.state,path:'demo-only'};

    }

    if(operation==='metrics')return {services:services.map(s=>({id:s.id,cpu:s.cpu,memory:s.memory,status:'ok'})),at:Date.now()/1000,warnings:[]};

    if(operation==='discover')return {namespaces,services:[base('candidate','unassigned','service-desk','systemd','web-service-desk.service',9801,'')],warnings:['Local preview: discoveries and actions are fixtures.']};

    if(operation==='namespaces'){if(p.namespace_operation==='create'){if(namespaces.some(n=>n.slug===p.slug))throw Error('Namespace already exists');namespaces.push({slug:p.slug,description:p.description,environment:p.environment});}else{if(services.some(x=>x.namespace===p.slug))throw Error('Namespace is not empty');namespaces.splice(namespaces.findIndex(n=>n.slug===p.slug),1);}return namespaces;}

    if(operation==='register'){if(services.some(x=>x.native===p.native))throw Error('Already registered');const item=base(String(nextId++),p.namespace,p.label,p.runtime,p.native,9801,'');item.capabilities={lifecycle:p.lifecycle,config:p.config};services.push(item);return item;}

    if(operation==='move'){s.namespace=p.namespace;return {moved:true};}

    if(operation==='unregister'){if(p.confirmation!==s.name)throw Error('Label did not match');services.splice(services.indexOf(s),1);return {};}

    if(operation==='action'){if(!s.capabilities.lifecycle)throw Error('Lifecycle permission disabled');s.state=p.verb==='stop'?'Stopped':'Running';s.uptime=0;audit.unshift({at:new Date().toISOString(),operation:p.verb,target:s.name,outcome:'demo-only'});return {state:s.state};}

    if(operation==='logs')return {text:'2026-10-22T00:00:00Z  Application started\n2026-10-22T00:00:01Z  Ready for requests\n2026-10-22T00:01:00Z  GET /health 200',note:'Sample logs only; no live server connection.'};

    if(operation==='environment')return {instances:{[s.native]:[{key:'ASPNETCORE_ENVIRONMENT',value:p.reveal?'Production':'••••••'},{key:'EXAMPLE_SECRET',value:p.reveal?'demo-secret-only':'••••••'}]},note:'Fixture environment. Values are samples.'};

    if(operation==='configuration')return {path:'/etc/systemd/system/'+s.native,revision:'demo-revision',editable:!!p.reveal,content:p.reveal?(config[s.id]||'[Unit]\nDescription='+s.name+'\nAfter=network.target\n\n[Service]\nExecStart=/usr/bin/dotnet /srv/example/App.dll\nEnvironment="ASPNETCORE_ENVIRONMENT=Production"\nRestart=always\n\n[Install]\nWantedBy=multi-user.target\n'):'[Unit]\nDescription='+s.name+'\n\n[Service]\n[sensitive line hidden]',note:'Sample file. Preview applies only to this in-memory demo.'};

    if(operation==='preview'){config.pending=p.content;return {token:'demo-ticket',diff:'--- current\n+++ proposed\n'+p.content,notice:'Demo: no files will be changed on the server.'};}

    if(operation==='apply'){config[s.id]=config.pending;return {backup:'demo-only: no server file',state:'Running'};}

    if(operation==='audit')return audit;

    if(operation==='export')return {schema:1,namespaces,registrations:services.map(x=>({id:x.id,namespace:x.namespace,native:x.native,runtime:x.runtime}))};

    throw Error('Unsupported demo operation');

  };

}());

