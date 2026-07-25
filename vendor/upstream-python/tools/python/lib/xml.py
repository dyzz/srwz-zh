import os.path

import pandas as pd

from tools.python.lib.FileIO import FileIO
from tools.python.lib.binary_extracted import text_to_bytes, bytes_to_text
from io import BytesIO
from pathlib import Path
from typing import Union
import struct
import lxml.etree as etree


class XML():


    @staticmethod
    def create_node(strings_node, jap_text:str, pointer_offset:int, id=-1, speaker_id=-1):
        entry_node = etree.SubElement(strings_node, "Entry")

        if pointer_offset != '':
            etree.SubElement(entry_node, "PointerOffset").text = str(pointer_offset).replace(", ", ",")

        etree.SubElement(entry_node, "JapaneseText").text = jap_text
        etree.SubElement(entry_node, "EnglishText")
        etree.SubElement(entry_node, "Notes")

        if jap_text == '':
            status_text = 'Done'
        else:
            status_text = 'To Do'

        if id > -1:
            etree.SubElement(entry_node, "Id").text = str(id)

        if speaker_id > -1:
            etree.SubElement(entry_node, "SpeakerId").text = str(speaker_id)
        etree.SubElement(entry_node, "Chapter").text = "Uncategorized"
        etree.SubElement(entry_node, "Status").text = status_text


    @staticmethod
    def count_translated_entries(xml_path:Path):
        root = etree.parse(xml_path).getroot()
        translated_entries = [ele for ele in root.iter('Entry') if ele.find('Status').text in ["Translated", "Edited", "Spaced", "Finalized", "Done"]]
        return len(translated_entries)

    @staticmethod
    def get_translated_XMLs(translated_folder:Path):
        return [int(file.stem) for file in translated_folder.iterdir() if XML.count_translated_entries(file) > 0]