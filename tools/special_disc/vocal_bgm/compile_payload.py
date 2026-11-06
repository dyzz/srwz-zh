from pathlib import Path
import os, subprocess, shutil

def compile_payload(W: Path, TC: Path, tremor: Path, ogg: Path, game="sp"):
    source = Path(__file__).resolve().parent
    W.mkdir(parents=True, exist_ok=True)
    (W/'iop').mkdir(exist_ok=True)
    for name in ['player.c','arena.c','hooks.S','payload.ld']:
        shutil.copyfile(source/name,W/name)
    for name in ['pcm.c','imports.lst','irx_imports.h','Makefile']:
        shutil.copyfile(source/'iop'/name,W/'iop'/name)
    if game in ('z','best'):
        from profiles import player_source,hook_source
        (W/'player.c').write_text(player_source((source/'player.c').read_text(),game))
        (W/'hooks.S').write_text(hook_source((source/'hooks.S').read_text(),game))
    elif game!='sp':raise ValueError('unsupported game profile')
    # GNU as paths are quoted; refuse embedded quotes/newlines rather than reinterpret them.
    for path in [ogg, W/'iop/vocalpcm.irx']:
        if any(c in str(path) for c in ['"','\n','\r']): raise ValueError('unsupported asset path')
    (W/'assets.S').write_text('.section .rodata\n.balign 64\n.global irx_start,irx_end\nirx_start:\n.incbin "'+str(W/'iop/vocalpcm.irx')+'"\nirx_end:\n.balign 64\n')
    SDK=TC/'ps2sdk';env=os.environ.copy();env.update(PS2DEV=str(TC),PS2SDK=str(SDK));env['PATH']=':'.join(str(TC/x) for x in ['ee/bin','iop/bin','bin','ps2sdk/bin'])+':'+env['PATH']
    for k in ['CPATH','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH','SDKROOT']:env.pop(k,None)
    def run(a):subprocess.run(list(map(str,a)),check=True,env=env,cwd=W)
    run(['make','-C',W/'iop'])
    src=tremor
    cc=TC/'ee/bin/mips64r5900el-ps2-elf-gcc'
    flags=['-O2','-G0','-fno-builtin','-ffunction-sections','-fdata-sections','-fsigned-char','-fno-strict-aliasing','-Wno-error=incompatible-pointer-types','-DLITTLE_ENDIAN=1234','-DBIG_ENDIAN=4321','-DBYTE_ORDER=1234','-I'+str(src),'-I'+str(SDK/'ports/include')]
    objects=[]
    for name in 'mdct block codebook floor0 floor1 info mapping0 registry res012 sharedbook synthesis vorbisfile window'.split():
     run([cc,*flags,'-c',src/(name+'.c'),'-o',W/(name+'.o')]);objects.append(name+'.o')
    for name in ['player.c','arena.c','hooks.S','assets.S']:
     obj=Path(name).stem+'.o';run([cc,*flags,'-c',W/name,'-o',W/obj]);objects.append(obj)
    run([cc,'-nostartfiles','-nostdlib','-G0','-Wl,--gc-sections','-T',W/'payload.ld','-o',W/'payload.elf',*objects,'-L'+str(SDK/'ports/lib'),'-logg','-lc','-lgcc'])
    run([TC/'ee/bin/mips64r5900el-ps2-elf-objcopy','-O','binary',W/'payload.elf',W/'payload.bin'])
    (W/'symbols.txt').write_text(subprocess.check_output([str(TC/'ee/bin/mips64r5900el-ps2-elf-nm'),str(W/'payload.elf')],env=env,text=True))
