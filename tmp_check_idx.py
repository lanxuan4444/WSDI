# -*- coding: utf-8 -*-
import os
for d in [r'D:\WSDI\Index\SDI', r'D:\SDI\Index\SDI']:
    if os.path.isdir(d):
        bins = [f for f in os.listdir(d) if f.endswith('.bin')]
        print(f'{d}: {len(bins)} bins')
    else:
        print(f'{d}: NOT EXIST')
