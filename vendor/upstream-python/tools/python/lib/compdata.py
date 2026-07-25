import os.path
import shutil
from os.path import exists

import pandas as pd

from tools.python.lib.FileIO import FileIO
from tools.python.lib.binary_extracted import text_to_bytes, bytes_to_text
from io import BytesIO
from pathlib import Path
from typing import Union
import subprocess
import struct

class CompData(FileIO):

    def __init__(self, path: Union[Path, str, BytesIO, bytes], mode="r+b", endian="little"):
        super().__init__(path, mode, endian)
        super().__enter__()
        self.base_address = 0x756700 - 0x10
        self.start = 0x90
        self.size = os.path.getsize(path)
        self.blocks_reference = []
        self.sections_start = []
        self.json_file = 'DATA/COMPDATA/00d.bin'

    def pack_file(self, paths:dict, original_file:Path):

        #Compress
        env = os.environ.copy()
        python = paths['tools'] / 'utilities'
        env["PATH"] = f"{python.as_posix()};{env['PATH']}"
        dec = paths["temp_files"] / 'DATA' / 'COMPDATA' / '00d.bin'
        new = paths["final_files"] / 'New_files' / 'DATA' / 'COMPDATA.BN'
        (paths["final_files"] / 'New_files' / 'DATA').mkdir(parents=True, exist_ok=True)

        orig = str(paths["temp_files"] / 'DATA' / 'COMPDATA' / 'COMPDATA.BN')
        r = subprocess.run(
            [
                paths['tools'] / 'utilities' / 'CompressTool.exe',
                "-c",
                str(dec),
                "9"
            ],
            env=env
        )
        comp = (dec.parent / '00d9.mwo')
        if (dec.parent / 'COMPDATA.BN').exists():
            (dec.parent / 'COMPDATA.BN').unlink()
        comp.rename(dec.parent / 'COMPDATA.BN')
        shutil.copy2(dec.parent / 'COMPDATA.BN', new)


