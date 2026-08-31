# -*- coding: utf-8 -*-
"""
Faster index builder: uses 7z to get all .inf content in one call per package.
"""
import subprocess, json, os, sys, re, time, tempfile, shutil
from pathlib import Path

def parse_inf_hwids(inf_path):
    """Parse a single .inf file and extract HWIDs."""
    hwids = set()
    valid_prefixes = {
        'PCI\\', 'USB\\', 'ACPI\\', 'HID\\', 'SCSI\\', 'IDE\\', 'SATA\\',
        'NVME\\', 'SWC\\', 'BTH\\', 'ROOT\\', 'I2C\\', 'SPI\\', 'UART\\',
        'GPIO\\', 'SERENUM\\', 'COMPOSITE\\', 'DISPLAY\\', 'HDAUDIO\\',
        'MEDIA\\', 'MONITOR\\', 'NET\\', 'PORTS\\', 'PRINTER\\',
        'PROCESSOR\\', 'STORAGE\\', 'SYSTEM\\', '*',
    }
    
    try:
        with open(inf_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except Exception:
        return hwids
    
    lines = content.split('\n')
    for line in lines:
        line = line.strip()
        if not line or line.startswith(';') or line.startswith('#'):
            continue
        if '=' not in line or ',' not in line:
            continue
        parts = line.split(',')
        for part in parts[1:]:
            hwid = part.strip().strip('"').strip("'")
            if not hwid:
                continue
            hwid_upper = hwid.upper()
            for prefix in valid_prefixes:
                if hwid_upper.startswith(prefix):
                    hwids.add(hwid_upper)
                    if '&SUBSYS' in hwid_upper:
                        hwids.add(hwid_upper.split('&SUBSYS')[0])
                    if '&REV' in hwid_upper:
                        hwids.add(hwid_upper.split('&REV')[0])
                    break
    return hwids

def main():
    drivers_dir = sys.argv[1] if len(sys.argv) > 1 else r'D:\SDI\Drivers'
    output_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), 'driver_index.json')
    
    # Find 7z
    sevz = os.path.join(os.path.dirname(__file__), '7z.exe')
    seven_zip = sevz if os.path.exists(sevz) else r'C:\Program Files\7-Zip\7z.exe'
    if not os.path.exists(seven_zip):
        seven_zip = r'C:\Program Files (x86)\7-Zip\7z.exe'
    if not os.path.exists(seven_zip):
        seven_zip = '7z.exe'
    
    pkg_files = sorted(Path(drivers_dir).glob('*.7z'))
    print(f'Found {len(pkg_files)} packages')
    
    index = {}
    if os.path.exists(output_path):
        with open(output_path, 'r', encoding='utf-8') as f:
            index = json.load(f)
        print(f'Loaded existing index: {len(index)-1} HWIDs')
    
    if '_packages_indexed' not in index:
        index['_packages_indexed'] = {}
    
    # Use a short temp dir to avoid path length issues
    temp_base = os.path.join(tempfile.gettempdir(), 'sdi_idx')
    
    for i, pkg_path in enumerate(pkg_files):
        pkg_name = pkg_path.name
        pkg_stem = pkg_path.stem
        
        if pkg_stem in index['_packages_indexed']:
            continue
        
        print(f'[{i+1}/{len(pkg_files)}] {pkg_name}', end=' ', flush=True)
        t0 = time.time()
        
        try:
            # Get file list (binary mode to avoid UnicodeDecodeError)
            r = subprocess.run([seven_zip, 'l', '-slt', str(pkg_path), '-r', '*.inf'],
                capture_output=True, timeout=60)
            stdout = r.stdout.decode('utf-8', errors='replace')
            
            inf_files = []
            for line in stdout.split('\n'):
                if line.startswith('Path = '):
                    f = line[7:].strip()
                    if f.lower().endswith('.inf'):
                        inf_files.append(f)
            
            if not inf_files:
                print('(no .inf files)')
                index['_packages_indexed'][pkg_stem] = {'file': pkg_name, 'size': pkg_path.stat().st_size, 'hwid_count': 0}
                continue
            
            # Extract all .inf to a short temp directory (avoids path length errors)
            temp_dir = os.path.join(temp_base, pkg_stem[:20])
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
            os.makedirs(temp_dir, exist_ok=True)
            
            r = subprocess.run([seven_zip, 'x', str(pkg_path), '-o' + temp_dir, '-y', '-r', '*.inf'],
                capture_output=True, timeout=120)
            
            all_hwids = set()
            # Find all extracted .inf files and parse them
            for root, dirs, files in os.walk(temp_dir):
                for f in files:
                    if f.lower().endswith('.inf'):
                        inf_path = os.path.join(root, f)
                        hwids = parse_inf_hwids(inf_path)
                        all_hwids.update(hwids)
            
            # Clean up temp
            shutil.rmtree(temp_dir, ignore_errors=True)
            
            for hwid in all_hwids:
                if hwid not in index:
                    index[hwid] = []
                if pkg_name not in index[hwid]:
                    index[hwid].append(pkg_name)
            
            index['_packages_indexed'][pkg_stem] = {
                'file': pkg_name,
                'size': pkg_path.stat().st_size,
                'hwid_count': len(all_hwids),
            }
            
            dt = time.time() - t0
            print(f'-> {len(all_hwids)} HWIDs ({dt:.1f}s)')
            
        except subprocess.TimeoutExpired:
            print('TIMEOUT')
        except Exception as e:
            print(f'ERROR: {e}')
    
    # Clean up base temp dir
    shutil.rmtree(temp_base, ignore_errors=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    
    size_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f'\nSaved: {output_path} ({size_mb:.1f} MB)')
    print(f'HWIDs: {len(index)-1}, Packages: {len(index["_packages_indexed"])}')

if __name__ == '__main__':
    main()
