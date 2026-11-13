"""Build the isolated SP vocal-BGM experiment; never alters the release ISO."""
from pathlib import Path
import argparse,json,subprocess
from bootstrap_tremor import ensure_tremor
from compile_payload import compile_payload
from build_image import build_image

def main():
    root=Path(__file__).resolve().parents[3]
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game',choices=['sp','z','best'],default='sp')
    p.add_argument('--ogg',type=Path,required=True,help='Full 48 kHz stereo Vorbis file')
    p.add_argument('--toolchain',type=Path,required=True,help='ps2dev root with ee/iop/ps2sdk')
    p.add_argument('--tremor-source',type=Path,default=None,help='PS2 Tremor checkout; defaults to the pinned clone under work/toolchain (fetched if absent)')
    p.add_argument('--workdir',type=Path,default=root/'work/analysis/sp-vorbis-rebuild')
    p.add_argument('--source-iso',type=Path,default=None)
    p.add_argument('--output-iso',type=Path,default=root/'build/iso/test/sp-vorbis-full.iso')
    p.add_argument('--replace',action='store_true')
    p.add_argument('--payload-only',action='store_true')
    a=p.parse_args()
    if a.tremor_source is None:a.tremor_source=ensure_tremor()
    if a.source_iso is None:a.source_iso=root/('build/iso/sources/best.iso' if a.game=='best' else 'build/iso/sources/original.iso' if a.game=='z' else 'build/iso/special-disc/sp-current.iso')
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','a:0','-show_entries','stream=codec_name,sample_rate,channels,duration_ts,time_base','-of','json',str(a.ogg)],text=True))['streams'][0]
    if any(probe.get(k)!=v for k,v in {'codec_name':'vorbis','sample_rate':'48000','channels':2,'time_base':'1/48000'}.items()):raise ValueError('Expected 48 kHz stereo Vorbis')
    if not a.payload_only and a.output_iso.exists() and not a.replace:p.error('Candidate exists; use --replace')
    compile_payload(a.workdir.resolve(),a.toolchain.resolve(),a.tremor_source.resolve(),a.ogg.resolve(),a.game)
    if not a.payload_only:
        from container import build_prefix,validate_prefix
        prefix=build_prefix(a.ogg.read_bytes(),int(probe['duration_ts']));validate_prefix(prefix)
        build_image(a.workdir.resolve(),a.source_iso.resolve(),a.output_iso.resolve(),a.replace,prefix,a.game)
if __name__=='__main__':main()
