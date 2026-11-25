const textBox=document.querySelector('#text'),count=document.querySelector('#count'),button=document.querySelector('#generate'),message=document.querySelector('#message'),player=document.querySelector('#player'),playerWrap=document.querySelector('#playerWrap'),download=document.querySelector('#download');
const apiKey=document.querySelector('#apikey');try{apiKey.value=localStorage.getItem('resham_key')||''}catch{}
apiKey.addEventListener('input',()=>{try{localStorage.setItem('resham_key',apiKey.value.trim())}catch{}});
textBox.addEventListener('input',()=>count.textContent=`${textBox.value.length} / 3000`);
button.addEventListener('click',async()=>{
  const text=textBox.value.trim(); if(!text){message.textContent='Please enter some text first.';textBox.focus();return;}
  button.disabled=true;button.textContent='Generating…';message.textContent='Generating speech. First request can download the model (large files), please wait.';playerWrap.classList.add('hidden');
  try{
    // No API key needed here: the server allows requests from its own web page.
    const response=await fetch('/v1/audio/speech',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text,language:document.querySelector('#language').value,length_scale:Number(document.querySelector('#speed').value)})});
    if(!response.ok){let detail='Voice generation failed';try{const data=await response.json();detail=data.detail||detail}catch{}throw new Error(detail)}
    const blob=await response.blob(),url=URL.createObjectURL(blob);player.src=url;download.href=url;download.download=`resham-${document.querySelector('#language').value}.wav`;playerWrap.classList.remove('hidden');message.textContent='Your voice is ready.';player.play().catch(()=>{});
  }catch(error){message.textContent=error.message+' — Check server logs and model download.'}
  finally{button.disabled=false;button.innerHTML='Generate voice <span>→</span>'}
});

// ---- API key management (admin key required) ----
const keyName=document.querySelector('#keyname'),genKey=document.querySelector('#genkey'),keyMsg=document.querySelector('#keymsg'),newKey=document.querySelector('#newkey'),keyList=document.querySelector('#keylist');
const adminFetch=async(path,opts={})=>{const r=await fetch(path,{...opts,headers:{'Content-Type':'application/json','X-API-Key':apiKey.value.trim()}});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(r.status===401?'Wrong or missing admin key':(d.detail||'Request failed'));return d};
async function loadKeys(){try{const list=await adminFetch('/v1/keys');keyList.innerHTML='';list.forEach(k=>{const row=document.createElement('div');const t=document.createElement('span');t.innerHTML=`<b></b> · ${k.key}${k.admin?' · admin':''}`;t.querySelector('b').textContent=k.name;row.appendChild(t);if(!k.admin){const b=document.createElement('button');b.type='button';b.textContent='Revoke';b.onclick=async()=>{try{await adminFetch('/v1/keys/'+k.id,{method:'DELETE'});loadKeys()}catch(e){keyMsg.textContent=e.message}};row.appendChild(b)}keyList.appendChild(row)});keyMsg.textContent=''}catch(e){keyList.innerHTML='';keyMsg.textContent=e.message}}
genKey.addEventListener('click',async()=>{try{const k=await adminFetch('/v1/keys',{method:'POST',body:JSON.stringify({name:keyName.value.trim()||'Other app'})});newKey.textContent=k.key;newKey.classList.remove('hidden');keyMsg.textContent='Copy this key now — it will not be shown again.';keyName.value='';loadKeys()}catch(e){keyMsg.textContent=e.message}});
apiKey.addEventListener('change',loadKeys);if(apiKey.value)loadKeys();