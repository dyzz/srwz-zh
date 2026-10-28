"""Batch adapter for the same ESM layout core imported by browser and Node.

Encoding, source identity, field capacities and ISO writeback remain Python
owners. No legacy layout is silently substituted if JS rejects a request.
"""
from pathlib import Path
import json,os,shutil,subprocess

ROOT=Path(__file__).resolve().parents[2]
CLI=ROOT/'shared/text-layout/cli.mjs'
if not CLI.is_file():
    # Community standalone packages the exact same ESM next to this adapter.
    CLI=Path(__file__).resolve().parents[1]/'js/cli.mjs'

class JsLayoutError(ValueError):
    def __init__(self, error):
        self.code=error['code'];self.details=error.get('details',{})
        super().__init__(error['message'])

def layout_batch(requests, *, timeout=30):
    node=os.environ.get('SRWZ_NODE') or shutil.which('node')
    if not node:raise RuntimeError('Node.js required for shared JS layout; set SRWZ_NODE')
    result=subprocess.run([node,str(CLI)],
        input=json.dumps(requests,ensure_ascii=False)+'\n',text=True,
        capture_output=True,check=True,timeout=timeout)
    return json.loads(result.stdout)

def request_layout(text, scene, *, action='layout', options=None):
    response=layout_batch([dict(text=text,scene=scene,action=action,options=options or {})])[0]
    if not response['ok']:raise JsLayoutError(response['error'])
    return response['result']
