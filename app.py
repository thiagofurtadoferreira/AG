import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

app = FastAPI(title="ReelDrop", docs_url=None, redoc_url=None)
lock = threading.RLock()
slots = threading.BoundedSemaphore(1)
jobs = {}
calls = defaultdict(deque)
BASE = Path(tempfile.mkdtemp(prefix="reeldrop-"))

SHORTCODE = re.compile(r"^/(reel|p|tv)/([A-Za-z0-9_-]{5,32})/?$")
FB_NUMERIC = re.compile(r"^[0-9]{5,25}$")
FB_TOKEN = re.compile(r"^[A-Za-z0-9_-]{5,100}$")
FB_REEL = re.compile(r"^/reel/([0-9]{5,25})/?$")
FB_VIDEO = re.compile(r"^/(?:[A-Za-z0-9._-]+/)?videos/([0-9]{5,25})/?$")
FB_SHARE = re.compile(r"^/share/(?:v|r)/([A-Za-z0-9_-]{5,100})/?$")
FB_WATCH_HOSTS = {"facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com"}
FB_SHORT_HOSTS = {"fb.watch", "www.fb.watch"}

class DownloadRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


def canonical(raw):
    """Allow only video-shaped URLs from supported social platforms.

    Do not forward arbitrary user-supplied URLs to the downloader.
    Tracking query strings are removed; a watch URL retains only numeric video IDs.
    """
    raw = raw.strip()
    try:
        u = urlsplit(raw)
        host = u.hostname
        if (u.scheme != "https" or u.username or u.password
                or u.port is not None
                or host not in {"instagram.com", "www.instagram.com", "m.instagram.com"} | FB_WATCH_HOSTS | FB_SHORT_HOSTS):
            raise ValueError()
    except ValueError:
        raise HTTPException(422, "Cole um link HTTPS válido do Instagram ou Facebook.")

    if host in {"instagram.com", "www.instagram.com", "m.instagram.com"}:
        m = SHORTCODE.fullmatch(u.path)
        if not m:
            raise HTTPException(422, "Para Instagram, use um link /reel/, /p/ ou /tv/.")
        return "https://www.instagram.com/" + m.group(1) + "/" + m.group(2) + "/", m.group(2), "instagram"

    if host in FB_SHORT_HOSTS:
        token = u.path.strip("/")
        if not FB_TOKEN.fullmatch(token):
            raise HTTPException(422, "Link curto do Facebook inválido.")
        return "https://fb.watch/" + token + "/", token, "facebook"

    m = FB_REEL.fullmatch(u.path)
    if m:
        return "https://www.facebook.com/reel/" + m.group(1) + "/", m.group(1), "facebook"

    m = FB_VIDEO.fullmatch(u.path)
    if m:
        return "https://www.facebook.com" + u.path.rstrip("/") + "/", m.group(1), "facebook"

    m = FB_SHARE.fullmatch(u.path)
    if m:
        return "https://www.facebook.com" + u.path.rstrip("/") + "/", m.group(1), "facebook"

    if u.path.rstrip("/") in ("/watch", "/video.php"):
        ids = parse_qs(u.query).get("v", [])
        if len(ids) == 1 and FB_NUMERIC.fullmatch(ids[0]):
            return "https://www.facebook.com/watch/?v=" + ids[0], ids[0], "facebook"

    raise HTTPException(422, "Link do Facebook não reconhecido. Use /reel/, /videos/, /watch/?v=, /share/v/, /share/r/ ou fb.watch.")

def setjob(jobid, **kwargs):
    with lock:
        if jobid in jobs:
            jobs[jobid].update(kwargs)
            jobs[jobid]["updated"] = time.time()

def cleanup(jobid):
    with lock:
        j = jobs.pop(jobid, None)
    if j:
        shutil.rmtree(j["folder"], ignore_errors=True)


def friendly(msg, platform):
    m = msg.lower()
    provider = "Facebook" if platform == "facebook" else "Instagram"
    if any(s in m for s in ("login", "cookies", "private", "sign in", "rate limit", "429", "cannot parse data", "no video formats found")):
        return f"O {provider} exigiu autenticação, bloqueou o acesso ou alterou a extração. Tente outro vídeo público ou mais tarde."
    if any(s in m for s in ("404", "not available", "unavailable", "not found")):
        return "Vídeo não encontrado ou indisponível publicamente."
    return f"Não foi possível baixar este vídeo. O {provider} pode ter restringido o acesso."

def worker(jobid, url, code, platform, folder):
    try:
        folder.mkdir(parents=True, exist_ok=True)
        setjob(jobid,status="downloading",message="Buscando a melhor qualidade disponível...")
        cmd = [sys.executable,"-m","yt_dlp","--ignore-config","--no-playlist",
               "--no-cache-dir","--no-mtime","--no-write-thumbnail","--no-write-info-json",
               "--socket-timeout","20","--retries","2","--fragment-retries","2",
               "--max-filesize","400M","--format","bv*+ba/b",
               "--merge-output-format","mp4","--remux-video","mp4",
               "-o",str(folder / (platform + "_" + code + ".%(ext)s")),"--",url]
        p = subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                           text=True,timeout=180,check=False)
        if p.returncode:
            raise RuntimeError(friendly(p.stdout[-2000:], platform))
        result = folder / (platform + "_" + code + ".mp4")
        if not result.exists() or not 0 < result.stat().st_size <= 400*1024*1024:
            raise RuntimeError("Não foi possível obter um arquivo MP4 válido.")
        setjob(jobid,status="ready",message="Vídeo pronto!",filename=result.name)
    except subprocess.TimeoutExpired:
        setjob(jobid,status="error",message="Tempo limite excedido. Tente novamente.")
    except Exception as e:
        setjob(jobid,status="error",message=str(e)[:300])
    finally:
        slots.release()

@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE

@app.get("/api/health")
def health():
    return {"status":"ok","service":"ReelDrop","version":"1.1.0","platforms":["instagram","facebook"]}

@app.post("/api/download",status_code=202)
def download(payload:DownloadRequest, request:Request):
    url,code,platform = canonical(payload.url)
    ip = request.client.host if request.client else "unknown"
    now=time.time()
    with lock:
        q=calls[ip]
        while q and q[0]<now-600:q.popleft()
        if len(q)>=10:raise HTTPException(429,"Muitas tentativas. Aguarde alguns minutos.")
        q.append(now)
        for jid,j in list(jobs.items()):
            if j["status"] in ("ready","error") and now-j["updated"]>1800:
                cleanup(jid)
    if not slots.acquire(blocking=False):
        raise HTTPException(429,"O servidor está ocupado. Tente novamente em instantes.")
    jobid=uuid.uuid4().hex
    folder=BASE/jobid
    with lock:
        jobs[jobid]={"status":"preparing","message":"Preparando download...","updated":now,"folder":folder,"platform":platform}
    threading.Thread(target=worker,args=(jobid,url,code,platform,folder),daemon=True).start()
    return {"id":jobid,"status":"preparing","platform":platform}

@app.get("/api/download/{jobid}")
def status(jobid:str):
    with lock:
        j=jobs.get(jobid)
        if not j:raise HTTPException(404,"Download não encontrado.")
        return {"status":j["status"],"message":j["message"],"platform":j["platform"]}

@app.get("/api/file/{jobid}")
def file(jobid:str):
    with lock:
        j=jobs.get(jobid)
        if not j or j["status"]!="ready":raise HTTPException(404,"Arquivo não está pronto.")
        f=j["folder"]/j["filename"]
    return FileResponse(f,filename=f.name,media_type="video/mp4",
                        background=BackgroundTask(cleanup,jobid),
                        headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})

PAGE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ReelDrop — Baixar vídeos do Instagram e Facebook</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;font:16px system-ui,-apple-system,Segoe UI,sans-serif;color:#fff;background:#0c1020;display:flex;align-items:center;justify-content:center;overflow-x:hidden}
body:before{content:"";position:fixed;inset:-30%;background:radial-gradient(ellipse at 25% 30%,#7935b943,transparent 40%),radial-gradient(ellipse at 85% 65%,#2562ce36,transparent 40%);pointer-events:none}
main{width:min(620px,calc(100% - 32px));padding:36px 0;position:relative;text-align:center}
.brand{display:inline-flex;align-items:center;gap:10px;font-size:27px;font-weight:850;letter-spacing:-1px}
.logo{width:38px;height:38px;display:grid;place-items:center;border-radius:12px;background:linear-gradient(135deg,#ae3de2,#ff4d92);font-size:21px}
.brand em{font-style:normal;color:#db83ff}
.kicker{margin:45px 0 12px;font-size:12px;font-weight:750;letter-spacing:2px;color:#c5a2ff}
h1{font-size:clamp(35px,7vw,54px);line-height:1.09;letter-spacing:-2px;margin:0 0 18px}
h1 span{background:linear-gradient(110deg,#fa88bb,#a892ff,#61b9ff);background-clip:text;color:transparent}
p{line-height:1.65;color:#abb4d1;margin:0 auto 28px;max-width:485px}
.card{text-align:left;background:#171b30e8;border:1px solid #3a3e60;border-radius:22px;padding:25px;box-shadow:0 18px 70px #0005}
label{display:block;font-weight:650;margin-bottom:11px;font-size:14px}
.field{display:flex;gap:8px;background:#101428;border:1px solid #4a4c70;border-radius:13px;padding:7px}
input{width:100%;min-width:0;flex:1;border:0;outline:0;background:transparent;color:#fff;padding:11px;font-size:14px}
input::placeholder{color:#7e839e}
button{border:0;cursor:pointer;font:inherit;font-weight:750}
#paste{white-space:nowrap;border-radius:9px;padding:0 12px;background:#303651;color:#fff;font-size:13px}
#go{width:100%;padding:16px;margin-top:15px;border-radius:12px;color:#fff;background:linear-gradient(100deg,#b14ce3,#ea4f9b);box-shadow:0 8px 26px #b34ce335;font-size:16px}
#go:disabled{opacity:.6;cursor:wait}
#status{font-size:14px;line-height:1.5;color:#e6c9ff;text-align:center;min-height:23px;margin-top:16px}
footer{font-size:12px;line-height:1.7;color:#8089a8;margin-top:26px}
a{color:#d7a1ff}
@media(max-width:400px){.card{padding:16px}#paste{padding:0 8px;font-size:12px}}
</style></head><body><main>
<div class="brand"><span class="logo">▶</span>Reel<em>Drop</em></div>
<div class="kicker">INSTAGRAM + FACEBOOK</div>
<h1>Seu vídeo favorito,<br><span>em um clique.</span></h1>
<p>Cole o link de um vídeo público do Instagram ou Facebook. O site identifica a plataforma e baixa o MP4 na melhor qualidade disponível.</p>
<div class="card"><form id="form"><label for="url">Link do vídeo</label>
<div class="field"><input id="url" type="url" required placeholder="Cole o link do Instagram ou Facebook" autocomplete="url">
<button id="paste" type="button">Colar link</button></div>
<div id="platform" style="margin:12px 0 0;text-align:center;color:#b3a6ef;font-size:13px" aria-live="polite">Instagram e Facebook</div>
<button id="go" type="submit">↓ &nbsp; Baixar vídeo</button></form>
<div id="status" role="status" aria-live="polite"></div></div>
<footer>Somente conteúdo público que você tem permissão para baixar.<br>Ferramenta independente, não afiliada ao Instagram ou Facebook.</footer>
</main><script>
const input=document.getElementById("url"),form=document.getElementById("form"),
btn=document.getElementById("go"),notice=document.getElementById("status"),platform=document.getElementById("platform");

function detect(){
let label="Cole um link do Instagram ou Facebook";
try{
const u=new URL(input.value.trim()),h=u.hostname.toLowerCase();
if(["instagram.com","www.instagram.com","m.instagram.com"].includes(h))label="✓ Instagram detectado";
else if(["facebook.com","www.facebook.com","m.facebook.com","web.facebook.com","fb.watch","www.fb.watch"].includes(h))label="✓ Facebook detectado";
else if(input.value.trim())label="Endereço não reconhecido";
}catch(e){}
platform.textContent=label;
}
input.addEventListener("input",detect);
document.getElementById("paste").onclick=async()=>{
try{input.value=await navigator.clipboard.readText();detect();input.focus()}catch(e){notice.textContent="Use Ctrl+V para colar o link.";input.focus()}};
const pause=ms=>new Promise(r=>setTimeout(r,ms));
form.onsubmit=async e=>{
e.preventDefault();btn.disabled=true;notice.textContent="Preparando o vídeo...";
try{
const response=await fetch("/api/download",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url:input.value.trim()})});
const job=await response.json();
if(!response.ok)throw Error(typeof job.detail==="string"?job.detail:"Não foi possível iniciar.");
let ready=false;
for(let i=0;i<95;i++){
await pause(2000);
const r=await fetch("/api/download/"+job.id);
const s=await r.json();
if(!r.ok)throw Error("Consulta de status falhou.");
notice.textContent=s.message;
if(s.status==="error")throw Error(s.message);
if(s.status==="ready"){ready=true;break;}
}
if(!ready)throw Error("O processamento demorou demais.");
notice.textContent="Transferindo seu MP4...";
const a=document.createElement("a");a.href="/api/file/"+job.id;a.download="";
document.body.appendChild(a);a.click();a.remove();
notice.textContent="Download iniciado! Confira os arquivos do navegador.";
}catch(err){notice.textContent=err.message||"Falha inesperada no download."}
finally{btn.disabled=false}
};
</script></body></html>"""
