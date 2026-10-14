"""Extract SP event speech for local Whisper and a source-bound subtitle draft."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import wave

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from srwz.codec import decode_production
from srwz.iso9660 import member_map, scan_iso9660
from special_disc.event_gallery.subtitles import records


def extract(source, config, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    audio = outdir / 'audio'
    audio.mkdir(exist_ok=True)
    members = member_map(scan_iso9660(source))
    with source.open('rb') as stream:
        def read(name):
            member = members[name]
            stream.seek(member.extent_lba * 2048)
            return stream.read(member.size)
        elf, veff, msh = (read(n) for n in ('SLPS_259.20', 'EFF/VEFF2DX.BIN', 'SOUND/CCC.MSH'))
        count = struct.unpack_from('<I', msh, 8)[0]
        clips, scenes = {}, []
        for entry in config['entries']:
            scene = {'id': entry['id'], 'name': entry['name'], 'effects': []}
            for effect in entry['effects']:
                chunk = effect + 1
                start, end = struct.unpack_from('<II', elf, 0x375230 + chunk * 4)
                resource = decode_production(veff[start:end]).output
                rec = records(resource)
                flags = rec[0][0]
                # Header bit6 adds the CCC voice timeline after optional textures.
                if not flags & 0x40:
                    continue
                timeline = rec[-1]
                assert len(timeline) % 4 == 0
                cues = []
                for at in range(0, len(timeline), 4):
                    frame, voice = struct.unpack_from('<HH', timeline, at)
                    if frame == 0xffff:
                        break
                    if voice == count:
                        cues.append({'effect_frame': frame, 'kind': 'stop_voice', 'ccc_id': voice})
                        continue
                    assert voice < count, (effect, frame, voice, count)
                    size, offset = struct.unpack_from('<II', msh, 12 + voice * 8)
                    assert size and size % 16 == 0 and offset + size <= members['SOUND/CCC.MSB'].size
                    if voice not in clips:
                        stream.seek(members['SOUND/CCC.MSB'].extent_lba * 2048 + offset)
                        data = stream.read(size)
                        pcm, previous, older = [], 0, 0
                        coefficients = [(0, 0), (60, 0), (115, -52), (98, -55), (122, -60)]
                        for block_at in range(0, size, 16):
                            block = data[block_at:block_at + 16]
                            shift, filt = block[0] & 15, block[0] >> 4
                            assert shift <= 12 and filt < len(coefficients)
                            a, b = coefficients[filt]
                            for n in range(28):
                                value = (block[2 + n // 2] >> (4 * (n % 2))) & 15
                                value = value - 16 if value > 7 else value
                                sample = max(-32768, min(32767, (value << 12 >> shift) + ((a * previous + b * older + 32) >> 6)))
                                pcm.append(sample)
                                older, previous = previous, sample
                        wav = audio / f'ccc-{voice:05d}.wav'
                        with wave.open(str(wav), 'wb') as output:
                            output.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
                            output.writeframes(struct.pack(f'<{len(pcm)}h', *pcm))
                        resampled = audio / f'ccc-{voice:05d}-16k.wav'
                        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(wav), '-ar', '16000', str(resampled)], check=True)
                        clips[voice] = {'ccc_id': voice, 'adpcm_sha256': hashlib.sha256(data).hexdigest(),
                                        'adpcm_bytes': size, 'samples': len(pcm), 'sample_rate': 22050,
                                        'duration_seconds': len(pcm) / 22050, 'wav': str(wav), 'whisper_wav': str(resampled)}
                    cues.append({'effect_frame': frame, 'kind': 'speech', 'ccc_id': voice})
                scene['effects'].append({'effect': effect, 'chunk': chunk, 'frames': struct.unpack_from('<I', rec[1])[0] & 0xffffff,
                                         'source_resource_sha256': hashlib.sha256(resource).hexdigest(), 'cues': cues})
            scenes.append(scene)
    result = {'source': str(source.resolve()), 'ccc_count': count, 'scenes': scenes,
              'clips': [clips[k] for k in sorted(clips)], 'boundary': 'Whisper drafts require human listening review; source CCC audio is unmodified.'}
    (outdir / 'extraction.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'build/iso/special-disc/sp-current.iso')
    parser.add_argument('--config', type=Path, default=ROOT / 'config/products/special-disc/event-gallery.json')
    parser.add_argument('--outdir', type=Path, required=True)
    parser.add_argument('--whisper', type=Path)
    parser.add_argument('--model', type=Path)
    args = parser.parse_args()
    result = extract(args.source, json.loads(args.config.read_text()), args.outdir)
    print(f"Extracted {len(result['clips'])} unique speech clips for {len(result['scenes'])} scenes", flush=True)
    if args.whisper:
        assert args.model and args.model.is_file()
        command = [str(args.whisper.resolve()), '-m', str(args.model.resolve()), '-l', 'ja', '-t', '4', '-otxt', '-osrt', '-oj']
        for clip in result['clips']:
            command += ['-f', clip['whisper_wav']]
        (args.outdir / 'whisper-command.json').write_text(json.dumps(command, ensure_ascii=False, indent=2) + '\n')
        with (args.outdir / 'whisper.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        print('Local Whisper transcription complete', flush=True)


if __name__ == '__main__':
    main()
