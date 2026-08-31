"""
SDI (Snappy Driver Installer) .bin index file parser

Loads all .bin files by decompressing and caching them in memory,
then uses real-time binary search (bytes.find) to precisely map
each HWID to its .7z driver package.

This avoids the complex loadable_vector<T> binary format parsing
by working at the byte level.  Since each HWID is stored as a
null-terminated string in the decompressed text pool, an exact
byte match uniquely identifies the correct .bin package.
"""

import lzma
import os
import time


def _normalize_hwid(raw: str) -> str:
    """Normalize HWID: uppercase, single backslash, strip instance suffix.

    IMPORTANT: only strip the trailing segment if it really looks like an
    instance ID (pure numeric, or 7+ char hex with only 0-9A-F). Otherwise we
    accidentally strip real HWID components like 'DHPE6332_COM_0' (which has
    letters and underscores but no '&'), turning 'MF\\DHPE6332_COM_0' into
    just 'MF' — that 2-byte prefix then matches 30+ unrelated bins.
    """
    h = raw.strip().upper()
    h = h.replace('\\\\', '\\')
    if '\\' in h:
        base, _, tail = h.rpartition('\\')
        if tail and _is_instance_suffix(tail):
            h = base
    return h


def _is_instance_suffix(tail: str) -> bool:
    """Decide if the trailing segment of a HWID is an instance ID (to strip)
    or a real HWID component (to keep).

    Real instance IDs (stripped):
      - pure decimal: '0', '1', '12345'
      - 7+ hex chars: '1CC10CEB41EF', '11583659' (SubKey patterns)
      - starts with SUBSYS/REV: 'SUBSYS_12345678', 'REV_0001'
      - '5&1CC10CEB&0&1' style (registry subkey: starts with digit)

    Real HWID components (kept):
      - 'DHPE6332_COM_0' (letters + underscores + digits)
      - 'VEN_8086&DEV_1234' (starts with VEN_/DEV_/CC_ etc.)
      - 'PCI9710_COM' (alphanumeric with underscores)
    """
    if not tail:
        return False
    # SUBSYS/REV suffix
    if tail.startswith('SUBSYS') or tail.startswith('REV'):
        return True
    # Pure decimal
    if tail.isdigit():
        return True
    # 7+ hex chars only (instance subkey like '1CC10CEB41EF')
    if len(tail) >= 7 and all(c in '0123456789ABCDEF' for c in tail):
        return True
    # Registry-style subkey: starts with a digit and contains '&'
    # e.g. '5&1CC10CEB&0&1', '0&23B5F4D&0&1' — never 'VEN_8086&DEV_7AA3'
    if tail[0].isdigit() and '&' in tail:
        return True
    # Otherwise: keep (VEN_xxx, DEV_xxx, CC_xxx, letters, etc.)
    return False


def _hwid_variants(hwid: str) -> list:
    """Generate fallback variants by progressively stripping segments.

    Uses the same _is_instance_suffix check as _normalize_hwid to avoid
    stripping real HWID components like 'DHPE6332_COM_0'.
    """
    h = hwid.strip().upper()
    h = h.replace('\\\\', '\\')
    if '\\' in h:
        base, _, tail = h.rpartition('\\')
        if tail and _is_instance_suffix(tail):
            h = base
    variants = [h]
    parts = h.split('&')
    for i in range(len(parts) - 1, 0, -1):
        variants.append('&'.join(parts[:i]))
    if '&SUBSYS' in h:
        variants.append(h.split('&SUBSYS')[0])
    if '&REV' in h:
        variants.append(h.split('&REV')[0])
    out = []
    seen = set()
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


class SDIBinParser:
    """Map HWIDs to .7z packages using decompressed .bin byte cache."""

    def __init__(self, bin_dir: str):
        self.bin_dir = bin_dir
        self.hwid_map: dict = {}    # hwid_upper -> [{pkg_name, bin_file, raw_hwid}]
        self.bin_info: dict = {}    # bin_filename -> {pkg_name, size, n_hwids_approx}
        self._loaded = False
        self._bodies: dict = {}     # filename -> decompressed bytes

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_all(self) -> bool:
        if not os.path.isdir(self.bin_dir):
            print(f"[!] Index directory not found: {self.bin_dir}")
            return False

        bin_files = sorted(f for f in os.listdir(self.bin_dir) if f.endswith('.bin'))
        print(f"[*] Loading {len(bin_files)} index files...")

        loaded = 0
        failed = []
        t0 = time.time()
        for i, fname in enumerate(bin_files):
            path = os.path.join(self.bin_dir, fname)
            try:
                self._decompress_bin(path, fname)
                loaded += 1
                if (i + 1) % 20 == 0:
                    print(f"    Loaded {i + 1}/{len(bin_files)}  ({time.time() - t0:.0f}s)")
            except Exception as e:
                failed.append((fname, str(e)))
                print(f"    Warning: {fname}: {e}")

        self._loaded = True
        self.load_stats = {
            'total_bins': len(bin_files),
            'loaded_bins': loaded,
            'failed_bins': len(failed),
            'failed_list': failed[:20],
            'load_time_s': round(time.time() - t0, 1),
        }
        print(
            f"[+] {loaded}/{len(bin_files)} packs loaded ({time.time() - t0:.1f}s)"
        )
        return loaded > 0

    def search_hwid(self, hwid: str) -> list:
        """Search for a HWID. Returns list of matching entry dicts.

        Performs exact binary search in cached decompressed .bin data.
        Tries exact HWID first, then variant fallback.
        """
        if not self._loaded:
            return []

        h = _normalize_hwid(hwid)

        # Try exact match
        result = self._binary_search(h)
        if result:
            return result

        # Variant fallback
        for variant in _hwid_variants(h):
            if variant == h:
                continue
            result = self._binary_search(variant)
            if result:
                return result

        return []

    def search_hwids(self, hwids: list) -> list:
        """Search multiple HWIDs, returning deduplicated matched entries."""
        seen_pkgs = set()
        results = []
        for hwid in hwids:
            for entry in self.search_hwid(hwid):
                pkg = entry['pkg_name']
                if pkg not in seen_pkgs:
                    seen_pkgs.add(pkg)
                    results.append(entry)
        return results

    def get_pkg_list_for_hwids(self, hwids: list) -> list:
        return list(dict.fromkeys(
            e['pkg_name'] for hwid in hwids for e in self.search_hwid(hwid)
        ))

    def get_stats(self) -> dict:
        return {
            'total_packs': len(self.bin_info),
            'load_stats': getattr(self, 'load_stats', {}),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _decompress_bin(self, filepath: str, filename: str):
        with open(filepath, 'rb') as f:
            raw = f.read()

        if len(raw) < 8 or raw[:3] != b'SDW':
            raise ValueError("invalid header")

        body = raw[7:]
        flag = body[0]

        if flag == 0x00:
            try:
                decompressed = lzma.decompress(body[1:], format=lzma.FORMAT_ALONE)
            except Exception:
                decompressed = lzma.decompress(body[1:])
        elif flag == 0x01:
            decompressed = body[1:]
        else:
            raise ValueError(f"unsupported compression flag {hex(flag)}")

        self._bodies[filename] = decompressed
        self.bin_info[filename] = {
            'pkg_name': filename.replace('.bin', '.7z'),
            'size': len(decompressed),
        }

    def _binary_search(self, hwid: str) -> list:
        """Search all cached .bin bodies for an exact null-terminated HWID string."""
        query = hwid.encode('ascii')
        results = []
        for fname, body in self._bodies.items():
            idx = body.find(query)
            while idx != -1:
                # Verify null-termination: byte before must be 0 (or start),
                # byte after must be 0 (or end)
                before = body[idx - 1] if idx > 0 else 0
                after = body[idx + len(query)] if idx + len(query) < len(body) else 0
                if before == 0 and after == 0:
                    pkg = fname.replace('.bin', '.7z')
                    results.append({
                        'bin_file': fname,
                        'pkg_name': pkg,
                        'raw_hwid': hwid,
                    })
                    # Found in this bin, move to next bin
                    break
                idx = body.find(query, idx + 1)
        return results


def get_parser(bin_dir: str) -> SDIBinParser:
    p = SDIBinParser(bin_dir)
    p.load_all()
    return p


if __name__ == '__main__':
    t0 = time.time()
    parser = SDIBinParser(r'D:\SDI\Index\SDI')
    parser.load_all()
    print(f"Total load time: {time.time() - t0:.1f}s")

    for test in [
        r'USB\VID_8087&PID_0A2A',
        r'PCI\VEN_8086&DEV_1234',
        r'USB\VID_0BDA',
        r'HDAUDIO\FUNC_01&VEN_10EC',
        r'PCI\VEN_10DE&DEV_1F08',
    ]:
        r = parser.search_hwid(test)
        pkgs = ', '.join(e['pkg_name'] for e in r)
        print(f"\n{test}: {len(r)} results -> {pkgs or 'NOT FOUND'}")
