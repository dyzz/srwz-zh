"""Executable-specific addresses; audio container IDs are shared by Z and SP."""
PROFILES={
 'sp':dict(executable='SLPS_259.20',hooks=[(0x18b1f0,[0x27bdfff0,0x34048090],'hook_stop'),(0x18b7e0,[0x27bdffe0,0xffbf0010],'hook_update'),(0x18b270,[0x27bdff40,0x3c020047],'hook_load'),(0x18c8a0,[0x27bdffe0,0x30828000],'hook_native')]),
 'best':dict(executable='SLPS_732.70',hooks=[(0x189920,[0x27bdfff0,0x34048090],'hook_stop'),(0x189f10,[0x27bdffe0,0xffbf0010],'hook_update'),(0x1899a0,[0x27bdff40,0x3c020041],'hook_load'),(0x18afb0,[0x27bdffe0,0x30828000],'hook_native')]),
 'z':dict(executable='SLPS_258.87',hooks=[(0x189580,[0x27bdfff0,0x34048090],'hook_stop'),(0x189b70,[0x27bdffe0,0xffbf0010],'hook_update'),(0x189600,[0x27bdff40,0x3c020041],'hook_load'),(0x18ac10,[0x27bdffe0,0x30828000],'hook_native')]),
}
Z_PLAYER_RELOCATIONS={0x18c8a0:0x18ac10,0x5dbb98:0x5585d8,0x11f0b0:0x11f130,0x11eed0:0x11ef50,0x11b260:0x11b2e0,0x11df08:0x11df88,0x11b380:0x11b400,0x123510:0x123590,0x123590:0x123610,0x123b30:0x123bb0}
Z_HOOK_RELOCATIONS={0x18b7e8:0x189b78,0x18b278:0x189608,0x18b7b0:0x189b40,0x18b1f8:0x189588,0x18c8a8:0x18ac18}
BEST_PLAYER_RELOCATIONS={**Z_PLAYER_RELOCATIONS,0x18c8a0:0x18afb0,0x5dbb98:0x558dd8}
BEST_HOOK_RELOCATIONS={k:v+0x3a0 for k,v in Z_HOOK_RELOCATIONS.items()}
def player_source(text,game='z'):
 # Replace in one pass: e.g. SP free address equals Z alloc address.
 import re
 return re.sub(r'0x[0-9a-f]+',lambda m:hex((BEST_PLAYER_RELOCATIONS if game=='best' else Z_PLAYER_RELOCATIONS).get(int(m[0],16),int(m[0],16))),text)
def hook_source(text,game='z'):
 import re
 text=re.sub(r'0x[0-9a-f]+',lambda m:hex((BEST_HOOK_RELOCATIONS if game=='best' else Z_HOOK_RELOCATIONS).get(int(m[0],16),int(m[0],16))),text)
 return text.replace('lui $2,0x47','lui $2,0x41')
