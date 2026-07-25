import shutil
import os
import stat
import struct
from pathlib import Path
import math
import pandas
import pandas as pd
import pycdlib
import pyjson5 as json
import pprint
import subprocess

import string
from dulwich import line_ending, porcelain
from tqdm import tqdm
import re
import lxml.etree as etree
from tools.python.lib.FileIO import FileIO
from tools.python.lib.archive import Archive
from tools.python.lib.xml import XML
from tools.python.lib.mtvpros import MtvPros
from tools.python.lib.stage import Stage
from tools.python.lib.compdata import CompData
from tools.python.lib.kurodata import Kurodata
from tools.python.lib.vt1 import Vt1
from tools.python.lib.decompressor import Decompressor
from tools.python.lib.binary_extracted import text_to_bytes, bytes_to_text
from tools.python import isotool
import datetime
class SRWZ():

    def __init__(self, project_file:Path, insert_mask: list[str], changed_only: bool = False):
        self.jsonTblTags = {}
        self.ijsonTblTags = {}
        self.slps_offsets = {}
        self.project_file = project_file
        self.id = 1
        self.list_status_insertion: list[str] = ['Done']
        self.list_status_insertion.extend(insert_mask)

        self.mips_ops = {
            "043C": b'\x84\x24',
            "053C": b'\xA5\x24',
            "063C": b'\xC6\x24',
            "113C": b'\x31\x26',
            "123C": b'\x52\x26',
            "143C": b'\x94\x26'

        }

        self.init_project_json(project_file)
        self.init_archives_json()
        self.init_tbl_json()
        self.init_menu_json()

    def init_project_json(self, project_file:Path):
        with open(project_file, encoding="utf-8") as f:
            json_raw = json.load(f)

        base_path = project_file.parent
        self.paths: dict[str, Path] = {k: base_path / v for k, v in json_raw["paths"].items()}
        self.main_exe_name = json_raw["main_exe_name"]
        self.asm_file = json_raw["asm_file"]

    def init_archives_json(self):
        with open(self.paths['archives'], encoding="utf-8") as f:
            self.archives = json.load(f)

    def init_menu_json(self):
        # Read json descriptor file
        with open(self.paths["menu_table"], encoding="utf-8") as f:
            self.menu_json = json.load(f)
            self.sections_offset = [
                (sect['name'],
                 int(reg['text_start'], 16) ,
                 int(reg['text_end'], 16)) for file in self.menu_json for sect in file['sections'] for reg in sect['regions'] if file['friendly_name'] == "SLPS"
            ]


    def init_tbl_json(self):
        with open(self.paths["encoding_table"], encoding="utf-8") as f:
            self.menu_files = json.load(f)

        for k, v in self.menu_files.items():
            self.jsonTblTags[k] = {int(k2, 16): v2 for k2, v2 in v.items()}

        for k, v in self.jsonTblTags.items():
            if k in ['tags', 'tbl']:
                self.ijsonTblTags[k] = {v2:k2 for k2, v2 in v.items()}
            else:
                self.ijsonTblTags[k] = {v2: hex(k2).replace('0x', '').upper() for k2, v2 in v.items()}
        #self.iTags = {v2.upper(): k2 for k2, v2 in self.jsonTblTags['tags'].items()}

    def extract_SLPS(self):

        with FileIO(self.paths['original_files'] / self.main_exe_name, 'rb') as f:

            text, buffer = bytes_to_text(f, 0x345F48)

            text, buffer = bytes_to_text(f, 0x345F70)

            t = 2

    def extract_iso(self, game_iso:Path):

        print("Extracting ISO files...")

        iso = pycdlib.PyCdlib()
        iso.open(str(game_iso))

        extract_to = self.paths["original_files"]
        self.clean_folder(extract_to)

        files = []
        for dirname, _, filelist in iso.walk(iso_path="/"):
            files += [dirname +'/'+x for x in filelist]

        for file in files:
            file_path = ''
            if file[0:2] == "//":
                file_path = file[2:]
            else:
                file_path = file[1:]
            out_path = extract_to / file_path
            out_path.parent.mkdir(parents=True, exist_ok=True)

            with iso.open_file_from_iso(iso_path=file) as f, open(str(out_path).split(";")[0], "wb+") as output:
                with tqdm(total=f.length(), desc=f"Extracting {file[1:].split(';')[0]}", unit="B", unit_divisor=1024,
                          unit_scale=True) as pbar:

                    while data := f.read(0x8000):
                        output.write(data)
                        pbar.update(len(data))

        iso.close()

    def handle_remove_readonly(self, func, path, exc_info):
        # Change the file permission and reattempt removal
        os.chmod(path, stat.S_IWRITE)
        func(path)

    def clean_folder(self, path: Path) -> None:
        target_files = list(path.iterdir())
        if len(target_files) != 0:
            print("Cleaning folder...")
            for file in target_files:
                if file.is_dir():
                    shutil.rmtree(file, onerror=self.handle_remove_readonly, ignore_errors=True)
                elif file.name.lower() != ".gitignore":
                    file.unlink(missing_ok=False)

    def clean_builds(self, path: Path) -> None:
        target_files = sorted(list(path.glob("*.iso")), key=lambda x: x.name)[:-3]
        if len(target_files) != 0:
            print("Cleaning builds folder...")
            for file in target_files:
                print(f"deleting {str(file.name)}...")
                file.unlink()

    def extract_SLPS_offsets(self, start:int, end:int)->list:
        with FileIO(self.paths['original_files'] / self.main_exe_name) as f:
            f.seek(start)

            offsets = []
            while(f.tell() < end):
                offsets.append(f.read_uint32())

            return offsets

    def extract_archive_offsets(self, archive_name:str):
        item = self.archives[archive_name]
        offsets = self.extract_SLPS_offsets(item['start'], item['end'])
        return offsets

    def pack_archive(self, folder:str, archive_name:str, translated_xml_folder:Path, file_class):

        # Copy original archive to final folder and
        # use the destination archive to rebuild
        source_archive = self.paths['original_files'] / folder / f'{archive_name}.BIN'
        destination_archive = self.paths['final_files'] / 'New_files' / folder / f'{archive_name}.BIN'
        shutil.copyfile(str(source_archive), str(destination_archive))

        # Create archive and prepare data
        offsets = self.extract_archive_offsets(source_archive.name)
        arc = Archive(path=destination_archive, offsets=offsets)
        patched_folder = self.paths['temp_files'] / folder / archive_name
        arc.set_folders(extracted_folder=self.paths['extracted_files'] / folder / archive_name,
                        patched_folder=patched_folder,
                        xml_folder=translated_xml_folder)

        # Repack all the translated files and update the offsets
        arc.pack_files(file_class)

    def extract_SLPS_archive(self, file_name:str):
        item = self.archives[file_name]
        offsets = self.extract_SLPS_offsets(item['start'], item['end'])

        with FileIO(self.paths['original_files'] / item['folder'] / file_name, 'rb') as f:
            archive_data = f.read()
            path = self.paths['original_files'] / item['folder'] / file_name
            file_size = os.path.getsize(path)

            if offsets[-1] < file_size:
                offsets.append(file_size)

            for i in range(len(offsets) - 1):
                #print(f'Offset: {hex(offsets[i])}')
                f.seek(offsets[i])
                file_data = archive_data[offsets[i]:offsets[i + 1]]

                # Write the new file
                new_folder = self.paths['extracted_files'] / item['folder'] / file_name.split('.')[0]
                new_folder.mkdir(exist_ok=True, parents=True)

                file = f'{str(i).zfill(2)}.bin'
                with open(new_folder / file, 'wb') as new:
                    new.write(file_data)

                if item['compressed']:
                    # print(f' {i}.bin')

                    dec = Decompressor()
                    dec.decompress(new_folder / file, new_folder / f'{str(i).zfill(2)}d.bin')

    def extract_seg_archive(self, file_name:str):
        item = self.archives[file_name]
        offsets = []
        path_seg = self.paths['original_files'] / item['folder'] / item['seg']
        file_size = os.path.getsize(path_seg)

        with FileIO(path_seg, 'rb') as seg:
            while seg.tell() < file_size:
                offset = seg.read_uint32()
                offsets.append(offset)

            if offsets[-1] < file_size:
                offsets.append(file_size)

        with FileIO(self.paths['original_files'] / item['folder'] / file_name, 'rb') as f:
            data = f.read()

        for i in range(len(offsets)-1):
            sub_data = data[offsets[i]:offsets[i+1]]

            # Write the new file
            new_folder = self.paths['extracted_files'] / item['folder'] / file_name.split('.')[0]
            new_folder.mkdir(exist_ok=True, parents=True)

            with open(new_folder / f'{i}.bin', 'wb') as new:
                new.write(sub_data)

            if item['compressed']:
                #print(f' {i}.bin')
                dec = Decompressor()
                dec.decompress(new_folder / f'{i}.bin', new_folder / f'{i}d.bin')

    def extract_all_archives(self):

        valid_archives = ['COMPDATA.BN', 'VT1.BIN']
        archives = [(file_name, item) for file_name, item in self.archives.items() if file_name in valid_archives]
        for file_name, item in (pb := tqdm(archives)):
            pb.set_description(f'Extracting Archive {file_name}')

            if 'seg' in item.keys():
                self.extract_seg_archive(file_name)

            else:
                self.extract_SLPS_archive(file_name)

        self.extract_stage_archive()

    def extract_stage_offsets(self):

        path = self.paths['tools'] / 'python' / 'Stages_Offset.bin'
        overlay_count = 205
        offsets = []

        with FileIO(path) as f:

            for _ in range(overlay_count):
                offset = f.read_uint32()
                offsets.append(offset)

        return offsets

    def extract_stage_pointers(self, data: bytes):
        sequence = b'\x01\x00\x00\x00'
        matches = []  # initializes the list for the matches
        curpos = 0  # current search position (starts at beginning)
        pattern = re.compile(sequence)  # the pattern to search
        while True:
            m = pattern.search(data[curpos:])  # search next occurence
            if m is None: break  # no more could be found: exit loop

            pos = curpos + m.start()

            val = struct.unpack('<I', data[pos:(pos+4)])[0]

            if (val <= 0xF) and ((pos % 16) == 0):
                matches.append(pos)  # append a pair (pos, string) to matches

            curpos += m.end()  # next search will start after the end of found string

        return matches

    def extract_stage_archive(self):

        with open(self.paths['original_files'] / 'DATA' / 'STAGE.BIN', 'rb') as st:
            data = st.read()

        funct = self.extract_stages_functions()
        offsets = self.extract_stage_offsets()
        offsets.append(os.path.getsize(self.paths['original_files'] / 'DATA' / 'STAGE.BIN'))

        for i in (pb := tqdm(range(len(offsets)-1))):
            pb.set_description(f'Extracting Stage {i}')
            stage_data = data[offsets[i]:offsets[i + 1]]
            folder = self.paths['extracted_files'] / 'DATA' / 'STAGE'
            folder.mkdir(parents=True, exist_ok=True)

            with open(folder / f'{str(i).zfill(3)}.bin', 'wb') as f:
                f.write(stage_data)

            # Decompress Stage file
            decompressed_file = folder / f'{str(i).zfill(3)}d.bin'
            dec = Decompressor()
            dec.decompress(source=folder / f'{str(i).zfill(3)}.bin', destination=decompressed_file)

            # Extract Stage text
            st = Stage(decompressed_file)
            #stage_id = int(stage_file.stem.replace('d', ''))
            stage_id = i

            if funct[stage_id] > 0:
                st.extract_conditions(funct[stage_id])
                name = f'{decompressed_file.stem.replace('d', '').zfill(3)}.xml'
                st.extract_stage_XML(original_path=self.paths['story_original'] / name,
                                     translated_path=self.paths['story_xml'] / name, keep_translations=True)

    def extract_stages_text(self):
        self.paths['story_original'].mkdir(parents=True, exist_ok=True)
        funct = self.extract_stages_functions()

        for stage_file in (pb := tqdm((self.paths['extracted_files'] / 'DATA' / 'STAGE').iterdir())):
            pb.set_description(f'Extracting Stage {stage_file.name}')
            #Only file that are decompressed
            if 'd' in stage_file.stem and stage_file.stem != '0d':
                st = Stage(stage_file)
                stage_id = int(stage_file.stem.replace('d', ''))

                if funct[stage_id] > 0:
                    st.extract_conditions(funct[stage_id])
                    name = f'{stage_file.stem.replace('d','').zfill(3)}.xml'
                    st.extract_stage_XML(original_path=self.paths['story_original'] / name,
                                         translated_path=self.paths['story_xml'] / name, keep_translations=True)

    def extract_stages_functions(self):
        start = 0x2FF0B0
        end = 0x2FF3E7
        functions = []
        with FileIO(self.paths['original_files'] / self.main_exe_name) as slps:
            slps.seek(start)

            while slps.tell() < end:
                functions.append(slps.read_uint32())
        return functions

    def decompress_file(self, compressed_file:Path):
        env = os.environ.copy()
        python = self.paths['tools'] / 'python'
        env["PATH"] = f"{python.as_posix()};{env['PATH']}"
        r = subprocess.run(
            [
                self.paths['tools'] / 'python' / 'CompressTool.exe',
                "-d",
                compressed_file
            ],
            input="\n",
            text=True,  # Treats input and output as strings
            capture_output=True,  # Saves the terminal output to result.stdout
            env=env
        )

        file_name = compressed_file.name
        dest_file = compressed_file.parent / f'{compressed_file.stem}d.bin'

        if dest_file.exists():
            dest_file.unlink()

        (compressed_file.parent / f'{file_name}.bin').rename(dest_file)

    def compress_file(self, decompressed_file:Path, lvl='9'):
        env = os.environ.copy()
        python = self.paths['tools'] / 'utilities'
        env["PATH"] = f"{python.as_posix()};{env['PATH']}"

        #r = subprocess.run(
        #    [
        #        self.paths['tools'] / 'python' / 'CompressTool.exe',
        #        "-c",
        #        str(decompressed_file),
        #        lvl
        #    ],
        #    env=env
        #)
        comp9 = decompressed_file.parent / f'{decompressed_file.stem}{lvl}.mwo'
        r = subprocess.run(
            [
                self.paths['tools'] / 'utilities' / 'SRWZ.exe',
                "-c",
                str(decompressed_file),
                str(comp9)
            ],
            env=env,
            stdout=subprocess.DEVNULL
        )

        comp_final = decompressed_file.parent / f'{decompressed_file.stem.replace("d","")}.bin'
        if comp_final.exists():
            comp_final.unlink()
        comp9.rename(comp_final)
    def extract_folder(self, folder:str):

        found = [item for file_name, item in self.archives.items() if file_name == folder]

        if len(found) > 0:

            compressed = int(found[0]['compressed'])
            for file in (self.paths['extracted_files'] /  found[0]['folder'] / folder.split('.')[0]).iterdir():

                if compressed == 1 and file.name.endswith('d.bin'):
                    self.extract_archive(file)



        else:
            print('Folder not found')

    def extract_archive(self, path:Path):

        size = os.path.getsize(path)

        with FileIO(path, 'rb') as f:

            nb_files = f.read_uint32()

            offsets = []
            for _ in range(nb_files):
                start = f.read_uint32()
                offsets.append(start)

            offsets.append(size)
            f.seek(0)
            original_data = f.read()

            for i in range(len(offsets)-1):
                data = original_data[offsets[i]:offsets[i+1]]

                ext = self.get_extension(data[:8])
                (path.parent / 'Extracted').mkdir(parents=True, exist_ok=True)

                with open(path.parent / 'Extracted' / f'{path.stem}_{i}.{ext}', 'wb') as new:
                    new.write(data)

    def get_extension(self, data:bytes):

        if data[:4] == b'TIM2':
            return 'tm2'

        else:
            return 'bin'

    def extract_all_summary(self):

        for file in (pb := tqdm((self.paths['extracted_files'] / 'DATA' / 'MTV_PROS').iterdir())):
            if str(file).endswith('d.bin'):
                mtv = MtvPros(file)
                pb.set_description(f'Extracting Summary {file.name}')
                mtv.extract_sections(self.paths['summary_original'])

    def extract_all_menus(self) -> None:

        xml_path = self.paths["menu_original"]
        xml_path.mkdir(exist_ok=True)

        # Read json descriptor file

        for entry in (pb := tqdm(self.menu_json)):
            pb.set_description(f'Extracting Menus {entry['friendly_name']}')
            if entry["file_path"] == "${main_exe}":
                file_path = self.paths["original_files"] / self.main_exe_name
            else:
                file_path = self.paths["extracted_files"] / entry["file_path"]

            with FileIO(file_path, "rb") as f:
                self.extract_menu_file(xml_path, entry, f, True)

            self.id = 1

    def extract_menu_file(self, xml_path: Path, file_def, f: FileIO, keep_translations:bool = True) -> None:

        base_offset = file_def["base_offset"]
        xml_root = etree.Element("MenuText")

        # Collect the canonical pointer for the embedded pairs
        emb = dict()
        if "embedded" in file_def:

            for section, items in file_def["embedded"].items():
                for pair in items:

                    hi_off= pair["HI"][0]
                    lo_off = pair["LO"][0]

                    f.seek(hi_off - base_offset)
                    hi = f.read_uint16() << 0x10
                    f.seek(lo_off - base_offset)
                    lo = f.read_int16()

                    offset = (hi + lo) - base_offset

                    if section in emb.keys():

                        if offset in emb[section].keys():
                            emb[section][offset][0].append(*pair["HI"])
                            emb[section][offset][1].append(*pair["LO"])

                        else:
                            emb[section][offset] = [pair["HI"], pair["LO"]]
                    else:

                        #New Section and new string
                        emb[section] = dict()
                        emb[section][offset] = [pair["HI"], pair["LO"]]

        for section in file_def['sections']:

            # Extract Pointers list out of the file
            pointers_offset = []
            pointers_value = []
            if 'pointers' in section.keys():
                for sect_pointers in section['pointers']:
                    if 'pointers_alone' in sect_pointers.keys():
                        pointers_offset, pointers_value = self.get_pointers_alone(f, sect_pointers["pointers_alone"], base_offset)
                    else:
                        pointers_start = int(sect_pointers["pointers_start"], 16) - base_offset
                        pointers_end = int(sect_pointers["pointers_end"], 16) - base_offset
                        pointers_offset_, pointers_value_ = self.get_style_pointers(f, (pointers_start, pointers_end), base_offset,
                                                                              sect_pointers['style'])
                        pointers_offset.extend(pointers_offset_)
                        pointers_value.extend(pointers_value_)

            # Make a list, we also merge the emb pointers with the
            # other kind in the case they point to the same text
            temp = dict()
            for off, val in zip(pointers_offset, pointers_value):
                text, buff = bytes_to_text(f, val)
                temp.setdefault(text, dict()).setdefault("ptr", []).append(off)

                if section['name'] in emb.keys() and val in emb[section['name']]:
                    temp[text]["emb"] = emb[section['name']].pop(val, None)

            if section['name'] in emb.keys():
                for offset, v in emb[section['name']].items():
                    text, buff = bytes_to_text(f, offset)
                    if text not in temp:
                        temp[text] = dict()
                        temp[text]["ptr"] = []

                    if "emb" in temp[text]:
                        v1 = v[0]
                        temp[text]["emb"][0].extend(v[0])
                        temp[text]["emb"][1].extend(v[1])
                    else:
                        temp[text]["emb"] = v


            # Remove duplicates
            list_informations = [(k, str(v['ptr'])[1:-1], v.setdefault('emb', None)) for k, v in temp.items()]

            # Build the XML Structure with the information
            self.create_node_XML(xml_root, list_informations, section['name'])



        # Debug
        debug = []
        df = pandas.DataFrame(debug, columns=['Text Offset', 'Text', 'Pointer Offset'])
        df['Dec'] = [int(ele, 16) for ele in df['Text Offset']]
        df['Size'] = df['Text'].apply(lambda x: len(x))
        df = df.sort_values('Dec', ascending=True)
        df.drop_duplicates(inplace=True)
        df.to_excel('../debug_menu.xlsx', index=False)

        if keep_translations:
            self.copy_translations_menu(root_original=xml_root, translated_path=self.paths['menu_xml'] / f"{file_def['friendly_name']}.xml")

        # Write to XML file
        # return etree.tostring(xml_root, encoding="UTF-8", pretty_print=True)
        file_name = file_def["friendly_name"] + ".xml"
        with open(xml_path / file_name, "wb") as xmlFile:
            xmlFile.write(etree.tostring(xml_root, encoding="UTF-8", pretty_print=True))

        # Write to XML file
        return etree.tostring(xml_root, encoding="UTF-8", pretty_print=True)

    def get_regular_pattern(self, file: FileIO, ptr_range: tuple[int, int], base_offset: int, style: str):
        split: list[str] = [ele for ele in re.split(r'([PT])|(\d+)', style) if ele]
        pointers_offset: list[int] = []
        pointers_value: list[int] = []
        file.seek(ptr_range[0])

        while file.tell() < ptr_range[1]:
            for step in split:

                if step == "P":
                    off = file.read_uint32()
                    if base_offset != 0 and off == 0: continue

                    if file.tell() - 4 < ptr_range[1] and off - base_offset > 0:
                        pointers_offset.append(file.tell() - 4)
                        pointers_value.append(off - base_offset)

                elif step == "T":
                    off = file.tell()
                    pointers_offset.append(off)
                    pointers_value.append(off)
                else:
                    file.read(int(step))

        return pointers_offset, pointers_value

    def get_all_possible(self, file: FileIO, ptr_range: tuple[int, int], base_offset: int):
        pointers_offset: list[int] = []
        pointers_value: list[int] = []
        file.seek(ptr_range[0])

        while file.tell() < ptr_range[1]:
            memory_offset = file.read_uint32()
            file_offset = memory_offset - base_offset

            if file_offset > 0:
                prev = file.read_at(file_offset - 1, 1)

                if file_offset >= 0x332B00 and prev == b'\x00':
                    pointers_offset.append(file.tell() - 4)
                    pointers_value.append(file_offset)

        return pointers_offset, pointers_value

    def get_MIPS_2nd(self, mips_1st:str, data:bytes, pos:int, register_hex:str)->int:

        start = pos

        # Find addiu
        for i in range(0,15):

            if data[pos:pos + 2] == self.mips_ops[register_hex]:
                return pos - 2
            pos += 4

        # Find lw
        pos = start -2
        print(hex(pos))
        for i in range(0,15):

            #Defect lw operation
            res = self.decode_lw(data[pos:pos+4])
            if res['is_lw'] is True and res['base'] == 'at':
                t = 2
                return pos
            pos += 4
        return -1

    def decode_lw(self, byte_data):
        # Ensure we have exactly 4 bytes
        if len(byte_data) != 4:
            raise ValueError("Expected exactly 4 bytes")

        # Convert little endian bytes → 32-bit integer
        word = int.from_bytes(byte_data, byteorder="little")

        # Extract fields
        opcode = (word >> 26) & 0x3F
        rs = (word >> 21) & 0x1F
        rt = (word >> 16) & 0x1F
        imm = word & 0xFFFF

        # Register names (MIPS standard)
        reg_names = [
            "zero", "at", "v0", "v1", "a0", "a1", "a2", "a3",
            "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7",
            "s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7",
            "t8", "t9", "k0", "k1", "gp", "sp", "fp", "ra"
        ]

        # Detect lw (opcode 0x23)
        is_lw = (opcode == 0x23)

        # Sign-extend immediate (optional but useful)
        if imm & 0x8000:
            imm_signed = imm - 0x10000
        else:
            imm_signed = imm

        result = {
            "is_lw": is_lw,
            "destination": reg_names[rt],
            "base": reg_names[rs],
            "immediate_hex": f"0x{imm:04X}",
            "immediate_signed": imm_signed
        }

        return result
    def get_MIPS_jal(self, data:bytes, pos:int)->int:
        jal_pattern = [b'\x48\x7F\x0E\x0C', b'\x68\xf1\x04\x0c', b'\xC8\x66\x0D\x0C', b'\x54\x65\x0D\x0C', b'\x6C\x65\x0D\x0C', b'\x3C\x31\x0D\x0C']


        for i in range(1, 12):
            t = data[pos:pos + 4]
            if data[pos:pos + 4] in jal_pattern :
                return pos
            pos += 4

        return -1

    def find_MIPS_pattern(self, base_hex:str, register_hex:str, file:Path):

        pattern = re.compile(bytes.fromhex(base_hex) + bytes.fromhex(register_hex))
        size = os.path.getsize(file)
        slps_base = 0xFE580
        slps_text_start = 0x440AC0

        with FileIO(file) as f:
            data = f.read()

        curpos= 0
        matches = []
        temp_pos = 0

        while True:
            m = pattern.search(data[curpos:])  # search next occurence
            if m is None: break  # no more could be found: exit loop

            pos = curpos + m.start()

            base = struct.unpack('<h',data[pos:pos+2])[0] << 16

            if pos < size - 20:
                hi = pos + slps_base

                if hi == 0x34FA64:
                    t = 2

                res = self.analyze_branch_from_bytes(data, pos - 4, slps_base)
                if res is not None and data[pos: pos+4] == data[pos +4: pos+8]:
                    #Double lui ax, ...
                    temp_pos = pos + 4
                    target_mem = res[2]
                    pos = target_mem - slps_base + 2

                else:
                    pos = pos + 6

                found_2nd_pos = self.get_MIPS_2nd(base_hex, data, pos, register_hex)

                if found_2nd_pos > -1:
                    pos = found_2nd_pos
                    lo = pos + slps_base
                    lo_value = struct.unpack('<h', data[pos:pos + 2])[0]
                    found_jal_pos = self.get_MIPS_jal(data[pos:], 0)
                    offset = base + lo_value
                    print(f'hi: {hex(hi)} lo: {hex(lo)} offset: {hex(offset)}')
                    len_d = len(data)

                    #Inside the range of text
                    if offset < 0x44627F:
                        matches.append((hi, lo, offset))

                    pos += 4

            curpos += m.end()  # next search will start after the end of found string

        return matches

    def update_MIPS_pointers_SLPS(self):
        tempmips = dict()
        base_possible = ['4400', '4300', '4200', '4100', '4500', '4600']
        register_possible = ['043C', '053C', '063C', '113C', '123C', '143C']
        slps_base = 0xFE580

        df = pandas.read_excel(self.paths['extracted_files'] / 'MIPS_Offset.xlsx', sheet_name='Offset')
        offsets_list = df['Offset'].tolist()
        offsets_list = [int(ele, 16) for ele in offsets_list]

        mips_text = []
        with FileIO(self.paths['original_files'] / 'SLPS_258.87', 'rb') as f:

            for base in base_possible:
                for register_hex in register_possible:

                    for hi, lo, text_offset in self.find_MIPS_pattern(base, register_hex,
                                                                                        self.paths["original_files"] /
                                                                                        'SLPS_258.87'):
                        section_found = [name for name, start, end in self.sections_offset if text_offset >= start and text_offset <= end]

                        if len(section_found) > 0 :
                            tempmips.setdefault(section_found[0], dict()).setdefault(text_offset, dict()).setdefault("ptr", []).append((hi,lo))
                            #text, b = bytes_to_text(f, offset= text_offset)
                            #print(f'Text: {text}')

            embed = {}
            for key, section in tempmips.items():
                sect = []
                for key_2, item in section.items():
                    hi = [ele[0] for ele in item['ptr']]
                    lo = [ele[1] for ele in item['ptr']]
                    sect.append( {"HI": hi, "LO":lo} )
                embed[key] = sect

            self.menu_json[0]['embedded'] = embed
            dumps = json.dumps(self.menu_json)
            pretty_json_str = pprint.pformat(self.menu_json, indent=4).replace("'", '"')

            with open(self.paths["menu_table"], 'w', encoding='utf-8') as f:
                f.write(pretty_json_str)

    def read_instruction_from_bytes(self, data: bytes, offset: int):
        if offset + 4 > len(data):
            return None
        # MIPS32 on PS2 is little-endian
        return struct.unpack_from('<I', data, offset)[0]

    def extract_branch_target(self, instruction: int, current_address: int) -> int:
        offset = instruction & 0xFFFF
        if offset & 0x8000:  # Sign-extend 16-bit immediate
            offset -= 0x10000
        return (current_address + 4) + (offset << 2)

    def is_beq(self, instr):
        return (instr >> 26) == 0b000100

    def is_bne(self, instr):
        return (instr >> 26) == 0b000101

    def is_blez(self, instr):
        return (instr >> 26) == 0b000110 and ((instr >> 21) & 0x1F) != 0

    def is_bgtz(self, instr):
        return (instr >> 26) == 0b000111 and ((instr >> 21) & 0x1F) != 0

    def analyze_branch_from_bytes(self, data: bytes, offset: int, base_address: int = 0):

        instr = self.read_instruction_from_bytes(data, offset)
        if instr is None:
            return None

        current_address = base_address + offset
        if self.is_beq(instr):
            return ('BEQ', hex(current_address), self.extract_branch_target(instr, current_address))
        elif self.is_bne(instr):
            return ('BNE', hex(current_address), self.extract_branch_target(instr, current_address))
        elif self.is_blez(instr):
            return ('BLEZ', hex(current_address), self.extract_branch_target(instr, current_address))
        elif self.is_bgtz(instr):
            return ('BGTZ', hex(current_address), self.extract_branch_target(instr, current_address))
        else:
            return None

    def get_style_pointers(self, file: FileIO, ptr_range: tuple[int, int], base_offset: int, style: str):

        if style == "*":
            pointers_offset, pointers_value = self.get_all_possible(file, ptr_range, base_offset)

        else:
            pointers_offset, pointers_value = self.get_regular_pattern(file, ptr_range, base_offset, style)

        return pointers_offset, pointers_value

    def get_pointers_alone(self, file: FileIO, pointers_alone, base_offset: int):

        res_offset = []
        res_value = []
        for pointer_offset in pointers_alone:
            offset = int(pointer_offset, 16)
            file.seek(offset)
            value = file.read_uint32()
            res_offset.append(offset)
            res_value.append(value - base_offset)

        return res_offset, res_value

    def create_node_XML(self, root, list_informations, section, max_len=0) -> None:
        strings_node = etree.SubElement(root, 'Strings')
        etree.SubElement(strings_node, 'Section').text = section

        for text, pointers_offset, emb in list_informations:
            self.create_entry(strings_node, pointers_offset, text, emb, max_len)

    def create_entry(self, strings_node, pointer_offset, text, emb=None, max_len=0):

        # Add it to the XML node
        entry_node = etree.SubElement(strings_node, "Entry")
        etree.SubElement(entry_node, "PointerOffset").text = str(pointer_offset).replace(", ", ",")

        if emb is not None:
            emb_node = etree.SubElement(entry_node, "EmbedOffset")
            etree.SubElement(emb_node, "hi").text = str(emb[0])[1:-1].replace(", ", ",")
            etree.SubElement(emb_node, "lo").text = str(emb[1])[1:-1].replace(", ", ",")

        if max_len != 0:
            etree.SubElement(entry_node, "MaxLength").text = str(max_len)

        etree.SubElement(entry_node, "JapaneseText").text = text

        etree.SubElement(entry_node, "EnglishText")
        etree.SubElement(entry_node, "Notes")
        #etree.SubElement(entry_node, "Id").text = str(self.id)

        self.id = self.id + 1

        if text == '':
            statusText = 'Done'
        else:
            statusText = 'To Do'

        etree.SubElement(entry_node, "Chapter").text = "Uncategorized"
        etree.SubElement(entry_node, "Status").text = statusText

    def pack_kurodata(self):
        kuro = Kurodata()
        kuro.copy_new_files(self.paths['images_updated'], self.paths['final_files'] / 'New_files' / 'KURODATA')

    def pack_mtvpros_archive(self):
        og_folder = self.paths['extracted_files'] / 'DATA' / 'MTV_PROS'
        dest_folder = self.paths['temp_files'] / 'DATA' / 'MTV_PROS'
        dest_folder.mkdir(parents=True, exist_ok=True)

        files_list = [ele for ele in og_folder.iterdir() if str(ele).endswith('d.bin')]
        offsets = [0]

        with open(self.paths['final_files'] / 'DATA' / 'MTV_PROS.BIN', 'rb+') as f:
            # Iterate on all files
            for file in files_list:
                # Copy file to destination
                shutil.copy( og_folder / file.name,
                            dest_folder / file.name )
                translated_path = self.paths['intermission_xml'] / f'{file.stem}.xml'

                bytes_new = b''
                if XML.count_translated_entries(translated_path) > 0:
                    # Pack the new file
                    mtv = MtvPros(dest_folder / file.name)
                    bytes_new = mtv.get_new_file(translated_path=translated_path, tools_path = self.paths['tools'])

                else:
                    bytes_new = open(og_folder / file.name, 'rb')

                f.write(bytes_new)
                offsets.append(bytes_new.tell())


    def patch_binaries(self):
        bin_path = self.paths["tools"] / "bin"
        cc_path = self.paths["tools"] / "bin" / "cc" / "bin"
        dll_path = self.paths["tools"] / "bin" / "dll"
        env = os.environ.copy()
        env["PATH"] = f"{bin_path.as_posix()};{cc_path.as_posix()};{dll_path.as_posix()};{env['PATH']}"

        r = subprocess.run(
            [
                str(self.paths["tools"] / "asm" / "armips.exe"),
                str(self.paths["tools"] / "asm" / "main.asm"),
                "-strequ",
                "__SLPS_PATH__",
                str(self.paths["temp_files"] / self.main_exe_name),
                "-strequ",
                "__PROP_PATH__",
                str(self.paths["font_updated"] / 'font_properties.bin'),
            ],
            env=env,
            cwd=str(self.paths["tools"] / "asm")
        )

        r2 = subprocess.run(
            [
                str(self.paths["tools"] / "asm" / "armips.exe"),
                str(self.paths["tools"] / "asm" / "kuro_stage.asm"),
                "-strequ",
                "__KURO_PATH__",
                str(self.paths["final_files"] / 'New_files' / 'KURODATA' / 'KVPDATA.BIN'),
            ],
            env=env,
            cwd=str(self.paths["tools"] / "asm")
        )
        if r.returncode != 0 or r2.returncode != 0:
            raise ValueError("Error running armips")

        (self.paths['final_files'] / 'New_files').mkdir(parents=True, exist_ok=True)
        shutil.copy(self.paths['temp_files'] / 'SLPS_258.87', self.paths['temp_files'] / 'SLPS_258.elf')
        shutil.copy(self.paths['temp_files'] / 'SLPS_258.87', self.paths['final_files'] / 'New_files' / 'SLPS_258.87')

    def copy_translations_menu(self, root_original, translated_path: Path):

        if translated_path.exists():

            original_entries = {entry_node.find('JapaneseText').text: (section.find('Section').text,) +
                                                                       self.parse_entry(entry_node) for section in
                                root_original.findall('Strings') for entry_node in section.findall('Entry')}

            tree = etree.parse(translated_path)
            root_translated = tree.getroot()
            translated_entries = {entry_node.find('JapaneseText').text: (section.find('Section').text,) +
                                                   self.parse_entry(entry_node) for section in
             root_translated.findall('Strings') for entry_node in section.findall('Entry')}


            for entry_node in root_original.iter('Entry'):

                jap_text = entry_node.find('JapaneseText').text

                if jap_text in translated_entries:

                    translated = translated_entries[jap_text]

                    if translated[2] is not None:
                        entry_node.find('EnglishText').text = translated[2]
                        entry_node.find('Status').text = translated[4]
                        entry_node.find('Notes').text = translated[5]

                        node = entry_node.find('Chapter')
                        if node is not None:
                            entry_node.find('Chapter').text = translated[6] or 'Uncategorized'
                        else:
                            etree.SubElement(entry_node, "Chapter").text = translated[6] or 'Uncategorized'


    def parse_entry(self, xml_node):

        jap_text = xml_node.find('JapaneseText').text
        eng_text = xml_node.find('EnglishText').text
        status = xml_node.find('Status').text
        notes = xml_node.find('Notes').text
        chapter_node = xml_node.find('Chapter')
        chapter = ''

        if chapter_node is not None:
            chapter = chapter_node.text

        final_text = eng_text or jap_text or ''
        return jap_text, eng_text, final_text, status, notes, chapter

    def make_iso(self):
        print("Creating new iso...")

        # We now pack the iso using every shortcut imaginable
        # because realistically we won't really touch anything
        # apart from the DAT.BIN and SLPS files
        # The logic was basically taken from PS2 Iso Rebuilder

        # Let's clean old build (if they exists)
        self.clean_builds(self.paths["game_builds"])

        # Set up new iso name
        n: datetime.datetime = datetime.datetime.now()
        new_iso = self.paths["game_builds"]
        new_iso /= f"SRWZ_{n.year:02d}{n.month:02d}{n.day:02d}{n.hour:02d}{n.minute:02d}.iso"

        with FileIO(new_iso, "wb+") as new:

            # 1st place the logo + iso data from the .ims file
            with open(self.paths["original_files"] / "_header.ims", "rb") as f:
                for _ in tqdm(range(273), desc="Copying iso header"):
                    new.write(f.read(0x800))
                anchor_save = f.read(0x800)

            # place the file data in
            files = [
                self.paths["original_files"] / "SYSTEM.CNF",
                self.paths["temp_files"] / "SLPS_254.50",
                self.paths["original_files"] / "IOPRP300.IMG",
                self.paths["original_files"] / "BOOT.IRX",
                self.paths["original_files"] / "MOV.BIN",
            ]

            for file in files:
                with open(file, "rb") as f:
                    f.seek(0, 2)
                    size = f.tell()
                    f.seek(0)
                    with tqdm(total=size, desc=f"Inserting {file.name}", unit="B", unit_divisor=1024,
                              unit_scale=True) as pbar:
                        while data := f.read(0x8000):
                            new.write(data)
                            pbar.update(len(data))
                new.write_padding(0x800)

            # Now we plop the new DAT.BIN in its legitimate spot
            sectors: list[int] = [0]
            remainders: list[int] = []
            total = (self.POINTERS_END - self.POINTERS_BEGIN) // 4
            dat_sz = 0
            for blob in tqdm(self._pack_dat_iter(sectors, remainders), total=total, desc="Inserting DAT.BIN"):
                new.write(blob)
                dat_sz += len(blob)

            # Align to nearest LBA
            new.write_padding(0x800)
            # get FIELD.BIN LBA
            fld_lba = new.tell() // 0x800

            # Now we plop FIELD.BIN in its legitimate spot
            with open(self.paths["original_files"] / "FLD.BIN", "rb") as dt:
                dt.seek(0, 2)
                fld_sz = dt.tell()
                dt.seek(0)
                with tqdm(total=fld_sz, desc="Inserting FLD.BIN", unit="B", unit_divisor=1024,
                          unit_scale=True) as pbar:
                    while data := dt.read(0x8000):
                        new.write(data)
                        pbar.update(len(data))

            # Align file and add the 20MiB pad cdvdgen adds
            new.write_padding(0x8000)
            new.write(b"\x00" * 0x13F_F800)

            # get end of volume spot
            end = new.tell()
            end_lba = end // 0x800

            # Put the Anchor in place
            new.write(anchor_save)

            # Now we update the file entries, DAT.BIN only need updated
            # size, FLD.BIN size and LBA, also update the PVD size
            new.write_int32_at(0x82992, dat_sz)
            new.write_int32_at(0x829C2, fld_lba)
            new.write_int32_at(0x8050, end_lba + 1)
            new.write_int32_at(end + 0xC, end_lba + 1)
            new.set_endian("big")
            new.write_int32_at(0x82996, dat_sz)
            new.write_int32_at(0x829C6, fld_lba)
            new.write_int32_at(0x8054, end_lba + 1)
            new.set_endian("little")

            # Finally, the SLPS, it's at the same location and size
            # so no problems for us
            new.seek((274 * 0x800) + self.POINTERS_BEGIN)
            for sector, remainder in zip(tqdm(sectors, desc="Updating SLPS offsets"), remainders):
                new.write(struct.pack("<I", sector + remainder))

    def build_ps2_iso(self, original_iso):
        # Let's clean old build (if they exists)
        self.clean_builds(self.paths["game_builds"])

        # Set up new iso name
        n: datetime.datetime = datetime.datetime.now()
        new_iso = self.paths["game_builds"]
        new_iso /= f"SRWZ_{n.year:02d}{n.month:02d}{n.day:02d}{n.hour:02d}{n.minute:02d}.iso"

        isotool.rebuild_iso(original_iso, self.paths['tools'] / 'python' / 'files.txt', self.paths['final_files'] / 'New_files', new_iso, 0)


    def pack_all_menu(self) -> None:
        xml_path = self.paths["menu_xml"]
        out_path = self.paths["temp_files"]

        # Read json descriptor file
        with open(self.paths["menu_table"], encoding="utf-8") as f:
            menu_json = json.load(f)

        for entry in (pbar := tqdm(menu_json)):

            if entry["file_path"] == "${main_exe}":
                file_path = self.paths["original_files"] / self.main_exe_name
                file_last = self.main_exe_name
            else:
                file_path = self.paths["extracted_files"] / entry["file_path"]
                file_last = entry["file_path"]

            pbar.set_description_str(entry["friendly_name"])
            base_offset = entry["base_offset"]
            pools: list[list[int]] = [[int(reg['text_start'], 16) - base_offset, int(reg['text_end'], 16) - int(reg['text_start'], 16)]
                                      for x in entry["sections"] for reg in x['regions'] if x['name'] != 'Unknown']
            pools.sort(key=lambda x: x[1])
            print(pools)

            with open(xml_path / (entry["friendly_name"] + ".xml"), "r", encoding='utf-8') as xmlFile:
                root = etree.fromstring(xmlFile.read().replace("<EnglishText></EnglishText>",
                                                               "<EnglishText empty=\"true\"></EnglishText>"),
                                        parser=etree.XMLParser(recover=True))

            with open(file_path, "rb") as f:
                file_b = f.read()

            with FileIO(file_b, "wb") as f:
                self.pack_menu_file(root, pools, base_offset, f)

                f.seek(0)
                print(out_path / file_last)
                (out_path / file_last).parent.mkdir(parents=True, exist_ok=True)
                with open(out_path / file_last, "wb") as g:
                    g.write(f.read())

    def pack_stage_archive(self):

        files_adjusted = list(range(13,20))
        files_adjusted.extend( [185, 186])
        files_adjusted = [str(ele).zfill(3) for ele in files_adjusted]
        stages_files_name = [ele for ele in (self.paths["extracted_files"] / 'DATA' / 'STAGE').iterdir() if
                             'd.' not in ele.name]
        sorted_files_name = sorted(stages_files_name)
        extracted_folder = self.paths['extracted_files'] / 'DATA' / 'STAGE'
        patched_folder = self.paths['temp_files'] / 'DATA' / 'STAGE'
        overlay_offsets = []

        with open(self.paths['final_files'] / 'New_files' / 'DATA' / 'STAGE.BIN', 'wb') as f:
            for file in sorted_files_name:
                file_path = Path(file)
                overlay_offsets.append(f.tell())

                if file_path.stem in files_adjusted:
                    data = self.pack_stage_file(file_path.stem)
                    f.write(data)

                else:
                    data = open(file_path, 'rb').read()
                    f.write(data)
                f.write(b'\x00')
                rest = -(f.tell()) & 15
                f.write(b'\x00' * rest)

            overlay_offsets.append(f.tell())

        self.update_stages_table(overlay_offsets)

    def update_stages_table(self, overlay_offsets: list):

        with FileIO(self.paths['final_files'] / 'New_files' / 'HEDBDY' / 'HB.BIN', 'rb+') as f:
            f.seek(0x7670)

            for val in overlay_offsets:
                f.write_uint32(val)

    def pack_stage_file(self, stage_name: str):

        # Copy file to destination
        dest_folder = self.paths['temp_files'] / 'DATA' / 'STAGE'
        dest_folder.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.paths['extracted_files'] / 'DATA' / 'STAGE' / f'{stage_name}d.bin',
                    dest_folder / f'{stage_name}d.bin')

        st = Stage(dest_folder / f'{stage_name}d.bin')
        st.extract_all_blocks()
        st.pack_file(dest_folder / f'{stage_name}d.bin', self.paths['story_xml'] / f'{stage_name.zfill(3)}.xml',
                     ['Translated', 'Edited'])
        st.close()
        # Compress the file
        self.compress_file(dest_folder / f'{stage_name}d.bin', '9')
        with open(dest_folder / f'{stage_name}.bin', 'rb') as f:
            return f.read()

    def pack_compdata(self):
        cp = CompData(path = self.paths['extracted_files'] / 'DATA' / 'COMPDATA' / '00d.bin')
        cp.pack_file(paths=self.paths, original_file=self.paths['extracted_files'] / 'DATA' / 'COMPDATA' / '0.bin')

    def convert_font_properties(self):
        df = pd.read_excel(self.paths['font_updated'] / 'VWF_Properties.xlsx')
        df = df.dropna(subset='Ascii')
        columns = ['Width_13', 'Width_0C', 'Width_00', 'Width_Other2']

        with FileIO(self.paths['font_updated'] / 'font_properties.bin', 'wb') as bin_file:
            for _, row in df[columns].iterrows():
                for hex_val in row:
                    int_val = int(str(hex_val), 16)
                    bin_file.write_uint8(int_val)

    def pack_font(self):
        self.convert_font_properties()

        item = self.archives['VT1.BIN']
        slps_offsets = self.extract_SLPS_offsets(item['start'], item['end'])
        vt1 = Vt1(path=self.paths['original_files'] / 'DATA' / 'VT1.BIN')
        new_offsets = vt1.pack_file(self.paths, slps_offsets)
        self.slps_offsets[item['start']] = new_offsets

    def update_slps_offsets(self):

        with FileIO(self.paths['final_files'] / "New_files" / 'SLPS_258.87', "rb+") as f:

            for start_offset, offsets in self.slps_offsets.items():
                f.seek(start_offset)

                for off in offsets:
                    f.write_uint32(off)

    def pack_menu_file(self, root, pools: list[list[int]], base_offset: int, f: FileIO, pad=False) -> None:
        entries = root.iter("Entry")
        not_valid_sections = ['Unknown']
        entries = [
            entry
            for strings in root.findall("Strings")
            if (section := strings.findtext("Section")) not in not_valid_sections
            for entry in strings.findall("Entry")
        ]

        i=0
        for line in entries:


            hi = []
            lo = []
            flat_ptrs = []

            p = line.find("EmbedOffset")
            if p is not None:
                hi = [int(x) - base_offset for x in p.find("hi").text.split(",")]
                lo = [int(x) - base_offset for x in p.find("lo").text.split(",")]

            poff = line.find("PointerOffset")
            if poff.text is not None:
                flat_ptrs = [int(x) for x in poff.text.split(",")]

            mlen = line.find("MaxLength")
            if mlen is not None:
                max_len = int(mlen.text)
                f.seek(flat_ptrs[0])
                text_bytes = self.get_node_bytes(line,pad) + b"\x00"
                if len(text_bytes) > max_len:
                    tqdm.write(
                        f"Line id {line.find('Id').text} ({line.find('JapaneseText').text}) too long, truncating...")
                    f.write(text_bytes[:max_len - 1] + b"\x00")
                else:
                    f.write(text_bytes + (b"\x00" * (max_len - len(text_bytes))))
                continue

            text_bytes = self.get_node_bytes(line,pad) + b"\x00"

            l = len(text_bytes)
            for pool in pools:

                if l <= pool[1]:
                    str_pos = pool[0]
                    pool[0] += l
                    pool[1] -= l
                    break
            else:
                print("Ran out of space")
                raise ValueError("Ran out of space")

            f.seek(str_pos)
            f.write(text_bytes)
            virt_pos = str_pos + base_offset

            for off in flat_ptrs:
                f.write_uint32_at(off, virt_pos)

            for _h, _l in zip(hi, lo):
                val_hi = (virt_pos >> 0x10) & 0xFFFF
                val_lo = (virt_pos) & 0xFFFF
                #print(f'hi pos: {hex(_h)} lo pos: {hex(_l)}')
                # can't encode the lui+addiu directly
                if val_lo >= 0x8000: val_hi += 1

                f.write_uint16_at(_h, val_hi)
                f.write_uint16_at(_l, val_lo)

            i+=1

    def get_node_bytes(self, entry_node, pad=False) -> bytes:

        # Grab the fields from the Entry in the XML
        #print(entry_node.find("JapaneseText").text)
        status = entry_node.find("Status").text
        japanese_text = entry_node.find("JapaneseText").text
        english_text = entry_node.find("EnglishText").text

        # Use the values only for Status = Done and use English if non-empty
        final_text = ''
        if status in self.list_status_insertion:
            final_text = english_text or ''
        else:
            final_text = japanese_text or ''

        #print(final_text)
        # Convert the text values to bytes using TBL, TAGS, COLORS, ...
        bytes_entry = text_to_bytes(final_text, True)

        #Pad with 00
        if pad:
            rest = 4 - len(bytes_entry) % 4 - 1
            bytes_entry += (b'\x00' * rest)

        return bytes_entry