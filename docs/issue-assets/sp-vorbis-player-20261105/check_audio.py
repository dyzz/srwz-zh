from pathlib import Path
import json,subprocess,wave,sys
import numpy as np
W=Path(__file__).resolve().parent;run=W/(sys.argv[1] if len(sys.argv)>1 else 'runtime-03')
def read(p):return np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-i',str(p),'-ar','8000','-ac','2','-f','f32le','-']),dtype='<f4').reshape(-1,2).astype(float)
x=read('/Users/nate/gba-sound/vorbis-preview-20261105/test-full48-vbr128.ogg');y=read(run/'battle.wav');z=x[:,0]-x[:,1];d=y[:,0]-y[:,1]
def corr(q,z):
 n=1<<(len(z)+len(q)-1).bit_length();v=np.fft.irfft(np.fft.rfft(z,n)*np.fft.rfft(q[::-1],n),n)[len(q)-1:len(z)];s=np.r_[0,np.cumsum(z*z)];v/=np.maximum(np.sqrt((s[len(q):]-s[:-len(q)])*np.sum(q*q)),1e-12);i=int(np.argmax(abs(v)));gain=float(np.dot(q,z[i:i+len(q)])/np.dot(z[i:i+len(q)],z[i:i+len(q)]));return dict(correlation=float(v[i]),reference_offset_seconds=i/8000,gain=gain)
windows={str(t):corr(d[t*8000:(t+4)*8000],z) for t in [8,28,48,88,128,168,208,228] if t+4<len(y)/8000}
keys=[json.loads(l) for l in (run/'battle.wav.keys.jsonl').read_text().splitlines()];speech=[dict(frame=x['frame'],sample=x['sample'],core=x['core'],voice=x['voice']) for x in keys if x['on'] and (int(x['ssa'],16) if isinstance(x['ssa'],str) else x['ssa'])==0x84810]
with wave.open(str(run/'battle.wav')) as f:raw=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').astype(np.int32)
near=int(np.count_nonzero(np.abs(raw)>=32760));rails=int(np.count_nonzero((raw==-32766)|(raw==32765)))
r=dict(near_full_scale_samples=near,spu2_rail_samples=rails,seconds=len(y)/8000,windows=windows,speech_events=speech,peak_min=int(raw.min()),peak_max=int(raw.max()),clipped_samples=int(np.count_nonzero((raw==-32768)|(raw==32767))),note='Actual SPU2 mix. Stereo difference suppresses centered speech and effects. Correlation is a continuity check, not a perceptual score.')
(run/'audio-check.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
