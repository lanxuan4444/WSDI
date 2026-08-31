#!/usr/bin/env python3
"""
sync_ftp.py — 从 FTP 服务器下载 LDTools 加密日志文件

用法:
    python sync_ftp.py

功能:
    1. 连接 FTP 服务器 (192.168.1.88, 匿名登录)
    2. 进入 /LDTLog 目录
    3. 下载所有 .json 加密文件到 ./enc/ 目录
    4. 生成 enc/manifest.json (文件列表)

注意:
    - 此脚本只负责下载加密文件，不做处理
    - 处理由前端 Web Crypto API 在浏览器中完成
    - 可随时重新运行以同步最新数据
"""

import os
import sys
import json
import socket
from ftplib import FTP

# ======================== 配置 ========================
FTP_HOST = "192.168.1.88"
FTP_USER = "anonymous"
FTP_PASS = "anonymous@"
FTP_DIR  = "/LDTLog"

# 脚本所在目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 加密文件保存目录
ENC_DIR    = os.path.join(SCRIPT_DIR, "enc")
# 清单文件
MANIFEST   = os.path.join(ENC_DIR, "manifest.json")

socket.setdefaulttimeout(30)


def main():
    # 创建目录
    os.makedirs(ENC_DIR, exist_ok=True)

    print(f"正在连接 FTP {FTP_HOST} ...")
    try:
        ftp = FTP(FTP_HOST, timeout=30)
        ftp.login(FTP_USER, FTP_PASS)
        print("✓ 连接成功")
    except Exception as e:
        print(f"✗ 连接失败: {e}")
        sys.exit(1)

    # 进入日志目录
    try:
        ftp.cwd(FTP_DIR)
        print(f"✓ 已进入 {FTP_DIR}")
    except Exception as e:
        print(f"✗ 无法进入目录 {FTP_DIR}: {e}")
        sys.exit(1)

    # 列出所有 .json 文件
    try:
        all_items = ftp.nlst()
        json_files = [f for f in all_items if f.lower().endswith(".json")]
    except Exception as e:
        print(f"✗ 无法列出文件: {e}")
        sys.exit(1)

    if not json_files:
        print("✗ 未找到任何 .json 文件")
        sys.exit(1)

    print(f"共发现 {len(json_files)} 个加密日志文件\n")

    # 下载文件
    downloaded = []
    failed = []

    for i, fname in enumerate(json_files, 1):
        local_path = os.path.join(ENC_DIR, fname)
        try:
            with open(local_path, "wb") as f:
                ftp.retrbinary(f"RETR {fname}", f.write)
            file_size = os.path.getsize(local_path)
            downloaded.append(fname)
            print(f"  [{i:>3}/{len(json_files)}] {fname}  ({file_size:,} bytes)")
        except Exception as e:
            failed.append((fname, str(e)))
            print(f"  [{i:>3}/{len(json_files)}] {fname}  ✗ 失败: {e}")
            # 清理不完整文件
            if os.path.exists(local_path):
                os.remove(local_path)

    ftp.quit()
    print(f"\n✓ 下载完成: {len(downloaded)} 个文件")
    if failed:
        print(f"✗ 失败: {len(failed)} 个文件")

    # 生成清单文件
    manifest = {
        "server": FTP_HOST,
        "directory": FTP_DIR,
        "total": len(downloaded),
        "files": downloaded,
    }
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"✓ 清单已生成: {MANIFEST}")
    print(f"\n现在可以用浏览器打开 index.html 查看日志（需通过 HTTP 服务器访问）")


if __name__ == "__main__":
    main()
