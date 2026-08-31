import urllib.request
r = urllib.request.urlopen('http://127.0.0.1:80/client_core_v25.ps1', timeout=10)
content = r.read().decode('utf-8')
# Use unicode escape for Chinese chars
target = '\u8bf7\u8f93\u5165\u8981\u4e0b\u8f7d\u7684\u7c7b\u76ee\u7f16\u53f7'
if target in content:
    print('OK_NEW')
else:
    print('FAIL_OLD')
print('Length:', len(content))
# Print bytes around the change to debug
idx = content.find(target)
if idx >= 0:
    print('FOUND at offset', idx)
else:
    # try other marker
    marker = 'A=\u5168\u90e8'
    idx2 = content.find(marker)
    print(f'A=marker at {idx2}')