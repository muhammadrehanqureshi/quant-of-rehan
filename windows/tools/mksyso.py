"""Write a Go .syso (COFF object, amd64) holding the Windows resources of the
exe: the icon group, its images and the version information. The Go linker
merges the .rsrc section of a .syso into the executable."""
import sys, struct

ico_path, out, version = sys.argv[1], sys.argv[2], sys.argv[3]   # version like 3.6.2.2
ico = open(ico_path, "rb").read()
_, _, n = struct.unpack_from("<HHH", ico, 0)
frames = []
for i in range(n):
    w, h, cc, res, planes, bits, size, off = struct.unpack_from("<BBBBHHII", ico, 6 + 16 * i)
    frames.append((w, h, cc, res, planes, bits, ico[off:off + size]))

# ---- resources: (type, id, data)
res_list = []
grp = struct.pack("<HHH", 0, 1, n)
for i, (w, h, cc, r, planes, bits, data) in enumerate(frames):
    grp += struct.pack("<BBBBHHIH", w, h, cc, r, planes, bits, len(data), i + 1)
    res_list.append((3, i + 1, data))
res_list.append((14, 1, grp))

def pad4(b): return b + b"\0" * ((-len(b)) % 4)
def wstr(s): return s.encode("utf-16-le") + b"\0\0"
def vnode(key, value, vtype, children=(), vlen=None):
    """One VS_VERSIONINFO style node: wLength, wValueLength, wType, key, pad,
    value, pad, children. wLength leaves out the padding after the last child."""
    b = pad4(b"\0\0" + struct.pack("<HH", len(value) if vlen is None else vlen, vtype) + wstr(key))
    b += value
    if children:
        b = pad4(b)
        b += b"".join(pad4(c) for c in children[:-1]) + children[-1]
    return struct.pack("<H", len(b)) + b[2:]

fv = tuple(int(x) for x in version.split("."))
fixed = struct.pack("<13I", 0xFEEF04BD, 0x00010000, (fv[0] << 16) | fv[1], (fv[2] << 16) | fv[3],
                    (fv[0] << 16) | fv[1], (fv[2] << 16) | fv[3], 0x3F, 0, 0x00040004, 1, 0, 0, 0)
strings = [("CompanyName", "Quant of Rehan, personal build"), ("FileDescription", "Quant of Rehan for Windows"),
           ("FileVersion", version), ("InternalName", "QuantOfRehan"), ("LegalCopyright", "Personal use"),
           ("OriginalFilename", "QuantOfRehan.exe"), ("ProductName", "Quant of Rehan"), ("ProductVersion", version)]
str_nodes = []
for k, v in strings:
    val = wstr(v)
    str_nodes.append(vnode(k, val, 1, vlen=len(val) // 2))
table = vnode("040904B0", b"", 1, str_nodes, vlen=0)
sfi = vnode("StringFileInfo", b"", 1, [table], vlen=0)
var = vnode("Translation", struct.pack("<HH", 0x0409, 0x04B0), 0, vlen=4)
vfi = vnode("VarFileInfo", b"", 1, [var], vlen=0)
ver = vnode("VS_VERSION_INFO", fixed, 0, [sfi, vfi], vlen=len(fixed))
res_list.append((16, 1, ver))

# ---- build the resource tree: type -> id -> language -> data entry
LANG = 0x0409
types = sorted(set(t for t, _, _ in res_list))
by_type = {t: sorted([(i, d) for tt, i, d in res_list if tt == t]) for t in types}

def dir_size(count): return 16 + 8 * count
root_sz = dir_size(len(types))
off = root_sz
type_dir_off = {}
for t in types:
    type_dir_off[t] = off
    off += dir_size(len(by_type[t]))
lang_dir_off = {}
for t in types:
    for i, _ in by_type[t]:
        lang_dir_off[(t, i)] = off
        off += dir_size(1)
entry_off = {}
for t in types:
    for i, _ in by_type[t]:
        entry_off[(t, i)] = off
        off += 16
data_off = {}
for t in types:
    for i, d in by_type[t]:
        data_off[(t, i)] = off
        off += (len(d) + 3) & ~3
total = off

def dirhdr(count): return struct.pack("<IIHHHH", 0, 0, 0, 0, 0, count)
buf = bytearray()
buf += dirhdr(len(types))
for t in types: buf += struct.pack("<II", t, 0x80000000 | type_dir_off[t])
for t in types:
    buf += dirhdr(len(by_type[t]))
    for i, _ in by_type[t]: buf += struct.pack("<II", i, 0x80000000 | lang_dir_off[(t, i)])
for t in types:
    for i, _ in by_type[t]:
        buf += dirhdr(1) + struct.pack("<II", LANG, entry_off[(t, i)])
relocs = []
for t in types:
    for i, d in by_type[t]:
        relocs.append(len(buf))                       # where OffsetToData sits
        buf += struct.pack("<IIII", data_off[(t, i)], len(d), 0, 0)
for t in types:
    for i, d in by_type[t]:
        assert len(buf) == data_off[(t, i)], (len(buf), data_off[(t, i)])
        buf += d + b"\0" * ((-len(d)) % 4)
assert len(buf) == total

# ---- COFF object
raw = bytes(buf)
sec_off = 20 + 40
rel_off = sec_off + len(raw)
sym_off = rel_off + 10 * len(relocs)
coff = struct.pack("<HHIIIHH", 0x8664, 1, 0, sym_off, 1, 0, 0)
coff += struct.pack("<8sIIIIIIHHI", b".rsrc", 0, 0, len(raw), sec_off, rel_off, 0, len(relocs), 0, 0x40000040)
coff += raw
for r in relocs: coff += struct.pack("<IIH", r, 0, 3)   # IMAGE_REL_AMD64_ADDR32NB against symbol 0
coff += struct.pack("<8sIhHBB", b".rsrc", 0, 1, 0, 3, 0)  # section symbol
coff += struct.pack("<I", 4)                              # empty string table
open(out, "wb").write(coff)
print("wrote", out, len(coff), "bytes,", len(res_list), "resources")
