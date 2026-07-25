import os.path
import shutil
import subprocess
from xml.etree.ElementTree import SubElement

from tools.python.lib.FileIO import FileIO
from tools.python.lib.binary_extracted import text_to_bytes, bytes_to_text
from tools.python.lib.decompressor import Decompressor
from tools.python.lib.xml import XML
from io import BytesIO
from pathlib import Path
from typing import Union
import lxml.etree as etree

class SubFile:
    def __init__(self, file_bytes:bytes, id:int, compressed:bool):
        self.file_bytes = file_bytes
        self.id = id
        self.compressed = compressed

class Archive(FileIO):

    def __init__(self, path: Union[Path, str, BytesIO, bytes], mode="r+b", endian="little",
                 offsets:list=[]):
        super().__init__(path, mode, endian)
        super().__enter__()
        self.nb_files = len(offsets)
        self.files = []
        self.load_files(offsets)

    def set_folders(self, extracted_folder:Path, patched_folder:Path, xml_folder:Path):
        self.extracted_folder = extracted_folder
        self.patched_folder = patched_folder
        self.xml_folder = xml_folder

    def load_files(self, offsets:list):
        dec = Decompressor()
        for i in range(len(offsets)-1):
            size = offsets[i+1] - offsets[i]
            file_bytes = self.read_at(pos=offsets[i], n=size)

            # If Decompressed size > Comp size then file is compressed
            compressed = False
            if dec.get_coded_int(file_bytes[0:8], 0)[1] > size:
                compressed = True


            self.files.append( SubFile(file_bytes, i, compressed) )

    def extract_files(self, extracted_folder:Path):
        dec = Decompressor()

        for file in self.files:

            sub_name = str(file.id).zfill(len(str(self.nb_files)))
            if file.compressed:
                dec.decompress(file.file_bytes, extracted_folder / f'{sub_name}d.bin')

            else:
                with open(extracted_folder / f'{sub_name}.bin', 'wb') as f:
                    f.write(file.file_bytes)

    def pack_files(self, file_class):
        new_offsets = []
        dec = Decompressor()

        self.seek(0)
        fill = len(str(self.nb_files))

        translated_id = XML.get_translated_XMLs(self.xml_folder)

        for file in self.files:
            new_offsets.append(self.tell())
            file_id = str(file.id).zfill(fill)

            if file.id in translated_id:
                #Copy original file to temp folder
                patched_file = self.patched_folder / f'{file_id}d.bin'
                shutil.copyfile(self.extracted_folder / f'{file_id}d.bin',
                                patched_file)

                #Insert new text from XML
                file_dec = file_class(patched_file)
                file_dec.insert_XML(self.xml_folder / f'{file_id}.xml', ['Translated', 'Edited', 'Done'])

                #Compress file if needed
                if file.compressed:
                    file_dec.close()
                    dec.compress(self.patched_folder / f'{file_id}d.bin', f'{file_id}.bin')

                data = open(self.patched_folder / f'{file_id}.bin', 'rb').read()

            else:
                data = file.file_bytes

            #Pad to 16 bytes
            if self.nb_files > 1:
                data += b'\x00' * (-len(data) % 0x10)

            self.write(data)