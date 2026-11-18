import os
import json
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
preview_cache = {}
preview_slots = threading.BoundedSemaphore(2)
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
YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
YT_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
YT_PATH = re.compile(r"^/(shorts|live|embed)/([A-Za-z0-9_-]{11})/?$")

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
                or host not in {"instagram.com", "www.instagram.com", "m.instagram.com"} | FB_WATCH_HOSTS | FB_SHORT_HOSTS | YT_HOSTS | YT_SHORT_HOSTS):
            raise ValueError()
    except ValueError:
        raise HTTPException(422, "Cole um link HTTPS válido do Instagram, Facebook ou YouTube.")

    if host in {"instagram.com", "www.instagram.com", "m.instagram.com"}:
        m = SHORTCODE.fullmatch(u.path)
        if not m:
            raise HTTPException(422, "Para Instagram, use um link /reel/, /p/ ou /tv/.")
        return "https://www.instagram.com/" + m.group(1) + "/" + m.group(2) + "/", m.group(2), "instagram"

    if host in YT_SHORT_HOSTS:
        code = u.path.strip("/")
        if not YT_ID.fullmatch(code):
            raise HTTPException(422, "Link youtu.be inválido. Cole o endereço de um vídeo.")
        return "https://youtu.be/" + code, code, "youtube"

    if host in YT_HOSTS:
        if u.path.rstrip("/") == "/watch":
            videos = parse_qs(u.query).get("v", [])
            if len(videos) == 1 and YT_ID.fullmatch(videos[0]):
                return "https://www.youtube.com/watch?v=" + videos[0], videos[0], "youtube"
        match = YT_PATH.fullmatch(u.path)
        if match:
            kind, code = match.groups()
            return "https://www.youtube.com/" + kind + "/" + code, code, "youtube"
        raise HTTPException(422, "YouTube: use /watch?v=, /shorts/, /live/, /embed/ ou youtu.be.")

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

def youtube_preview_fallback(url, code):
    """YouTube's public thumbnail may be available without full video metadata."""
    return {"url": url, "shortcode": code, "platform": "youtube",
            "title": "Vídeo do YouTube", "thumbnail": "https://i.ytimg.com/vi/" + code + "/hqdefault.jpg",
            "verified": False}


def select_thumbnail(meta):
    thumbnail = meta.get("thumbnail")
    options = meta.get("thumbnails") or []
    ranked = sorted(
        (item for item in options if isinstance(item, dict) and item.get("url")),
        key=lambda item: (item.get("width") or 0) * (item.get("height") or 0),
        reverse=True
    )
    for item in ranked:
        url = item["url"]
        if isinstance(url, str) and url.startswith("https://"):
            return url
    return thumbnail if isinstance(thumbnail, str) and thumbnail.startswith("https://") else None


@app.post("/api/preview")
def video_preview(payload: DownloadRequest):
    url, code, platform = canonical(payload.url)
    now = time.time()
    with lock:
        cached = preview_cache.get(url)
        if cached and now - cached["timestamp"] < 1200:
            return cached["data"]
    if not preview_slots.acquire(blocking=False):
        raise HTTPException(429, "Muitas solicitações de prévia. Tente novamente.")
    try:
        command = [
            sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
            "--skip-download", "--dump-single-json", "--no-warnings",
            "--socket-timeout", "10", "--retries", "1",
            *(["--js-runtimes", "node"] if platform == "youtube" else []),
            "--", url,
        ]
        proc = subprocess.run(command, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=35, check=False)
        if proc.returncode:
            if platform == "youtube":
                return youtube_preview_fallback(url, code)
            raise HTTPException(422, friendly(proc.stderr + proc.stdout, platform))
        try:
            meta = json.loads(proc.stdout)
        except json.JSONDecodeError:
            if platform == "youtube":
                return youtube_preview_fallback(url, code)
            raise HTTPException(422, "Não foi possível identificar a capa do vídeo.")
        if not isinstance(meta, dict):
            raise HTTPException(422, "Não foi possível extrair informações deste vídeo.")
        thumb = select_thumbnail(meta)
        if not thumb:
            if platform == "youtube":
                return youtube_preview_fallback(url, code)
            raise HTTPException(422, "Este vídeo não disponibilizou imagem de capa.")
        result = {
            "url": url, "platform": platform, "shortcode": code,
            "title": str(meta.get("title") or "Vídeo detectado")[:150],
            "thumbnail": thumb,
        }
        with lock:
            preview_cache[url] = {"timestamp": time.time(), "data": result}
        return result
    except subprocess.TimeoutExpired:
        if platform == "youtube":
            return youtube_preview_fallback(url, code)
        raise HTTPException(504, "A captura da capa demorou demais. Tente novamente.")
    finally:
        preview_slots.release()


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
    provider = {"facebook": "Facebook", "instagram": "Instagram", "youtube": "YouTube"}.get(platform, "A plataforma")
    if any(s in m for s in ("login", "cookies", "private", "sign in", "rate limit", "429", "cannot parse data", "no video formats found", "confirm you\'re not a bot", "confirm you are not a bot")):
        return f"O {provider} exigiu autenticação, bloqueou o acesso ou alterou a extração. Tente outro vídeo público ou mais tarde."
    if any(s in m for s in ("404", "not available", "unavailable", "not found")):
        return "Vídeo não encontrado ou indisponível publicamente."
    return f"Não foi possível baixar este vídeo. O {provider} pode ter restringido o acesso."

def worker(jobid, url, code, platform, folder):
    try:
        folder.mkdir(parents=True, exist_ok=True)
        setjob(jobid, status="downloading", progress=0,
               message="Conectando à plataforma e preparando o vídeo...")
        cmd = [
            sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
            "--no-cache-dir", "--no-mtime", "--no-write-thumbnail",
            "--no-write-info-json", "--socket-timeout", "20", "--retries", "2",
            "--fragment-retries", "2", "--max-filesize", "400M",
            *(["--js-runtimes", "node"] if platform == "youtube" else []),
            "--newline", "--progress-template", "download:REELDROP_PROGRESS:%(progress._percent_str)s",
            "--format", "bv*+ba/b", "--merge-output-format", "mp4",
            "--remux-video", "mp4",
            "-o", str(folder / (platform + "_" + code + ".%(ext)s")), "--", url
        ]
        history = deque(maxlen=30)
        timed_out = threading.Event()
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace", bufsize=1) as proc:
            def terminate():
                if proc.poll() is None:
                    timed_out.set()
                    proc.kill()
            timer = threading.Timer(180, terminate)
            timer.daemon = True
            timer.start()
            try:
                assert proc.stdout is not None
                for line in proc.stdout:
                    history.append(line.strip())
                    match = re.search(r"REELDROP_PROGRESS:\s*([\d.,]+)%", line)
                    if match:
                        try:
                            pct = min(99, max(0, int(float(match.group(1).replace(",", ".")))))
                            setjob(jobid, status="downloading", progress=pct,
                                   message=f"Baixando o vídeo... {pct}%")
                        except ValueError:
                            pass
                code_returned = proc.wait()
            finally:
                timer.cancel()
        if timed_out.is_set():
            raise RuntimeError("Tempo limite excedido. Tente novamente.")
        if code_returned:
            raise RuntimeError(friendly("\n".join(history), platform))
        result = folder / (platform + "_" + code + ".mp4")
        if not result.exists() or not 0 < result.stat().st_size <= 400 * 1024 * 1024:
            raise RuntimeError("Não foi possível obter um arquivo MP4 válido.")
        setjob(jobid, status="ready", progress=100, message="Vídeo pronto!", filename=result.name)
    except Exception as e:
        setjob(jobid, status="error", message=str(e)[:300])
    finally:
        slots.release()


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE

@app.get("/api/health")
def health():
    return {"status":"ok","service":"ReelDrop","version":"1.3.0","platforms":["instagram","facebook","youtube"]}

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
        jobs[jobid]={"status":"preparing","message":"Preparando download...","progress":0,"updated":now,"folder":folder,"platform":platform}
    threading.Thread(target=worker,args=(jobid,url,code,platform,folder),daemon=True).start()
    return {"id":jobid,"status":"preparing","platform":platform}

@app.get("/api/download/{jobid}")
def status(jobid:str):
    with lock:
        j=jobs.get(jobid)
        if not j:raise HTTPException(404,"Download não encontrado.")
        return {"status":j["status"],"message":j["message"],"progress":j["progress"],"platform":j["platform"]}

@app.get("/api/file/{jobid}")
def file(jobid:str):
    with lock:
        j=jobs.get(jobid)
        if not j or j["status"]!="ready":raise HTTPException(404,"Arquivo não está pronto.")
        f=j["folder"]/j["filename"]
    return FileResponse(f,filename=f.name,media_type="video/mp4",
                        background=BackgroundTask(cleanup,jobid),
                        headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})

def youtube_diagnostic_once():
    """Temporary one-off metadata test for a user-reported public Short."""
    target = "https://www.youtube.com/shorts/5g83JHxpI8k"
    cmd = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
           "--skip-download", "--print", "id", "--js-runtimes", "node",
           "--socket-timeout", "12", "--retries", "1", "--",
           target]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           errors="replace", timeout=60)
        details = (p.stderr or "").splitlines()
        print("REELDROP_YOUTUBE_TEST result=" + str(p.returncode), flush=True)
        for line in details[-24:]:
            cleaned = re.sub(r"https?://\\S+", "[url]", line)
            print("REELDROP_YOUTUBE_TEST " + cleaned[:450], flush=True)
    except Exception as exc:
        print("REELDROP_YOUTUBE_TEST exception=" + type(exc).__name__, flush=True)

threading.Thread(target=youtube_diagnostic_once, daemon=True).start()


PAGE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ReelDrop — Baixar vídeos do Instagram, Facebook e YouTube</title>
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

.preview{margin-top:16px;background:#101428;border:1px solid #414365;border-radius:14px;padding:12px;display:grid;grid-template-columns:125px 1fr;align-items:center;gap:12px}
.preview img{width:125px;height:100px;object-fit:cover;border-radius:10px;background:#2a3050}
.preview-details{min-width:0;display:flex;flex-direction:column;gap:7px;overflow:hidden}
.preview-details strong{font-size:14px;line-height:1.4;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.preview-details small{color:#9eacdb;font-size:12px}
.shares{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:8px}
.shares a,.shares button{display:inline-flex;align-items:center;justify-content:center;padding:10px 11px;border:1px solid #535b81;border-radius:10px;background:#242b44;color:#f8f9ff;font-size:12px;font-weight:700;text-decoration:none}
.shares #wa{background:#184734;border-color:#347454}
.hidden{display:none!important}
#progress-wrap{margin-top:8px}
.track{height:7px;background:#252a45;overflow:hidden;border-radius:99px}
#progress-bar{width:0;height:100%;background:linear-gradient(90deg,#be53eb,#ec54a5);transition:width .3s}
.progress-hint{font-size:12px;margin:8px 0 0;text-align:center}
@media(max-width:430px){.preview{grid-template-columns:95px 1fr}.preview img{width:95px;height:98px}.shares{display:grid;grid-template-columns:1fr}.shares button,.shares a{width:100%}}
</style></head><body><main>
<div class="brand"><span class="logo">▶</span>Reel<em>Drop</em></div>
<div class="kicker">INSTAGRAM + FACEBOOK + YOUTUBE</div>
<h1>Seu vídeo favorito,<br><span>em um clique.</span></h1>
<p>Cole o link de um vídeo público do Instagram, Facebook ou YouTube. O site identifica a plataforma e baixa o MP4 na melhor qualidade acessível.</p>
<div class="card"><form id="form"><label for="url">Link do vídeo</label>
<div class="field"><input id="url" type="url" required placeholder="Cole um link do Instagram, Facebook ou YouTube" autocomplete="url">
<button id="paste" type="button">Colar link</button></div>
<div id="platform" style="margin:12px 0 0;text-align:center;color:#b3a6ef;font-size:13px" aria-live="polite">Instagram, Facebook e YouTube</div>
<section id="preview" class="preview hidden" aria-label="Prévia do vídeo">
  <img id="thumbnail" alt="Capa do vídeo" loading="lazy">
  <div class="preview-details">
    <strong id="preview-title">Vídeo detectado</strong>
    <small id="preview-platform">Instagram, Facebook ou YouTube</small>
  </div>
  <div class="shares">
    <a id="wa" href="#" target="_blank" rel="noopener noreferrer">Compartilhar no WhatsApp</a>
    <button id="share-native" type="button">Compartilhar</button>
    <button id="share-copy" type="button">Copiar link</button>
  </div>
</section>
<button id="go" type="submit">↓ &nbsp; Baixar vídeo</button></form>
<div id="status" role="status" aria-live="polite"></div>
<div id="progress-wrap" class="hidden"><div class="track"><div id="progress-bar"></div></div><p class="progress-hint">O download no navegador será iniciado quando o vídeo estiver pronto.</p></div></div>
<footer>Somente conteúdo público que você tem permissão para baixar.<br>Ferramenta independente, não afiliada ao Instagram, Facebook ou YouTube.</footer>
</main><script>
const input=document.getElementById("url"),form=document.getElementById("form"),
btn=document.getElementById("go"),notice=document.getElementById("status"),
platform=document.getElementById("platform"),preview=document.getElementById("preview"),
thumb=document.getElementById("thumbnail"),title=document.getElementById("preview-title"),
previewPlatform=document.getElementById("preview-platform"),wa=document.getElementById("wa"),
shareNative=document.getElementById("share-native"),shareCopy=document.getElementById("share-copy"),
progressWrap=document.getElementById("progress-wrap"),progressBar=document.getElementById("progress-bar");
const supported=["instagram.com","www.instagram.com","m.instagram.com","facebook.com","www.facebook.com","m.facebook.com","web.facebook.com","fb.watch","www.fb.watch","youtube.com","www.youtube.com","m.youtube.com","music.youtube.com","youtu.be","www.youtu.be"];
const pause=ms=>new Promise(r=>setTimeout(r,ms));
let timer=null, seq=0, aborter=null, shareURL="", busy=false;
function platformOf(raw){
  try{const u=new URL(raw.trim());if(u.protocol!=="https:" || !supported.includes(u.hostname.toLowerCase())) return null;
  if(u.hostname.includes("instagram"))return "instagram";
  if(u.hostname.includes("youtube")||u.hostname.includes("youtu.be"))return "youtube";
  return "facebook";}catch(e){return null}
}
function detect(){
  const found=platformOf(input.value);
  platform.textContent=found==="instagram"?"✓ Instagram detectado":found==="facebook"?"✓ Facebook detectado":found==="youtube"?"✓ YouTube detectado":"Cole um link válido do Instagram, Facebook ou YouTube";
}
function youtubeCode(raw) {
 try {
  const u = new URL(raw);
  const host = u.hostname.toLowerCase();
  let id = null;
  if(host==="youtu.be"||host==="www.youtu.be") id=u.pathname.replace(/^\/|\/$/g,"");
  else if(host.includes("youtube.com")) {
    if(u.pathname==="/watch") id=u.searchParams.get("v");
    else { const m=u.pathname.match(/^\/(?:shorts|live|embed)\/([A-Za-z0-9_-]{11})\/?$/); if(m)id=m[1]; }
  }
  return id&&/^[A-Za-z0-9_-]{11}$/.test(id)?id:null;
 } catch(e){return null;}
}
function hidePreview(){preview.classList.add("hidden");thumb.removeAttribute("src");shareURL="";}
function setProgress(message,pct=0){
  progressWrap.classList.remove("hidden");notice.textContent=message;
  progressBar.style.width=Math.min(100,Math.max(0,pct))+"%";
}
function refresh(){
  detect();clearTimeout(timer);seq++;if(aborter)aborter.abort();hidePreview();
  const found=platformOf(input.value);
  if(!found)return;
  if(found==="youtube") {
    const id=youtubeCode(input.value.trim());
    if(id) {
      preview.classList.remove("hidden");
      title.textContent="Capa do vídeo do YouTube";
      previewPlatform.textContent="YouTube";
      thumb.src="https://i.ytimg.com/vi/"+id+"/hqdefault.jpg";
      shareURL=input.value.trim();
      wa.href="https://wa.me/?text="+encodeURIComponent("Veja este vídeo: "+shareURL);
    }
  }
  const request=seq;
  timer=setTimeout(async()=>{
    const pasted=input.value.trim();
    aborter=new AbortController();
    notice.textContent="Capturando capa do vídeo...";
    try{
      const response=await fetch("/api/preview",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url:pasted}),signal:aborter.signal});
      const result=await response.json();
      if(request!==seq || pasted!==input.value.trim())return;
      if(!response.ok)throw Error(result.detail||"Capa indisponível para este vídeo.");
      shareURL=result.url;
      title.textContent=result.title||"Vídeo detectado";
      previewPlatform.textContent=result.platform==="youtube"?"YouTube":result.platform==="facebook"?"Facebook":"Instagram";
      thumb.src=result.thumbnail;
      thumb.alt="Capa do vídeo: "+title.textContent;
      wa.href="https://wa.me/?text="+encodeURIComponent("Veja este vídeo: "+shareURL);
      preview.classList.remove("hidden");notice.textContent="";
    }catch(e){
      if(e.name!=="AbortError" && request===seq){notice.textContent="Prévia indisponível. Você ainda pode tentar baixar o vídeo."}
    }
  },600);
}
input.addEventListener("input",refresh);
document.getElementById("paste").onclick=async()=>{
  try{input.value=await navigator.clipboard.readText();refresh();input.focus();}
  catch(e){notice.textContent="Use Ctrl+V ou pressione e segure para colar.";input.focus();}
};
shareNative.onclick=async()=>{
  if(!shareURL)return;
  try{
    if(navigator.share)await navigator.share({title:title.textContent,text:"Veja este vídeo",url:shareURL});
    else {await navigator.clipboard.writeText(shareURL);notice.textContent="Link copiado para compartilhar.";}
  }catch(e){if(e.name!=="AbortError")notice.textContent="Não foi possível compartilhar neste navegador.";}
};
shareCopy.onclick=async()=>{
  if(!shareURL)return;
  try{await navigator.clipboard.writeText(shareURL);notice.textContent="Link copiado!";}
  catch(e){notice.textContent="Não foi possível copiar o link.";}
};
form.onsubmit=async e=>{
 e.preventDefault();if(busy)return;
 if(!platformOf(input.value)){notice.textContent="Cole um link HTTPS válido.";return;}
 busy=true;btn.disabled=true;btn.textContent="Baixando... aguarde";setProgress("Preparando vídeo...",0);
 try{
  const response=await fetch("/api/download",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url:input.value.trim()})});
  const created=await response.json();
  if(!response.ok)throw Error(created.detail||"Não foi possível iniciar.");
  let ready=false;
  for(let i=0;i<100;i++){
   const r=await fetch("/api/download/"+created.id,{cache:"no-store"});
   const j=await r.json();
   if(!r.ok)throw Error(j.detail||"Consulta falhou.");
   setProgress(j.message||"Baixando vídeo...",j.progress||0);
   if(j.status==="error")throw Error(j.message||"Não foi possível baixar o vídeo.");
   if(j.status==="ready"){ready=true;break;}
   await pause(2000);
  }
  if(!ready)throw Error("Tempo limite de processamento.");
  setProgress("Vídeo pronto! Iniciando download no navegador...",100);
  const a=document.createElement("a");a.href="/api/file/"+created.id;
  a.style.display="none";document.body.appendChild(a);a.click();a.remove();
 }catch(e){notice.textContent=e.message||"Erro inesperado.";progressWrap.classList.add("hidden");}
 finally{busy=false;btn.disabled=false;btn.textContent="↓  Baixar vídeo";}
};
</script></body></html>"""
