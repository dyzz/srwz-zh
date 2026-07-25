import os.path
import shutil

import pandas as pd

from tools.python.lib.FileIO import FileIO
from tools.python.lib.binary_extracted import text_to_bytes, bytes_to_text
from io import BytesIO
from pathlib import Path
from typing import Union
import subprocess
import struct

class Vt1(FileIO):

    def __init__(self, path: Union[Path, str, BytesIO, bytes], mode="r+b", endian="little"):
        super().__init__(path, mode, endian)
        super().__enter__()
        self.size = os.path.getsize(path)
        self.json_file = 'DATA/COMPDATA/0d.bin'

    def pack_file(self, paths:dict, files_offset:list)->list:
        final_offsets = []
        data_original = self.read()
        data = b''

        #Loop on all files in Vt1
        for index, file_offset in enumerate(files_offset[:-1]):
            final_offsets.append(len(data))

            #Font
            if index == 2:

                with open(paths['font_updated'] / '2.bin', 'rb') as f:
                    data += f.read()

            else:
                data += data_original[file_offset:files_offset[index+1]]

        #Write final file
        final_path = paths['final_files'] / 'New_files' / 'DATA' / 'VT1.BIN'
        if os.path.exists(final_path):
            os.remove(final_path)

        with open(final_path, 'wb') as f:
            f.write(data)

        final_offsets.append(len(data))
        return final_offsets

