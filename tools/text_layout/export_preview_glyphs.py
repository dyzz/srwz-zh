"""Extract exact 24x24 native glyph cells for browser preview; never rerasterize.

``glyphs`` maps characters to their stock cells; ``latinBank.glyphs`` maps ASCII letters,
digits and - . ' / to the HarmonyOS bank cells used by the proportional scenes.
"""
from pathlib import Path
import json,hashlib,sys,argparse,math
R=Path(__file__).resolve().parents[2];sys.path[:0]=[str(R/'tools'),str(R/'tools/special_disc/writeback')]
from srwz.font import decode_vt1_font_segment,decode_glyph,glyph_index_for_code,read_extended_glyph_table,ascii_glyph_index
from migrate_slps_text import encoding_tables
ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=R/'shared/text-layout/assets');args=ap.parse_args()
from PIL import Image
from srwz.iso9660 import member_map,scan_iso9660
manifest_path=R/'manifests/editions/original/current.json';manifest_raw=manifest_path.read_bytes();m=json.loads(manifest_raw);iso=R/m['output']['path'];h=hashlib.sha256()
with iso.open('rb')as f:
 for block in iter(lambda:f.read(1<<20),b''):h.update(block)
assert h.hexdigest()==m['output']['sha256'],'Current ISO identity drift'
proof_path=R/m['readback']['path'];proof_raw=proof_path.read_bytes();assert hashlib.sha256(proof_raw).hexdigest()==m['readback']['sha256'];proof=json.loads(proof_raw)
members=member_map(scan_iso9660(iso));inputs={}
with iso.open('rb')as f:
 for key,name in [('slps','SLPS_258.87'),('vt1','DATA/VT1.BIN')]:
  entry=members[name];f.seek(entry.extent_lba*2048);inputs[key]=f.read(entry.size)
font=decode_vt1_font_segment(inputs['slps'],inputs['vt1']).decoded;digest=hashlib.sha256(font).hexdigest();assert digest==proof['font']['decoded_sha256']
frozen=proof_path.parent.parent
proposal=frozen/'work/build/special-disc/text-candidate/font/proposal.json'
assert proposal.exists()
for name in ['config/encoding/codebook.json','vendor/upstream-python/project/tbl_all.json']:
 assert hashlib.sha256((R/name).read_bytes()).digest()==hashlib.sha256((frozen/name).read_bytes()).digest(),'Frozen encoding identity drift'
T,_,codes,_=encoding_tables(proposal);extended=read_extended_glyph_table(inputs['slps']);mapping={}
for ch in sorted(set(T.inverse_characters)|set(codes)):
 if len(ch)!=1:continue
 code=codes.get(ch,T.inverse_characters.get(ch))
 try:index=ascii_glyph_index(code)if 0x20<=code<=0x7e else glyph_index_for_code(code,extended)
 except (ValueError,TypeError):continue
 if index*288+288<=len(font):mapping[ch]=index
# Production writeback folds fullwidth Latin/digits before encoding.
for ch in list(mapping):
 if 'Ａ'<=ch<='Ｚ' or 'ａ'<=ch<='ｚ' or '０'<=ch<='９':
  folded=chr(ord(ch)-0xfee0)
  if folded in mapping:mapping[ch]=mapping[folded]
# HarmonyOS Latin bank (srwz.latin_bank): the proportional scenes draw ASCII letters, digits and - . ' /
# from these 82 cells; fixed-pitch scenes keep the stock glyphs mapped above.
from srwz import latin_bank
bank_base=latin_bank.base_glyph_index();bank_indices=latin_bank.glyph_indices();bank_slots=latin_bank.slot_characters()
assert bank_base==576 and len(bank_indices)==latin_bank.SLOT_COUNT==82 and bank_indices[-1]*288+288<=len(font)
for slot in bank_slots:assert any(decode_glyph(font,bank_base+slot)),'Latin bank cell is blank: '+bank_slots[slot]
indices=sorted(set(mapping.values())|set(bank_indices));columns=64;rows=math.ceil(len(indices)/columns);image=Image.new('RGBA',(columns*24,rows*24));positions={}
for slot,index in enumerate(indices):
 x=slot%columns*24;y=slot//columns*24;positions[index]=[x,y];pixels=decode_glyph(font,index);tile=Image.new('RGBA',(24,24));tile.putdata([(255,255,255,value*17)for value in pixels]);image.paste(tile,(x,y))
args.output.mkdir(parents=True,exist_ok=True);png=args.output/'native-glyphs.png';image.save(png,optimize=True)
image_sha=hashlib.sha256(png.read_bytes()).hexdigest();hashed=png.with_name('native-glyphs.'+image_sha[:12]+'.png');png.replace(hashed);png=hashed
meta=dict(schemaVersion=2,cellSize=24,width=image.width,height=image.height,image=png.name,imageSha256=hashlib.sha256(png.read_bytes()).hexdigest(),fontDecodedSha256=digest,manifestSha256=hashlib.sha256(manifest_raw).hexdigest(),isoSha256=m['output']['sha256'],proposalSha256=hashlib.sha256(proposal.read_bytes()).hexdigest(),glyphs={ch:positions[index]for ch,index in mapping.items()},latinBank=dict(baseGlyphIndex=bank_base,cells=[positions[index]for index in bank_indices],glyphs={ch:positions[bank_base+slot]for slot,ch in sorted(bank_slots.items())},use='Proportional scenes only, where the layout engine returns an advanceBox metric; keys are NFKC-folded ASCII'),source='Exact decoded production 4bpp cells; low nibble left; white RGB and alpha=nibble*17; no trimming, rerasterization or per-character baseline changes')
(args.output/'native-glyphs.json').write_text(json.dumps(meta,ensure_ascii=False,separators=(',',':'))+'\n');print(len(mapping),'characters',len(indices),'native cells',png.stat().st_size,'PNG bytes',digest)
