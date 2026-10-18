# -*- coding: utf-8 -*-
"""Parse SDI log: extract device -> candidate drivers (packname, status) blocks."""
import re, io, sys

log = r'C:\Users\Administrator\AppData\Local\Temp\SDI_logs\2026_10_16__17_38_40__DESKTOP-49J0UHU_log.txt'
text = open(log, 'r', encoding='utf-8', errors='replace').read()
lines = text.split('\n')
print(f'total lines: {len(lines)}')

# Find matcher section structure: look for candidate table rows.
# Header: 'altsectscore | score | date | decorscore | markerscore | status | drvsection | packname | infcrc | inffile | manuf | version | HWID | drvdesc'
hdr_idx = [i for i, l in enumerate(lines) if 'altsectscore | score' in l]
print(f'candidate-table headers found: {len(hdr_idx)}')

# Show one full block around the first header to understand format
if hdr_idx:
    i = hdr_idx[0]
    print('--- context around first candidate table ---')
    for j in range(max(0, i-40), min(len(lines), i+15)):
        print(f'{j:6d}: {lines[j]}')
