import { BACKEND, publicApiError } from "../../../lib/backend";
export const runtime="nodejs";
export async function GET(){
  try{
    const res=await fetch(BACKEND+"/api/health",{cache:"no-store",signal:AbortSignal.timeout(12000)});
    return new Response(await res.text(),{status:res.status,headers:{"content-type":"application/json"}});
  }catch{return publicApiError("Backend fora do ar.",502);}
}
