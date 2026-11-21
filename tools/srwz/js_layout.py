"""Batch adapter for the same ESM layout core imported by browser and Node.

Encoding, source identity, field capacities and ISO writeback remain Python
owners. No legacy layout is silently substituted if JS rejects a request.
"""
from pathlib import Path
import atexit,json,os,select,shutil,subprocess,threading,time

ROOT=Path(__file__).resolve().parents[2]
CLI=ROOT/'shared/text-layout/cli.mjs'
if not CLI.is_file():
    # Community standalone packages the exact same ESM next to this adapter.
    CLI=Path(__file__).resolve().parents[1]/'js/cli.mjs'

class JsLayoutError(ValueError):
    def __init__(self, error):
        self.code=error['code'];self.details=error.get('details',{})
        super().__init__(error['message'])

class _Worker:
    """One Node process running the JSONL adapter: a request line in, a response line out."""

    def __init__(self, node, cli):
        self.process=subprocess.Popen([node,cli],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        self.buffer=b''

    def ask(self, payload, timeout):
        self.process.stdin.write(payload);self.process.stdin.flush()
        descriptor=self.process.stdout.fileno();deadline=time.monotonic()+timeout
        while b'\n' not in self.buffer:
            if not select.select([descriptor],[],[],max(0.0,deadline-time.monotonic()))[0]:
                raise TimeoutError('shared JS layout worker timed out')
            chunk=os.read(descriptor,1<<20)
            if not chunk:raise EOFError('shared JS layout worker exited')
            self.buffer+=chunk
        line,_,self.buffer=self.buffer.partition(b'\n')
        return json.loads(line)

    def close(self):
        try:self.process.kill();self.process.wait(timeout=5)
        except (OSError,subprocess.TimeoutExpired):pass
        for stream in (self.process.stdin,self.process.stdout):
            try:stream.close()
            except OSError:pass


# Node startup and loading the engine cost about 45 ms. A build asks for thousands of batches (354 in one SP
# stage component alone), so the adapter is kept running and each batch is one line to it. Idle workers wait
# in a small pool; concurrent callers each take their own. SRWZ_JS_LAYOUT_ONESHOT=1 starts a process per batch.
_IDLE={};_IDLE_LOCK=threading.Lock();_MAX_IDLE=8


def _forget_inherited_workers():
    # A forked child must not talk on its parent's pipes.
    global _IDLE_LOCK
    _IDLE.clear();_IDLE_LOCK=threading.Lock()


def _close_idle_workers():
    with _IDLE_LOCK:
        workers=[w for pool in _IDLE.values() for w in pool];_IDLE.clear()
    for worker in workers:worker.close()


if hasattr(os,'register_at_fork'):os.register_at_fork(after_in_child=_forget_inherited_workers)
atexit.register(_close_idle_workers)


def _one_shot(node, requests, timeout):
    result=subprocess.run([node,str(CLI)],
        input=json.dumps(requests,ensure_ascii=False)+'\n',text=True,
        capture_output=True,check=True,timeout=timeout)
    return json.loads(result.stdout)


def layout_batch(requests, *, timeout=30):
    node=os.environ.get('SRWZ_NODE') or shutil.which('node')
    if not node:raise RuntimeError('Node.js required for shared JS layout; set SRWZ_NODE')
    requests=list(requests)
    if os.environ.get('SRWZ_JS_LAYOUT_ONESHOT')=='1':return _one_shot(node,requests,timeout)
    key=(node,str(CLI))
    with _IDLE_LOCK:
        pool=_IDLE.get(key);worker=pool.pop() if pool else None
    try:
        if worker is None:worker=_Worker(node,str(CLI))
        responses=worker.ask((json.dumps(requests,ensure_ascii=False)+'\n').encode('utf-8'),timeout)
    except (OSError,EOFError,TimeoutError,ValueError):
        # Whatever went wrong with the kept process, a fresh one reports it the way callers expect.
        if worker is not None:worker.close()
        return _one_shot(node,requests,timeout)
    with _IDLE_LOCK:
        pool=_IDLE.setdefault(key,[])
        if len(pool)<_MAX_IDLE:pool.append(worker);worker=None
    if worker is not None:worker.close()
    return responses

def request_layout(text, scene, *, action='layout', options=None):
    response=layout_batch([dict(text=text,scene=scene,action=action,options=options or {})])[0]
    if not response['ok']:raise JsLayoutError(response['error'])
    return response['result']
