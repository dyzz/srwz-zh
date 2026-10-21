from pathlib import Path
import sys,json,re,time,subprocess,concurrent.futures,shutil
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent))
import capture_height as c
E=R/'docs/issue-assets/native-text-rendering-20261021/smaller-body';E.mkdir(parents=True,exist_ok=True)
log=R/'work/analysis/library-font-fix-20261021/build-smaller.log';deadline=time.monotonic()+240
while True:
 text=log.read_text();match=re.search(r'"batch_manifest": "([^"]+)"',text)
 if match:break
 if time.monotonic()>deadline:raise TimeoutError('build did not complete')
 time.sleep(2)
batch=json.loads((R/match[1]).read_text());shutil.copy2(R/match[1],E/'production-build.json');digest=batch['input_digest']
s=(R/'work/analysis/library-font-fix-20261021/audit_vertical_iso.py').read_text().replace('2431e91b9a261426ae0175f1ad6ba48053075cdd9398b320a41760bca5b73e3f',digest).replace("expected_letter=11 if domain=='robot' else 13","expected_letter=11 if domain=='robot' else 12").replace("(expected_letter if letter else base_height)","(expected_letter if letter else (11 if base_height==12 else base_height))").replace('/vertical-refinement/iso-audit.json','/smaller-body/iso-audit.json')
p=R/'work/analysis/library-font-fix-20261021/audit_smaller_iso.py';p.write_text(s);subprocess.run([sys.executable,str(p)],cwd=R,check=True)
print('Build and ISO audit ready:',digest,flush=True)
c.OUT=R/'work/runtime/lrps2/library-smaller-body-20261021'
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
 for ed in ex.map(c.capture,c.ISOS):print(ed,'captured',flush=True)
