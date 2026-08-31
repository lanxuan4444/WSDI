"""Test FTP connection - Python 3.15 compatible"""
from ftplib import FTP
import traceback

HOST = "192.168.1.88"
USER = "anonymous"
PASS = "anonymous@"
FTP_DIR = "/LDTLog"

print("=" * 60)
print("Test 1: Connect + CWD + NLST (default mode)")
print("=" * 60)
try:
    ftp = FTP(timeout=10)
    ftp.connect(HOST)
    ftp.login(USER, PASS)
    print(f"  Connected. passiveserver={ftp.passiveserver}")
    print(f"  CWD to {FTP_DIR}...")
    ftp.cwd(FTP_DIR)
    print(f"  CWD OK")
    print(f"  NLST...")
    files = ftp.nlst()
    print(f"  NLST returned {len(files)} items")
    for f in files[:5]:
        print(f"    {f}")
    ftp.quit()
    print("  SUCCESS")
except Exception as e:
    print(f"  ERROR: {e}")
    traceback.print_exc()

print()
print("=" * 60)
print("Test 2: List root first")
print("=" * 60)
try:
    ftp = FTP(timeout=10)
    ftp.connect(HOST)
    ftp.login(USER, PASS)
    print(f"  passiveserver={ftp.passiveserver}")
    print("  Root NLST:")
    root = ftp.nlst()
    print(f"    {len(root)} items")
    for f in root[:10]:
        print(f"    {f}")
    ftp.quit()
except Exception as e:
    print(f"  ERROR: {e}")
    traceback.print_exc()

print()
print("=" * 60)
print("Test 3: try dir() not nlst()")
print("=" * 60)
try:
    ftp = FTP(timeout=10)
    ftp.connect(HOST)
    ftp.login(USER, PASS)
    ftp.cwd(FTP_DIR)
    print("  DIR output:")
    lines = []
    ftp.dir(lines.append)
    for line in lines[:5]:
        print(f"    {line}")
    print(f"  Total: {len(lines)} lines")
    ftp.quit()
except Exception as e:
    print(f"  ERROR: {e}")
    traceback.print_exc()
