"""
WSDI B2 模块 - 跟踪哪些大文件已经上传到 B2，并生成签名下载 URL

启动时从 B2 拉一份文件清单缓存到内存，server.py 的 get_file_url 据此判断：
- 文件 size > LARGE_FILE_THRESHOLD 且 已上传到 B2 → 走 /api/b2/<filename> (WSDI server 302 重定向到 B2)
- 否则 → 走本地 + CF 缓存

文件清单每 10 分钟自动刷新一次（新增/重传文件后无需重启 server）。

签名 URL 流程：
1. 客户端访问 https://yanhong.online/api/b2/xxx.7z
2. cloudflared 转发到 WSDI server (localhost:80)
3. WSDI server 调 B2 API b2_get_download_authorization 拿临时签名 token（1 小时有效）
4. WSDI server 302 重定向到 https://f004.backblazeb2.com/file/wsdi-drivers/xxx.7z?Authorization=xxx
5. 客户端直连 B2 下载（走 CF Bandwidth Alliance → 流量免费）
"""

import os
import sys
import json
import threading
import time
import subprocess
import urllib.request
import base64

from urllib.parse import quote

# ---- 敏感配置：优先从 config_secret.py 读取（该文件不入库），回退到环境变量 ----
def _load_secret(name, default=None):
    """从 config_secret.py 读取；若缺失则回退到环境变量。"""
    return getattr(_SECRET, name, None) or os.environ.get(name, default)


# 尝试加载不入库的本地密钥文件（可能不存在）
try:
    from config_secret import *
    _SECRET = sys.modules['config_secret']
except Exception:
    # 提供空容器，_load_secret 会回退到环境变量
    class _SECRET:
        pass

# ---- 配置 ----
RCLONE_PATH = _load_secret('RCLONE_PATH', r"D:\WSDI\tools\rclone-v1.67.0-windows-amd64\rclone.exe")
RCLONE_CONF = _load_secret('RCLONE_CONF', r"D:\WSDI\tools\rclone.conf")
REMOTE = _load_secret('REMOTE', "wsdi-b2:wsdi-drivers")

LARGE_FILE_THRESHOLD = 512 * 1024 * 1024  # 512MB

# B2 凭据
B2_KEY_ID = _load_secret('B2_KEY_ID')
B2_APP_KEY = _load_secret('B2_APP_KEY')
B2_BUCKET_NAME = _load_secret('B2_BUCKET_NAME', 'wsdi-drivers')
B2_BUCKET_ID = _load_secret('B2_BUCKET_ID')
B2_API_BASE = _load_secret('B2_API_BASE', 'https://api004.backblazeb2.com')

# 若 config_secret 与环境变量都缺，运行时给出明确报错
if not B2_KEY_ID or not B2_APP_KEY:
    raise RuntimeError(
        "B2 凭据缺失：请创建 server/config_secret.py 或设置 B2_KEY_ID/B2_APP_KEY 环境变量"
    )

# 签名 URL 有效期（秒），7 天（B2 最大值），任何网络都能下完
AUTH_DURATION = 604800

# B2 通过 CF Worker 代理（走 Bandwidth Alliance，流量免费）
# 客户端访问 b2.yanhong.online/xxx.7z → CF Worker → B2 签名 URL → 302 → 客户端直连 B2
# 流量路径：客户端 → CF edge → B2 → CF edge → 客户端（Bandwidth Alliance 免费）
B2_PROXY_BASE = "https://b2.yanhong.online"

# 本地 + CF 缓存
LOCAL_PROXY_BASE = "https://yanhong.online/files"

# 缓存
_b2_files = None  # set of filenames that exist in B2
_b2_files_lock = threading.Lock()
_last_refresh = 0
_refresh_interval = 600  # 10 分钟刷新一次

# B2 auth token 缓存（避免每次请求都重新认证）
_auth_cache = None  # { token, apiUrl, downloadUrl, expireAt }
_auth_lock = threading.Lock()


def _list_b2_files():
    """调 rclone lsjson 列出 B2 桶内所有文件名。"""
    try:
        result = subprocess.run(
            [RCLONE_PATH, "lsjson", REMOTE, "--config", RCLONE_CONF],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(f"[!] rclone lsjson failed: {result.stderr.strip()}")
            return set()
        files = json.loads(result.stdout)
        return {f["Name"] for f in files}
    except Exception as e:
        print(f"[!] B2 file list failed: {e}")
        return set()


def refresh_b2_files():
    """重新拉 B2 文件清单。"""
    global _b2_files, _last_refresh
    files = _list_b2_files()
    with _b2_files_lock:
        _b2_files = files
        _last_refresh = time.time()
    print(f"[+] B2 file list refreshed: {len(files)} files in B2")
    return files


def get_b2_files():
    """获取 B2 文件清单（带自动刷新）。"""
    global _last_refresh
    with _b2_files_lock:
        if _b2_files is None or (time.time() - _last_refresh) > _refresh_interval:
            pass
    if _b2_files is None or (time.time() - _last_refresh) > _refresh_interval:
        refresh_b2_files()
    with _b2_files_lock:
        return _b2_files or set()


def is_on_b2(filename):
    """判断某文件是否已上传到 B2。"""
    return filename in get_b2_files()


def list_b2_files_with_meta(prefix=None):
    """列出 B2 桶内所有文件，包含元信息（Size/ModTime/MimeType）。

    Args:
        prefix: 可选前缀过滤（如 'tools/'）；None 表示全部

    Returns:
        list of dict: [{ name, size, mod_time, mime_type }, ...]
    """
    try:
        result = subprocess.run(
            [RCLONE_PATH, "lsjson", REMOTE, "--config", RCLONE_CONF, "--recursive"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(f"[!] rclone lsjson failed: {result.stderr.strip()}")
            return []
        files = json.loads(result.stdout)
        out = []
        for f in files:
            # rclone lsjson recursive 返回：Path 是完整路径（如 tools/README.txt），
            # Name 只是文件名（README.txt）。必须用 Path 做前缀匹配和返回。
            path = f.get("Path", f.get("Name", ""))
            if f.get("IsDir"):
                continue
            if prefix and not path.startswith(prefix):
                continue
            out.append({
                "name": path,
                "size": f.get("Size", 0),
                "mod_time": f.get("ModTime", ""),
                "mime_type": f.get("MimeType", ""),
            })
        return out
    except Exception as e:
        print(f"[!] B2 file list with meta failed: {e}")
        return []


def get_file_url(filename, prefix="Drivers/", file_size=0):
    """根据是否在 B2 上，返回正确的 URL。

    所有上传到 B2 的文件都走 CF Worker 代理（Bandwidth Alliance 免流量）。
    这样小文件（< 512MB）也不依赖本地服务器 + CF 缓存，避免 CF 不稳定导致 404。

    Args:
        filename: 文件名（如 DP_xxx.7z）
        prefix: 路径前缀（Drivers/ 或 Index/SDI/）—— 仅用于 B2 上不存在时的回退
        file_size: 文件大小（字节），0 表示未知

    Returns:
        URL 字符串
    """
    safe = quote(filename, safe="/")

    # 只要文件在 B2 上就走 B2（不管大小）
    if is_on_b2(filename):
        return f"{B2_PROXY_BASE}/{safe}"

    # 回退：本地 + CF 缓存（B2 上没有的文件）
    return f"{LOCAL_PROXY_BASE}/{prefix}{safe}"


# ============================================================
# B2 API 调用：生成签名下载 URL
# ============================================================

def _b2_authorize_account():
    """调 B2 API b2_authorize_account 拿 auth token 和 download URL。"""
    global _auth_cache
    now = time.time()
    with _auth_lock:
        if _auth_cache and _auth_cache['expireAt'] > now + 60:
            return _auth_cache

    basic = base64.b64encode(f"{B2_KEY_ID}:{B2_APP_KEY}".encode()).decode()
    req = urllib.request.Request(
        f"{B2_API_BASE}/b2api/v3/b2_authorize_account",
        headers={'Authorization': f'Basic {basic}'}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        with _auth_lock:
            _auth_cache = {
                'token': data['authorizationToken'],
                'apiUrl': data['apiInfo']['storageApi']['apiUrl'],
                'downloadUrl': data['apiInfo']['storageApi']['downloadUrl'],
                'expireAt': now + 23 * 3600,  # 23 小时刷新
            }
        print(f"[+] B2 auth token refreshed (valid 23h)")
        return _auth_cache
    except Exception as e:
        print(f"[!] B2 authorize failed: {e}")
        return None


def get_signed_download_url(filename):
    """生成 B2 临时签名下载 URL。

    Args:
        filename: B2 桶里的文件名（如 DP_xxx.7z）

    Returns:
        签名 URL 字符串，或 None（失败时）
    """
    auth = _b2_authorize_account()
    if not auth:
        return None

    # 调 b2_get_download_authorization 拿临时 token
    body = json.dumps({
        'bucketId': B2_BUCKET_ID,
        'fileNamePrefix': filename,
        'validDurationInSeconds': AUTH_DURATION,
    }).encode()
    req = urllib.request.Request(
        f"{auth['apiUrl']}/b2api/v3/b2_get_download_authorization",
        data=body,
        method='POST',
        headers={
            'Authorization': auth['token'],
            'Content-Type': 'application/json',
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        # 构造完整下载 URL
        signed_token = data['authorizationToken']
        url = f"{auth['downloadUrl']}/file/{B2_BUCKET_NAME}/{quote(filename)}?Authorization={quote(signed_token)}"
        return url
    except Exception as e:
        print(f"[!] B2 get_download_authorization failed: {e}")
        return None


def start_background_refresh():
    """启动后台线程，定期刷新 B2 文件清单。"""
    def worker():
        while True:
            try:
                refresh_b2_files()
            except Exception as e:
                print(f"[!] B2 refresh error: {e}")
            time.sleep(_refresh_interval)

    t = threading.Thread(target=worker, daemon=True, name="b2-refresh")
    t.start()
    print(f"[+] B2 background refresh thread started (interval={_refresh_interval}s)")
    return t


if __name__ == "__main__":
    # 单独运行测试
    print("=== B2 file list ===")
    files = refresh_b2_files()
    print(f"B2 has {len(files)} files:")
    for f in sorted(files):
        print(f"  {f}")

    if files:
        print("\n=== Test signed URL ===")
        test_file = sorted(files)[0]
        url = get_signed_download_url(test_file)
        if url:
            print(f"Signed URL for {test_file}:")
            print(f"  {url[:100]}...")
        else:
            print("Failed to get signed URL")
