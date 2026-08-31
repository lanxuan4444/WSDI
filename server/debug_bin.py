import lzma, struct
f = open(r'd:\WSDI\index\SDI\DP_wBluetooth_26061.bin', 'rb')
d = f.read()
body = d[7:]
decompressed = lzma.decompress(body[1:], format=lzma.FORMAT_ALONE)
print("Decompressed size:", len(decompressed))

INT32 = '<I'
INT32_S = '<i'

def read_vec8(data, offset):
    """8-byte header: count, capacity"""
    count = struct.unpack_from(INT32, data, offset)[0]
    cap = struct.unpack_from(INT32, data, offset+4)[0]
    return count, cap, offset + 8

def read_vec12(data, offset):
    """12-byte header: count, capacity, memSize"""
    count = struct.unpack_from(INT32, data, offset)[0]
    cap = struct.unpack_from(INT32, data, offset+4)[0]
    mem = struct.unpack_from(INT32, data, offset+8)[0]
    return count, cap, mem, offset + 12

# SDI serializes all vectors as: count (4), capacity (4), elements
# But "count" might be encoded differently if >= 1<<28
# 929 is way less than 1<<28, so that's not the issue

# Let me check: maybe the first value 122628 is NOT count but something else
# Could the format be: total_data_size (4), element_count (4), capacity (4)?
# 122628 / 132 = 929.0 exactly! So 122628 = 929 * 132 = total data size

# Let's try: first 4 bytes = data size, next 4 = count, next 4 = capacity
# This would explain the 12-byte header

offset = 0
data_size = struct.unpack_from(INT32, decompressed, 0)[0]
count = struct.unpack_from(INT32, decompressed, 4)[0]
cap = struct.unpack_from(INT32, decompressed, 8)[0]
print("Inffile header: data_size={} count={} cap={}".format(data_size, count, cap))
print("  data_size / 132 =", data_size / 132)
print("  count * 132 =", count * 132)
offset = 12

# Now the actual inffile data
inffile_data_end = offset + data_size
print("  inffile data: {} -> {}".format(offset, inffile_data_end))

# Next vector
data_size2 = struct.unpack_from(INT32, decompressed, inffile_data_end)[0]
count2 = struct.unpack_from(INT32, decompressed, inffile_data_end+4)[0]
cap2 = struct.unpack_from(INT32, decompressed, inffile_data_end+8)[0]
print("Manufacturer header: data_size={} count={} cap={}".format(data_size2, count2, cap2))
print("  data_size / 16 =", data_size2 / 16)

manuf_data_end = inffile_data_end + 12 + data_size2
print("  manuf data: {} -> {}".format(inffile_data_end + 12, manuf_data_end))

# Next vector
data_size3 = struct.unpack_from(INT32, decompressed, manuf_data_end)[0]
count3 = struct.unpack_from(INT32, decompressed, manuf_data_end+4)[0]
cap3 = struct.unpack_from(INT32, decompressed, manuf_data_end+8)[0]
print("Desc header: data_size={} count={} cap={}".format(data_size3, count3, cap3))
print("  data_size / 24 =", data_size3 / 24)

desc_data_end = manuf_data_end + 12 + data_size3

# Next
data_size4 = struct.unpack_from(INT32, decompressed, desc_data_end)[0]
count4 = struct.unpack_from(INT32, decompressed, desc_data_end+4)[0]
cap4 = struct.unpack_from(INT32, decompressed, desc_data_end+8)[0]
print("HWID header: data_size={} count={} cap={}".format(data_size4, count4, cap4))
print("  data_size / 12 =", data_size4 / 12)

hwid_data_end = desc_data_end + 12 + data_size4

# Next
data_size5 = struct.unpack_from(INT32, decompressed, hwid_data_end)[0]
count5 = struct.unpack_from(INT32, decompressed, hwid_data_end+4)[0]
cap5 = struct.unpack_from(INT32, decompressed, hwid_data_end+8)[0]
print("Text header: data_size={} count={} cap={}".format(data_size5, count5, cap5))

text_end = hwid_data_end + 12 + data_size5
print("Total: {} / {} ({}%)".format(text_end, len(decompressed), text_end*100//len(decompressed)))
print("HWID count:", count4)
