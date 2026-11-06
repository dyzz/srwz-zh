#!/usr/bin/env node
/** Local browser + backend integration lab; no writeback or deployment. */
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {respond} from './cli-handler.mjs';
const files=new Map([['/','index.html'],['/index.html','index.html'],['/demo.mjs','demo.mjs'],['/engine.mjs','engine.mjs'],['/contracts.mjs','contracts.mjs']]);
const atlas=JSON.parse(await readFile(new URL('./assets/native-glyphs.json',import.meta.url),'utf8'));
files.set('/assets/native-glyphs.json','assets/native-glyphs.json');files.set('/assets/'+atlas.image,'assets/'+atlas.image);
const port=Number(process.env.PORT||8767);
const server=createServer(async(req,res)=>{
  res.setHeader('Cache-Control','no-store');res.setHeader('X-Content-Type-Options','nosniff');
  const path=new URL(req.url,'http://localhost').pathname;
  if(req.method==='POST'&&path==='/api/layout'){
    let size=0,chunks=[];
    try{
      for await(const chunk of req){size+=chunk.length;if(size>256*1024){res.writeHead(413);res.end();return;}chunks.push(chunk);}
      const input=JSON.parse(Buffer.concat(chunks).toString('utf8'));
      const result=Array.isArray(input)?input.map(respond):respond(input);
      res.setHeader('Content-Type','application/json; charset=utf-8');res.end(JSON.stringify(result));
    }catch(error){res.writeHead(400,{'Content-Type':'application/json'});res.end(JSON.stringify({ok:false,error:{code:'json',message:error.message}}));}
    return;
  }
  if(req.method!=='GET'||!files.has(path)){res.writeHead(404);res.end();return;}
  try{const name=files.get(path);res.setHeader('Content-Type',name.endsWith('.mjs')?'text/javascript; charset=utf-8':name.endsWith('.json')?'application/json; charset=utf-8':name.endsWith('.png')?'image/png':'text/html; charset=utf-8');res.end(await readFile(fileURLToPath(new URL(name,import.meta.url))));}
  catch{res.writeHead(500);res.end('Unable to read local asset');}
});
server.listen(port,'127.0.0.1',()=>console.log(`SRWZ shared JS layout: http://127.0.0.1:${port}`));
