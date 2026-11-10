"""Redraw a line align_check.py found: clean session, load its checkpoint, replay the
presses, screenshot the final step.

  PYTHONPATH=tools python3 replay_shot.py ISO CARD OUTDIR ALIGN_JSON [metal]
"""
import json, sys
from pathlib import Path
sys.path[:0] = ['tools']
from srwz.armsx2_runtime import Armsx2Session
iso, card, out, align = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]).resolve(), Path(sys.argv[4]).resolve()
kw = dict(renderer='metal', upscale=4) if len(sys.argv) > 5 else {}
found = json.loads(align.read_text())['found'][0]
with Armsx2Session(iso, card, out, **kw) as vm:
    vm.run(600); vm.cmd('load ' + str(align.parent / found['checkpoint']))
    for step in range(1, found['stepsAfterCheckpoint'] + 1):
        vm.run(30)
        if step in found['pressesAfterStep']: vm.press('circle', 3)
    print(vm.cmd('shot aligned-replay').lines)
