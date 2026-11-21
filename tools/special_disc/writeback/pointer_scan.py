"""Aligned 32-bit words of a decoded member that point into one slot."""
import numpy


def sites_into(data, base, offset, capacity):
    """(sites, interior): byte offsets of the aligned little-endian words whose value minus ``base`` lies in
    [offset, offset + capacity), in ascending order, and whether any of them points past the slot's start.

    The same answer as testing every fourth byte with struct.unpack_from; one vector pass instead of a
    Python loop over the whole member for every slot."""
    words = numpy.frombuffer(data, dtype='<u4', count=len(data) // 4).astype(numpy.int64)
    target = words - base
    hits = numpy.nonzero((target >= offset) & (target < offset + capacity))[0]
    return (hits * 4).tolist(), bool((target[hits] != offset).any())
