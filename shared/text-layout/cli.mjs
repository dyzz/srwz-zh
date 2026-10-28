#!/usr/bin/env node
/** JSON/JSONL stdin/stdout adapter. Batch arrays amortize Node startup. */
import { createInterface } from 'node:readline';
import {respond} from './cli-handler.mjs';
for await (const line of createInterface({input:process.stdin,crlfDelay:Infinity})) {
  if(!line.trim())continue;
  try { const request=JSON.parse(line);process.stdout.write(JSON.stringify(Array.isArray(request)?request.map(respond):respond(request))+'\n'); }
  catch(error){process.stdout.write(JSON.stringify({ok:false,error:{code:'json',message:error.message}})+'\n');}
}
