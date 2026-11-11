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

# Exact earlier browser players. Migration accepts only these payloads and
# verifies every installed hook (at that version's addresses) before replacing
# the reserved ELF segment. v1: first browser player (2026-11-05).
# v2: asynchronous loader (2026-11-06); its AutoDMA blocked native core-1
# sound-effect uploads, so v2 images must be upgraded to the current player.
LEGACY_HOOKS=dict(hook_stop=0x8ce8f0,hook_update=0x8ce5e0,hook_load=0x8ce6e0,hook_native=0x8ce9f0)
V2_HOOKS=dict(hook_stop=0x8cea50,hook_update=0x8ce740,hook_load=0x8ce840,hook_native=0x8ceb50)
LEGACY_PLAYERS={
 'sp':[dict(version=1,sha256='c4aee88978fb199fcc7449cb6ed0a7fc49fab31e900058627ce82b7e06badc2a',size=139460,hooks=LEGACY_HOOKS),
       dict(version=2,sha256='74c00c73c7fc253ce51311b362e160385a6a66732b1a0fad519676ded287f197',size=139780,hooks=V2_HOOKS)],
 'z':[dict(version=1,sha256='d93ea0ffb10fa9fb3ee1df83a5bab4a87022094271b6173f55f3286d4d331278',size=139460,hooks=LEGACY_HOOKS),
      dict(version=2,sha256='b9005930bee1360ae82d8713b979cf228c86ff3db79b30e4ec6721e2b282c7ca',size=139780,hooks=V2_HOOKS)],
 'best':[dict(version=1,sha256='154fe43be30e191437e75d734cadff41680c3d1b0af8921c51331dfae8990ea9',size=139460,hooks=LEGACY_HOOKS),
         dict(version=2,sha256='c9458404c9f1f891f5fb5b04c8d35b42fe62ece0a8c5ecd0b6a5501ad8e3ba08',size=139780,hooks=V2_HOOKS)],
}
