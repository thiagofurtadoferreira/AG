import { NextResponse } from "next/server";

export const BACKEND = (process.env.REELDROP_BACKEND_URL || "https://reeldrop-instagram.onrender.com").replace(/\/+$/, "");
const hosts = new Set([
  "instagram.com", "www.instagram.com", "m.instagram.com",
  "facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com",
  "fb.watch", "www.fb.watch", "youtube.com", "www.youtube.com",
  "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"
]);

export function validSocialUrl(value:unknown): value is string {
  if(typeof value !== "string" || value.length>2048 || value.length<15)return false;
  try {
    const u=new URL(value);
    return u.protocol==="https:" && hosts.has(u.hostname.toLowerCase())
      && !u.username && !u.password && !u.port;
  }catch { return false; }
}

export function publicApiError(detail:string,status:number){
  return NextResponse.json({detail},{status});
}

export async function forwardPost(path:"/api/preview"|"/api/download", req:Request):Promise<Response>{
  let payload:unknown;
  try{payload=await req.json();}catch{return publicApiError("Envie o campo url em JSON.",400);}
  if(!payload || typeof payload!=="object" || !validSocialUrl((payload as {url?:unknown}).url)){
    return publicApiError("Cole um endereço HTTPS válido do Instagram, Facebook ou YouTube.",422);
  }
  try{
    const response=await fetch(BACKEND+path,{
      method:"POST",
      headers:{"content-type":"application/json"},
      body:JSON.stringify({url:(payload as {url:string}).url}),
      cache:"no-store",
      signal:AbortSignal.timeout(path==="/api/preview"?47000:15000)
    });
    const data=await response.text();
    return new Response(data,{
      status:response.status,
      headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store"}
    });
  }catch{
    return publicApiError("Serviço de processamento temporariamente indisponível.",502);
  }
}
