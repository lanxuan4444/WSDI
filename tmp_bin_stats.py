# -*- coding: utf-8 -*-
import os
d = r'D:\SDI\Index\SDI'
files = [f for f in os.listdir(d) if f.endswith('.bin')]
total = sum(os.path.getsize(os.path.join(d, f)) for f in files)
print(f'bin count: {len(files)}')
print(f'total size: {total/1024/1024:.2f} MB')
big = sorted(files, key=lambda f: -os.path.getsize(os.path.join(d, f)))[:5]
for f in big:
    print(f'  {f}: {os.path.getsize(os.path.join(d,f))/1024:.0f} KB')
