import os.path
import sys
import argparse
import time
import subprocess
import shutil
from tools.python.lib.FileIO import FileIO
from pathlib import Path
from io import BytesIO
import pandas
import numpy
import itertools
from typing import Union
from multiprocessing.dummy import Pool as ThreadPool


class Decompressor():

    def __init__(self, compressed:Path=None, decompressed:Path=None):
        if compressed is not None:
            with open(compressed, 'rb') as f:
                self.compressed_data = list(f.read())
                self.compressed_size = len(self.compressed_data)

        if decompressed is not None:
            with open(decompressed, 'rb') as f:
                self.decompressed_data = list(f.read())
                self.decompressed_size = len(self.decompressed_data)

        self.results = []

    def decompress(self, source:Path, destination:Path):
        base_path = Path(os.getcwd())
        r = subprocess.run(
            [
                base_path / 'tools' / 'utilities' / 'SRWZ.exe',
                "-d",
                str(source),
                str(destination)
            ],
            input="\n",
            text=True
        )


    def decompress2(self, source: Union[Path, bytes], destination: Path, pos:int = 0):


        with open(source, 'rb') as f:
            input = numpy.array(list(f.read()))

        input_pos = pos
        pos, output_size = self.get_coded_int(input[input_pos:], 0)
        input_pos += pos

        pos, flags = self.get_coded_int(input[input_pos:], 0)
        input_pos += pos
        n2 = 1 << (((flags >> 1) & 0xF) + 8)

        if n2 > output_size:
            if (flags & 0x21) != 1 and (flags & 0x40):
                pos, temp = self.get_coded_int(input[input_pos:], 0)
                input_pos += pos

        elif flags & 0x40:
            pos, temp = self.get_coded_int(input[input_pos:], 0)
            input_pos += pos

        coded_int = []
        pos, temp = self.get_coded_int(input[input_pos:], 0)
        coded_int.append((tuple(input[input_pos:(input_pos + pos)].tolist()), temp.item(), "normal"))
        input_pos += pos

        output = [0] * output_size
        output_pos = 0

        magic_val = []
        dist_dum = []
        while output_pos < output_size:
            uncomp_len = 0
            counter = 0
            all_bytes = []

            temp = input[input_pos]
            input_pos += 1

            uncomp_len = temp & 0xF
            base_uncomp = uncomp_len
            counter = temp >> 4
            base_counter = counter
            magic_val.append((temp.item(), uncomp_len.item(), counter.item()))
            #print(f"Compressed Pos: {hex(input_pos - 1)}")
            #print(f"Byte: {hex(temp)} - Uncomp: {uncomp_len} - counter: {counter}")

            if uncomp_len == 0:
                temp2 = input_pos
                pos, uncomp_len = self.get_coded_int(input[input_pos:], 0)
                res = [hex(t) for t in input[temp2:(temp2+pos)]]
                #print(f'First temp - byte: {hex(temp)} - uncomp: {uncomp_len} - counter: {counter}')
                #print(f'Adjusted Comp - Byte: {res} - Uncomp: {uncomp_len} - counter: {counter}')
                coded_int.append((tuple(input[input_pos:(input_pos + pos)].tolist()), uncomp_len.item(), "uncomp_len"))
                input_pos += pos


            if counter == 0:
                temp2 = input_pos
                #print(f"Counter updated: {hex(temp2)}")
                pos, counter = self.get_coded_int(input[input_pos:], 0)
                res = [hex(t) for t in input[temp2:(temp2+ pos)]]

                coded_int.append((tuple(input[input_pos:(input_pos + pos)].tolist()), counter.item(), "counter"))
                input_pos += pos


            #if (base_counter != counter) or (base_uncomp != uncomp_len):
            #    print(f'Byte Updated: {hex(temp)} - Uncomp: {uncomp_len} - Counter: {counter}')

            #print(f'Dest Pos: {hex(output_pos)} - Uncomp: {uncomp_len}')
            for i in range(uncomp_len):
                output[output_pos] = input[input_pos]
                output_pos += 1
                input_pos += 1

            if output_pos == output_size: break

            for i in range(counter):
                temp = input[input_pos]
                all_bytes = []
                all_bytes.append(f'{temp:x}')
                debug = []
                debug.append(temp)
                input_pos += 1
                distance = (temp & 0xF) >> 1


                if (temp & 0x1) == 0:
                    t = input_pos
                    d_i = distance

                    pos, distance = self.get_coded_int(input[input_pos:], distance)
                    t = [f'{ele:x}' for ele in input[input_pos:(input_pos + pos)]]
                    #print(f'Bytes: {" ".join(t)} - Distance: {distance}')
                    all_bytes.append('Distance updated')
                    all_bytes.extend(t)
                    coded_int.append((tuple(input[input_pos:(input_pos + pos)].tolist()), distance.item(), "distance"))
                    input_pos += pos
                #else:
                #    print(f'Regular distance - First: {hex(temp)} - Distance: {~distance} - Size: {(temp >> 4) + 1}')

                distance = ~distance
                length = temp >> 4

                if length == 0:
                    pos, length = self.get_coded_int(input[input_pos:], 0)
                    all_bytes.append('Length updated')
                    all_bytes.extend([f'{ele:x}' for ele in input[input_pos:(input_pos + pos)]])
                    coded_int.append((tuple(input[input_pos:(input_pos + pos)].tolist()), length.item(), "length"))
                    debug.extend(input[input_pos:(input_pos + pos)])
                    input_pos += pos


                length += 1
                #print(f"Byte: {' '.join(all_bytes)} - Dist: {distance} - Length: {length}")
                dist_dum.append((distance, length, temp))
                pos = output_pos + distance

                if length + output_pos > output_size:
                    length = output_size - output_pos


                for l in range(length):
                    output[output_pos] = output[pos]
                    output_pos += 1
                    pos += 1

        dist_df = pandas.DataFrame(dist_dum)
        dist_df.to_excel('../dist_dum.xlsx', index=False)

        #pandas.DataFrame(coded_int, )
        #print(f"Original file pos: {hex(input_pos)}")
        with open(destination, 'wb') as d:
            decomp = bytes(output)
            d.write(decomp)
            return decomp

    def get_coded_int(self, buff:list, start:int):
        num = start
        pos = 0
        bytes_list = []
        while True:
            c = buff[pos]
            bytes_list.append(hex(c))
            num = (num << 7) | (c >> 1)
            pos = pos + 1

            if (c & 1) == 1:
                break

            return pos, num

    def compress(self, decompressed_file:Path, final_name:str):

        base_path = Path(os.getcwd())
        comp = (decompressed_file.parent / f'{decompressed_file.stem}9.mwo')
        r = subprocess.run(
            [
                base_path / 'tools' / 'utilities' / 'SRWZ.exe',
                "-c",
                str(decompressed_file),
                str(comp)
            ]
        )

        if (decompressed_file.parent / final_name).exists():
            (decompressed_file.parent / final_name).unlink()
        comp.rename(decompressed_file.parent / final_name)
        #shutil.copy2(decompressed_file.parent / final_name, compressed_file)

    def elements_in_array(self, check_elements, elements):
        i = 0
        offset = 0
        for element in elements:
            if len(check_elements) <= offset:
                # All of the elements in check_elements are in elements
                return i - len(check_elements)

            if check_elements[offset] == element:
                offset += 1
            else:
                offset = 0

            i += 1
        return -1

    def compress2(self, compressed_file:Path):
        text_bytes = self.decompressed_data
        max_sliding_window_size = 4096
        encoding = 'utf-8'

        search_buffer = []  # Array of integers, representing bytes
        check_characters = []  # Array of integers, representing bytes
        output = []  # Output array

        i = 0
        for char in text_bytes:
            start = time.time()
            index = self.elements_in_array(check_characters,
                                      search_buffer)  # The index where the characters appears in our search buffer
            end = time.time()
            if self.elements_in_array(check_characters + [char], search_buffer) == -1 or i == len(text_bytes) - 1:
                if i == len(text_bytes) - 1 and self.elements_in_array(check_characters + [char], search_buffer) != -1:
                    # Only if it's the last character then add the next character to the text the token is representing
                    check_characters.append(char)

                if len(check_characters) > 1:
                    index = self.elements_in_array(check_characters, search_buffer)
                    offset = i - index - len(check_characters)  # Calculate the relative offset
                    length = len(check_characters)  # Set the length of the token (how many character it represents)

                    token = f"<{offset},{length}>"  # Build our token

                    if len(token) > length:
                        # Length of token is greater than the length it represents, so output the characters
                        output.extend(check_characters)  # Output the characters
                    else:
                        output.extend(token.encode(encoding))  # Output our token

                    search_buffer.extend(check_characters)  # Add the characters to our search buffer
                else:
                    output.extend(check_characters)  # Output the character
                    search_buffer.extend(check_characters)  # Add the characters to our search buffer

                check_characters = []

            check_characters.append(char)

            if len(search_buffer) > max_sliding_window_size:  # Check to see if it exceeds the max_sliding_window_size
                search_buffer = search_buffer[1:]  # Remove the first element from the search_buffer

            i += 1

        with open(compressed_file, 'wb') as f:
            f.write(output)


def coded_int_map(possible_val:list):
    num = 0
    pos = 0
    result = []

    for val in possible_val:
        num = (num << 7) | (val >> 1)
        pos = pos + 1

        if (val & 1) == 1:  # test if number is impair
            result.append(tuple(possible_val + [num]))
            break

    return result

def calculate_coded():

    mapped_result_1 = [coded_int_map([ele1]) for ele1 in range(255)]
    mapped_result_1_filtered = [ele[0] for ele in mapped_result_1 if len(ele) > 0]
    df_1 = pandas.DataFrame(mapped_result_1_filtered, columns=["Coded1", "Decompressed"])
    df_1.to_excel('../coded1.xlsx', index=False)

    mapped_result_2 = [coded_int_map([ele1, ele2]) for ele1, ele2 in itertools.product(range(255), range(255))]
    mapped_result_2_filtered = [(ele[0][0], ele[0][1], ele[0][2]) for ele in mapped_result_2 if len(ele) > 0]
    df_2 = pandas.DataFrame(mapped_result_2_filtered, columns=["Coded1", "Coded2", "Decompressed"])
    df_2.to_excel('../coded2.xlsx', index=False)

    mapped_result_3 = [coded_int_map([ele1, ele2, ele3]) for ele1, ele2, ele3 in itertools.product(range(255), range(255), range(50))]
    mapped_result_3_filtered = [(ele[0][0], ele[0][1], ele[0][2], ele[0][3]) for ele in mapped_result_3 if
                                len(ele) > 0]
    df_3 = pandas.DataFrame(mapped_result_3_filtered, columns=["Coded1", "Coded2", "Coded3", "Decompressed"])
    df_3.to_csv('../coded3.csv', index=False)














def get_arguments(argv=None):
    # Init argument parser
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "-s",
        "--source",
        required=True,
        type=Path,
        metavar="source",
        help="source file",
    )

    parser.add_argument(
        "-d",
        "--destination",
        required=True,
        type=Path,
        metavar="destination",
        help="destination file that will be created",
    )

    args = parser.parse_args()

    return args

if __name__ == "__main__":
    args = get_arguments()

    decompress(args.source, args.destination)
