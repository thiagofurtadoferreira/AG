import {forwardPost} from "../../../lib/backend";
export const runtime="nodejs";
export async function POST(req:Request){return forwardPost("/api/download",req);}
