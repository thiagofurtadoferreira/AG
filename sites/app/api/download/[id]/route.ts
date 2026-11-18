import { BACKEND, publicApiError } from "../../../../lib/backend";
export const runtime="nodejs";
export async function GET(_req:Request,{params}:{params:Promise<{id:string}>}){
  const {id}=await params;
  if(!/^[a-f0-9]{32}$/.test(id))return publicApiError("Identificador de download inválido.",422);
  try{
    const res=await fetch(BACKEND+"/api/download/"+id,{cache:"no-store",signal:AbortSignal.timeout(15000)});
    return new Response(await res.text(),{status:res.status,
      headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store"}});
  }catch{return publicApiError("Falha ao consultar o download.",502);}
}
