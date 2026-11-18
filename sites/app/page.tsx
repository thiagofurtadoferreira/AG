"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type Platform = "instagram"|"facebook"|"youtube";
type Preview = {url:string;title?:string;thumbnail:string;platform:Platform;verified?:boolean};
type Job = {id:string;platform:Platform};
type State = {status:string;message:string;progress:number;platform:Platform};
const ORIGIN="https://reeldrop-instagram.onrender.com";
const YOUTUBE_ID=/^[A-Za-z0-9_-]{11}$/;
const allowed=new Set([
"instagram.com","www.instagram.com","m.instagram.com",
"facebook.com","www.facebook.com","m.facebook.com","web.facebook.com",
"fb.watch","www.fb.watch",
"youtube.com","www.youtube.com","m.youtube.com","music.youtube.com","youtu.be","www.youtu.be"]);

function identify(raw:string):{platform:Platform;url:string;code?:string}|null{
  try{
    const u=new URL(raw.trim());
    if(u.protocol!=="https:"||!allowed.has(u.hostname.toLowerCase())||u.port||u.username||u.password)return null;
    const h=u.hostname.toLowerCase();
    if(h.includes("instagram"))return {platform:"instagram",url:raw.trim()};
    if(h.includes("facebook")||h.includes("fb.watch"))return {platform:"facebook",url:raw.trim()};
    let code="";
    if(h==="youtu.be"||h==="www.youtu.be")code=u.pathname.slice(1).replace(/\/$/,"");
    else if(u.pathname==="/watch")code=u.searchParams.get("v")||"";
    else code=u.pathname.match(/^\/(?:shorts|live|embed)\/([A-Za-z0-9_-]{11})\/?$/)?.[1]||"";
    return YOUTUBE_ID.test(code)?{platform:"youtube",url:raw.trim(),code}:null;
  }catch{return null;}
}

async function json<T>(response:Response):Promise<T>{
  let body:unknown={};
  try{body=await response.json();}catch{/* may be temporarily unavailable */}
  if(!response.ok)throw new Error(typeof (body as {detail?:unknown})?.detail==="string" ? (body as {detail:string}).detail : "O servidor não conseguiu processar a solicitação.");
  return body as T;
}
const sleep=(ms:number)=>new Promise<void>(resolve=>setTimeout(resolve,ms));

export default function Page(){
  const [url,setUrl]=useState("");
  const [preview,setPreview]=useState<Preview|null>(null);
  const [notice,setNotice]=useState("");
  const [phase,setPhase]=useState("");
  const [percent,setPercent]=useState(0);
  const [busy,setBusy]=useState(false);
  const [fileUrl,setFileUrl]=useState<string|null>(null);
  const abort=useRef<AbortController|null>(null);
  const parsed=useMemo(()=>identify(url),[url]);
  const shareUrl=preview?.url||parsed?.url||"";

  useEffect(()=>{
    abort.current?.abort();
    const controller=new AbortController();
    abort.current=controller;
    setPreview(null);
    setFileUrl(null);
    if(!parsed || busy)return ()=>controller.abort();
    if(parsed.platform==="youtube" && parsed.code){
      setPreview({
        url:parsed.url,platform:"youtube",title:"Vídeo do YouTube",
        thumbnail:"https://i.ytimg.com/vi/"+parsed.code+"/hqdefault.jpg",verified:false
      });
    }
    const timer=setTimeout(async()=>{
      setNotice("Consultando a capa do vídeo...");
      try{
        const p=await json<Preview>(await fetch("/api/preview",{
          method:"POST",headers:{"content-type":"application/json"},
          body:JSON.stringify({url:parsed.url}),signal:controller.signal
        }));
        if(!controller.signal.aborted){setPreview(p);setNotice("");}
      }catch(e){
        if(!controller.signal.aborted)setNotice(
          parsed.platform==="youtube"?"Capa exibida. O vídeo pode estar bloqueado para download.":"Prévia indisponível; você ainda pode tentar baixar."
        );
      }
    },550);
    return ()=>{clearTimeout(timer);controller.abort();};
  },[url,parsed?.platform,parsed?.url,parsed?.code,busy]);

  async function onPaste(){
    try{
      const content=await navigator.clipboard.readText();
      setUrl(content.trim());
      setNotice("");
    }catch{
      setNotice("Não foi possível acessar a área de transferência. Cole manualmente.");
    }
  }
  async function onCopy(){
    try{await navigator.clipboard.writeText(shareUrl);setNotice("Link copiado!");}
    catch{setNotice("Não foi possível copiar automaticamente.");}
  }
  async function onShare(){
    if(!shareUrl)return;
    try{
      if(navigator.share)await navigator.share({title:preview?.title||"Vídeo",url:shareUrl,text:"Veja este vídeo"});
      else await onCopy();
    }catch(e){if((e as Error)?.name!=="AbortError")setNotice("Compartilhamento indisponível neste navegador.");}
  }
  async function download(event:React.FormEvent){
    event.preventDefault();
    if(!parsed){setNotice("Cole um link de vídeo válido.");return;}
    setBusy(true);setPhase("Iniciando processamento...");setPercent(0);setNotice("");setFileUrl(null);
    try{
      const job=await json<Job>(await fetch("/api/download",{
        method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({url:parsed.url})
      }));
      let finished=false;
      for(let attempt=0;attempt<95;attempt++){
        const result=await json<State>(await fetch("/api/download/"+job.id,{cache:"no-store"}));
        setPhase(result.message||"Processando mídia");
        setPercent(result.progress||0);
        if(result.status==="error")throw new Error(result.message||"Não foi possível baixar.");
        if(result.status==="ready"){finished=true;break;}
        await sleep(2000);
      }
      if(!finished)throw new Error("O processamento ultrapassou o tempo limite.");
      const file=ORIGIN+"/api/file/"+job.id;
      setFileUrl(file);
      setPhase("Arquivo pronto. Se não iniciar, toque em 'Salvar MP4'.");
      setPercent(100);
      const anchor=document.createElement("a");
      anchor.href=file;anchor.rel="noopener";anchor.style.display="none";
      document.body.appendChild(anchor);anchor.click();anchor.remove();
    }catch(e){setNotice((e as Error).message||"Falha inesperada.");setPhase("");}
    finally{setBusy(false);}
  }

  const names:Record<Platform,string>={instagram:"Instagram",facebook:"Facebook",youtube:"YouTube"};
  return <main className="layout">
    <header className="logo"><span className="mark">▶</span>Reel<span>Drop</span></header>
    <div className="eyebrow">INSTAGRAM · FACEBOOK · YOUTUBE</div>
    <h1>Seu vídeo favorito, <strong>em um clique.</strong></h1>
    <p className="intro">Cole o link de um vídeo público. Veja a capa e baixe um MP4 quando a plataforma permitir o acesso.</p>
    <section className="card">
      <form onSubmit={download}>
        <label htmlFor="link">Link do vídeo</label>
        <div className="inputrow">
          <input id="link" type="url" value={url} onChange={e=>setUrl(e.target.value)}
                 placeholder="Cole o link do Instagram, Facebook ou YouTube" required readOnly={busy}/>
          <button type="button" onClick={onPaste} disabled={busy} className="paste">Colar link</button>
        </div>
        <div className="detected">{parsed ? "✓ "+names[parsed.platform]+" detectado" : "Instagram, Facebook e YouTube"}</div>
        {preview && <div className="preview">
          <img src={preview.thumbnail} alt={"Capa: "+(preview.title||"Vídeo")} referrerPolicy="no-referrer"/>
          <div className="detail">
            <b>{preview.title||"Vídeo detectado"}</b>
            <small>{names[preview.platform]}</small>
            {preview.verified===false && <small className="note">Capa não confirma que o vídeo pode ser baixado.</small>}
          </div>
        </div>}
        {shareUrl && <div className="actions">
          <a href={"https://wa.me/?text="+encodeURIComponent("Veja este vídeo: "+shareUrl)}
             target="_blank" rel="noopener noreferrer" className="whatsapp">Compartilhar no WhatsApp</a>
          <button type="button" onClick={onShare}>Compartilhar</button>
          <button type="button" onClick={onCopy}>Copiar link</button>
        </div>}
        <button className="primary" disabled={!parsed||busy} type="submit">
          {busy?"Processando vídeo...":"↓ Baixar vídeo"}
        </button>
      </form>
      {phase && <div className="status" role="status">
        <div>{phase}</div><div className="track"><div style={{width:percent+"%"}}/></div>
        <small>{percent>0?percent+"%": "Preparando download..."}</small>
      </div>}
      {notice && <div className="notice" role="status">{notice}</div>}
      {fileUrl && <a className="filelink" href={fileUrl}>Salvar MP4</a>}
    </section>
    <footer>Use apenas vídeos próprios ou autorizados. Este serviço não contorna login, DRM ou bloqueios de acesso.
      <p>Alguns vídeos do YouTube não podem ser baixados nesta hospedagem devido a erros 403/429.</p>
      <a href={ORIGIN} target="_blank" rel="noopener noreferrer">Versão original no Render</a>
    </footer>
  </main>;
}
