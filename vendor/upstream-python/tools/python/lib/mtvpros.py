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


class MtvPros(FileIO):

    def __init__(self, path: Union[Path, str, BytesIO, bytes], mode="r+b", endian="little"):
        super().__init__(path, mode, endian)
        super().__enter__()
        self.size = os.path.getsize(path)
        self.nb_sections = self.get_nb_sections()
        self.xml_name = f'{path.stem.replace('d','').zfill(2)}.xml'

    def get_nb_sections(self):
        self.seek(0x2C)
        return self.read_uint32() + self.read_uint32() + self.read_uint32()

    def extract_sections(self, original_path:Path):
        original_path.mkdir(parents=True, exist_ok=True)
        root = etree.Element("SummaryText")
        strings_node = etree.SubElement(root, 'Strings')
        etree.SubElement(strings_node, "Section").text = 'Text'

        self.seek(0x3C)
        nb_entries = 0


        for count in range(self.nb_sections):
            pos = self.tell()
            type = self.read(4).decode('utf-8')
            offset = self.read_uint32()

            # Extract if text
            if type == 'text':
                self.read(0x22)
                nb = self.read_uint32()
                text_offset = self.tell()
                b_text = self.read_at(text_offset, nb)
                text, b_text = bytes_to_text(FileIO(BytesIO(b_text)))

                entry_node = etree.SubElement(strings_node, "Entry")
                etree.SubElement(entry_node, "PointerOffset").text = str(text_offset)
                etree.SubElement(entry_node, "JapaneseText").text = text
                etree.SubElement(entry_node, "EnglishText")
                etree.SubElement(entry_node, "Notes")
                etree.SubElement(entry_node, "Chapter").text = "Uncategorized"
                etree.SubElement(entry_node, "Status").text = "To Do"
                etree.SubElement(entry_node, "Length").text = str(nb)

                nb_entries += 1

            self.seek(pos + offset + 8)

        #if keep_translations:
        #    self.copy_translations(root_original=root,
        #                           translated_path=translated_path)

        if nb_entries > 0:
            with open(original_path / self.xml_name, "wb") as xmlFile:
                xmlFile.write(etree.tostring(root, encoding="UTF-8", pretty_print=True))



    def get_new_file(self, translated_path:Path, tools_path:Path):


        # Check if translated
        nb_translated = XML.count_translated_entries(translated_path)

        if nb_translated > 0:
            # Insert text from XML
            self.insert_XML(translated_path)

        # Compress the file
        env = os.environ.copy()
        python = tools_path / 'utilties'
        env["PATH"] = f"{python.as_posix()};{env['PATH']}"
        comp = (self.path.parent / f'{self.path.stem}9.mwo')
        r = subprocess.run(
            [
                tools_path / 'python' / 'SRWZ.exe',
                "-c",
                str(self.path),
                comp
            ],
            env=env
        )

        comp_ = self.path.parent / f'{self.path.stem}.bin'
        if comp_.exists():
            comp_.unlink()
        comp.rename(comp_)

        with open((self.path.parent / self.path.stem.replace('.d','')), 'wb') as f:
            return f.read()

    def insert_XML(self, translated_path:Path, translated_status:list):

        with open(self.path, 'r+b') as f:
            # Get all entries with start offset
            root = etree.parse(translated_path).getroot()

            for entry_node in root.iter('Entry'):

                offset = int(entry_node.find('PointerOffset').text)
                f.seek(offset)

                text = entry_node.find('JapaneseText').text
                status = entry_node.find('Status').text
                length = int(entry_node.find('Length').text)

                if status in translated_status:
                    text = entry_node.find('EnglishText').text

                bytes_to_insert = text_to_bytes(text, True)
                f.write(bytes_to_insert)
                f.write((length - len(bytes_to_insert)) * b'\x00')
