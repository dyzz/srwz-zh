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

class Kurodata():

    def __init__(self):
        self.base = 0

    def copy_new_files(self, original_folder:Path, new_folder:Path):
        shutil.copy(original_folder / 'KVPDATA.BIN', new_folder / 'KVPDATA.BIN')
        shutil.copy(original_folder / 'KVMDATA.BIN', new_folder / 'KVMDATA.BIN')