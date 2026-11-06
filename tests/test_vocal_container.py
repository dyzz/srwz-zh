"""The on-disc ABI must reject corruption and match the browser writer exactly."""
import importlib.util,json,struct,subprocess,unittest,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('vocal_container',ROOT/'tools/special_disc/vocal_bgm/container.py');c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
class VocalContainerTests(unittest.TestCase):
 def test_browser_bytes_match(self):
  js=ROOT.parent/'srwz-patch-web/public/js/vocal-container.mjs'
  if not js.exists():self.skipTest('companion web checkout absent')
  for body,frames in [(None,0),(b'OggS'+bytes(range(256))*9,10606551)]:
   code=f"import {{buildPrefix}} from {json.dumps(js.as_uri())};process.stdout.write(buildPrefix({('new Uint8Array('+json.dumps(list(body))+')') if body else 'null'},{frames}));"
   self.assertEqual(subprocess.check_output(['node','--input-type=module','-e',code]),c.build_prefix(body,frames))
 def test_corrupt_metadata_and_audio_rejected(self):
  good=c.build_prefix(b'OggS'+b'x'*4096,48000)
  for off in [0,48,2048+19*64,18432+5]:
   bad=bytearray(good);bad[off]^=1
   with self.subTest(offset=off),self.assertRaises(ValueError):c.validate_prefix(bad)
 def test_entry_bounds_rejected_even_with_valid_crc(self):
  for field,value in [(2,2048),(3,c.MAX_TRACK+1),(4,44100),(5,1),(6,0),(7,1),(8,47999),(9,0x8000),(11,1)]:
   bad=bytearray(c.build_prefix(b'OggS'+b'x'*4096,48000));struct.pack_into('<I',bad,2048+19*64+field*4,value)
   struct.pack_into('<I',bad,44,zlib.crc32(bad[2048:c.DATA]));struct.pack_into('<I',bad,48,0);struct.pack_into('<I',bad,48,zlib.crc32(bad[:2048]))
   with self.subTest(field=field),self.assertRaises(ValueError):c.validate_prefix(bad)
 def test_empty_and_full(self):
  self.assertEqual(c.validate_prefix(c.build_prefix(None)),[])
  a=c.validate_prefix(c.build_prefix(b'OggS1234',48000))[0]
  self.assertEqual(a[:9],(19,1,c.DATA,8,48000,2,48000,0,48000))
 def test_oversized_input_rejected(self):
  with self.assertRaises(ValueError):c.build_prefix(b'OggS'+bytes(c.MAX_TRACK),48000)

class VocalContainerV2Tests(unittest.TestCase):
 def test_multiple_tracks_and_loop_gain(self):
  b=c.build_tracks({0:dict(ogg=b'OggSa',frames=48000),19:dict(ogg=b'OggSb',frames=96000,start=12000,end=84000,gain=130762),100:dict(ogg=b'OggSc',frames=24000,once=True)})
  entries=c.validate_prefix(b)
  self.assertEqual([a[0] for a in entries],[0,19,100]);self.assertEqual(entries[1][7:10],(12000,84000,130762));self.assertEqual(entries[2][11],1)
  self.assertEqual(struct.unpack_from('<I',b,8)[0],2)
 def test_v2_rejects_invalid_loop_and_gain(self):
  for extra in [dict(start=200,end=100),dict(end=48001),dict(gain=260905)]:
   with self.subTest(extra=extra),self.assertRaises(ValueError):c.build_tracks({19:dict(ogg=b'OggSx',frames=48000,**extra)})
 def test_unknown_song_rejected(self):
  with self.assertRaises(ValueError):c.build_tracks({101:dict(ogg=b'OggSx',frames=48000)})

if __name__=='__main__':unittest.main()
