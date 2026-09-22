"""Use the fast compressor first; exhaust the portfolio only for tight slots."""
from srwz.codec import SrwzEncodeError, reencode_changed_suffix


def encode_slot(before, after, *, max_output_size, original_result):
    try:
        return reencode_changed_suffix(before, after, strategy='rust-fit',
            max_output_size=max_output_size, original_result=original_result)
    except SrwzEncodeError:
        return reencode_changed_suffix(before, after, strategy='rust-maximum',
            max_output_size=max_output_size, original_result=original_result)
