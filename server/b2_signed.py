"""
WSDI B2 签名 URL 生成模块
直接调 B2 API 生成临时下载 URL（1 小时有效）
客户端拿到 URL 后直连 B2 下载（走 CF Bandwidth Alliance，流量免费）
"""

import os
import sys
import base64
import json
import urllib.request
import urllib.parse
import time
import threading

# ---- 敏感配置：优先从 config_secret.py 读取（该文件不入库），回退到环境变量 ----
def _load_secret(name, default=None):
    return getattr(_SECRET, name, None) or os.environ.get(name, default)


try:
    from config_secret import *
    _SECRET = sys.modules['config_secret']
except Exception:
    class _SECRET:
        pass


# ---- B2 凭据 ----
B2_KEY_ID = _load_secret('B2_KEY_ID')
B2_APP_KEY = _load_secret('B2_APP_KEY')
B2_BUCKET_NAME = _load_secret('B2_BUCKET_NAME', 'wsdi-drivers')
B2_BUCKET_ID = _load_secret('B2_BUCKET_ID')
B2_API_BASE = _load_secret('B2_API_BASE', 'https://api004.backblazeb2.com')

if not B2_KEY_ID or not B2_APP_KEY:
    raise RuntimeError("B2 凭据缺失：请创建 server/config_secret.py 或设置 B2_KEY_ID/B2_APP_KEY 环境变量")

AUTH_DURATION = 3600  # 签名 URL 有效期 1 小时

# ---- 缓存 ----
_auth_cache = None  # { token, api_url, download_url, expire_at }
_auth_lock = threading.Lock()


def _authorize_account():
    """调 b2_authorize_account 拿 token 和 download_url"""
    auth_str = f"{B2_KEY_ID}:{B2_APP_KEY}"
    basic = base64.b64encode(auth_str.encode()).decode()

    req = urllib.request.Request(
        f"{B2_API_BASE}/b2api/v3/b2_authorize_account",
        headers={"Authorization": f"Basic {basic}"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())

    return {
        "token": data["authorizationToken"],
        "api_url": data["apiInfo"]["storageApi"]["apiUrl"],
        "download_url": data["apiInfo"]["storageApi"]["downloadUrl"],
        "expire_at": time.time() + 23 * 3600,  # 23 小时刷新
    }


def _get_auth():
    """获取 auth token（带缓存）"""
    global _auth_cache
    with _auth_lock:
        now = time.time()
        if _auth_cache is None or _auth_cache["expire_at"] < now + 60:
            _auth_cache = _authorize_account()
        return _auth_cache


def get_download_url(filename, duration=AUTH_DURATION):
    """生成 B2 临时签名下载 URL

    Args:
        filename: B2 上的文件名（如 DP_xxx.7z）
        duration: URL 有效期（秒），默认 1 小时

    Returns:
        临时签名 URL，客户端可直接访问下载
    """
    auth = _get_auth()

    body = json.dumps({
        "bucketId": B2_BUCKET_ID,
        "fileNamePrefix": filename,
        "validDurationInSeconds": duration,
    }).encode()

    req = urllib.request.Request(
        f"{auth['api_url']}/b2api/v3/b2_get_download_authorization",
        data=body,
        method="POST",
        headers={
            "Authorization": auth["token"],
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())

    # 完整 URL: https://f004.backblazeb2.com/file/wsdi-drivers/<filename>?Authorization=<token>
    safe_name = urllib.parse.quote(filename, safe="/")
    return (
        f"{auth['download_url']}/file/{B2_BUCKET_NAME}/{safe_name}"
        f"?Authorization={urllib.parse.quote(data['authorizationToken'])}"
    )


if __name__ == "__main__":
    # 单独测试
    url = get_download_url("DP_Chipset_26061.7z")
    print(f"Signed URL: {url[:100]}...")
    print(f"Length: {len(url)}")
