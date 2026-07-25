import os
from pathlib import Path
import lxml.etree as etree
from tools.python.lib.FileIO import FileIO
from tools.python.lib.binary_extracted import text_to_bytes, bytes_to_text, get_shift_equivalent
import pytest
import pyjson5 as json
import pdb
from io import BytesIO
base_path = Path('tools/python/tests')

@pytest.mark.parametrize("n", range(6))
def test_tags_to_text(config_tags, n):
    input = config_tags[n]['byte']
    input_bytes = bytes.fromhex(input.replace(' ',''))
    with FileIO(base_path / 'tags_to_text.bin', 'wb+') as f:
        f.write(input_bytes)
        f.write(b'\x00')
        f.seek(0)
        expected = config_tags[n]['text']
        res = bytes_to_text(f,0)[0]
        assert res == expected

@pytest.mark.parametrize("n", range(7))
def test_tags_to_byte(config_tags, n):

    input = config_tags[n]['text']

    expected = config_tags[n]['byte'].replace(' ', '')

    output_bytes = text_to_bytes(input, False)
    output = output_bytes.hex().upper()
    assert( output == expected)

def test_shift():
    c = 'S'
    output = get_shift_equivalent(c)
    assert(output == b'\x82\x72')
@pytest.fixture
def config_tags():
    with open(base_path / 'test_tags.json', encoding='utf-8') as f:
        json_data = json.load(f)
        return [{"byte":k, "text":json_data[k]} for k in json_data.keys()]

