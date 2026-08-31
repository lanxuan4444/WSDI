import json
f = open(r'D:\WSDI\server\driver_index.json', 'r', encoding='utf-8')
idx = json.load(f)
f.close()
test = 'USB\\VID_8087&PID_0A2A'
print('Found:', test in idx)
if test in idx:
    print(json.dumps(idx[test], indent=2, ensure_ascii=False)[:500])
else:
    parts = test.split('&')
    for i in range(len(parts), 0, -1):
        partial = '&'.join(parts[:i])
        if partial in idx:
            print(f'Partial [{partial}]:', json.dumps(idx[partial], indent=2, ensure_ascii=False)[:500])
            break
