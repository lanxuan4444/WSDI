"""Brute-force analyze .bin format to find correct header layout."""
import struct
import lzma
import os
import sys

SIZES = [132, 16, 24, 12]  # inffile, manufacturer, desc, hwid
NAMES = ['inffile', 'manufacturer', 'desc', 'hwid']


def load_body(path):
    with open(path, 'rb') as f:
        raw = f.read()
    body = raw[7:]
    if body[0] == 0x00:
        return lzma.decompress(body[1:], format=lzma.FORMAT_ALONE)
    return body[1:]


def try_parse(body, verbose=True):
    """Try to parse all 4 vector blocks with 12-byte headers.

    Header format: data_size(4), count(4), capacity(4)
    Constraint: data_size == count * elem_size
    Returns list of (name, count, data_start, data_end) or None.
    """
    offset = 0
    blocks = []
    for name, esz in zip(NAMES, SIZES):
        if offset + 12 > len(body):
            return None
        ds, cnt, cap = struct.unpack_from('<3I', body, offset)
        # Validate
        if ds != cnt * esz:
            if verbose:
                print(f'  {name}: FAIL ds={ds} cnt={cnt} esz={esz} (ds != cnt*esz)')
            return None
        blocks.append((name, cnt, offset + 12, offset + 12 + ds))
        offset += 12 + ds
    return blocks, offset


def try_parse_8byte(body, verbose=True):
    """Try 8-byte headers: count(4), capacity(4), then data."""
    offset = 0
    blocks = []
    for name, esz in zip(NAMES, SIZES):
        if offset + 8 > len(body):
            return None
        cnt, cap = struct.unpack_from('<2I', body, offset)
        if cnt > 500000 or cap > 500000:
            if verbose:
                print(f'  {name}: FAIL cnt={cnt} cap={cap} unreasonable')
            return None
        data_start = offset + 8
        data_end = data_start + cnt * esz
        if data_end > len(body):
            if verbose:
                print(f'  {name}: FAIL end={data_end} > size={len(body)}')
            return None
        blocks.append((name, cnt, data_start, data_end))
        offset = data_end
    return blocks, offset


def analyze(path):
    body = load_body(path)
    fname = os.path.basename(path)
    print(f'=== {fname} ({len(body)} bytes) ===')

    # Show first header values
    v0, v1, v2 = struct.unpack_from('<3I', body, 0)
    print(f'  first 3 ints: {v0}, {v1}, {v2}')
    print(f'  v0/132 = {v0/132:.3f}')

    # Try 12-byte format
    print('  Trying 12-byte headers (ds, cnt, cap)...')
    result = try_parse(body)
    if result:
        blocks, offset = result
        print(f'  OK! Blocks:')
        for name, cnt, s, e in blocks:
            print(f'    {name}: count={cnt} data=[{s}:{e}]')
        print(f'  After 4 blocks: offset={offset}, remaining={len(body)-offset}')
        # Txt block
        tc, tcap, tmem = struct.unpack_from('<3I', body, offset)
        print(f'  Txt: count={tc} cap={tcap} mem={tmem}')
        text_start = offset + 12
        text_end = text_start + tmem
        print(f'  Txt data=[{text_start}:{text_end}], remaining={len(body)-text_end}')
        return blocks, text_start, tmem
    else:
        print('  12-byte failed')

    # Try 8-byte format
    print('  Trying 8-byte headers (cnt, cap)...')
    result = try_parse_8byte(body)
    if result:
        blocks, offset = result
        print(f'  OK! offset after blocks={offset}')
        tc, tcap, tmem = struct.unpack_from('<3I', body, offset)
        print(f'  Txt: count={tc} cap={tcap} mem={tmem}')
        return blocks, offset + 12, tmem
    else:
        print('  8-byte failed')

    return None


if __name__ == '__main__':
    bin_dir = r'D:\WSDI\index\SDI'
    files = sorted(f for f in os.listdir(bin_dir) if f.endswith('.bin'))
    # Test a few files
    for fname in ['DP_MTD_custom.bin', 'DP_Battery_custom.bin', 'DP_wBluetooth_26061.bin',
                  'DP_Chipset_26061.bin', 'DP_LAN_Realtek_26054.bin']:
        path = os.path.join(bin_dir, fname)
        if os.path.exists(path):
            analyze(path)
            print()
