"""Debug: raw rclone lsjson recursive output for tools/"""
import subprocess, json

rclone = r"D:\WSDI\tools\rclone-v1.67.0-windows-amd64\rclone.exe"
conf = r"D:\WSDI\tools\rclone.conf"
remote = "wsdi-b2:wsdi-drivers"

result = subprocess.run(
    [rclone, "lsjson", remote, "--config", conf, "--recursive"],
    capture_output=True, text=True, timeout=120,
)
print(f"returncode: {result.returncode}")
if result.returncode == 0:
    data = json.loads(result.stdout)
    print(f"Total: {len(data)}")
    for f in data:
        if 'tools' in f['Name'].lower() or 'readme' in f['Name'].lower():
            print(f"  MATCH: {json.dumps(f)}")
else:
    print(f"stderr: {result.stderr}")
