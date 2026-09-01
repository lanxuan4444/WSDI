#!/usr/bin/env python3
"""
WSDI Server - Remote Driver Installer Backend
"""

import json
import os
import io
import tempfile
import zipfile
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote, quote
import mimetypes
import re

# ---- SDI .bin index parser (直接解析 .bin 二进制，不依赖任何日志) ----
_sdi_parser = None

def get_sdi_parser():
    """懒加载 SDI .bin 解析器，加载所有 .bin 到内存。"""
    global _sdi_parser
    if _sdi_parser is None:
        try:
            from sdi_bin_parser import SDIBinParser
            _sdi_parser = SDIBinParser(INDEX_DIR)
            _sdi_parser.load_all()
            print(f"[+] SDI bin parser loaded: {len(_sdi_parser._bodies)} bins")
        except Exception as e:
            print(f"[!] SDI bin parser init failed: {e}")
            _sdi_parser = False
    return _sdi_parser if _sdi_parser is not False else None


def search_hwid(hwid: str) -> list:
    """在所有 .bin 中搜索 HWID，返回匹配的 .7z 包名列表。
    
    直接解析 SDI 自带的 .bin 索引文件（LZMA 压缩的二进制格式），
    不依赖 SDI 日志或任何外部工具。
    """
    parser = get_sdi_parser()
    if not parser:
        return []
    results = parser.search_hwid(hwid)
    return [r['pkg_name'] for r in results]

# ============================================================
# CONFIG
# ============================================================
HOST = "0.0.0.0"
PORT = 80

# ---- 部署路径：优先从 config_secret.py（不入库）读取，回退到环境变量/相对路径 ----
def _load_deploy_path(name, default):
    """读取部署路径：config_secret.py > 环境变量 > 默认值。"""
    try:
        from config_secret import DRIVERS_DIR as _d, INDEX_DIR as _i, \
            SDI_LITE_PATH as _s, ZIP_7Z_PATH as _z
        _map = {'DRIVERS_DIR': _d, 'INDEX_DIR': _i, 'SDI_LITE_PATH': _s, 'ZIP_7Z_PATH': _z}
        return _map[name]
    except Exception:
        return os.environ.get(name, default)


# Drivers .7z packages (NOT to be extracted, SDI reads them directly)
DRIVERS_DIR = _load_deploy_path("DRIVERS_DIR", r"D:\SDI\Drivers")

# Index .bin files: use the original SDI index directly.
INDEX_DIR = _load_deploy_path("INDEX_DIR", r"D:\SDI\Index\SDI")

# SDI Lite .7z (contains SDI executable, themes, langs, etc.)
SDI_LITE_PATH = _load_deploy_path("SDI_LITE_PATH", r"D:\WSDI\cache\sdi_lite\SDI_R2601.7z")

# 7-Zip portable .zip
ZIP_7Z_PATH = _load_deploy_path("ZIP_7Z_PATH", r"D:\WSDI\cache\tools\7z_portable.zip")

# ---- 文件服务模式（混合模式）----
# 小文件（≤512MB）→ 本地服务 + CF 边缘缓存（0 流量费）
# 大文件（>512MB）→ B2 直链 + CF Bandwidth Alliance（0 流量费）
# COS 仅作冷备份，不读不写
USE_LOCAL = True

# CF 免费版单文件缓存上限（512MB），超过此大小走 B2
LARGE_FILE_THRESHOLD = 512 * 1024 * 1024  # 512MB

# Backblaze B2 配置（大文件存储）
# 需要先在 B2 创建 bucket 并上传大文件
# B2_URL_BASE 是 B2 文件的公开访问 URL 前缀
# 格式: https://f000.backblazeb2.com/file/<bucket-name>/
# 或通过 CF Workers 代理: https://b2.yanhong.online/
B2_BUCKET = "wsdi-drivers"
B2_URL_BASE = "https://b2.yanhong.online"  # CF Worker 代理 B2（走 Bandwidth Alliance）
# 直接 B2 URL（备用，不走 CF）:
# B2_URL_BASE = f"https://f000.backblazeb2.com/file/{B2_BUCKET}"

# COS 配置（仅作冷备份参考，不读不写）
COS_BASE = "https://wsdi-drivers-2026-1449166909.cos.ap-guangzhou.myqcloud.com"
COS_DRIVERS_PREFIX = "Drivers/"
COS_INDEX_PREFIX = "Index/SDI/"
COS_SDI_LITE_URL = f"{COS_BASE}/SDI_R2601.7z"
COS_7Z_URL = f"{COS_BASE}/7z_portable.zip"
COS_SDI_FULL_URL = f"{COS_BASE}/sdi_full.7z"

# 兼容旧代码的别名
USE_COS = not USE_LOCAL


def get_file_url(filename, prefix="Drivers/", file_size=0):
    """根据文件大小 + B2 状态决定走本地（CF 缓存）还是 B2（大文件）。

    委托给 b2.py 模块，它会查 B2 上的实际文件清单，
    只有真正上传到 B2 的大文件才会走 B2 链路。

    Args:
        filename: 文件名（如 DP_xxx.7z）
        prefix: 路径前缀（Drivers/ 或 Index/SDI/）
        file_size: 文件大小（字节），0 表示未知

    Returns:
        URL 字符串
    """
    try:
        import b2 as b2mod
        return b2mod.get_file_url(filename, prefix, file_size)
    except Exception as e:
        # 回退到旧的纯大小判断逻辑
        safe = quote(filename, safe="/")
        if USE_LOCAL and file_size > 0 and file_size <= LARGE_FILE_THRESHOLD:
            return f"https://yanhong.online/files/{prefix}{safe}"
        elif USE_LOCAL and file_size > LARGE_FILE_THRESHOLD:
            return f"{B2_URL_BASE}/{prefix}{safe}"
        elif USE_LOCAL:
            return f"https://yanhong.online/files/{prefix}{safe}"
        else:
            return f"{COS_BASE}/{prefix}{safe}"

# ============================================================
# CATEGORY-BASED CANDIDATES
# ============================================================
CATEGORY_PACKS = {
    'bluetooth': ['DP_wBluetooth_custom.7z', 'DP_wBluetooth_26061.7z'],
    'chipset': ['DP_Chipset_custom.7z', 'DP_Chipset_26061.7z'],
    'video': ['DP_Video_Intel_custom.7z', 'DP_Video_nVIDIA_custom.7z', 'DP_Videos_AMD_custom.7z', 'DP_Videos_Others_custom.7z'],
    'lan': ['DP_LAN_Intel_custom.7z', 'DP_LAN_Realtek_custom.7z', 'DP_LAN_Others_custom.7z'],
    'wlan': ['DP_WLAN-WiFi_custom.7z'],
    'sound': ['DP_Sound_Intel_custom.7z', 'DP_Sounds_Realtek_custom.7z', 'DP_Sound_Others_custom.7z'],
    'storage': ['DP_MassStorage_custom.7z'],
    'touchpad': ['DP_Touchpad_Alps_custom.7z', 'DP_Touchpad_Others_custom.7z', 'DP_Touchpad_Synaptics_26044.7z', 'DP_Touchpad_Elan_26043.7z'],
    'camera': ['DP_Camera_custom.7z', 'DP_WebCam_custom.7z'],
    'cardreader': ['DP_CardReader_custom.7z'],
    'biometric': ['DP_Biometric_custom.7z'],
    'monitor': ['DP_Monitor_custom.7z'],
    'usb': ['DP_xUSB_custom.7z', 'DP_zUSB3_26040.7z'],
    'printer': ['DP_Printer_custom.7z'],
    'misc': ['DP_Misc_custom.7z', 'DP_Vendor_26061.7z'],
}

GPU_VENDOR_HINTS = {
    'NVIDIA': 'N卡去 NVIDIA 官网。',
    'AMD': 'A卡去 AMD 官网。',
    'INTEL': 'I卡去 Intel 官网。',
}

# ============================================================
# HELPER: get .bin index path for a given .7z driver package
# ============================================================
def get_index_bin(pkg_name):
    """Given e.g. 'DP_wBluetooth_26061.7z', return the matching .bin path."""
    base = pkg_name.replace(".7z", "")
    bin_name = base + ".bin"
    bin_path = os.path.join(INDEX_DIR, bin_name)
    if os.path.isfile(bin_path):
        return bin_path
    return None

# ============================================================
# HELPER: get driver .7z path
# ============================================================
def get_driver_path(pkg_name):
    p = os.path.join(DRIVERS_DIR, pkg_name)
    if os.path.isfile(p):
        return p
    return None

# ============================================================
# REQUEST HANDLER
# ============================================================
class WSDIHandler(BaseHTTPRequestHandler):
    # Prevent an idle or slow client from holding a worker indefinitely.
    request_timeout = 30

    def setup(self):
        super().setup()
        self.connection.settimeout(self.request_timeout)

    def log_message(self, format, *args):
        print(f"[{self.client_address[0]}] {args[0]}")

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_redirect(self, location, status=302):
        body = b""
        self.send_response(status)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, download_name=None):
        if not os.path.isfile(path):
            self._send_json({"error": "file not found"}, 404)
            return

        file_size = os.path.getsize(path)
        download_name = download_name or os.path.basename(path)
        content_type = self._guess_mime(download_name)

        # Parse Range header
        range_header = self.headers.get('Range', '')
        start = 0
        end = file_size - 1
        status_code = 200

        if range_header.startswith('bytes='):
            try:
                range_val = range_header[6:]  # strip 'bytes='
                if '-' in range_val:
                    parts = range_val.split('-')
                    if parts[0]:
                        start = int(parts[0])
                    if parts[1]:
                        end = int(parts[1])
                    else:
                        end = file_size - 1
                if start >= file_size:
                    start = file_size - 1
                if end >= file_size:
                    end = file_size - 1
                if start > end:
                    start = end
                status_code = 206
            except Exception:
                start = 0
                end = file_size - 1
                status_code = 200

        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", end - start + 1)
        if status_code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Accept-Ranges", "bytes")
        # HTML 页面：inline 渲染；其他文件：attachment 强制下载
        if download_name.endswith(('.html', '.htm')):
            self.send_header("Content-Disposition", "inline")
        else:
            self.send_header("Content-Disposition",
                             f'attachment; filename="{download_name}"')
        self.send_header("Access-Control-Allow-Origin", "*")

        # ---- 缓存策略（混合模式）----
        # 1. 动态内容（.ps1 .bat .html .exe）→ 永不缓存（实时更新）
        # 2. 小文件（≤512MB .7z .bin .zip）→ CF 缓存 1 年 + 浏览器 1 天
        # 3. 大文件（>512MB）→ 不应该走这里（走 B2），但万一来了就不缓存
        if download_name.endswith(('.ps1', '.bat', '.html', '.exe')):
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        elif file_size <= LARGE_FILE_THRESHOLD:
            # 小文件：CF 长期缓存（s-maxage=31536000=1年），浏览器 1 天
            self.send_header("Cache-Control", "public, max-age=86400, s-maxage=31536000, immutable")
            self.send_header("CDN-Cache-Control", "public, max-age=31536000")
        else:
            # 大文件：不缓存（应该走 B2，不应该到这）
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        with open(path, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk_size = min(65536, remaining)
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _guess_mime(self, filename):
        ext = os.path.splitext(filename)[1].lower()
        mapping = {
            '.7z': 'application/x-7z-compressed',
            '.zip': 'application/zip',
            '.bin': 'application/octet-stream',
            '.ps1': 'text/plain; charset=utf-8',
            '.bat': 'text/plain; charset=utf-8',
            '.exe': 'application/octet-stream',
            '.html': 'text/html; charset=utf-8',
            '.json': 'application/json',
        }
        return mapping.get(ext, 'application/octet-stream')

    def _send_html(self, path):
        if not os.path.isfile(path):
            self._send_json({"error": "home page not found"}, 404)
            return
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ---- GET routes ----
    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path).rstrip("/")
        if path == "":
            path = "/"

        if path == "/api/health":
            self._send_json({"ok": True, "service": "wsdi"})

        elif path == "/api/printers":
            # 列出本机打印机（网络打印前端用）
            import printer as printer_mod
            self._send_json({
                "ok": True,
                "printers": printer_mod.list_printers(),
                "available": printer_mod.printers_available(),
                "default": printer_mod.get_default_printer(),
            })

        elif path == "/api/sdi_lite":
            # SDI Lite: 优先走 B2（如果已上传），否则本地 serve
            try:
                import b2 as b2mod
                if b2mod.is_on_b2("SDI_R2601.7z"):
                    self._send_redirect(f"{b2mod.B2_PROXY_BASE}/SDI_R2601.7z")
                    return
            except Exception:
                pass
            if USE_LOCAL:
                self._send_file(SDI_LITE_PATH, "SDI_R2601.7z")
            else:
                self._send_redirect(COS_SDI_LITE_URL)

        elif path == "/api/sdi_full":
            # SDI Full
            try:
                import b2 as b2mod
                if b2mod.is_on_b2("SDI_R2601.7z"):
                    self._send_redirect(f"{b2mod.B2_PROXY_BASE}/SDI_R2601.7z")
                    return
            except Exception:
                pass
            if USE_LOCAL:
                self._send_file(SDI_LITE_PATH, "SDI_R2601.7z")
            else:
                self._send_redirect(COS_SDI_FULL_URL)

        elif path == "/api/7z_portable":
            # 7-Zip portable: 优先走 B2，否则本地 serve
            try:
                import b2 as b2mod
                if b2mod.is_on_b2("7z_portable.zip"):
                    self._send_redirect(f"{b2mod.B2_PROXY_BASE}/7z_portable.zip")
                    return
            except Exception:
                pass
            if USE_LOCAL:
                self._send_file(ZIP_7Z_PATH, "7z_portable.zip")
            else:
                self._send_redirect(COS_7Z_URL)

        elif path == "/api/index_list":
            # Return list of all .bin index files available on COS
            bin_files = []
            if os.path.isdir(INDEX_DIR):
                bin_files = sorted(
                    f for f in os.listdir(INDEX_DIR) if f.endswith('.bin')
                )
            self._send_json({
                "bins": bin_files,
                "count": len(bin_files),
                "cos_base": COS_BASE if USE_COS else None,
                "cos_index_prefix": COS_INDEX_PREFIX if USE_COS else None,
            })

        elif path == "/api/b2_status":
            # 查看 B2 状态：哪些文件已上传到 B2
            try:
                import b2 as b2mod
                b2_files = sorted(b2mod.get_b2_files())
                # 本地大文件清单
                local_large = []
                if os.path.isdir(DRIVERS_DIR):
                    for f in os.listdir(DRIVERS_DIR):
                        p = os.path.join(DRIVERS_DIR, f)
                        if os.path.isfile(p) and os.path.getsize(p) > LARGE_FILE_THRESHOLD:
                            local_large.append(f)
                local_large = sorted(local_large)
                missing = [f for f in local_large if f not in b2_files]
                self._send_json({
                    "b2_file_count": len(b2_files),
                    "b2_files": b2_files,
                    "local_large_count": len(local_large),
                    "local_large_files": local_large,
                    "missing_from_b2": missing,
                    "missing_count": len(missing),
                    "b2_proxy_base": b2mod.B2_PROXY_BASE,
                })
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path.startswith("/api/b2/"):
            # B2 大文件重定向：生成签名 URL，302 重定向客户端到 B2
            # 走 CF Bandwidth Alliance，流量免费
            filename = path[len("/api/b2/"):]
            # 防止路径遍历
            filename = filename.replace("..", "").replace("\\", "/").strip("/")
            if not filename:
                self._send_json({"error": "no filename"}, 400)
                return
            try:
                import b2 as b2mod
                # 检查文件是否在 B2 上
                if not b2mod.is_on_b2(filename):
                    self._send_json({"error": f"file not in B2: {filename}"}, 404)
                    return
                # 生成签名 URL
                signed_url = b2mod.get_signed_download_url(filename)
                if signed_url:
                    print(f"[B2] Redirect {filename} -> {signed_url[:80]}...")
                    self._send_redirect(signed_url)
                else:
                    self._send_json({"error": "failed to generate signed URL"}, 502)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        elif path.startswith("/api/download_pkg/"):
            # Download a specific driver .7z
            pkg_name = path[len("/api/download_pkg/"):]
            p = get_driver_path(pkg_name)
            self._send_file(p, pkg_name)

        elif path.startswith("/api/download_index/"):
            # Download a specific index .bin
            bin_name = path[len("/api/download_index/"):]
            p = os.path.join(INDEX_DIR, bin_name)
            self._send_file(p, bin_name)

        elif path.startswith("/files/"):
            # 本地文件服务（CF CDN 缓存路径）
            # /files/Drivers/xxx.7z → D:\SDI\Drivers\xxx.7z
            # /files/Index/SDI/xxx.bin → D:\SDI\Index\SDI\xxx.bin
            # /files/SDI_R2601.7z → D:\WSDI\cache\sdi_lite\SDI_R2601.7z
            # /files/7z_portable.zip → D:\WSDI\cache\7z\7z_portable.zip
            file_path = path[len("/files/"):]
            # 防止路径遍历攻击
            file_path = file_path.replace("..", "").replace("\\", "/")
            parts = file_path.split("/")

            # 检查是否是根目录的已知文件
            root_files = {
                "SDI_R2601.7z": SDI_LITE_PATH,
                "7z_portable.zip": ZIP_7Z_PATH,
            }
            if parts[0] in root_files and len(parts) == 1:
                self._send_file(root_files[parts[0]], parts[0])
                return

            # Drivers/xxx.7z
            if parts[0] == "Drivers" and len(parts) >= 2:
                drv_name = "/".join(parts[1:])
                local_path = os.path.join(DRIVERS_DIR, drv_name.replace("/", os.sep))
                if os.path.isfile(local_path):
                    self._send_file(local_path, os.path.basename(drv_name))
                else:
                    self._send_json({"error": "file not found"}, 404)
                return

            # Index/SDI/xxx.bin
            if parts[0] == "Index" and len(parts) >= 2:
                idx_name = "/".join(parts[1:])
                local_path = os.path.join(INDEX_DIR, idx_name.replace("/", os.sep))
                if os.path.isfile(local_path):
                    self._send_file(local_path, os.path.basename(idx_name))
                else:
                    self._send_json({"error": "file not found"}, 404)
                return

            self._send_json({"error": "file not found"}, 404)

        elif path == "/tools":
            # 工具下载页面
            tools_html = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "web", "tools.html"
            )
            self._send_file(tools_html, "tools.html")

        elif path == "/api/tools":
            # 返回 B2 上 tools/ 前缀下的文件列表
            try:
                import b2 as b2mod
                files = b2mod.list_b2_files_with_meta(prefix="tools/")
                # 计算总大小 + 生成下载 URL
                total_size = 0
                result_files = []
                for f in files:
                    total_size += f["size"]
                    # 下载 URL 走 CF Worker (b2.yanhong.online)
                    # 单次 URL 编码（保留 /，编码空格、中文等）：
                    #   - 服务端：quote(name, safe="/") 单次编码
                    #   - Worker：decodeURIComponent → encodeURI 达到单次编码效果
                    # 避免双重编码（%20 → %2520）导致 B2 找不到文件。
                    from urllib.parse import quote
                    safe_name = quote(f["name"], safe="/")
                    result_files.append({
                        "name": f["name"],
                        "size": f["size"],
                        "mod_time": f["mod_time"],
                        "mime_type": f["mime_type"],
                        "url": f"{b2mod.B2_PROXY_BASE}/{safe_name}",
                    })
                self._send_json({
                    "files": result_files,
                    "total_size": total_size,
                    "count": len(result_files),
                })
            except Exception as e:
                self._send_json({"error": str(e), "files": []}, 500)

        elif path == "/client_core_v25.ps1":
            # Serve the client PowerShell script
            script_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "web", "client_core_v25.ps1"
            )
            self._send_file(script_path, "client_core_v25.ps1")

        elif path == "/client.bat":
            # Serve the client batch file
            bat_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "web", "client.bat"
            )
            self._send_file(bat_path, "client.bat")

        elif path in ("/", "/index.html"):
            # Home page
            html_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "web", "index.html"
            )
            self._send_html(html_path)

        elif path == "/WSDI_Client.exe":
            # Serve the packaged client executable
            exe_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "web", "WSDI_Client.exe"
            )
            self._send_file(exe_path, "WSDI_Client.exe")

        elif path.lower().startswith("/ldth5"):
            # Reverse proxy to LDTH5 log viewer (localhost:9876)
            self._proxy_ldth5(parsed)

        elif path.lower().startswith("/hfs"):
            # Reverse proxy to HFS file server (localhost:8080)
            self._proxy_hfs(parsed)

        elif path.startswith("/~") or path == "/favicon.ico":
            # HFS 旧版首页可能使用根路径资源；公网入口需要兜底转发。
            self._proxy_hfs(parsed)

        else:
            self._send_json({"error": "not found"}, 404)

    # ---- POST routes ----
    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path).rstrip("/")

        if path.lower().startswith("/ldth5"):
            # Reverse proxy POST to LDTH5
            self._proxy_ldth5(parsed)
        elif path.lower().startswith("/hfs"):
            # Reverse proxy POST to HFS
            self._proxy_hfs(parsed)
        elif path == "/api/analyze":
            self._handle_analyze()
        elif path == "/api/print":
            self._handle_print()
        else:
            self._send_json({"error": "not found"}, 404)

    def _proxy_hfs(self, parsed):
        """Reverse proxy HFS requests to localhost:8080."""
        raw_path = parsed.path
        prefix = "/hfs"
        sub_path = raw_path[len(prefix):] if raw_path.lower().startswith(prefix) else raw_path
        if not sub_path or sub_path == "/":
            sub_path = "/"
        hfs_url = "http://localhost:8080" + sub_path
        if parsed.query:
            hfs_url += "?" + parsed.query

        try:
            body = None
            content_length = self.headers.get("Content-Length")
            if content_length:
                body = self.rfile.read(int(content_length))

            req = urllib.request.Request(hfs_url, data=body, method=self.command)
            for header, value in self.headers.items():
                if header.lower() in ("host", "connection", "content-length", "accept-encoding"):
                    continue
                req.add_header(header, value)

            with urllib.request.urlopen(req, timeout=120) as resp:
                content = resp.read()
                content_type = resp.headers.get("Content-Type", "")
                if "text/html" in content_type:
                    try:
                        html = content.decode("utf-8")
                        # HFS 资源可能出现在 href、src、url() 或内联脚本中，
                        # 统一改写到 /hfs/ 前缀，避免请求落到主站根路径。
                        html = re.sub(r'(["\'(])/~', r'\1/hfs/~', html)
                        html = re.sub(r'(["\'(])/favicon\.ico', r'\1/hfs/favicon.ico', html, flags=re.IGNORECASE)
                        html = html.replace("location.href='/'", "location.href='/hfs/'")
                        html = html.replace('location.href="/"', 'location.href="/hfs/"')
                        if "<base" not in html.lower():
                            head_end = html.lower().find("</head>")
                            base_tag = '<base href="/hfs/">'
                            if head_end != -1:
                                html = html[:head_end] + base_tag + "\n" + html[head_end:]
                            else:
                                html = base_tag + "\n" + html
                        content = html.encode("utf-8")
                    except Exception:
                        pass

                self.send_response(resp.status)
                for header, value in resp.headers.items():
                    if header.lower() in ("transfer-encoding", "content-length", "connection", "content-encoding"):
                        continue
                    self.send_header(header, value)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
        except urllib.error.HTTPError as e:
            err_body = e.read()
            self.send_response(e.code)
            for header, value in e.headers.items():
                if header.lower() in ("transfer-encoding", "content-length", "connection"):
                    continue
                self.send_header(header, value)
            self.send_header("Content-Length", str(len(err_body)))
            self.end_headers()
            self.wfile.write(err_body)
        except Exception as e:
            self._send_json({
                "error": "HFS file server not available",
                "detail": str(e),
                "hint": "Make sure HFS is running on port 8080"
            }, 502)

    def _proxy_ldth5(self, parsed):
        """Reverse proxy requests to LDTH5 log viewer on localhost:9876.

        LDTH5 runs at the root path, so we strip the /LDTH5 prefix before
        forwarding. For the HTML index page we inject <base href="/LDTH5/">
        so that relative URLs (api/..., Img/...) resolve under /LDTH5/.
        """
        raw_path = parsed.path
        # Strip /LDTH5 prefix case-insensitively
        prefix = "/LDTH5"
        if raw_path.lower().startswith(prefix.lower()):
            sub_path = raw_path[len(prefix):]
        else:
            sub_path = raw_path
        if sub_path == "" or sub_path == "/":
            sub_path = "/"

        ldth5_url = "http://localhost:9876" + sub_path
        if parsed.query:
            ldth5_url += "?" + parsed.query

        try:
            body = None
            content_length = self.headers.get("Content-Length")
            if content_length:
                body = self.rfile.read(int(content_length))

            req = urllib.request.Request(ldth5_url, data=body, method=self.command)
            for header, value in self.headers.items():
                if header.lower() in ("host", "connection", "content-length"):
                    continue
                req.add_header(header, value)

            # 批量日志下载可能耗时较长，放宽超时到 120 秒
            with urllib.request.urlopen(req, timeout=120) as resp:
                content = resp.read()
                content_type = resp.headers.get("Content-Type", "")

                # Inject <base> into HTML responses so relative paths work
                if "text/html" in content_type and sub_path == "/":
                    try:
                        html = content.decode("utf-8")
                        if "<base" not in html.lower():
                            head_end = html.lower().find("</head>")
                            base_tag = '<base href="/LDTH5/">'
                            if head_end != -1:
                                html = html[:head_end] + base_tag + "\n" + html[head_end:]
                            else:
                                # No </head>, prepend after opening <head> if present
                                head_start = html.lower().find("<head>")
                                if head_start != -1:
                                    insert_pos = head_start + len("<head>")
                                    html = html[:insert_pos] + "\n" + base_tag + html[insert_pos:]
                                else:
                                    html = base_tag + "\n" + html
                            content = html.encode("utf-8")
                            # Update content-length if it was set
                            if "content-length" in {h.lower() for h in resp.headers.keys()}:
                                resp.headers.replace_header("Content-Length", str(len(content)))
                    except Exception:
                        pass  # If injection fails, serve original content

                self.send_response(resp.status)
                for header, value in resp.headers.items():
                    if header.lower() == "transfer-encoding":
                        continue
                    self.send_header(header, value)
                self.end_headers()
                self.wfile.write(content)

        except urllib.error.HTTPError as e:
            try:
                err_body = e.read()
            except Exception:
                err_body = b""
            self.send_response(e.code)
            for header, value in e.headers.items():
                if header.lower() == "transfer-encoding":
                    continue
                self.send_header(header, value)
            self.send_header("Content-Length", len(err_body))
            self.end_headers()
            self.wfile.write(err_body)

        except Exception as e:
            self._send_json({
                "error": "LDTH5 log viewer not available",
                "detail": str(e),
                "hint": "Make sure LDTH5 server is running on port 9876"
            }, 502)

    def _handle_print(self):
        """网络打印：接收上传文件 + 密码，用本机打印机打印。

        POST /api/print?printer=<name>&password=<pwd>&filename=<xxx>
        Body: 文件原始字节（application/octet-stream），文件名放 X-Filename 头或 filename 参数。
        """
        import printer as printer_mod

        # 读取打印访问密码（优先 config_secret.py，回退环境变量）
        try:
            from config_secret import PRINT_ACCESS_PASSWORD as _pwd
            print_password = _pwd
        except Exception:
            print_password = os.environ.get("PRINT_ACCESS_PASSWORD", "print2026")

        # 参数解析：优先从 body 前缀读取 JSON meta（4 字节大端长度 + JSON）
        parsed = urlparse(self.path)
        qs = {}
        if parsed.query:
            for kv in parsed.query.split("&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    qs[unquote(k)] = unquote(v)

        printer_name = qs.get("printer", "")
        password = qs.get("password", "")
        filename = qs.get("filename", "")
        settings = {}

        # 读取 body（必须读取后才能 peek 前缀）
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length <= 0:
            self._send_json({"ok": False, "error": "没有收到文件内容"}, 400)
            return
        if length > printer_mod.MAX_FILE_SIZE:
            self._send_json({"ok": False, "error": "文件过大（上限 20MB）"}, 413)
            return

        raw_full = self.rfile.read(length)

        # 尝试从 body 前 4 字节提取 JSON meta（前端新格式）
        meta = None
        if len(raw_full) >= 4:
            try:
                meta_len = int.from_bytes(raw_full[:4], "big")
                if 0 < meta_len < 65536 and len(raw_full) >= 4 + meta_len:
                    meta_str = raw_full[4:4 + meta_len].decode("utf-8", errors="replace")
                    meta = json.loads(meta_str)
                    raw = raw_full[4 + meta_len:]
            except Exception:
                meta = None

        if meta is None:
            # 回退到旧格式：URL 参数 + X-Filename 头
            raw = raw_full
            if not filename:
                filename = self.headers.get("X-Filename", "")
                if filename:
                    try:
                        filename = unquote(filename)
                    except Exception:
                        pass
        else:
            # 从 meta 取参数
            if not printer_name:
                printer_name = meta.get("printer", "")
            if not password:
                password = meta.get("password", "")
            if not filename:
                filename = meta.get("filename", "")
            # 打印设置（份数/纸张/单双面/横向/页码范围）
            if isinstance(meta.get("settings"), dict):
                settings = meta["settings"]

        # 1. 校验密码
        if password != print_password:
            self._send_json({"ok": False, "error": "打印密码错误"}, 401)
            return

        # 2. 校验打印机存在
        if printer_name:
            printers = printer_mod.list_printers()
            if not any(p.lower() == printer_name.lower() for p in printers):
                self._send_json({"ok": False, "error": "打印机不存在"}, 400)
                return

        # 3. 检查扩展名是否支持
        if not filename:
            # 无文件名，尝试从 content-type 推断
            ct = self.headers.get("Content-Type", "")
            if "pdf" in ct:
                filename = "upload.pdf"
            elif "image/png" in ct:
                filename = "upload.png"
            elif "image/jpeg" in ct or "image/jpg" in ct:
                filename = "upload.jpg"
            else:
                filename = "upload.bin"

        ext = os.path.splitext(filename)[1].lower()
        if ext not in printer_mod.ALLOWED_EXT:
            self._send_json({
                "ok": False,
                "error": f"不支持的文件类型: {ext or '(无扩展名)'}",
                "allowed": list(printer_mod.ALLOWED_EXT.keys()),
            }, 415)
            return

        # 5. 保存到临时目录
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(suffix=ext, prefix="wsdi_print_")
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
        except Exception as e:
            self._send_json({"ok": False, "error": f"保存文件失败: {e}"}, 500)
            return

        # 6. 打印（传递打印设置：份数/纸张/单双面/横向/页码范围）
        try:
            ok, msg = printer_mod.print_file(tmp_path, printer_name or None, settings or {})
            resp = {"ok": ok, "message": msg, "filename": filename, "printer": printer_name or "默认"}
            if settings:
                resp["settings"] = settings
            self._send_json(resp)
        except Exception as e:
            self._send_json({"ok": False, "error": f"打印异常: {e}"}, 500)
        finally:
            printer_mod.cleanup_temp(tmp_path)

    def _handle_analyze(self):
        """Receive HWID list, return matched driver packages + indexes.

        Uses SDI-generated JSON match index (sdi_match_index.json) for
        precise HWID-to-driver-package mapping. Falls back to category
        heuristic if the index is not available.
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8")
            data = json.loads(raw)
        except Exception:
            self._send_json({"error": "invalid JSON"}, 400)
            return

        hwids = data.get("hwids", [])
        devices = data.get("devices", [])
        if not hwids and not devices:
            self._send_json({"error": "no hwids provided"}, 400)
            return

        # Merge HWIDs from devices list (some clients only send devices[])
        if not hwids:
            hwids = []
            for dev in devices:
                h = dev.get('hwid', '')
                if h and h not in hwids:
                    hwids.append(h)
                # Also include any alternate hwids from the device
                for alt in dev.get('hwids', []) or []:
                    if alt and alt not in hwids:
                        hwids.append(alt)

        matched_pkgs = {}       # required (problem devices)
        matched_hwids = {}
        optional_pkgs = {}      # optional (updatable devices)
        gpu_notices = []

        def add_gpu_notice(dev):
            text = f"{dev.get('description', '')} {dev.get('hwid', '')}".upper()
            vendor = next((name for name in GPU_VENDOR_HINTS if name in text), None)
            if vendor:
                notice = GPU_VENDOR_HINTS[vendor]
            else:
                notice = '显卡去官网。找不到官网就百度搜型号+驱动。'
            if notice not in gpu_notices:
                gpu_notices.append(notice)

        # Build hwid -> is_problem map from devices
        hwid_problem_map = {}
        for dev in devices:
            h = dev.get('hwid', dev.get('instance_id', ''))
            hwid_problem_map[h] = dev.get('is_problem', True)

        # NOTE: Previous versions had a SKIP_HWID_PREFIXES filter here that
        # excluded MF\*, ROOT\*, SW\* etc. This was a workaround for the client
        # uploading ALL PnP devices (300+). Now that the client correctly
        # uploads only yellow-bang devices (ConfigManagerErrorCode != 0), every
        # HWID it sends is genuinely missing a driver and MUST be matched.
        # So we no longer skip any prefixes.
        driver_hwids = list(hwids)
        skipped_hwids = []

        # ---- PRIMARY: Use SDI bin parser + JSON cache for HWID matching ----
        # SDI bin index contains the HWID list each driver pack supports.
        # If a HWID matches a .bin entry, the user doesn't have that driver
        # installed (the client only sends yellow-bang devices), so it's REQUIRED.
        for hwid in driver_hwids:
            pkgs = search_hwid(hwid)
            if pkgs:
                # SDI bin match -> always REQUIRED
                for pkg_name in pkgs:
                    if not get_driver_path(pkg_name):
                        continue
                    if pkg_name not in matched_pkgs:
                        driver_path = get_driver_path(pkg_name)
                        size = os.path.getsize(driver_path) if driver_path else 0
                        idx_bin = get_index_bin(pkg_name)
                        matched_pkgs[pkg_name] = {
                            "size": size,
                            "index": os.path.basename(idx_bin) if idx_bin else None,
                            "category": "sdi_match",
                        }
                    matched_hwids.setdefault(hwid, []).append(pkg_name)

        # ---- FALLBACK: Smart per-HWID heuristic for unmatched devices ----
        # Only fallback for real hardware HWIDs (MF\* etc already excluded)
        unmatched_hwids = [h for h in driver_hwids if h not in matched_hwids]

        if unmatched_hwids:
            # Vendor-aware package selector: use HWID/description to pick the best sub-package
            def get_best_packages(category, hwid_text, desc_text):
                """Use vendor hints from HWID/description to return only relevant packages."""
                text = (hwid_text + ' ' + desc_text).upper()
                vendor_map = {
                    'video': [
                        (['VEN_8086', 'INTEL', 'UHD', 'HD GRAPHICS', 'IRIS'], ['DP_Video_Intel_custom.7z']),
                        (['VEN_10DE', 'NVIDIA', 'GEFORCE', 'QUADRO', 'RTX', 'GTX'], ['DP_Video_nVIDIA_custom.7z']),
                        (['VEN_1002', 'AMD', 'RADEON', 'ATI', 'RX '], ['DP_Videos_AMD_custom.7z']),
                    ],
                    'sound': [
                        (['VEN_8086', 'INTEL'], ['DP_Sound_Intel_custom.7z']),
                        (['VEN_10EC', 'REALTEK'], ['DP_Sounds_Realtek_custom.7z']),
                    ],
                    'lan': [
                        (['VEN_8086', 'INTEL'], ['DP_LAN_Intel_custom.7z']),
                        (['VEN_10EC', 'REALTEK'], ['DP_LAN_Realtek_custom.7z']),
                    ],
                    'touchpad': [
                        (['SYNAPTICS', 'SYN'], ['DP_Touchpad_Synaptics_26044.7z']),
                        (['ELAN', 'ELAN_'], ['DP_Touchpad_Elan_26043.7z']),
                        (['ALPS'], ['DP_Touchpad_Alps_custom.7z']),
                    ],
                }
                if category in vendor_map:
                    for keywords, pkgs in vendor_map[category]:
                        if any(kw in text for kw in keywords):
                            return [p for p in pkgs if get_driver_path(p)]
                    # No vendor identified → return 'Others' variant only
                    fallback_map = {
                        'video': ['DP_Videos_Others_custom.7z'],
                        'sound': ['DP_Sound_Others_custom.7z'],
                        'lan': ['DP_LAN_Others_custom.7z'],
                        'touchpad': ['DP_Touchpad_Others_custom.7z'],
                    }
                    if category in fallback_map:
                        return [p for p in fallback_map[category] if get_driver_path(p)]
                # Categories without sub-packages: return all (usually just 1-2)
                return [p for p in CATEGORY_PACKS.get(category, []) if get_driver_path(p)]

            def infer_categories(dev):
                text = f"{dev.get('class','')} {dev.get('description','')} {dev.get('hwid','')}".upper()
                cats = []
                rules = [
                    ('bluetooth', ['BLUETOOTH', 'BTH']),
                    ('chipset', ['CHIPSET', 'SM BUS', 'SYSTEM DEVICE']),
                    ('video', ['DISPLAY', 'VIDEO', 'GRAPHICS', 'NVIDIA', 'AMD', 'RADEON', 'INTEL(R) UHD', 'INTEL(R) HD']),
                    ('lan', ['ETHERNET', 'LAN', 'NETWORK CONTROLLER', 'NETWORK ADAPTER', 'GIGABIT']),
                    ('wlan', ['WLAN', 'WIRELESS', 'WI-FI', 'WIFI']),
                    ('sound', ['AUDIO', 'SOUND', 'HIGH DEFINITION AUDIO', 'REALTEK', 'CONEXANT', 'IDT']),
                    ('storage', ['STORAGE', 'SATA', 'NVME', 'AHCI', 'RAID', 'MASS STORAGE']),
                    ('touchpad', ['TOUCHPAD', 'MOUSE', 'TRACKPAD']),
                    ('camera', ['CAMERA', 'WEBCAM']),
                    ('cardreader', ['CARD READER', 'CARDREADER', 'SD HOST', 'MMC']),
                    ('biometric', ['BIOMETRIC', 'FINGERPRINT']),
                    ('monitor', ['MONITOR', 'DISPLAY']),
                    ('usb', ['XHCI', 'USB 3', 'USB HUB', 'USB ROOT']),
                    ('printer', ['PRINTER']),
                ]
                for cat, keys in rules:
                    if any(k in text for k in keys):
                        cats.append(cat)
                return cats or ['misc']

            # Only process devices whose HWID wasn't matched by SDI bin
            for dev in devices:
                hwid = dev.get('hwid', dev.get('instance_id', ''))
                if hwid not in unmatched_hwids:
                    continue
                desc = dev.get('description', '')
                categories = infer_categories(dev)
                if 'video' in categories:
                    add_gpu_notice(dev)
                for cat in categories:
                    best_pkgs = get_best_packages(cat, hwid, desc)
                    for pkg_name in best_pkgs:
                        if not get_driver_path(pkg_name):
                            continue
                        # Fallback match -> REQUIRED (these devices have no
                        # driver installed, otherwise they wouldn't be flagged
                        # by the client at all)
                        if pkg_name not in matched_pkgs:
                            driver_path = get_driver_path(pkg_name)
                            size = os.path.getsize(driver_path) if driver_path else 0
                            idx_bin = get_index_bin(pkg_name)
                            matched_pkgs[pkg_name] = {
                                "size": size,
                                "index": os.path.basename(idx_bin) if idx_bin else None,
                                "category": cat,
                                "fallback": True,
                            }
                        matched_hwids.setdefault(hwid, []).append(pkg_name)

            # ---- HWID keyword fallback for devices still unmatched ----
            still_unmatched = [h for h in unmatched_hwids if h not in matched_hwids]
            if still_unmatched:
                for hwid in still_unmatched:
                    text = hwid.upper()
                    fallback_cats = []
                    if 'BTH' in text or 'BLUETOOTH' in text:
                        fallback_cats.append('bluetooth')
                    if 'VEN_8086' in text or 'PCI' in text:
                        fallback_cats.append('chipset')
                    if 'DISPLAY' in text or 'VIDEO' in text:
                        fallback_cats.append('video')
                        gpu_notices.append('显卡去官网。找不到官网就百度搜型号+驱动。')
                    if 'NETWORK' in text or 'NET' in text or 'LAN' in text:
                        fallback_cats.append('lan')
                    if 'WLAN' in text or 'WI-FI' in text or 'WIFI' in text:
                        fallback_cats.append('wlan')
                    if 'AUDIO' in text or 'SOUND' in text:
                        fallback_cats.append('sound')
                    if 'STORAGE' in text or 'SATA' in text or 'NVME' in text:
                        fallback_cats.append('storage')
                    if not fallback_cats:
                        fallback_cats = ['misc']
                    for cat in fallback_cats:
                        for pkg_name in get_best_packages(cat, hwid, ''):
                            if not get_driver_path(pkg_name):
                                continue
                            # Always REQUIRED
                            if pkg_name not in matched_pkgs:
                                driver_path = get_driver_path(pkg_name)
                                size = os.path.getsize(driver_path) if driver_path else 0
                                idx_bin = get_index_bin(pkg_name)
                                matched_pkgs[pkg_name] = {
                                    "size": size,
                                    "index": os.path.basename(idx_bin) if idx_bin else None,
                                    "category": cat,
                                    "fallback": True,
                                }
                            matched_hwids.setdefault(hwid, []).append(pkg_name)

        if not matched_pkgs and not optional_pkgs:
            self._send_json({
                "matched": False,
                "message": "No candidate drivers found",
                "drivers": [],
                "optional_drivers": [],
                "gpu_notices": gpu_notices,
                "hwids": hwids,
                "devices": devices,
            })
            return

        # Build reverse map: package → list of HWIDs
        pkg_hwid_map = {}
        for hwid, pkgs in matched_hwids.items():
            for pkg in pkgs:
                pkg_hwid_map.setdefault(pkg, []).append(hwid)

        driver_list = []
        for pkg_name, info in matched_pkgs.items():
            entry = {
                "pkg": pkg_name,
                "size": info["size"],
                "size_mb": round(info["size"] / (1024 * 1024), 2),
                "index": info["index"],
                "for_hwids": pkg_hwid_map.get(pkg_name, []),
            }
            if USE_LOCAL:
                # 混合模式：B2 上有的文件走 B2（Bandwidth Alliance 免流量），
                # 否则回退到本地 + CF 缓存
                entry["url"] = get_file_url(pkg_name, "Drivers/", info["size"])
                if info.get("index"):
                    # .bin 索引文件也走 get_file_url（已上传到 B2 时走 B2）
                    entry["index_url"] = get_file_url(info["index"], "Index/SDI/", 0)
            elif USE_COS:
                safe = quote(pkg_name, safe="/")
                entry["url"] = f"{COS_BASE}/Drivers/{safe}"
                if info.get("index"):
                    entry["index_url"] = f"{COS_BASE}/Index/SDI/{quote(info['index'])}"
            driver_list.append(entry)

        optional_list = []
        for pkg_name, info in optional_pkgs.items():
            if pkg_name in matched_pkgs:
                continue
            entry = {
                "pkg": pkg_name,
                "size": info["size"],
                "size_mb": round(info["size"] / (1024 * 1024), 2),
                "index": info["index"],
                "category": info.get("category", ""),
                "for_hwids": pkg_hwid_map.get(pkg_name, []),
            }
            if USE_LOCAL:
                entry["url"] = get_file_url(pkg_name, "Drivers/", info["size"])
                if info.get("index"):
                    entry["index_url"] = get_file_url(info["index"], "Index/SDI/", 0)
            elif USE_COS:
                safe = quote(pkg_name, safe="/")
                entry["url"] = f"{COS_BASE}/Drivers/{safe}"
                if info.get("index"):
                    entry["index_url"] = f"{COS_BASE}/Index/SDI/{quote(info['index'])}"
            optional_list.append(entry)

        self._send_json({
            "matched": True,
            "drivers": driver_list,
            "optional_drivers": optional_list,
            "matched_hwids": matched_hwids,
            "gpu_notices": gpu_notices,
            "total_size_mb": round(sum(d["size"] for d in driver_list) / (1024 * 1024), 2),
            "optional_size_mb": round(sum(d["size"] for d in optional_list) / (1024 * 1024), 2),
            "diagnostics": {
                "total_hwids": len(hwids),
                "driver_hwids": len(driver_hwids),
                "skipped_composite": len(skipped_hwids),
                "hwids_matched": len([h for h in driver_hwids if h in matched_hwids]),
                "required_packages": len(driver_list),
                "optional_packages": len(optional_list),
            },
        })

# ============================================================
# MAIN
# ============================================================
def main():
    # 启动 B2 后台刷新线程
    try:
        import b2 as b2mod
        b2mod.refresh_b2_files()  # 启动时立即拉一次
        b2mod.start_background_refresh()
    except Exception as e:
        print(f"[!] B2 module init failed: {e}")

    print(f"""
╔══════════════════════════════════════╗
║       WSDI Server - Remote Driver   ║
║       Installer Backend             ║
╠══════════════════════════════════════╣
║  Drivers : {DRIVERS_DIR}
║  Index   : {INDEX_DIR}
║  SDI Lite: {SDI_LITE_PATH}
║  7z Zip  : {ZIP_7Z_PATH}
║  Port    : {PORT}
║  COS     : {"ON" if USE_COS else "OFF"}  {COS_BASE}
╚══════════════════════════════════════╝
""")
    class WSDIServer(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    server = WSDIServer((HOST, PORT), WSDIHandler)
    print(f"[*] Listening on http://{HOST}:{PORT} (threaded)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Shutting down...")
        server.shutdown()

if __name__ == "__main__":
    main()
