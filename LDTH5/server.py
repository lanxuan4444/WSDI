#!/usr/bin/env python3
"""
server.py — LDTools 日志查看器一体化服务

功能：
    1. 提供静态文件服务（index.html 等）
    2. /api/manifest  — 连接 FTP 拉取文件列表（内存缓存）
    3. /api/file      — 分别从 FTP 拉取加密文件，服务端处理后返回明文 JSON（内存缓存）
    4. /api/refresh   — 刷新文件列表缓存（不清数据缓存）
    5. /api/clear-decrypt-cache — 清空数据缓存（手动刷新用）

特性：
    - 所有 FTP 数据仅缓存在内存中，进程退出即清空，绝不落盘
    - 服务端处理（AES-256-CBC + HMAC-SHA256），前端无需 Web Crypto API
    - 多线程并发处理（ThreadingHTTPServer），FTP 操作不阻塞其他请求
    - 后台守护线程每 30 秒自动轮询 FTP，检测新增文件后刷新列表缓存
    - 日志系统：按月分子目录（Run_log/YYYY_M/）+ 按天轮转（保留 30 天）+ 定时统计摘要
    - 监听 0.0.0.0:9876，移动端可通过内网 IP 直接访问
    - FTP 连接失败时返回 503 + 错误码 + 错误详情

用法：
    pip install pycryptodome
    python server.py
    浏览器打开 http://localhost:9876
"""

import os
import sys
import io
import json
import re
import time
import socket
import shutil
import hashlib
import hmac
import secrets
import webbrowser
import subprocess
import threading
import logging
from datetime import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
from ftplib import FTP

# ---- 系统托盘依赖 ----
import pystray
from PIL import Image, ImageDraw, ImageFont, ImageOps

# ======================== 依赖检查 ========================
try:
    from Crypto.Cipher import AES
except ImportError:
    print("缺少依赖 pycryptodome，请先安装：")
    print("    pip install pycryptodome")
    sys.exit(1)

# ======================== 配置 ========================
FTP_HOST    = "192.168.1.88"
FTP_USER    = "anonymous"
FTP_PASS    = "anonymous@"
FTP_DIR     = "/LDTLog"                # FTP 日志根目录
# 相对于 FTP_DIR 的检索子目录列表；"" 表示根目录本身，其余为子目录名。
# 子目录下存放与根目录相同结构的加密 JSON（如旧数据），逐个追加检索即可。
FTP_SCAN_DIRS = ["", "EtnLogData"]
FTP_TIMEOUT = 10          # FTP 连接/读取超时（秒）

PORT       = 9876
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- 访问控制：只有带有效 token 的请求才能调用 API ----
ACCESS_PASSWORD = "19008"             # 页面访问密码（修改后重启服务生效）
ACCESS_TOKEN_TTL = 28800                # token 有效期 8 小时（秒），超时需重新登录

_valid_tokens = {}          # dict[token → expire_timestamp]
LOG_DIR    = os.path.join(SCRIPT_DIR, "Run_log")          # 日志根目录，按月分子目录
SERVICE_URL = f"http://localhost:{PORT}"
PID_FILE   = os.path.join(SCRIPT_DIR, "server.pid")

# 注意：不使用 socket.setdefaulttimeout()！
# 它会全局影响所有 socket，包括 HTTP 服务器的 keep-alive 连接，
# 导致浏览器空闲连接在超时后触发 TimeoutError + AttributeError 崩溃。

# ======================== 日志系统 ========================
# 特性：
#   - 按月分子目录：Run_log/2026_8/server.log
#   - 按天轮转（跨天自动重命名为 server.log.YYYY-MM-DD，保留 30 天）
#   - 控制台 + 文件双输出（pythonw 时控制台无效果但不影响文件）
#   - 毫秒级时间戳 + 日志级别 + 模块名
#   - 格式：[2026-08-03 16:53:45.123] [INFO ] [DECRYPT] 缓存命中: xxx.json
LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)-5s] [%(name)-8s] %(message)s"
LOG_DATE   = "%Y-%m-%d %H:%M:%S"
LOG_BACKUP = 30  # 每月目录中最多保留 30 个历史日志文件

_loggers = {}  # 缓存已创建的 logger 实例


class DailyRotatingFileHandler(logging.Handler):
    """自定义日志 handler：按月分子目录 + 按天轮转。

    目录结构：
        Run_log/
          2026_8/
            server.log              ← 今天的日志（当前写入）
            server.log.2026-08-02   ← 昨天的日志
            server.log.2026-08-01   ← 前天的日志
            ...（自动保留最近 30 天）
          2026_9/
            server.log
            ...

    跨天/跨月时自动轮转，无需外部调度。
    通过文件最后修改时间判断是否需要轮转，服务重启不会误轮转当天文件。
    """

    def __init__(self, base_dir: str, backup_count: int = 30):
        super().__init__()
        self._base_dir = base_dir
        self._backup_count = backup_count
        self._stream = None
        self._last_date = None    # datetime.date，用于检测跨天
        self._current_path = None

    # ---------------- 内部工具 ----------------

    @staticmethod
    def _month_key(dt: datetime = None) -> str:
        if dt is None:
            dt = datetime.now()
        return f"{dt.year}_{dt.month}"

    # ---------------- 核心：轮转 + 写入 ----------------

    def _rotate_if_needed(self):
        """根据当前日期判断是否需要轮转，跨天/跨月时自动处理。"""
        now = datetime.now()
        today = now.date()

        # 同一天且 stream 已打开 → 无需轮转
        if self._last_date == today and self._stream is not None:
            return

        month_dir = os.path.join(self._base_dir, self._month_key(now))
        os.makedirs(month_dir, exist_ok=True)

        log_path = os.path.join(month_dir, "server.log")

        # 现有文件是旧日期的 → 加日期后缀轮转
        if os.path.exists(log_path):
            mtime = datetime.fromtimestamp(os.path.getmtime(log_path)).date()
            if mtime < today:
                backup = f"{log_path}.{mtime:%Y-%m-%d}"
                try:
                    os.rename(log_path, backup)
                except OSError:
                    pass

        # 关闭旧 stream（如果有）
        if self._stream:
            self._stream.close()
            self._stream = None

        # 打开今天的日志文件
        self._stream = open(log_path, "a", encoding="utf-8", buffering=1)
        self._current_path = log_path
        self._last_date = today

        # 清理当月目录中的旧备份
        self._cleanup(month_dir)

    def _cleanup(self, month_dir: str):
        """删除超出 backup_count 的历史日志文件。"""
        try:
            backups = sorted(
                [f for f in os.listdir(month_dir) if f.startswith("server.log.")],
                reverse=True,
            )
            for old in backups[self._backup_count:]:
                try:
                    os.remove(os.path.join(month_dir, old))
                except OSError:
                    pass
        except Exception:
            pass  # 清理失败不影响日志写入

    # ---------------- Handler 接口 ----------------

    def emit(self, record: logging.LogRecord):
        try:
            self._rotate_if_needed()
            msg = self.format(record)
            self._stream.write(msg + "\n")
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self):
        self.acquire()
        try:
            if self._stream:
                self._stream.flush()
                self._stream.close()
                self._stream = None
        finally:
            self.release()
        super().close()


def get_logger(name: str) -> logging.Logger:
    """获取或创建模块级 logger。线程安全，可在任意位置调用。"""
    if name in _loggers:
        return _loggers[name]
    lg = logging.getLogger(f"LDT.{name}")
    lg.setLevel(logging.DEBUG)  # logger 本身设 DEBUG，由 handler 级别控制
    lg.propagate = False        # 不向上传播到 root logger
    _loggers[name] = lg
    return lg

def setup_logging():
    """初始化日志系统：创建 Run_log/ 目录、配置 handler、连接各 logger。"""
    os.makedirs(LOG_DIR, exist_ok=True)

    # ---- 文件 handler：按天轮转 + 按月分子目录，保留 30 天 ----
    fh = DailyRotatingFileHandler(LOG_DIR, backup_count=LOG_BACKUP)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE))

    # ---- 控制台 handler：python server.py 时可见 ----
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE))

    # 将所有已注册 logger 连接到 handler
    for lg in _loggers.values():
        lg.addHandler(fh)
        lg.addHandler(ch)

# 预创建所有模块 logger（setup_logging 会统一配 handler）
log_main    = get_logger("MAIN")
log_ftp     = get_logger("FTP")
log_api     = get_logger("API")
log_decrypt = get_logger("DECRYPT")

# ---- 统计计数器（供定时摘要使用） ----
_stats_lock = threading.Lock()
_stats = {
    "api_ok": 0,          # 200 响应数
    "api_err": 0,         # 4xx/5xx 响应数
    "cache_hits": 0,      # 数据缓存命中
    "cache_misses": 0,    # 数据缓存未命中（需 FTP 下载）
    "decrypt_count": 0,   # 实际处理次数
    "decrypt_total_ms": 0.0,  # 处理总耗时（毫秒）
    "decrypt_max_ms": 0.0,    # 最慢单次处理耗时
    "decrypt_bytes": 0,   # 处理总字节数
}

def stats_log_summary():
    """输出运行摘要日志（每 5 分钟调用一次）"""
    with _stats_lock:
        total_api = _stats["api_ok"] + _stats["api_err"]
        total_cache = _stats["cache_hits"] + _stats["cache_misses"]
        hit_rate = (100.0 * _stats["cache_hits"] / total_cache) if total_cache > 0 else 0
        avg_ms = (_stats["decrypt_total_ms"] / _stats["decrypt_count"]) if _stats["decrypt_count"] > 0 else 0

        log_main.info("=" * 50)
        log_main.info(f"运行摘要 (累计)")
        log_main.info(f"  API 请求  : {total_api} 次 (200:{_stats['api_ok']}, 错误:{_stats['api_err']})")
        log_main.info(f"  数据缓存  : 命中率 {hit_rate:.1f}% ({_stats['cache_hits']}/{total_cache})")
        log_main.info(f"  处理操作  : {_stats['decrypt_count']} 次, 平均 {avg_ms:.0f}ms, 最慢 {_stats['decrypt_max_ms']:.0f}ms")
        log_main.info(f"  处理数据  : {_stats['decrypt_bytes']//1024} KB (共 {_stats['decrypt_bytes']} 字节)")
        log_main.info("=" * 50)

def _stats_loop(interval=300):
    """后台线程：每 interval 秒输出一次统计摘要"""
    while True:
        time.sleep(interval)
        try:
            stats_log_summary()
        except Exception:
            pass

# ======================== 托盘全局状态 ========================
_tray_icon = None          # pystray.Icon 实例
_server = None             # ThreadingServer 实例
_ftp_state = {"ok": False, "file_count": 0, "last_error": ""}
_ftp_state_lock = threading.Lock()

def get_ftp_state():
    with _ftp_state_lock:
        return dict(_ftp_state)

def set_ftp_state(ok=None, file_count=None, last_error=None):
    with _ftp_state_lock:
        if ok is not None: _ftp_state["ok"] = ok
        if file_count is not None: _ftp_state["file_count"] = file_count
        if last_error is not None: _ftp_state["last_error"] = last_error

def update_tray_menu():
    """刷新托盘菜单中的文件数量和状态文本"""
    global _tray_icon
    if _tray_icon is None:
        return
    state = get_ftp_state()
    status_text = "运行中" if state["ok"] else f"⚠ {state['last_error'] or '异常'}"
    _tray_icon.title = f"LDTools — {status_text} | {state['file_count']} 个文件"
    # 重建菜单以更新禁用项的文本
    # [2026-08-22 FIX] pystray 的 update_menu() 不接受参数（只刷新显示）；
    # 正确做法：给 icon.menu 赋新值（setter 内部会自动调用 update_menu 刷新）
    _tray_icon.menu = _build_tray_menu(_tray_icon)


_V1 = bytes.fromhex("7ad543a8fddcb85f71ecb0d8c717db4e9bd614388fc78984f2f0fa266f68c98f")
_V2 = bytes.fromhex("8d661517545dcf154fbc014d8edb9a326434d54df2c9992403dacee6bb1ecbcd")
_X1 = bytes.fromhex("b1a5e44b526421b464e5894436a8e00d212897d330211ad10685e07b0598866b")
_X2 = bytes.fromhex("63a57d54fa6010a947fe31a60cb8da6ed5e7ec5e006688c0b529af6d35abd9d2")
_K1 = bytes(a ^ b for a, b in zip(_V1, _X1))
_K2 = bytes(a ^ b for a, b in zip(_V2, _X2))

# ======================== 内存缓存（进程退出即清空） ========================
_cache_lock = threading.Lock()
_file_list_cache  = None      # list[str]  — FTP 文件名列表（纯文件名，供前端使用）
_file_path_map    = {}        # dict[str, str]  — 文件名 → FTP 相对路径（如 "EtnLogData/xxx.json"）
_decrypted_cache  = {}        # dict[str, dict]  — 文件名 → 处理后的明文 JSON
_file_version     = 0         # int — 文件列表版本号，每次文件变化时 +1


# ======================== 备注持久化（notes.json 落盘） ========================
# [2026-08-22] 新增：备注从浏览器 localStorage 迁移到服务端持久化（方案A + 口径D）
# 结构：{ "SN序列号": { "text": "备注内容", "updatedAt": "YYYY-MM-DD HH:MM:SS" } }
# 乐观锁：POST 带 baseUpdatedAt（前端加载时看到的 updatedAt），不一致返回 409 + current
# 回滚标记：删除本段 + do_GET/do_POST 中的 /api/notes 路由 + handle_notes/handle_notes_post 即可
NOTES_FILE = os.path.join(SCRIPT_DIR, "notes.json")
# [2026-08-22] RLock（可重入锁）：notes_upsert / handle_notes 持锁后内部会再调 _notes_load()
# （其内部也获取同一把锁）。用普通 Lock 会同线程自我死锁 → 锁被永久占用 → /api/notes 全部挂起
# → 前端 init 卡在 loadNotesRemote() → 日志加载不出来。
# 回滚标记：如需还原为普通锁，改回 threading.Lock()（同时必须消除嵌套获取）。
_notes_lock = threading.RLock()
_notes_cache = None          # dict[sn → {"text","updatedAt"}] — None 表示尚未从磁盘加载


def _notes_load():
    """懒加载 notes.json 到内存缓存（首次访问时执行）"""
    global _notes_cache
    if _notes_cache is not None:
        return _notes_cache
    with _notes_lock:
        if _notes_cache is None:
            data = {}
            try:
                if os.path.exists(NOTES_FILE):
                    with open(NOTES_FILE, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    if isinstance(raw, dict):
                        # 兼容清洗：只保留合法结构
                        for sn, v in raw.items():
                            if isinstance(sn, str) and sn and isinstance(v, dict) and isinstance(v.get("text"), str):
                                data[sn] = {"text": v["text"], "updatedAt": v.get("updatedAt", "")}
            except (json.JSONDecodeError, OSError) as e:
                log_api.warning(f"notes.json 读取失败，按空处理: {e}")
            _notes_cache = data
    return _notes_cache


def _notes_persist():
    """把内存缓存写回 notes.json（调用方需已持有 _notes_lock）"""
    try:
        with open(NOTES_FILE, "w", encoding="utf-8") as f:
            json.dump(_notes_cache, f, ensure_ascii=False, indent=2)
    except OSError as e:
        log_api.error(f"notes.json 写入失败: {e}")


def notes_upsert(sn, text, base_updated_at=None, force=False):
    """保存/删除一条备注（text 为空即删除）。

    返回 (ok, payload)：
      - 成功：(True, {"ok": True, "updatedAt": ..., "deleted": bool})
      - 冲突：(False, current_note 或 None)  — 由调用方包装为 409
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _notes_lock:
        notes = _notes_load()
        current = notes.get(sn)
        # ---- 乐观锁冲突检测（force=true 跳过） ----
        if not force:
            if base_updated_at is None:
                # 前端认为是新备注，但服务器已存在 → 他人已创建 → 冲突
                if current is not None:
                    return False, current
            else:
                # 前端基于某个版本修改，但服务器版本不一致（或已被删除）→ 冲突
                if current is None or current.get("updatedAt") != base_updated_at:
                    return False, current
        # ---- 执行写入/删除 ----
        if text:
            notes[sn] = {"text": text, "updatedAt": now}
            deleted = False
        else:
            deleted = sn in notes
            notes.pop(sn, None)
        _notes_persist()
    return True, {"ok": True, "updatedAt": now, "deleted": deleted}


# ======================== 出库记录（[2026-08-24 OUTBOUND] 由 CPU 档案就地改造） ========================
# 设备出库状态拍照记录：主机记录（必选）+ 配件记录（可选）两组照片
# 存储：Outbound_System_Condition_Archive/OSCA_YYYYMMDD-HHMMSS_<SN>/{host_*, part_*, meta.json}
# 特性：原图直传零转码、魔数嗅探、SHA256 审计、原子写入（tmp → rename）、索引自愈
#       [2026-08-22] 删除/覆盖改为直接永久删除（暂移软删除 .trash/deletions.log 机制）
# 历史方案：CPU PSN/FPO 拍照记录见 Docs/CPU-Photo-Archive-Plan.md（v3 定稿）
# 回滚标记：删除本段（至 _outbound_archive_delete 结束）+ do_GET/do_POST/do_DELETE 中的
#          /api/outbound-archive、/api/outbound-image 路由 + handle_outbound_* 方法 + end_headers 的
#          _img_cache 分支 + _check_auth/_require_auth 的 qs 参数即可完整回滚。
OUTBOUND_ARCHIVE_DIR   = os.path.join(SCRIPT_DIR, "Outbound_System_Condition_Archive")
OUTBOUND_INDEX_FILE    = os.path.join(OUTBOUND_ARCHIVE_DIR, "index.json")
OUTBOUND_MAX_IMAGE_BYTES  = 35 * 1024 * 1024   # 单张 35MB 上限

_outbound_write_lock = threading.RLock()   # 串行化写操作（上传落盘/删除/索引更新）；RLock 防同线程嵌套死锁
_outbound_index_cache = None               # dict[sn → {folder, uploadedAt, files:[...]}]，None 表示未加载
_OB_SN_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')   # SN 白名单字符（防路径注入）


def _ob_sn_ok(sn):
    return isinstance(sn, str) and bool(_OB_SN_RE.match(sn))


def _safe_join(base, rel):
    """路径白名单校验：拒绝 .. 段/绝对路径/反斜杠，realpath 二次校验必须在 base 内。

    返回拼接后的绝对路径，不合法返回 None。
    """
    if not rel or not isinstance(rel, str) or "\\" in rel:
        return None
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return None
    path = os.path.join(base, *parts)
    try:
        bp = os.path.realpath(base)
        rp = os.path.realpath(path)
        if os.path.commonpath([bp, rp]) != bp:
            return None
    except (ValueError, OSError):
        return None
    return path


def _parts_shrink_image(blob, ext):
    """[2026-10-03 SHRINK] 上传照片落地前重编码：EXIF 转正 + 最长边 PARTS_IMG_MAX_EDGE + JPEG q85。

    返回 (新bytes, 新ext)；只有变小才替换（小图重编码可能反而变大），
    PIL 异常时原样返回原图（压缩失败不阻断上传）。
    """
    try:
        img = Image.open(io.BytesIO(blob))
        img = ImageOps.exif_transpose(img)          # 按手机 EXIF 转正（与缩略图逻辑一致）
        if max(img.size) > PARTS_IMG_MAX_EDGE:
            img.thumbnail((PARTS_IMG_MAX_EDGE, PARTS_IMG_MAX_EDGE))
        out = io.BytesIO()
        img.convert("RGB").save(out, "JPEG", quality=PARTS_IMG_JPEG_QUALITY, optimize=True)
        data = out.getvalue()
        if len(data) < len(blob):
            return data, "jpg"
    except Exception as e:
        log_api.warning(f"照片重编码失败，按原图保存: {e}")
    return blob, ext


def _sniff_image(data):
    """文件头魔数嗅探 → (ext, mime)；非法格式返回 None。扩展名/MIME 不作为信任依据。"""
    if len(data) >= 3 and data[0:3] == b"\xff\xd8\xff":
        return "jpg", "image/jpeg"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def _outbound_index_persist():
    """写回 index.json。调用方需已持有 _outbound_write_lock。
    [2026-08-22 清理] 移除 .bak 备份：方案 A 启动时强制按磁盘重建索引，
    .bak 里的旧 cache 状态已无恢复价值（恢复了反而是脏数据）。
    """
    global _outbound_index_cache
    try:
        os.makedirs(OUTBOUND_ARCHIVE_DIR, exist_ok=True)
        with open(OUTBOUND_INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(_outbound_index_cache, f, ensure_ascii=False, indent=2)
    except OSError as e:
        log_api.error(f"出库 index.json 写入失败: {e}")


def _outbound_index_rebuild():
    """扫描归档目录重建索引（索引自愈）。跳过 .trash / .tmp_* / 非 OSCA_ 前缀目录。

    文件夹名 OSCA_YYYYMMDD-HHMMSS_<SN>：SN 白名单含 '-'，但时间戳段不含 '_'，
    故按第一个 '_' 切分出时间戳与 SN（SN 自身可含 '_'）。
    meta.json 缺失时仅记录文件名/大小，sha256 留空（首次访问 /api/outbound-image 时懒计算补记）。
    """
    idx = {}
    try:
        entries = os.listdir(OUTBOUND_ARCHIVE_DIR)
    except OSError:
        return idx
    for name in entries:
        full = os.path.join(OUTBOUND_ARCHIVE_DIR, name)
        if name.startswith(".") or not os.path.isdir(full):
            continue
        rest = name.split("_", 1)          # ["OSCA", "YYYYMMDD-HHMMSS_<SN>"]
        if len(rest) != 2 or rest[0] != "OSCA":
            continue
        tail = rest[1].split("_", 1)       # ["YYYYMMDD-HHMMSS", "<SN>"]
        if len(tail) != 2 or not tail[0]:
            continue
        sn = tail[1]
        if not _ob_sn_ok(sn):
            continue
        meta = {}
        try:
            with open(os.path.join(full, "meta.json"), "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            meta = {}
        files = []
        try:
            for fn in sorted(os.listdir(full)):
                fpath = os.path.join(full, fn)
                if fn == "meta.json" or fn.startswith(".") or not os.path.isfile(fpath):
                    continue
                ftype = "host" if fn.startswith("host") else ("part" if fn.startswith("part") else "other")
                files.append({"type": ftype, "name": fn,
                              "size": os.path.getsize(fpath), "sha256": ""})
        except OSError:
            pass
        idx[sn] = {"folder": name, "uploadedAt": meta.get("uploadedAt", ""), "files": files}
    log_api.warning("出库索引自愈重建完成（index.json 缺失或损坏）")
    return idx


def _outbound_index_load():
    """懒加载 index.json 到内存缓存；缺失/损坏时扫描目录自愈重建。"""
    global _outbound_index_cache
    if _outbound_index_cache is not None:
        return _outbound_index_cache
    with _outbound_write_lock:
        if _outbound_index_cache is not None:
            return _outbound_index_cache
        idx = None
        if os.path.exists(OUTBOUND_INDEX_FILE):
            try:
                with open(OUTBOUND_INDEX_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    idx = {}
                    for sn, v in raw.items():
                        if _ob_sn_ok(sn) and isinstance(v, dict) and isinstance(v.get("folder"), str):
                            files = []
                            if isinstance(v.get("files"), list):
                                for it in v["files"]:
                                    if isinstance(it, dict) and isinstance(it.get("name"), str):
                                        try:
                                            size = int(it.get("size") or 0)
                                        except (TypeError, ValueError):
                                            size = 0
                                        files.append({"type": it.get("type", ""), "name": it["name"],
                                                      "size": size, "sha256": str(it.get("sha256") or "")})
                            idx[sn] = {"folder": v["folder"], "uploadedAt": str(v.get("uploadedAt") or ""),
                                       "files": files}
            except (json.JSONDecodeError, OSError, ValueError) as e:
                log_api.warning(f"出库 index.json 读取失败，将自愈重建: {e}")
                idx = None
        if idx is None:
            _outbound_index_cache = _outbound_index_rebuild()
            _outbound_index_persist()
        else:
            _outbound_index_cache = idx
    return _outbound_index_cache


def _outbound_archive_upload(sn, files_input):
    """原子上传落盘：临时文件夹 → 魔数/大小校验 → 旧档永久删除 → rename 生效 → 更新索引。

    files_input: {type: (原始文件名, bytes)}，type ∈ {'host','part'}，至少一项。
    返回 (ok, payload)。
    """
    now = datetime.now()
    ts = now.strftime("%Y%m%d-%H%M%S")
    folder_name = f"OSCA_{ts}_{sn}"
    tmp_dir = os.path.join(OUTBOUND_ARCHIVE_DIR, f".tmp_{sn}_{ts}")
    with _outbound_write_lock:
        idx = _outbound_index_load()
        try:
            os.makedirs(OUTBOUND_ARCHIVE_DIR, exist_ok=True)
            os.makedirs(tmp_dir)
            files_meta = []
            original_names = {}
            for ftype in ("host", "part"):
                item = files_input.get(ftype)
                if not item or not item[1]:
                    continue
                orig_name, blob = item
                sniff = _sniff_image(blob)
                if sniff is None:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    return False, {"code": "ERR_BAD_IMAGE",
                                   "message": f"{ftype} 文件不是有效的图片（仅支持 JPEG/PNG/WebP）"}
                if len(blob) > OUTBOUND_MAX_IMAGE_BYTES:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    return False, {"code": "ERR_TOO_LARGE",
                                   "message": f"{ftype} 文件超过单张 35MB 上限"}
                ext, _mime = sniff
                fname = f"{ftype}_{ts}.{ext}"
                with open(os.path.join(tmp_dir, fname), "wb") as f:
                    f.write(blob)
                files_meta.append({"type": ftype, "name": fname, "size": len(blob),
                                   "sha256": hashlib.sha256(blob).hexdigest()})
                original_names[ftype] = orig_name or ""
            meta = {
                "uploadedAt": now.strftime("%Y-%m-%d %H:%M:%S"),
                "originalNames": original_names,
                "sizes": {f["type"]: f["size"] for f in files_meta},
                "sha256": {f["type"]: f["sha256"] for f in files_meta},
            }
            with open(os.path.join(tmp_dir, "meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            # 旧档案（若有）直接永久删除（[2026-08-22] 暂移软删除机制）
            old = idx.get(sn)
            if old and old.get("folder"):
                old_dir = _safe_join(OUTBOUND_ARCHIVE_DIR, old["folder"])
                if old_dir and os.path.isdir(old_dir):
                    shutil.rmtree(old_dir, ignore_errors=True)
            # 临时文件夹 → 正式文件夹（原子 rename）
            os.rename(tmp_dir, os.path.join(OUTBOUND_ARCHIVE_DIR, folder_name))
            # 更新索引并落盘
            idx[sn] = {"folder": folder_name, "uploadedAt": meta["uploadedAt"], "files": files_meta}
            _outbound_index_persist()
            log_api.info(f"出库档案上传: {sn} → {folder_name}（{len(files_meta)} 张, "
                         f"{sum(f['size'] for f in files_meta)//1024}KB）")
            return True, {"ok": True, "folder": folder_name, "uploadedAt": meta["uploadedAt"],
                          "files": files_meta}
        except OSError as e:
            shutil.rmtree(tmp_dir, ignore_errors=True)   # 失败清理临时目录，原档案不受影响
            log_api.error(f"出库档案上传失败: {sn}: {e}")
            return False, {"code": "ERR_IO", "message": f"写入失败: {e}"}


def _outbound_archive_delete(sn):
    """永久删除：直接移除档案文件夹 + 更新索引。（[2026-08-22] 暂移软删除 .trash 机制）"""
    with _outbound_write_lock:
        idx = _outbound_index_load()
        entry = idx.get(sn)
        if not entry:
            return False, {"code": "ERR_NOT_FOUND", "message": "该 SN 无出库档案"}
        try:
            target = _safe_join(OUTBOUND_ARCHIVE_DIR, entry["folder"])
            if target and os.path.isdir(target):
                shutil.rmtree(target)
        except OSError as e:
            log_api.error(f"出库档案删除失败: {sn}: {e}")
            return False, {"code": "ERR_IO", "message": f"删除失败: {e}"}
        idx.pop(sn, None)
        _outbound_index_persist()
        log_api.info(f"出库档案删除: {sn}（{entry['folder']}）已永久删除")
        return True, {"ok": True, "deleted": True, "folder": entry["folder"]}


def _outbound_archive_summary():
    """全量摘要（卡片徽章数据源）：{sn: {folder, uploadedAt, count}}，轻量无明细。"""
    idx = _outbound_index_load()
    return {sn: {"folder": v["folder"], "uploadedAt": v.get("uploadedAt", ""),
                 "count": len(v.get("files", []))} for sn, v in idx.items()}


def _outbound_self_heal_remove(sn):
    """[2026-08-22 CPU-ARCHIVE-self-heal → 2026-08-24 OUTBOUND] 从索引移除指定 SN 并写回 index.json。

    调用方无需持有 _outbound_write_lock，本函数内部自取。
    """
    with _outbound_write_lock:
        idx = _outbound_index_load()
        if sn in idx:
            del idx[sn]
            _outbound_index_persist()
            log_api.warning(f"出库索引自愈：已移除 SN={sn} 的幽灵档案")


def _outbound_archive_detail(sn):
    """单 SN 明细（含图片 URL），无档案返回 None。

    [2026-08-22 CPU-ARCHIVE-self-heal → 2026-08-24 OUTBOUND] 加磁盘真实性校验：cache 有该 SN 但 OSCA 文件夹
    或图片文件物理缺失时（用户手动删了文件夹但没走 DELETE API），自动清理 cache 并返回 None，
    避免「detail 元数据存在但 outbound-image 404」的幽灵档案现象。
    """
    idx = _outbound_index_load()
    v = idx.get(sn)
    if not v:
        return None
    # 磁盘真实性校验：OSCA 文件夹必须存在
    folder_path = os.path.join(OUTBOUND_ARCHIVE_DIR, v.get("folder", ""))
    if not os.path.isdir(folder_path):
        log_api.warning(f"出库自愈检测：SN={sn} 文件夹缺失（{v.get('folder')}），清理索引")
        _outbound_self_heal_remove(sn)
        return None
    # 校验每个文件物理存在性，剔除缺失的（保留存在的）
    files_alive = []
    for f in v.get("files", []):
        fpath = os.path.join(folder_path, f.get("name", ""))
        if os.path.isfile(fpath):
            item = dict(f)
            item["url"] = "/api/outbound-image?path=" + quote(f"{v['folder']}/{f['name']}", safe="")
            files_alive.append(item)
    if not files_alive:
        log_api.warning(f"出库自愈检测：SN={sn} 所有文件均缺失，清理索引")
        _outbound_self_heal_remove(sn)
        return None
    # 部分文件缺失 → 同步更新 cache + index.json（避免 summary 仍返回旧 count）
    if len(files_alive) < len(v.get("files", [])):
        missing = len(v.get("files", [])) - len(files_alive)
        log_api.warning(f"出库自愈检测：SN={sn} 的 {missing} 个文件物理缺失，更新索引")
        with _outbound_write_lock:
            idx2 = _outbound_index_load()
            if sn in idx2:
                # cache 只存元数据（不含 url），重新构造干净数组
                idx2[sn]["files"] = [
                    {"type": f["type"], "name": f["name"], "size": f["size"], "sha256": f["sha256"]}
                    for f in files_alive
                ]
                _outbound_index_persist()
    return {"exists": True, "folder": v["folder"], "uploadedAt": v.get("uploadedAt", ""), "files": files_alive}


def _parse_multipart(body, content_type):
    """手写 multipart/form-data 解析（Python 3.13 已移除 cgi 模块，决策 2026-08-22）。

    返回 {field_name: (filename 或 None, bytes)}；Content-Type 无 boundary 返回 None。
    注：按 boundary 字节切分——浏览器生成的 boundary 为随机串，
    图片二进制中出现的概率可忽略。
    """
    m = re.search(r'boundary="?([^";]+)"?', content_type or "")
    if not m:
        return None
    boundary = ("--" + m.group(1)).encode("latin-1")
    fields = {}
    for part in body.split(boundary)[1:-1]:     # 首段为 boundary 之前内容，末段为结束标记
        if part.startswith(b"\r\n"):
            part = part[2:]
        elif part.startswith(b"\n"):
            part = part[1:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        elif part.endswith(b"\n"):
            part = part[:-1]
        sep = part.find(b"\r\n\r\n")
        if sep >= 0:
            head, content = part[:sep], part[sep + 4:]
        else:
            sep = part.find(b"\n\n")
            if sep < 0:
                continue
            head, content = part[:sep], part[sep + 2:]
        name_m = re.search(r'name="([^"]*)"', head.decode("utf-8", "replace"))
        if not name_m:
            continue
        fname_m = re.search(r'filename="([^"]*)"', head.decode("utf-8", "replace"))
        fields[name_m.group(1)] = (fname_m.group(1) if fname_m else None, content)
    return fields


def _parse_multipart_multi(body, content_type):
    """multipart/form-data 多值解析：同名部件收集为列表。

    返回 {field_name: [(filename 或 None, bytes), ...]}；Content-Type 无 boundary 返回 None。
    APK/网页多图上传时同名 cpuFile 出现多次，也兼容 cpuFile_1..N 命名（调用方归并）。
    """
    m = re.search(r'boundary="?([^";]+)"?', content_type or "")
    if not m:
        return None
    boundary = ("--" + m.group(1)).encode("latin-1")
    fields = {}
    for part in body.split(boundary)[1:-1]:
        if part.startswith(b"\r\n"):
            part = part[2:]
        elif part.startswith(b"\n"):
            part = part[1:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        elif part.endswith(b"\n"):
            part = part[:-1]
        sep = part.find(b"\r\n\r\n")
        if sep >= 0:
            head, content = part[:sep], part[sep + 4:]
        else:
            sep = part.find(b"\n\n")
            if sep < 0:
                continue
            head, content = part[:sep], part[sep + 2:]
        name_m = re.search(r'name="([^"]*)"', head.decode("utf-8", "replace"))
        if not name_m:
            continue
        fname_m = re.search(r'filename="([^"]*)"', head.decode("utf-8", "replace"))
        fields.setdefault(name_m.group(1), []).append(
            (fname_m.group(1) if fname_m else None, content))
    return fields


# ======================== 主机配件档案（[2026-09-29 PARTS] APK 拍照识别 → 上传归档） ========================
# 手机 APK（LDPartsScanner）拍照 CPU/主机 → ML Kit 端上 OCR 识别 → 用户确认 → multipart 上传到本服务。
# 存储：[2026-10-02 DATE-TREE] Parts_Archive/<年>/<月>/<日>/<主机SN>/…（月/日不补零，如 2026/9/29/J16Z144；
#       同日同 SN 撞名追加 _2/_3）。旧平铺 PA_YYYYMMDD-HHMMSS_<SN> 启动时由 _parts_migrate_layout 自动迁移。
# [2026-09-29 KEEP-BOTH] 每次上传都是一条完整新档案，绝不覆盖旧记录——
# 同一颗 CPU（同编号）出现在不同机器上、或重复拍照时，各条档案完整保留互不干扰；
# 同秒同 SN 撞名时文件夹名追加 -2/-3 序号保证唯一。CPU/主机各最多 6 张照片。
# API（全部走既有 Bearer/?token= 鉴权）：
#   GET    /api/parts-archive                → {"records":[...]}（全量，档案量小一次拉齐）
#   GET    /api/parts-archive?folder=<dir>   → 单条明细（含图片 URL），无则 {"exists": false}
#   POST   /api/parts-archive                → multipart 上传（sn 必填 + cpuModel/cpuBatch/cpuCode/note + cpuFile*/hostFile*）
#   POST   /api/parts-archive/update         → 修改档案参数（JSON：{folder, fields:{sn/cpuModel/...}}，[2026-10-08 EDIT] 网页编辑纠错）
#   DELETE /api/parts-archive?folder=<dir>   → 永久删除档案文件夹
#   GET    /api/parts-image?path=<rel>       → 图片按需下载（支持 ?token=，<img> 标签用）
# 回滚标记：删除本段（至本段结束）+ do_GET/do_POST/do_DELETE 路由 + handle_parts_* 方法 + main() 启动对齐块。
PARTS_ARCHIVE_DIR        = r"D:\Users\Administrator\Desktop\ETNLOGO\Parts_Archive"  # [2026-10-23 MOVED] 数据外置到 ETNLOGO（重装系统后合并新旧数据）
PARTS_INDEX_FILE         = os.path.join(PARTS_ARCHIVE_DIR, "index.json")
PARTS_MAX_IMAGE_BYTES    = 35 * 1024 * 1024     # 单张 35MB 上限
PARTS_MAX_FILES_PER_TYPE = 6                    # 每类最多 6 张
# [2026-10-13 DELETE-ADMIN] 网页删除档案需管理员密码（区别于登录密码，二次确认防线）
PARTS_ADMIN_PASSWORD     = "4328085"
# [2026-09-30 v1.02] 配件类目：CPU / 主机 / 内存 / 固态 / 其他（网卡仅保留旧档案兼容，APP 已下线）
PARTS_FILE_TYPES         = ("cpu", "host", "ram", "ssd", "nic", "other")
PARTS_TEXT_FIELDS        = ("machineModel",                             # 主机型号（标签拍照识别）
                            "cpuModel", "cpuBatch", "cpuCode",           # CPU 三元组
                            "ramInfo", "ssdInfo", "nicInfo", "otherInfo", # 各配件识别参数（自由文本）
                            "vendor",                                    # [2026-10-11 VENDOR] 供应商（联想/戴尔/建钰/其他/无 或手输）
                            "note")                                       # 备注
PARTS_TEXT_MAXLEN        = {"machineModel": 64, "cpuModel": 64, "cpuBatch": 64, "cpuCode": 64,
                            "ramInfo": 500, "ssdInfo": 500, "nicInfo": 500,
                            "otherInfo": 500, "vendor": 64, "note": 500}
PARTS_THUMB_DIR          = os.path.join(PARTS_ARCHIVE_DIR, ".thumbs")   # 缩略图缓存（. 前缀目录，索引自愈跳过）
PARTS_THUMB_SIZE         = 256   # 缩略图最长边（像素）

# [2026-10-03 SHRINK] 上传照片落地重编码：手机原图多为 12MP 高清 JPEG（单张 4-8MB），
# 档案查看用不需要原分辨率 → EXIF 转正 + 最长边 2560px + JPEG q85，
# 体积约为原图 1/4~1/3、画质肉眼无差（OCR 在 APP 端上传前已完成，服务端不依赖原图分辨率）。
PARTS_IMG_MAX_EDGE       = 2560
PARTS_IMG_JPEG_QUALITY   = 85

_parts_write_lock  = threading.RLock()   # 串行化写操作（落盘/删除/索引）；RLock 防同线程嵌套死锁
_parts_index_cache = None                # dict[folder → record]，None 表示未加载
# [2026-10-02 DATE-TREE] 档案相对路径白名单：<年>/<月>/<日>/<SN>（月/日 1-2 位不补零；同日撞名 SN_N）
_PA_FOLDER_RE = re.compile(r'^\d{4}/\d{1,2}/\d{1,2}/[A-Za-z0-9_-]{1,64}(?:_\d+)?$')


def _parts_index_persist():
    """原子写回 index.json。调用方需已持有 _parts_write_lock。"""
    tmp = PARTS_INDEX_FILE + ".tmp"
    try:
        os.makedirs(PARTS_ARCHIVE_DIR, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_parts_index_cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PARTS_INDEX_FILE)
    except OSError as e:
        log_api.error(f"配件档案 index.json 写入失败: {e}")
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _parts_migrate_layout():
    """[2026-10-02 DATE-TREE] 旧平铺结构 PA_YYYYMMDD-HHMMSS_<SN> → 日期树 YYYY/M/D/SN（幂等）。

    把顶层 PA_ 档案夹搬进对应日期目录（同日撞名追加 _2/_3）；
    全部搬完后旧 index.json 键全部失效 → 删除让 _parts_index_load 自愈重建，
    旧缩略图缓存同理直接清掉（按新路径按需重新生成）。
    """
    try:
        entries = os.listdir(PARTS_ARCHIVE_DIR)
    except OSError:
        return
    pa_re = re.compile(r'^PA_(\d{4})(\d{2})(\d{2})-\d{6}_(.+)$')
    moved = 0
    for name in entries:
        m = pa_re.match(name)
        full = os.path.join(PARTS_ARCHIVE_DIR, name)
        if not m or not os.path.isdir(full):
            continue
        year, month, day, sn = m.group(1), str(int(m.group(2))), str(int(m.group(3))), m.group(4)
        day_dir = os.path.join(PARTS_ARCHIVE_DIR, year, month, day)
        dest_rel = f"{year}/{month}/{day}/{sn}"
        target = os.path.join(day_dir, sn)
        uniq = 1
        while os.path.exists(target):
            uniq += 1
            dest_rel = f"{year}/{month}/{day}/{sn}_{uniq}"
            target = os.path.join(day_dir, f"{sn}_{uniq}")
        try:
            os.makedirs(day_dir, exist_ok=True)
            os.rename(full, target)
            moved += 1
        except OSError as e:
            log_api.error(f"配件档案迁移失败 {name}: {e}")
    if not moved:
        return
    shutil.rmtree(PARTS_THUMB_DIR, ignore_errors=True)
    try:
        os.remove(PARTS_INDEX_FILE)
    except OSError:
        pass
    log_api.warning(f"配件档案目录结构迁移完成：{moved} 条 PA_ 档案 → 日期树（年/月/日/SN）")


def _parts_index_rebuild(existing=None):
    """扫描归档目录重建索引（索引自愈）。[2026-10-02 DATE-TREE] 递归扫描 年/月/日/SN 日期树，
    兼容容错顶层旧 PA_ 命名（正常已被 _parts_migrate_layout 迁走）。跳过 . 前缀目录。

    meta.json 缺失时仅按文件名归档（字段留空，sha256 留空，懒计算补记）。
    """
    idx = {}
    try:
        entries = os.listdir(PARTS_ARCHIVE_DIR)
    except OSError:
        return idx
    pa_re = re.compile(r'^PA_(\d{4})(\d{2})(\d{2})-\d{6}_(.+)$')

    def _scan(rel, full):
        if existing is not None:
            if rel in existing or not _PA_FOLDER_RE.fullmatch(rel):
                return
            if not os.path.isfile(os.path.join(full, "meta.json")):
                return
        meta = {}
        try:
            with open(os.path.join(full, "meta.json"), "r", encoding="utf-8") as f:
                meta = json.load(f)
            if not isinstance(meta, dict):
                raise ValueError("meta.json 必须是对象")
        except Exception:
            if existing is not None:
                log_api.warning(f"配件档案补索引跳过损坏元数据: {rel}")
                return
            meta = {}
        files = []
        metadata_files = meta.get("files") if isinstance(meta.get("files"), list) else []
        file_metadata = {item.get("name"): item for item in metadata_files
                         if isinstance(item, dict) and isinstance(item.get("name"), str)}
        try:
            for fn in sorted(os.listdir(full)):
                fpath = os.path.join(full, fn)
                if fn == "meta.json" or fn.startswith(".") or not os.path.isfile(fpath):
                    continue
                ftype = next((t for t in ("cpu", "host", "ram", "ssd", "nic")
                              if fn.startswith(t)), "other")
                files.append({"type": ftype, "name": fn,
                              "size": os.path.getsize(fpath),
                              "sha256": str(file_metadata.get(fn, {}).get("sha256") or "")})
        except OSError:
            pass
        idx[rel] = {
            "folder": rel,
            "sn": str(meta.get("sn") or rel.rsplit("/", 1)[-1] or ""),
            "machineModel": str(meta.get("machineModel") or ""),
            "cpuModel": str(meta.get("cpuModel") or ""),
            "cpuBatch": str(meta.get("cpuBatch") or ""),
            "cpuCode": str(meta.get("cpuCode") or ""),
            "ramInfo": str(meta.get("ramInfo") or ""),
            "ssdInfo": str(meta.get("ssdInfo") or ""),
            "nicInfo": str(meta.get("nicInfo") or ""),
            "otherInfo": str(meta.get("otherInfo") or ""),
            "vendor": str(meta.get("vendor") or ""),
            "note": str(meta.get("note") or ""),
            "uploadedAt": str(meta.get("uploadedAt") or ""),
            "files": files,
        }

    for name in entries:
        full = os.path.join(PARTS_ARCHIVE_DIR, name)
        if name.startswith(".") or not os.path.isdir(full):
            continue
        if re.match(r'^\d{4}$', name):
            # 新日期树：<年>/<月>/<日>/<SN>
            try:
                months = os.listdir(full)
            except OSError:
                continue
            for mon in months:
                mfull = os.path.join(full, mon)
                if mon.startswith(".") or not os.path.isdir(mfull):
                    continue
                try:
                    days = os.listdir(mfull)
                except OSError:
                    continue
                for day in days:
                    dfull = os.path.join(mfull, day)
                    if day.startswith(".") or not os.path.isdir(dfull):
                        continue
                    try:
                        sns = os.listdir(dfull)
                    except OSError:
                        continue
                    for sn in sns:
                        sfull = os.path.join(dfull, sn)
                        if sn.startswith(".") or not os.path.isdir(sfull):
                            continue
                        _scan(f"{name}/{mon}/{day}/{sn}", sfull)
        elif pa_re.match(name):
            _scan(name, full)   # 旧平铺命名容错（迁移未完成的残留）
    if existing is None:
        log_api.warning("配件档案索引自愈重建完成（index.json 缺失或损坏）")
    return idx


def _parts_index_reconcile():
    """补齐目录存在但未入索引的档案，已有索引条目保持不变。"""
    with _parts_write_lock:
        idx = _parts_index_load()
        missing = _parts_index_rebuild(existing=idx)
        if missing:
            idx.update(missing)
            _parts_index_persist()
            log_api.warning(f"配件档案补齐漏索引: {', '.join(sorted(missing))}")
        return {folder: dict(rec) for folder, rec in idx.items()}


def _parts_index_load():
    """懒加载 index.json 到内存缓存；缺失/损坏时扫描目录自愈重建。
    [2026-10-02 DATE-TREE] 首次加载前先把旧平铺结构迁移进日期树（幂等，无旧档案时空转）。"""
    global _parts_index_cache
    if _parts_index_cache is not None:
        return _parts_index_cache
    with _parts_write_lock:
        if _parts_index_cache is not None:
            return _parts_index_cache
        _parts_migrate_layout()
        idx = None
        if os.path.exists(PARTS_INDEX_FILE):
            try:
                with open(PARTS_INDEX_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    idx = {}
                    for folder, v in raw.items():
                        if not (_PA_FOLDER_RE.match(folder) and isinstance(v, dict)):
                            continue
                        files = []
                        if isinstance(v.get("files"), list):
                            for it in v["files"]:
                                if isinstance(it, dict) and isinstance(it.get("name"), str):
                                    try:
                                        size = int(it.get("size") or 0)
                                    except (TypeError, ValueError):
                                        size = 0
                                    files.append({"type": it.get("type", ""), "name": it["name"],
                                                  "size": size, "sha256": str(it.get("sha256") or "")})
                        idx[folder] = {
                            "folder": folder,
                            "sn": str(v.get("sn") or folder.rsplit("/", 1)[-1] or ""),
                            "machineModel": str(v.get("machineModel") or ""),
                            "cpuModel": str(v.get("cpuModel") or ""),
                            "cpuBatch": str(v.get("cpuBatch") or ""),
                            "cpuCode": str(v.get("cpuCode") or ""),
                            "ramInfo": str(v.get("ramInfo") or ""),
                            "ssdInfo": str(v.get("ssdInfo") or ""),
                            "nicInfo": str(v.get("nicInfo") or ""),
                            "otherInfo": str(v.get("otherInfo") or ""),
                            "vendor": str(v.get("vendor") or ""),
                            "note": str(v.get("note") or ""),
                            "uploadedAt": str(v.get("uploadedAt") or ""),
                            "files": files,
                        }
            except (json.JSONDecodeError, OSError, ValueError) as e:
                log_api.warning(f"配件档案 index.json 读取失败，将自愈重建: {e}")
                idx = None
        if idx is None:
            _parts_index_cache = _parts_index_rebuild()
            _parts_index_persist()
        else:
            _parts_index_cache = idx
    return _parts_index_cache


def _parts_record_alive(folder, rec):
    """磁盘真实性校验：文件夹存在且至少一张图片物理存在；幽灵档案自动清索引并返回 None。"""
    folder_path = os.path.join(PARTS_ARCHIVE_DIR, folder)
    if not os.path.isdir(folder_path):
        log_api.warning(f"配件档案自愈检测：文件夹缺失（{folder}），清理索引")
        _parts_self_heal_remove(folder)
        return None
    files_alive = []
    for f in rec.get("files", []):
        fpath = os.path.join(folder_path, f.get("name", ""))
        if os.path.isfile(fpath):
            item = dict(f)
            item["url"] = "/api/parts-image?path=" + quote(f"{folder}/{f['name']}", safe="")
            files_alive.append(item)
    # [2026-09-29 PHOTO-OPTIONAL] 纯参数档案（本来就 0 张照片）正常保留；
    # 只有"原来有照片但磁盘上全部缺失"才视为幽灵档案清理
    if not files_alive and rec.get("files"):
        log_api.warning(f"配件档案自愈检测：{folder} 所有图片缺失，清理索引")
        _parts_self_heal_remove(folder)
        return None
    if len(files_alive) < len(rec.get("files", [])):
        log_api.warning(f"配件档案自愈检测：{folder} 部分图片缺失，更新索引")
        with _parts_write_lock:
            idx2 = _parts_index_load()
            if folder in idx2:
                idx2[folder]["files"] = [
                    {"type": f["type"], "name": f["name"], "size": f["size"], "sha256": f["sha256"]}
                    for f in files_alive
                ]
                _parts_index_persist()
    rec = dict(rec)
    rec["files"] = files_alive
    return rec


def _parts_self_heal_remove(folder):
    """从索引移除指定档案并写回 index.json（内部自取锁）。"""
    with _parts_write_lock:
        idx = _parts_index_load()
        if folder in idx:
            del idx[folder]
            _parts_index_persist()
            log_api.warning(f"配件档案索引自愈：已移除幽灵档案 {folder}")


def _parts_archive_upsert(fields, files_input):
    """原子上传落盘：临时文件夹 → 魔数/大小校验 → rename 生效 → 更新索引。

    [2026-09-29 KEEP-BOTH] 不按 SN 覆盖：同一颗 CPU 出现在不同机器（或重复拍照）时，
    每次上传都完整保留为一条新档案；同秒同 SN 撞名时文件夹名追加 -2/-3 序号保证唯一。
    fields: {key: str}，sn 必填；files_input: {type: [(原始文件名, bytes), ...]}，type ∈ {'cpu','host'}。
    返回 (ok, payload)。
    """
    sn = fields.get("sn", "")
    now = datetime.now()
    ts = now.strftime("%Y%m%d-%H%M%S")
    # [2026-10-02 DATE-TREE] 落盘路径 Parts_Archive/<年>/<月>/<日>/<SN>（月/日不补零，如 2026/10/2/J16Z144）；
    # 同日同 SN 撞名追加 _2/_3。tmp 建在目标日期目录下（. 前缀自愈跳过）保证同盘原子 rename。
    # [2026-10-13 OPTIONAL-SN] SN 可空：文件夹名用 NOSN-<时分秒> 兜底（用户要求所有参数都不必填，
    # 只要有照片即可上传；meta.sn 存空串，网页显示「未填编号」）
    sn_dir = sn if sn else f"NOSN-{now.strftime('%H%M%S')}"
    year_s, month_s, day_s = str(now.year), str(now.month), str(now.day)
    day_dir = os.path.join(PARTS_ARCHIVE_DIR, year_s, month_s, day_s)
    tmp_dir = os.path.join(day_dir, f".tmp_{sn_dir}_{ts}")
    with _parts_write_lock:
        idx = _parts_index_load()
        # 文件夹唯一性：同日同 SN（并发/重复上传）追加序号
        sn_base = sn_dir
        uniq = 1
        while (f"{year_s}/{month_s}/{day_s}/{sn_dir}" in idx
               or os.path.exists(os.path.join(day_dir, sn_dir))):
            uniq += 1
            sn_dir = f"{sn_base}_{uniq}"
        folder_name = f"{year_s}/{month_s}/{day_s}/{sn_dir}"
        try:
            os.makedirs(day_dir, exist_ok=True)
            os.makedirs(tmp_dir)
            files_meta = []
            original_names = []
            counters = {t: 0 for t in PARTS_FILE_TYPES}
            for ftype in PARTS_FILE_TYPES:
                for orig_name, blob in files_input.get(ftype, []):
                    if not blob:
                        continue
                    sniff = _sniff_image(blob)
                    if sniff is None:
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                        return False, {"code": "ERR_BAD_IMAGE",
                                       "message": f"{ftype} 图片格式无效（仅支持 JPEG/PNG/WebP）"}
                    if len(blob) > PARTS_MAX_IMAGE_BYTES:
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                        return False, {"code": "ERR_TOO_LARGE",
                                       "message": f"{ftype} 图片超过单张 35MB 上限"}
                    ext, _mime = sniff
                    # [2026-10-03 SHRINK] 高清原图落地前重编码（2560px/q85，体积约 1/4~1/3，画质肉眼无差）
                    blob, ext = _parts_shrink_image(blob, ext)
                    counters[ftype] += 1
                    fname = f"{ftype}_{ts}_{counters[ftype]}.{ext}"
                    with open(os.path.join(tmp_dir, fname), "wb") as f:
                        f.write(blob)
                    files_meta.append({"type": ftype, "name": fname, "size": len(blob),
                                       "sha256": hashlib.sha256(blob).hexdigest()})
                    original_names.append(str(orig_name or ""))
            # [2026-09-29 PHOTO-OPTIONAL] 照片可选：识别到关键信息可只存参数（0 张照片也建档）
            meta = {
                "sn": sn,
                "machineModel": fields.get("machineModel", ""),
                "cpuModel": fields.get("cpuModel", ""),
                "cpuBatch": fields.get("cpuBatch", ""),
                "cpuCode": fields.get("cpuCode", ""),
                "ramInfo": fields.get("ramInfo", ""),
                "ssdInfo": fields.get("ssdInfo", ""),
                "nicInfo": fields.get("nicInfo", ""),
                "otherInfo": fields.get("otherInfo", ""),
                "vendor": fields.get("vendor", ""),
                "note": fields.get("note", ""),
                "uploadedAt": now.strftime("%Y-%m-%d %H:%M:%S"),
                "originalNames": original_names,
                "files": files_meta,
            }
            with open(os.path.join(tmp_dir, "meta.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            # [2026-09-29 KEEP-BOTH] 旧档一律保留（同一 CPU/主机重复出现时不覆盖，新档案完整落盘）
            # 临时文件夹 → 正式文件夹（原子 rename）
            os.rename(tmp_dir, os.path.join(day_dir, sn_dir))
            idx[folder_name] = {
                "folder": folder_name, "sn": sn,
                "machineModel": meta["machineModel"],
                "cpuModel": meta["cpuModel"], "cpuBatch": meta["cpuBatch"],
                "cpuCode": meta["cpuCode"],
                "ramInfo": meta["ramInfo"], "ssdInfo": meta["ssdInfo"],
                "nicInfo": meta["nicInfo"], "otherInfo": meta["otherInfo"],
                "vendor": meta["vendor"],
                "note": meta["note"],
                "uploadedAt": meta["uploadedAt"], "files": files_meta,
            }
            _parts_index_persist()
            log_api.info(f"配件档案上传: {sn} → {folder_name}（{len(files_meta)} 张, "
                         f"{sum(f['size'] for f in files_meta)//1024}KB）")
            return True, {"ok": True, "folder": folder_name, "uploadedAt": meta["uploadedAt"],
                          "files": files_meta}
        except OSError as e:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            log_api.error(f"配件档案上传失败: {sn}: {e}")
            return False, {"code": "ERR_IO", "message": f"写入失败: {e}"}


def _parts_archive_delete(folder):
    """永久删除指定档案文件夹 + 更新索引。"""
    if not _PA_FOLDER_RE.match(folder or ""):
        return False, {"code": "ERR_BAD_REQUEST", "message": "folder 参数不合法"}
    with _parts_write_lock:
        idx = _parts_index_load()
        entry = idx.get(folder)
        if not entry:
            return False, {"code": "ERR_NOT_FOUND", "message": "档案不存在"}
        try:
            target = _safe_join(PARTS_ARCHIVE_DIR, folder)
            if target and os.path.isdir(target):
                shutil.rmtree(target)
            # 顺手清理该档案的缩略图缓存（.thumbs/<folder 中的 / 换 __>__*.jpg）
            try:
                thumb_prefix = folder.replace("/", "__") + "__"
                for fn in os.listdir(PARTS_THUMB_DIR):
                    if fn.startswith(thumb_prefix):
                        os.remove(os.path.join(PARTS_THUMB_DIR, fn))
            except OSError:
                pass
        except OSError as e:
            log_api.error(f"配件档案删除失败: {folder}: {e}")
            return False, {"code": "ERR_IO", "message": f"删除失败: {e}"}
        idx.pop(folder, None)
        _parts_index_persist()
        log_api.info(f"配件档案删除: {folder}（SN={entry.get('sn')}）已永久删除")
        return True, {"ok": True, "deleted": True, "folder": folder}


def _parts_archive_update(folder, fields):
    """[2026-10-08 EDIT] 修改档案参数字段（CPU 编号录错等场景）——只改 meta.json + 索引，照片不动。

    可编辑字段白名单：sn/machineModel/cpuModel/cpuBatch/cpuCode/ramInfo/ssdInfo/otherInfo/note
    （nicInfo 仅旧档案兼容，不在编辑范围）。sn 允许修改：文件夹名不动，索引以 meta.sn 为准
    （_parts_index_rebuild 自愈重建同样优先读 meta.json 的 sn）。
    """
    if not _PA_FOLDER_RE.match(folder or ""):
        return False, {"code": "ERR_BAD_REQUEST", "message": "folder 参数不合法"}
    allowed = ("sn", "machineModel", "cpuModel", "cpuBatch", "cpuCode",
               "ramInfo", "ssdInfo", "otherInfo", "vendor", "note")
    clean = {}
    for k in allowed:
        if k not in (fields or {}):
            continue
        v = str(fields.get(k) or "").strip()
        if len(v) > PARTS_TEXT_MAXLEN.get(k, 200):
            return False, {"code": "ERR_BAD_REQUEST", "message": f"{k} 超过长度上限"}
        clean[k] = v
    if "sn" in clean and not _ob_sn_ok(clean["sn"]):
        return False, {"code": "ERR_BAD_REQUEST",
                       "message": "主机编号缺失或含非法字符（仅允许字母数字、-、_）"}
    if not clean:
        return False, {"code": "ERR_BAD_REQUEST", "message": "没有可修改的字段"}
    with _parts_write_lock:
        idx = _parts_index_load()
        entry = idx.get(folder)
        if not entry:
            return False, {"code": "ERR_NOT_FOUND", "message": "档案不存在"}
        target = _safe_join(PARTS_ARCHIVE_DIR, folder)
        if not target or not os.path.isdir(target):
            return False, {"code": "ERR_NOT_FOUND", "message": "档案文件夹缺失"}
        meta_path = os.path.join(target, "meta.json")
        try:
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                meta = {}
            meta.update(clean)
            meta["editedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except OSError as e:
            log_api.error(f"配件档案编辑失败: {folder}: {e}")
            return False, {"code": "ERR_IO", "message": f"写入失败: {e}"}
        # 索引同步：entry 是内存缓存的引用，改完持久化
        entry.update(clean)
        entry["editedAt"] = meta["editedAt"]
        _parts_index_persist()
        log_api.info(f"配件档案编辑: {folder} → {clean}")
        return True, {"ok": True, "folder": folder}


# -------------------- [2026-10-12 AI-COMPLETE] 照片参数补全 --------------------
# 档案有照片但参数（含 SN）缺失时，服务端用 Windows 自带离线 OCR 引擎（WinRT，不联网）
# 识别照片文字，再用与 APP OcrParser 一致的规则提取参数，只填充空字段，绝不覆盖已有值。

OCR_PS1 = os.path.join(SCRIPT_DIR, "ocr_winrt.ps1")

_PA_AI_RAM_BRANDS = ("SAMSUNG", "三星", "SK HYNIX", "HYNIX", "海力士", "KINGSTON", "金士顿",
                      "CRUCIAL", "英睿达", "MICRON", "镁光", "ADATA", "威刚", "G.SKILL", "芝奇",
                      "CORSAIR", "海盗船", "TEAMGROUP", "十铨", "RAMAXEL", "记忆科技",
                      "KINGBANK", "金百达", "CUSO", "酷兽", "JUHOR", "玖合", "GLOWAY", "光威",
                      "KLEVV", "科赋", "APACER", "宇瞻", "TRANSCEND", "创见", "PATRIOT", "博帝",
                      "LEXAR", "雷克沙", "HUAWEI", "LENOVO", "联想", "HP", "DELL", "UNION MEMORY")
_PA_AI_RAM_PN_PREFIX = (("M378", "SAMSUNG"), ("M471", "SAMSUNG"), ("M393", "SAMSUNG"),
                        ("HMA", "SK HYNIX"), ("MTA", "MICRON"))
_PA_AI_SSD_BRANDS = ("SAMSUNG", "三星", "SK HYNIX", "海力士", "WESTERN DIGITAL", "WD", "西部数据",
                      "SANDISK", "闪迪", "KINGSTON", "金士顿", "CRUCIAL", "英睿达", "MICRON", "镁光",
                      "KIOXIA", "铠侠", "INTEL", "SEAGATE", "希捷", "TOSHIBA", "东芝", "ADATA", "威刚",
                      "HP", "DELL", "LENOVO", "联想", "HUAWEI", "ACER", "GIGABYTE", "PLEXTOR", "浦科特",
                      "HIKSEMI", "海康威视", "COLORFUL", "七彩虹", "GALAX", "影驰", "MAXSUN", "铭瑄",
                      "FANXIANG", "梵想", "AIGO", "爱国者", "TIGO", "金泰克", "NETAC", "朗科",
                      "TECLAST", "台电", "TRANSCEND", "创见", "LEXAR", "雷克沙", "UNION MEMORY",
                      "PHISON", "群联", "LITEON", "LITE-ON", "建兴", "SSSTC", "YMTC", "长江存储",
                      "致态", "MAXIO", "联芸", "SOLIDIGM")
_PA_RE_HOST_SN = re.compile(
    r'(?<![A-Z])(?:出\s*厂\s*编\s*号|序\s*列\s*号|快\s*速\s*服\s*务\s*代\s*码|服\s*务\s*编\s*号|'
    r'服\s*务\s*代\s*码|编\s*号|S\s*/?\s*[NT]|SVC\s*TAG|SERVICE\s*TAG|EXPRESS(?:\s*SERVICE\s*)?CODE)'
    r'\s*[:：]?\s*([A-Z0-9][A-Z0-9-]{4,19})')
_PA_RE_MODEL_LABEL = re.compile(
    r'(?:型\s*号(?:\s*名\s*称)?|型\s*號|机\s*型|\bMODEL\b|\bMODE\b|\bMACHINE\s*TYPE\b)\s*[:：]?\s*(\S.*)')
_PA_RE_MODEL_CUT = re.compile(
    r'批\s*号|出\s*厂\s*编\s*号|序\s*列\s*号|日\s*期|生\s*产\s*日\s*期|https?://|www\.|'
    r'\bMODEL\b|\bMODE\b|\bMACHINE\s*TYPE\b|\bS\s*/?\s*N\b\s*[:：]|\bP\s*/?\s*N\b\s*[:：]|'
    r'额\s*定\s*电\s*压|额\s*定\s*电\s*流|额\s*定\s*频\s*率|频\s*率|C\s*M\s*I\s*I\s*T|生\s*产\s*地',
    re.IGNORECASE)
_PA_RE_MODEL_FRAGMENT = re.compile(r'^(?:\d{3}[A-Z]{0,2}|\d{4}(?:[A-Z][A-Z0-9]{0,3})?)$')
_PA_RE_CPU_I = re.compile(r'(?:CORE)?\s*[Il1]([3579])\s*[-]?\s*(\d{4,5})([A-Z]{0,2})')
_PA_RE_CPU_ULTRA = re.compile(r'ULTRA\s*([3579])\s+(\d{3}[A-Z]{0,2})(?![A-Z])')
_PA_RE_CPU_RYZEN = re.compile(r'RYZEN\s*(?:\(TM\)|TM|™)?\s*([3579])\s*[- ]?\s*(\d{4}[A-Z0-9]{0,4})(?![A-Z0-9])')
_PA_RE_CPU_SERIES = re.compile(r'(ULTRA|RYZEN\s*(?:\(TM\)|TM|™)?)\s*([3579])\s*$')
_PA_RE_FPO = re.compile(r'(?<![A-Z0-9])([A-Z]\d{3}[A-Z]\d{3})(?![A-Z0-9])')
_PA_RE_ATPO = re.compile(r'(?<!\d)(\d{5})(?!\d)')
_PA_RE_RAM_CAP = re.compile(r'(?<!\d)(\d{1,3})\s?GB(?![A-Z])')
_PA_RE_RAM_TYPE = re.compile(r'(LPDDR\d|DDR\d|PC[45])(?:[-\s]?(\d{4,5}))?')
_PA_RE_SERIAL = re.compile(r'(?<![A-Z])(S/?N|P/?N)\s*[:：]?\s*([A-Z0-9][A-Z0-9-]{3,19})(?![A-Z0-9])')
_PA_RE_SSD_CAP = re.compile(r'(?<!\d)(\d{1,4}(?:\.\d)?\s?(GB|TB))(?![A-Z])')


def _pa_norm(s):
    """OCR 行规范化：全角冒号/破折号归一 + 大写（与 APP normalize 一致）。"""
    return str(s or "").replace('：', ':').replace('—', '-').replace('－', '-').replace('–', '-').upper()


def _pa_clean_model(v):
    v = str(v or "").replace('\u3000', ' ').replace('\u00A0', ' ').strip()
    cut = _PA_RE_MODEL_CUT.search(v)
    if cut:
        v = v[:cut.start()].strip()
    while v.endswith((':', '：', '-', ',')):
        v = v[:-1].strip()
    return v


def _pa_extract_host(raw_lines):
    """主机照片 → SN + 型号（保留原始大小写）。"""
    sn, model = "", ""
    for i, raw in enumerate(raw_lines):
        line = str(raw or "").strip()
        if not line:
            continue
        if not sn:
            m = _PA_RE_HOST_SN.search(_pa_norm(line))
            if m:
                sn = m.group(1)
        if not model:
            m = _PA_RE_MODEL_LABEL.search(line)
            if m:
                v = _pa_clean_model(m.group(1))
                if v and not re.search(r'\d', v) and i + 1 < len(raw_lines):
                    nxt = str(raw_lines[i + 1] or "").strip()
                    if _PA_RE_MODEL_FRAGMENT.match(nxt):
                        v = v + " " + _pa_clean_model(nxt)
                if v:
                    model = v
    return sn, model


def _pa_extract_cpu(lines):
    model, batch, code = "", "", ""
    norm = [_pa_norm(l) for l in lines]
    for line in norm:
        line = line.strip()
        if not line:
            continue
        if not model:
            m = _PA_RE_CPU_I.search(line)
            if m:
                suffix = m.group(3) or ""
                if suffix == "TM":
                    suffix = ""
                model = f"I{m.group(1)}-{m.group(2)}{suffix}"
            m = _PA_RE_CPU_ULTRA.search(line)
            if m:
                model = f"ULTRA {m.group(1)} {m.group(2)}"
            m = _PA_RE_CPU_RYZEN.search(line)
            if m:
                model = f"RYZEN {m.group(1)} {m.group(2)}"
        if not batch:
            m = _PA_RE_FPO.search(line)
            if m:
                batch = m.group(1)
    if not model:
        for i, line in enumerate(norm[:-1]):
            s = _PA_RE_CPU_SERIES.search(line.strip())
            if not s:
                continue
            frag = norm[i + 1].strip()
            if _PA_RE_MODEL_FRAGMENT.match(frag):
                model = ("RYZEN " if "RYZEN" in s.group(1) else "ULTRA ") + s.group(2) + " " + frag
                break
    if not code:
        best = {}
        stream = ""
        for line in norm:
            line = _PA_RE_CPU_I.sub(' ', line)
            line = _PA_RE_CPU_ULTRA.sub(' ', line)
            line = _PA_RE_CPU_RYZEN.sub(' ', line).strip()
            if re.fullmatch(r'\d{1,4}', line):
                if len(stream) == 5:
                    stream = ""
                stream += line
                if len(stream) == 5:
                    best.setdefault(stream, 3 if stream[0] == '0' else 2)
                continue
            stream = ""
            for m in _PA_RE_ATPO.finditer(line):
                t = m.group(1)
                score = 3 if re.fullmatch(r'\d{5}', line) else (2 if t[0] == '0' else 1)
                best[t] = max(best.get(t, 0), score)
        for t, sc in sorted(best.items(), key=lambda kv: -kv[1]):
            code = t
            break
    return model, batch, code


def _pa_extract_ram(lines):
    brand = cap = gen_freq = ""
    serials = []
    for raw in lines:
        line = _pa_norm(raw)
        if not brand:
            for b in _PA_AI_RAM_BRANDS:
                if b in line:
                    brand = "UM" if b == "UNION MEMORY" else b
                    break
            else:
                for prefix, name in _PA_AI_RAM_PN_PREFIX:
                    if prefix in line:
                        brand = name
                        break
        if not cap:
            m = _PA_RE_RAM_CAP.search(line)
            if m:
                cap = m.group(1) + "GB"
        if not gen_freq:
            m = _PA_RE_RAM_TYPE.search(line)
            if m:
                gen_freq = (m.group(1) + " " + m.group(2) + "MHz") if m.group(2) else m.group(1)
        for m in _PA_RE_SERIAL.finditer(line):
            tag = "PN" if m.group(1).replace("/", "") == "PN" else "SN"
            value = m.group(2)
            if value not in [v for _, v in serials]:
                serials.append((tag, value))
    if not (brand or cap or gen_freq or serials):
        return ""
    # [2026-10-12] 提取字段精简（用户定义）：内存 = 品牌 容量 代数 频率 SN（PN 不入摘要）
    serials = [(t, v) for t, v in serials if t == "SN"] or serials
    parts = [p for p in (brand, cap, gen_freq) if p]
    sn_count = len({v for t, v in serials if t == "SN"})
    if sn_count >= 2:
        parts.append(f"x{sn_count}")
    return " ".join(parts) + "".join(f" | {t}:{v}" for t, v in serials)


def _pa_extract_ssd(lines):
    brand = cap = kind = ""
    serials = []
    for raw in lines:
        line = _pa_norm(raw)
        if not brand:
            for b in _PA_AI_SSD_BRANDS:
                if b in line:
                    brand = "UM" if b == "UNION MEMORY" else b
                    break
        if not cap:
            m = _PA_RE_SSD_CAP.search(line)
            if m:
                cap = m.group(1).replace(" ", "")
        if not kind:
            if re.search(r'NV\s*M\s*E|PCIE|PCI-E', line):
                kind = "NVMe"
            elif 'SATA' in line:
                kind = "SATA"
            elif re.search(r'M\.2|SSD|固态', line):
                kind = "SSD"
        for m in _PA_RE_SERIAL.finditer(line):
            tag = "PN" if m.group(1).replace("/", "") == "PN" else "SN"
            value = m.group(2)
            if value not in [v for _, v in serials]:
                serials.append((tag, value))
    if not (brand or cap or kind or serials):
        return ""
    # [2026-10-12] 提取字段精简（用户定义）：硬盘 = 品牌 容量 协议 NVMe/SATA SN（PN 不入摘要）
    serials = [(t, v) for t, v in serials if t == "SN"] or serials
    parts = [p for p in (brand, cap, kind) if p]
    return " ".join(parts) + "".join(f" | {t}:{v}" for t, v in serials)


def _pa_ocr_photo(path, deg=0):
    """单张照片 → 文本行列表（Windows 离线 OCR）。失败返回空列表。

    [2026-10-12 ROTATE] deg 为旋转角度（90 的倍数）：竖拍/横拍错向的照片
    旋转后重识别，供网页「旋转重识别」按钮调用。
    """
    deg = int(deg or 0)
    if deg % 360 == 0:
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", OCR_PS1, str(path)]
    else:
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", OCR_PS1, "-Path", str(path),
               "-Rotate", str((deg % 360) // 90)]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=90)
        text = out.stdout.decode("utf-8", "replace")
    except Exception as e:
        log_api.warning(f"照片 OCR 执行失败 {os.path.basename(path)}: {e}")
        return []
    if out.returncode == 2 or "OCR_ENGINE_UNAVAILABLE" in text:
        log_api.error("Windows OCR 引擎不可用（需在系统设置安装中文语言包的 OCR）")
        return []
    if out.returncode != 0:
        log_api.warning(f"照片 OCR 失败 {os.path.basename(path)}: {text.strip()[:120]}")
        return []
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _parts_analyze_scan(folder, rotations=None):
    """[2026-10-12 AI-COMPLETE] OCR 档案照片并提取参数建议（不写库）。

    返回 (True, {"suggestions": {...}, "ocr": {type: [lines]}}) 或 (False, err)。
    suggestions 含全部可提取字段（即使档案已有值），供网页修改弹窗左右对比。
    [2026-10-12 ROTATE] rotations = {"cpu": 90, "ram": 180, ...}：该类型照片旋转后
    重 OCR（竖拍照片识别率救回），网页「旋转重识别」按钮传入。
    """
    if not isinstance(folder, str) or not _PA_FOLDER_RE.fullmatch(folder):
        return False, {"code": "ERR_BAD_REQUEST", "message": "folder 参数不合法"}
    rot = {}
    if isinstance(rotations, dict):
        for k, v in rotations.items():
            if k in ("cpu", "host", "ram", "ssd"):
                try:
                    deg = int(v)
                except (TypeError, ValueError):
                    continue
                rot[k] = deg % 360
    with _parts_write_lock:
        entry = _parts_index_load().get(folder)
        if not entry:
            return False, {"code": "ERR_NOT_FOUND", "message": "档案不存在"}
        folder_path = _safe_join(PARTS_ARCHIVE_DIR, folder)
        if not folder_path or not os.path.isdir(folder_path):
            return False, {"code": "ERR_NOT_FOUND", "message": "档案文件夹缺失"}
        files = [dict(f) for f in entry.get("files", []) if isinstance(f, dict)]
    lines_by_type = {}
    counts = {}
    for f in files:
        name = f.get("name", "")
        if not isinstance(name, str) or os.path.basename(name) != name:
            continue
        ftype = f.get("type")
        if ftype not in ("cpu", "host", "ram", "ssd"):
            continue
        if counts.get(ftype, 0) >= PARTS_MAX_FILES_PER_TYPE:
            continue
        path = _safe_join(folder_path, name)
        if not path or not os.path.isfile(path):
            continue
        counts[ftype] = counts.get(ftype, 0) + 1
        lines_by_type.setdefault(ftype, []).extend(_pa_ocr_photo(path, rot.get(ftype, 0)))
    if not any(lines_by_type.values()):
        return False, {"code": "ERR_OCR", "message": "没有识别到照片文字，请检查照片清晰度或OCR引擎"}
    host_sn, host_model = _pa_extract_host(lines_by_type.get("host", []))
    cpu_model, cpu_batch, cpu_code = _pa_extract_cpu(lines_by_type.get("cpu", []))
    ram_summary = _pa_extract_ram(lines_by_type.get("ram", []))
    ssd_summary = _pa_extract_ssd(lines_by_type.get("ssd", []))
    suggestions = {"sn": host_sn.strip(), "machineModel": host_model.strip(),
                   "cpuModel": cpu_model.strip(), "cpuBatch": cpu_batch.strip(),
                   "cpuCode": cpu_code.strip(), "ramInfo": ram_summary.strip(),
                   "ssdInfo": ssd_summary.strip()}
    return True, {"suggestions": suggestions,
                  "ocr": {t: values[:48] for t, values in lines_by_type.items()}}


def _parts_analyze(folder, rotations=None):
    """兼容旧分析入口：仅返回建议，保存必须由用户确认后通过 update 接口提交。"""
    ok, payload = _parts_analyze_scan(folder, rotations)
    if not ok:
        return ok, payload
    return True, {"ok": True, "folder": folder, "ai": payload["suggestions"],
                  "filled": {}, "ocr": payload["ocr"], "saved": False}


def _pa_serial_pairs(summary):
    """从摘要串里解析 (tag, value) 对，供 SN 追加逻辑复用。"""
    pairs = []
    for m in re.finditer(r'\|\s*(SN|PN):([A-Z0-9][A-Z0-9.-]*)', str(summary or "")):
        pairs.append((m.group(1), m.group(2)))
    return pairs


# [2026-10-13 REMOVED] _parts_ocr_single（提取文字单图 OCR）已随功能移除——用户反馈识别体验不佳，网页仅保留旋转查看。


def _parts_archive_photo_append(folder, ftype, files_input):
    """[2026-10-13 PHOTO-APPEND] 向已有档案追加照片（网页编辑弹窗「补传照片」用）。

    folder 档案相对路径；ftype ∈ PARTS_FILE_TYPES；files_input = [(原始名, bytes), ...]。
    该类现有照片 + 新增 ≤ PARTS_MAX_FILES_PER_TYPE；魔数/大小校验 + 2560px 重编码，
    与上传同标准。返回 (ok, payload)。
    """
    if not isinstance(folder, str) or not _PA_FOLDER_RE.fullmatch(folder):
        return False, {"code": "ERR_BAD_REQUEST", "message": "folder 参数不合法"}
    if ftype not in PARTS_FILE_TYPES:
        return False, {"code": "ERR_BAD_REQUEST", "message": "照片类型不合法"}
    if not files_input:
        return False, {"code": "ERR_BAD_REQUEST", "message": "没有选择照片"}
    with _parts_write_lock:
        idx = _parts_index_load()
        entry = idx.get(folder)
        if not entry:
            return False, {"code": "ERR_NOT_FOUND", "message": "档案不存在"}
        folder_path = _safe_join(PARTS_ARCHIVE_DIR, folder)
        if not folder_path or not os.path.isdir(folder_path):
            return False, {"code": "ERR_NOT_FOUND", "message": "档案文件夹缺失"}
        meta_path = os.path.join(folder_path, "meta.json")
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            return False, {"code": "ERR_IO", "message": "meta.json 读取失败"}
        files_meta = [f for f in meta.get("files", []) if isinstance(f, dict)]
        have = sum(1 for f in files_meta if f.get("type") == ftype)
        if have + len(files_input) > PARTS_MAX_FILES_PER_TYPE:
            return False, {"code": "ERR_TOO_MANY",
                           "message": f"{ftype} 照片已达上限（现有 {have} 张，每类最多 {PARTS_MAX_FILES_PER_TYPE} 张）"}
        now = datetime.now()
        ts = now.strftime("%Y%m%d-%H%M%S")
        added = []
        counters = {"n": have}
        for orig_name, blob in files_input:
            if not blob:
                continue
            sniff = _sniff_image(blob)
            if sniff is None:
                return False, {"code": "ERR_BAD_IMAGE", "message": "图片格式无效（仅支持 JPEG/PNG/WebP）"}
            if len(blob) > PARTS_MAX_IMAGE_BYTES:
                return False, {"code": "ERR_TOO_LARGE", "message": "单张照片超过 35MB 上限"}
            blob, ext = _parts_shrink_image(blob, sniff[0])
            counters["n"] += 1
            fname = f"{ftype}_{ts}_w{counters['n']}.{ext}"   # _w 标记网页补传，不与 APP 命名冲突
            try:
                with open(os.path.join(folder_path, fname), "wb") as f:
                    f.write(blob)
            except OSError as e:
                log_api.error(f"补传照片写入失败 {folder}/{fname}: {e}")
                return False, {"code": "ERR_IO", "message": f"写入失败: {e}"}
            added.append({"type": ftype, "name": fname, "size": len(blob),
                          "sha256": hashlib.sha256(blob).hexdigest()})
            meta.setdefault("originalNames", []).append(str(orig_name or "网页补传"))
        if not added:
            return False, {"code": "ERR_BAD_REQUEST", "message": "没有有效照片"}
        meta["files"] = files_meta + added
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except OSError as e:
            return False, {"code": "ERR_IO", "message": f"meta 写入失败: {e}"}
        entry["files"] = meta["files"]          # 内存索引引用同步后持久化
        _parts_index_persist()
        log_api.info(f"配件档案补传照片: {folder} +{len(added)} 张 {ftype}")
        return True, {"ok": True, "folder": folder, "added": added,
                      "count": sum(1 for f in meta["files"] if f.get("type") == ftype)}


def _parts_image_read(rel):
    """读取档案图片（路径白名单 + 魔数嗅探 + sha256 懒补记）。返回 (data, mime) 或抛 LookupError/OSError。"""
    full = _safe_join(PARTS_ARCHIVE_DIR, rel)
    if full is None:
        raise LookupError("路径不合法")
    if not os.path.isfile(full):
        raise FileNotFoundError(rel)
    with open(full, "rb") as f:
        data = f.read()
    sniff = _sniff_image(data[:16])
    mime = sniff[1] if sniff else "application/octet-stream"
    try:
        with _parts_write_lock:
            idx = _parts_index_load()
            folder, fname = rel.rsplit("/", 1)   # [DATE-TREE] rel=<年/月/日/SN>/<文件名>
            rec = idx.get(folder)
            if rec:
                for fi in rec.get("files", []):
                    if fi.get("name") == fname and not fi.get("sha256"):
                        fi["sha256"] = hashlib.sha256(data).hexdigest()
                        _parts_index_persist()
                        break
    except Exception:
        pass
    return data, mime


def _parts_thumb_read(rel):
    """读取/生成缩略图（最长边 PARTS_THUMB_SIZE 的 JPEG，缓存到 .thumbs/）。

    [2026-09-29 THUMB] 列表页展示极小缩略图省流量，点击查看器才加载原图。
    生成失败（图片损坏/PIL 异常）时回退返回原图。
    返回 (data, mime)；路径非法抛 LookupError，文件缺失抛 FileNotFoundError。
    """
    full = _safe_join(PARTS_ARCHIVE_DIR, rel)
    if full is None:
        raise LookupError("路径不合法")
    if not os.path.isfile(full):
        raise FileNotFoundError(rel)
    thumb_name = rel.replace("/", "__")
    if not re.match(r'^[A-Za-z0-9._-]+$', thumb_name):
        raise LookupError("路径不合法")
    try:
        os.makedirs(PARTS_THUMB_DIR, exist_ok=True)
    except OSError:
        pass
    thumb_path = os.path.join(PARTS_THUMB_DIR, thumb_name)
    if not os.path.isfile(thumb_path):
        try:
            with Image.open(full) as img:
                img = ImageOps.exif_transpose(img)   # 按手机 EXIF 转正
                img.thumbnail((PARTS_THUMB_SIZE, PARTS_THUMB_SIZE))
                img.convert("RGB").save(thumb_path, "JPEG", quality=80)
        except Exception as e:
            log_api.warning(f"缩略图生成失败，回退原图: {rel}: {e}")
            try:
                os.remove(thumb_path)
            except OSError:
                pass
            with open(full, "rb") as f:
                data = f.read()
            sniff = _sniff_image(data[:16])
            return data, (sniff[1] if sniff else "application/octet-stream")
    with open(thumb_path, "rb") as f:
        return f.read(), "image/jpeg"



def decrypt_log(data: bytes) -> dict:
    """处理单个加密文件（格式: IV[16] + HMAC[32] + ciphertext）"""
    if len(data) < 49:
        raise ValueError("文件太小，格式不正确（<49 bytes）")

    iv = data[:16]
    mac_received = data[16:48]
    ciphertext = data[48:]

    # HMAC-SHA256 验签
    mac_expected = hmac.new(_K2, iv + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(mac_received, mac_expected):
        raise ValueError("HMAC 验签失败，数据可能被篡改")

    # AES-256-CBC 解码 + PKCS7 去填充
    cipher = AES.new(_K1, AES.MODE_CBC, iv)
    plaintext = cipher.decrypt(ciphertext)
    pad_len = plaintext[-1]
    if pad_len < 1 or pad_len > 16:
        raise ValueError(f"PKCS7 填充异常: pad_len={pad_len}")
    plaintext = plaintext[:-pad_len]

    return json.loads(plaintext.decode("utf-8"))


def ftp_connect():
    """连接 FTP 服务器，返回 FTP 对象；失败抛异常"""
    ftp = FTP(timeout=FTP_TIMEOUT)
    ftp.connect(FTP_HOST)               # 连接主机（使用 FTP_TIMEOUT）
    ftp.login(FTP_USER, FTP_PASS)        # 匿名登录
    ftp.cwd(FTP_DIR)                     # 切换到日志目录
    return ftp


def ftp_safe_close(ftp):
    """安全关闭 FTP 连接，忽略所有异常"""
    try:
        ftp.quit()
    except Exception:
        try:
            ftp.close()
        except Exception:
            pass


def list_dir_json(ftp, subdir):
    """列出 FTP_DIR/<subdir> 目录下的 .json 文件。

    Args:
        ftp: 已连接并登录的 FTP 对象（调用后 cwd 会被改到目标目录）。
        subdir: 相对于 FTP_DIR 的子目录名；"" 表示 FTP_DIR 根目录本身。

    Returns:
        list[tuple[str, str]] — (纯文件名, 相对 FTP_DIR 的路径)
        例: 根目录文件 ("xxx.json", "xxx.json")
            子目录文件 ("xxx.json", "EtnLogData/xxx.json")
    """
    target = FTP_DIR if not subdir else f"{FTP_DIR}/{subdir}"
    ftp.cwd(target)
    items = ftp.nlst()
    result = []
    for f in items:
        if not f.lower().endswith(".json"):
            continue
        # nlst 可能返回纯文件名或含路径，统一取 basename 作为对前端暴露的文件名
        base = f.rsplit("/", 1)[-1]
        rel = base if not subdir else f"{subdir}/{base}"
        result.append((base, rel))
    return result


def get_file_list():
    """获取 FTP 文件列表（带内存缓存）。

    遍历 FTP_SCAN_DIRS 中的所有目录（根目录 + 各子目录），
    收集 .json 文件，构建「纯文件名 → 相对路径」映射。
    前端拿到的始终是纯文件名列表，子目录来源对前端透明。
    """
    global _file_list_cache, _file_path_map
    with _cache_lock:
        if _file_list_cache is not None:
            return _file_list_cache

    # 缓存未命中，连接 FTP 逐目录拉取
    log_ftp.info("拉取文件列表...")
    t0 = time.time()
    path_map = {}
    ftp = ftp_connect()
    try:
        for subdir in FTP_SCAN_DIRS:
            try:
                for base, rel in list_dir_json(ftp, subdir):
                    path_map[base] = rel   # 同名时后者覆盖（实际时间戳文件名撞名概率极低）
            except Exception:
                # 某个子目录不存在时不影响其他目录，静默跳过
                continue
    finally:
        ftp_safe_close(ftp)

    json_files = list(path_map.keys())
    with _cache_lock:
        _file_list_cache = json_files
        _file_path_map = path_map
    elapsed_ms = (time.time() - t0) * 1000
    log_ftp.info(f"文件列表已缓存: {len(json_files)} 个 .json, 耗时 {elapsed_ms:.0f}ms")
    return json_files


def get_decrypted_file(fname: str) -> dict:
    """获取单个文件的处理结果（带内存缓存）。

    通过 _file_path_map 查找文件对应的 FTP 相对路径（子目录文件形如
    "EtnLogData/xxx.json"），ftp_connect() 已 cwd 到 FTP_DIR，故直接用相对路径 RETR。
    """
    with _cache_lock:
        if fname in _decrypted_cache:
            with _stats_lock:
                _stats["cache_hits"] += 1
            log_decrypt.debug(f"缓存命中: {fname}")
            return _decrypted_cache[fname]
        rel = _file_path_map.get(fname)

    with _stats_lock:
        _stats["cache_misses"] += 1

    # 映射缺失（如 manifest 尚未调用、或缓存刚被清空），先拉取文件列表填充映射
    if rel is None:
        try:
            get_file_list()
        except Exception:
            pass
        with _cache_lock:
            rel = _file_path_map.get(fname, fname)  # 仍查不到则回退用纯文件名

    # 缓存未命中，从 FTP 下载并处理
    t0 = time.time()
    buf = bytearray()
    ftp = ftp_connect()
    try:
        ftp.retrbinary(f"RETR {rel}", buf.extend)
    finally:
        ftp_safe_close(ftp)

    raw_bytes = bytes(buf)
    raw = decrypt_log(raw_bytes)
    elapsed_ms = (time.time() - t0) * 1000

    with _stats_lock:
        _stats["decrypt_count"] += 1
        _stats["decrypt_total_ms"] += elapsed_ms
        _stats["decrypt_bytes"] += len(raw_bytes)
        if elapsed_ms > _stats["decrypt_max_ms"]:
            _stats["decrypt_max_ms"] = elapsed_ms

    log_decrypt.info(f"{rel} → 处理 {len(raw_bytes)//1024}KB, 耗时 {elapsed_ms:.0f}ms")

    with _cache_lock:
        _decrypted_cache[fname] = raw
    return raw


def clear_file_list_cache():
    """仅清空文件列表缓存（_file_list_cache + _file_path_map），保留数据缓存"""
    global _file_list_cache
    with _cache_lock:
        _file_list_cache = None
        _file_path_map.clear()


def clear_decrypt_cache():
    """仅清空数据缓存（_decrypted_cache），保留文件列表"""
    with _cache_lock:
        _decrypted_cache.clear()


def clear_cache():
    """清空全部内存缓存（文件列表 + 数据缓存）"""
    global _file_list_cache
    with _cache_lock:
        _file_list_cache = None
        _file_path_map.clear()
        _decrypted_cache.clear()


def get_version_info():
    """返回当前版本信息（供前端轮询检测文件变化）"""
    with _cache_lock:
        fcount = len(_file_list_cache) if _file_list_cache is not None else 0
        return {"version": _file_version, "fileCount": fcount}



def refresh_file_list():
    """后台自动刷新：仅更新文件列表缓存，不清除数据缓存；
       检测到文件变化时递增 _file_version，供前端轮询使用。
       同时更新托盘状态和通知。

    遍历 FTP_SCAN_DIRS 全部目录，重新构建文件名→相对路径映射。
    """
    global _file_list_cache, _file_path_map, _file_version
    try:
        path_map = {}
        ftp = ftp_connect()
        try:
            for subdir in FTP_SCAN_DIRS:
                try:
                    for base, rel in list_dir_json(ftp, subdir):
                        path_map[base] = rel
                except Exception:
                    continue
        finally:
            ftp_safe_close(ftp)
        json_files = list(path_map.keys())
        with _cache_lock:
            old_list = _file_list_cache
            _file_list_cache = json_files
            _file_path_map = path_map
            # 首次填充不递增（old_list 为 None），后续有变化才递增
            if old_list is not None and set(json_files) != set(old_list):
                new_count = len(json_files) - len(old_list)
                _file_version += 1
                sign = "+" if new_count > 0 else ""
                log_ftp.info(f"文件列表变化: {len(old_list)} → {len(json_files)} ({sign}{new_count})")
                # 托盘气泡通知
                if new_count > 0 and _tray_icon:
                    _tray_icon.notify(f"发现 {new_count} 个新日志文件", "LDTools")
            set_ftp_state(ok=True, file_count=len(json_files))
    except Exception as e:
        code, msg = ftp_error_code(e)
        was_ok = get_ftp_state()["ok"]
        set_ftp_state(ok=False, last_error=msg)
        log_ftp.warning(f"刷新失败: {msg}")
        # 从正常→异常时弹通知
        if was_ok and _tray_icon:
            _tray_icon.notify(f"⚠ FTP 连接异常: {msg}", "LDTools")
    finally:
        # 确保托盘菜单始终更新，不受异常影响
        try:
            update_tray_menu()
        except Exception as e:
            log_main.warning(f"托盘菜单更新失败: {e}")


def background_ftp_poll(interval=30):
    """守护线程：每隔 interval 秒自动检测 FTP 新增文件"""
    while True:
        time.sleep(interval)
        try:
            refresh_file_list()
        except Exception:
            pass


def ftp_error_code(exc):
    """将 FTP 异常转为简短错误码"""
    msg = str(exc).lower()
    if isinstance(exc, socket.timeout) or "timeout" in msg:
        return "ERR_FTP_TIMEOUT", "FTP 连接超时"
    if "refused" in msg or "connection refused" in msg:
        return "ERR_FTP_CONN_REFUSED", "FTP 拒绝连接"
    if "no route" in msg or "unreachable" in msg:
        return "ERR_FTP_UNREACHABLE", "FTP 网络不可达"
    if "530" in msg:
        return "ERR_FTP_AUTH", "FTP 登录认证失败"
    if "550" in msg:
        return "ERR_FTP_NO_DIR", "FTP 目录不存在"
    if "name or service not known" in msg or "getaddrinfo" in msg:
        return "ERR_FTP_DNS", "FTP 域名解析失败"
    return "ERR_FTP_UNKNOWN", f"FTP 错误: {exc}"


# ======================== 系统托盘 ========================
def _make_tray_image():
    """生成 64×64 托盘图标（蓝底圆角方块 + 白色 "LT" 文字）"""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # 圆角矩形背景
    draw.rounded_rectangle([2, 2, 62, 62], radius=14, fill=(41, 128, 185))
    # "LT" 文字
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 28)
    except Exception:
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 26)
        except Exception:
            font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), "LT", font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (64 - tw) // 2
    y = (64 - th) // 2 - 2
    draw.text((x, y), "LT", fill=(255, 255, 255), font=font)
    return img


def _build_tray_menu(icon):
    """构建托盘右键菜单（每次调用时读取最新状态）"""
    state = get_ftp_state()
    status_text = "运行中" if state["ok"] else f"⚠ {state['last_error'] or '异常'}"
    file_text = f"共 {state['file_count']} 个文件" if state["file_count"] > 0 else "等待文件列表..."

    def open_browser(icon, item):
        webbrowser.open(SERVICE_URL)

    def copy_url(icon, item):
        cmd = f'echo {SERVICE_URL}| clip'
        subprocess.run(cmd, shell=True)
        icon.notify("已复制到剪贴板", "LDTools")

    def restart_service(icon, item):
        try:
            clear_cache()
            refresh_file_list()
            icon.notify("服务已重启，缓存已清空", "LDTools")
        except Exception as e:
            log_main.warning(f"重启服务失败: {e}")
            icon.notify("重启失败，请检查日志", "LDTools")

    def quit_app(icon, item):
        icon.stop()

    # 菜单：普通项 + 禁用信息项
    return pystray.Menu(
        pystray.MenuItem("🌐 打开日志查看器", open_browser, default=True, visible=True),
        pystray.MenuItem("📋 复制地址", copy_url),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(f"📊 文件: {file_text}", None, enabled=False),
        pystray.MenuItem(f"🔄 状态: {status_text}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("⏸ 重启服务", restart_service),
        pystray.MenuItem("❌ 退出", quit_app),
    )


def start_tray():
    """启动系统托盘（在主线程调用，会阻塞直到用户退出）"""
    global _tray_icon
    icon = pystray.Icon(
        "LDTools",
        _make_tray_image(),
        "LDTools — 启动中...",
        menu=_build_tray_menu(None),  # 占位菜单，后续 update_tray_menu 会刷新
    )
    _tray_icon = icon
    icon.run()
class LogViewerHandler(SimpleHTTPRequestHandler):

    protocol_version = "HTTP/1.1"   # 启用 keep-alive，复用连接避免 TIME_WAIT 堆积
    timeout = 300                    # keep-alive 空闲超时（秒），5 分钟足够浏览操作间隔

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SCRIPT_DIR, **kwargs)

    # -------------------- 缓存控制 --------------------
    def end_headers(self):
        """所有响应完全禁用缓存。
        [2026-08-22 CPU-bug-cache → 2026-08-24 OUTBOUND] 出库图片原本 'private, max-age=86400' 缓存 24h，
        用户移动端删除文件夹后浏览器还能显示（图片缓存）→ 改为完全 no-store，
        让用户每次刷新都重新从服务端读，磁盘不存在直接 404，符合用户「每次刷新强制清理缓存」诉求。
        回滚标记：恢复 'private, max-age=86400' + 加 _img_cache 分支即恢复 24h 缓存。"""
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        super().end_headers()

    # -------------------- 日志 --------------------
    def log_request(self, code='-', size='-'):
        """记录正常请求 + 更新统计计数器"""
        cmd  = getattr(self, 'command', '---')
        path = getattr(self, 'path', '???')
        if path.startswith("/api/"):
            with _stats_lock:
                try:
                    sc = int(code)
                    if 200 <= sc < 400:
                        _stats["api_ok"] += 1
                    else:
                        _stats["api_err"] += 1
                except (ValueError, TypeError):
                    _stats["api_ok"] += 1  # code='-' 当作成功
        log_api.debug(f"{cmd} {path} → {code}")

    def log_error(self, format, *args):
        """记录错误请求，忽略 keep-alive 超时（正常现象）"""
        if args and isinstance(args[0], (TimeoutError, socket.timeout)):
            return
        cmd = getattr(self, 'command', '---')
        msg = format % args if args else format
        log_api.warning(f"{cmd} ! {msg}")

    def log_message(self, format, *args):
        """通用日志（不被 log_request / log_error 覆盖时使用）"""
        cmd = getattr(self, 'command', '---')
        msg = format % args if args else format
        log_api.debug(f"{cmd} {msg}")

    # -------------------- 连接异常处理 --------------------
    def handle(self):
        """覆盖 handle()，捕获浏览器断开连接等异常，避免打印 traceback 或线程泄漏"""
        try:
            super().handle()
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError,
                socket.timeout, TimeoutError, OSError, ValueError):
            self.close_connection = True

    # -------------------- 认证 --------------------
    def _read_body(self):
        """读取请求体"""
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length > 0 else b""

    def _check_auth(self, qs=None) -> bool:
        """验证请求头中的 Bearer token 是否有效。返回 True 表示鉴权通过。
        [2026-08-22 CPU-ARCHIVE → 2026-08-24 OUTBOUND] qs 参数：额外接受 ?token= 查询参数鉴权——
        <img> 标签无法携带 Authorization 头，图片 URL 只能把 token 放查询串。
        回滚标记：删掉 qs 相关两行即可。"""
        auth = self.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        if not token and qs:
            token = (qs.get("token") or [""])[0]
        if not token:
            return False
        now = time.time()
        with _cache_lock:  # 复用 _cache_lock 保护 _valid_tokens
            expire = _valid_tokens.get(token)
        if expire is None:
            return False
        if now > expire:
            with _cache_lock:
                _valid_tokens.pop(token, None)
            return False
        return True

    def _require_auth(self, qs=None) -> bool:
        """检查鉴权，不通过时返回 401 并返回 False"""
        if self._check_auth(qs):
            return True
        self.send_error_json(401, "ERR_AUTH", "未登录或 token 已过期")
        return False

    def do_OPTIONS(self):
        """处理 CORS 预检请求（浏览器跨域时自动发送）"""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_POST(self):
        """处理 POST 请求（/api/auth、/api/notes、/api/outbound-archive）"""
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/api/auth":
            self.handle_auth()
        elif path == "/api/notes":            # [2026-08-22] 备注保存/删除（方案A）
            if not self._require_auth(qs): return
            self.handle_notes_post()
        elif path == "/api/outbound-archive":      # [2026-08-22 CPU-ARCHIVE → 2026-08-24 OUTBOUND] 图片上传（multipart）
            if not self._require_auth(qs): return
            self.handle_outbound_archive_post()
        elif path == "/api/outbound-archive/rebuild":  # [2026-08-24 OUTBOUND] 强制重建索引
            if not self._require_auth(qs): return
            self.handle_outbound_archive_rebuild()
        elif path == "/api/parts-archive":             # [2026-09-29 PARTS] 配件档案 multipart 上传
            if not self._require_auth(qs): return
            self.handle_parts_archive_post()
        elif path == "/api/parts-archive/update":      # [2026-10-08 EDIT] 配件档案参数修改（JSON）
            if not self._require_auth(qs): return
            self.handle_parts_archive_update()
        elif path == "/api/parts-archive/photo":       # [2026-10-13 PHOTO-APPEND] 档案补传照片
            if not self._require_auth(qs): return
            self.handle_parts_archive_photo()
        else:
            self.send_error_json(405, "ERR_METHOD", "不支持的请求方法")

    def do_DELETE(self):
        """处理 DELETE 请求（[2026-08-22 CPU-ARCHIVE → 2026-08-24 OUTBOUND] /api/outbound-archive 永久删除）"""
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        if path == "/api/outbound-archive":
            if not self._require_auth(qs): return
            self.handle_outbound_archive_delete(qs)
        elif path == "/api/parts-archive":             # [2026-09-29 PARTS] 配件档案永久删除
            if not self._require_auth(qs): return
            self.handle_parts_archive_delete(qs)
        else:
            self.send_error_json(405, "ERR_METHOD", "不支持的请求方法")

    def handle_auth(self):
        """POST /api/auth — 验证密码，返回 token"""
        try:
            body = self._read_body()
            data = json.loads(body)
            pw = data.get("password", "")
        except (json.JSONDecodeError, Exception):
            self.send_error_json(400, "ERR_BAD_REQUEST", "请求格式错误")
            return

        # 恒定时间比较，防止时序攻击
        if not hmac.compare_digest(pw, ACCESS_PASSWORD):
            log_api.warning("登录失败: 密码错误")
            self.send_error_json(401, "ERR_AUTH", "密码错误")
            return

        token = secrets.token_hex(32)
        expire = time.time() + ACCESS_TOKEN_TTL
        with _cache_lock:
            _valid_tokens[token] = expire
            # 清理过期的 token（顺便做，避免无限膨胀）
            stale = [t for t, e in _valid_tokens.items() if time.time() > e]
            for t in stale:
                del _valid_tokens[t]

        log_api.info(f"登录成功, token={token[:8]}..., 有效期 {ACCESS_TOKEN_TTL//3600}h")
        self.send_json({"ok": True, "token": token})

    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # [2026-08-22 STALE-FIX] 注意：缓存控制统一由 end_headers() 的全局 no-store 负责
        # （普通模式旧数据/无痕模式新数据 = 浏览器缓存症状；切勿在此重复发 Cache-Control）
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status, code, message):
        self.send_json({"error": True, "code": code, "message": message}, status)

    # -------------------- 路由 --------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        # favicon — 返回 204 避免浏览器反复请求 404
        if path == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        # ----- API 路由（全部需要鉴权） -----
        if path == "/api/manifest":
            if not self._require_auth(): return
            self.handle_manifest()
        elif path == "/api/file":
            if not self._require_auth(): return
            self.handle_file(qs)
        elif path == "/api/refresh":
            if not self._require_auth(): return
            self.handle_refresh()
        elif path == "/api/clear-decrypt-cache":
            if not self._require_auth(): return
            self.handle_clear_decrypt_cache()
        elif path == "/api/version":
            if not self._require_auth(): return
            self.handle_version()
        elif path == "/api/notes":            # [2026-08-22] 备注读取（方案A）
            if not self._require_auth(qs): return
            self.handle_notes()
        elif path == "/api/outbound-archive":      # [2026-08-22 CPU-ARCHIVE → 2026-08-24 OUTBOUND] 档案查询（全量摘要/单SN明细）
            # [2026-08-22 DBG-bugfix] 之前 _require_auth() 没传 qs，导致 ?token= 鉴权 401
            if not self._require_auth(qs): return
            self.handle_outbound_archive_get(qs)
        elif path == "/api/outbound-image":        # [2026-08-22 CPU-ARCHIVE → 2026-08-24 OUTBOUND] 图片按需下载（支持 ?token=）
            if not self._require_auth(qs): return
            self.handle_outbound_image(qs)
        elif path == "/api/parts-archive":         # [2026-09-29 PARTS] 配件档案查询（全量/单条明细）
            if not self._require_auth(qs): return
            self.handle_parts_archive_get(qs)
        elif path == "/api/parts-image":           # [2026-09-29 PARTS] 配件档案图片按需下载（支持 ?token=）
            if not self._require_auth(qs): return
            self.handle_parts_image(qs)
        elif path == "/api/parts-thumb":           # [2026-09-29 THUMB] 配件档案缩略图（列表页用，点击才拉原图）
            if not self._require_auth(qs): return
            self.handle_parts_thumb(qs)
        else:
            # 静态文件（index.html / CSS / JS / Img 等）
            super().do_GET()

    def handle_manifest(self):
        try:
            files = get_file_list()
            # [2026-08-22 STALE-FIX] 服务端直接从文件名提取日期范围元数据
            # 作为前端 parseFileName 的兜底，防止 state.dataMaxDate 落后导致
            # 默认日期范围 clamp 掉最新数据（如 08-22 的新文件不显示）
            earliest, latest = None, None
            for f in files:
                m = re.match(r"^(\d{2})(\d{2})(\d{2})-", f)
                if m:
                    ds = "20%s-%s-%s" % (m.group(1), m.group(2), m.group(3))
                    if earliest is None or ds < earliest:
                        earliest = ds
                    if latest is None or ds > latest:
                        latest = ds
            self.send_json({
                "files": files,
                "total": len(files),
                "earliestDate": earliest or "",
                "latestDate": latest or "",
            })
        except Exception as e:
            code, msg = ftp_error_code(e)
            self.send_error_json(503, code, msg)

    def handle_file(self, qs):
        fname = qs.get("name", [None])[0]
        if not fname:
            self.send_error_json(400, "ERR_BAD_REQUEST", "缺少 name 参数")
            return

        try:
            data = get_decrypted_file(fname)
            self.send_json(data)
        except Exception as e:
            code, msg = ftp_error_code(e)
            if "ERR_FTP" in code:
                self.send_error_json(503, code, msg)
            else:
                self.send_error_json(500, "ERR_DECRYPT", f"处理失败: {e}")

    def handle_refresh(self):
        """刷新文件列表缓存，不触及数据缓存。页面刷新/init 时调用。"""
        clear_file_list_cache()
        log_api.info("刷新文件列表缓存")
        self.send_json({"ok": True, "message": "文件列表缓存已刷新"})

    def handle_clear_decrypt_cache(self):
        """仅清空数据缓存。手动"刷新数据"时调用。"""
        clear_decrypt_cache()
        log_api.info("清空数据缓存")
        self.send_json({"ok": True, "message": "数据缓存已清空"})

    def handle_version(self):
        self.send_json(get_version_info())

    # -------------------- 备注（方案A：notes.json 本地持久化） --------------------
    def handle_notes(self):
        """GET /api/notes — 返回全部备注

        [2026-08-22] 增加 firstBoot 标记：仅在 notes.json 文件**磁盘不存在**时为 true，
        用于前端首次部署迁移旧 localStorage 数据；文件存在后恒为 false，
        杜绝"服务端数据被全删后，某设备旧快照复活"的问题。
        回滚：将响应体改回 {"notes": snapshot} 即可。
        """
        with _notes_lock:
            notes = _notes_load()
            snapshot = {sn: dict(v) for sn, v in notes.items()}   # 浅拷贝，避免序列化期间被并发修改
        first_boot = not os.path.exists(NOTES_FILE)
        self.send_json({"notes": snapshot, "firstBoot": first_boot})

    def handle_notes_post(self):
        """POST /api/notes — 保存/删除一条备注（乐观锁）

        请求体：{ "sn": "序列号", "text": "备注内容（空=删除）",
                  "baseUpdatedAt": "加载时看到的版本时间（新备注传 null）", "force": false }
        成功：{ "ok": true, "updatedAt": "...", "deleted": false }
        冲突：409 { "error": true, "code": "ERR_CONFLICT", "current": {...} }
        """
        try:
            body = self._read_body()
            data = json.loads(body)
        except Exception:
            self.send_error_json(400, "ERR_BAD_REQUEST", "请求格式错误")
            return

        sn = data.get("sn")
        text = data.get("text", "")
        if not isinstance(sn, str) or not sn:
            self.send_error_json(400, "ERR_BAD_REQUEST", "缺少 sn 参数")
            return
        if not isinstance(text, str):
            self.send_error_json(400, "ERR_BAD_REQUEST", "text 必须是字符串")
            return

        ok, payload = notes_upsert(sn, text, base_updated_at=data.get("baseUpdatedAt"),
                                    force=bool(data.get("force")))
        if ok:
            log_api.debug(f"备注保存: {sn[:12]}... force={data.get('force')} deleted={payload.get('deleted')}")
            self.send_json(payload)
        else:
            # 乐观锁冲突：返回 409 + 服务器当前内容，前端弹冲突气泡
            log_api.info(f"备注冲突: {sn[:12]}...")
            self.send_json({"error": True, "code": "ERR_CONFLICT",
                            "message": "备注已被他人修改，请确认后覆盖",
                            "current": payload}, 409)

    # -------------------- 出库记录（[2026-08-24 OUTBOUND] 由 CPU 档案就地改造） --------------------
    def handle_outbound_archive_get(self, qs):
        """GET /api/outbound-archive — 不带 sn：全量摘要（卡片徽章数据源）；
        带 sn：单 SN 明细（含图片 URL），无档案返回 {exists: false}。"""
        sn = (qs.get("sn") or [None])[0]
        if sn is None:
            self.send_json({"archives": _outbound_archive_summary()})
            return
        if not _ob_sn_ok(sn):
            self.send_error_json(400, "ERR_BAD_REQUEST", "SN 含非法字符")
            return
        detail = _outbound_archive_detail(sn)
        self.send_json(detail if detail else {"exists": False})

    def handle_outbound_archive_rebuild(self):
        """POST /api/outbound-archive/rebuild — [2026-08-24 OUTBOUND] 强制重建索引

        场景：服务端进程未重启，但磁盘被外部修改（用户手动删文件夹/手动编辑 index.json），
        导致内存 cache 与磁盘不一致。调用此接口清空 cache + 扫描磁盘重建。
        """
        global _outbound_index_cache
        with _outbound_write_lock:
            _outbound_index_cache = None     # 清缓存，强制下次 _outbound_index_load 重新扫描
            new_idx = _outbound_index_rebuild()
            _outbound_index_cache = new_idx
            _outbound_index_persist()
            log_api.warning(f"出库索引手动重建完成，共 {len(new_idx)} 条")
        self.send_json({"ok": True, "count": len(new_idx),
                        "archives": {sn: {"folder": v["folder"], "uploadedAt": v.get("uploadedAt", ""),
                                          "count": len(v.get("files", []))} for sn, v in new_idx.items()}})

    def handle_outbound_archive_post(self):
        """POST /api/outbound-archive — multipart 上传（fields: sn / hostFile / partFile）

        校验：Content-Length 预检（两张 35MB + 余量）→ SN 白名单 → 至少一张 →
        魔数嗅探 + 单张 35MB（在 _outbound_archive_upload 内、写盘前完成）。
        """
        try:
            clen = int(self.headers.get("Content-Length", 0))
        except ValueError:
            clen = 0
        if clen > OUTBOUND_MAX_IMAGE_BYTES * 2 + 64 * 1024:
            # 超限直接拒绝并断开连接（不读 body，避免无谓占用内存/带宽）
            self.close_connection = True
            self.send_error_json(413, "ERR_TOO_LARGE", "请求体超过上限（两张图片共 70MB + 余量）")
            return
        body = self._read_body()
        fields = _parse_multipart(body, self.headers.get("Content-Type", ""))
        if fields is None or "sn" not in fields:
            self.send_error_json(400, "ERR_BAD_REQUEST", "multipart 解析失败或缺少 sn 字段")
            return
        sn = fields["sn"][1].decode("utf-8", "replace").strip()
        if not _ob_sn_ok(sn):
            self.send_error_json(400, "ERR_BAD_REQUEST", "SN 缺失或含非法字符（仅允许字母数字、-、_）")
            return
        files_input = {}
        for ftype in ("host", "part"):
            item = fields.get(f"{ftype}File")
            if item and item[1]:
                files_input[ftype] = item
        if not files_input:
            self.send_error_json(400, "ERR_BAD_REQUEST", "至少需要上传一张图片（hostFile / partFile）")
            return
        ok, payload = _outbound_archive_upload(sn, files_input)
        if ok:
            self.send_json(payload)
        else:
            status = 413 if payload.get("code") == "ERR_TOO_LARGE" else 400
            self.send_error_json(status, payload.get("code", "ERR_UPLOAD"),
                                 payload.get("message", "上传失败"))

    def handle_outbound_archive_delete(self, qs):
        """DELETE /api/outbound-archive?sn= — 永久删除档案文件夹"""
        sn = (qs.get("sn") or [""])[0]
        if not _ob_sn_ok(sn):
            self.send_error_json(400, "ERR_BAD_REQUEST", "缺少 sn 参数或含非法字符")
            return
        ok, payload = _outbound_archive_delete(sn)
        self.send_json(payload) if ok else \
            self.send_error_json(404 if payload.get("code") == "ERR_NOT_FOUND" else 500,
                                 payload.get("code", "ERR_DELETE"), payload.get("message", "删除失败"))

    def handle_outbound_image(self, qs):
        """GET /api/outbound-image?path=<rel> — 按需下载单张原图（路径白名单校验）"""
        rel = (qs.get("path") or [""])[0]
        if not rel:
            self.send_error_json(400, "ERR_BAD_REQUEST", "缺少 path 参数")
            return
        full = _safe_join(OUTBOUND_ARCHIVE_DIR, rel)
        if full is None:
            self.send_error_json(403, "ERR_FORBIDDEN", "路径不合法")
            return
        if not os.path.isfile(full):
            self.send_error_json(404, "ERR_NOT_FOUND", "图片不存在")
            return
        try:
            with open(full, "rb") as f:
                data = f.read()
        except OSError as e:
            self.send_error_json(500, "ERR_IO", f"读取失败: {e}")
            return
        sniff = _sniff_image(data[:16])
        mime = sniff[1] if sniff else "application/octet-stream"
        # 懒计算：自愈重建的索引缺 sha256，首次访问时补记（审计指纹完整化）
        try:
            with _outbound_write_lock:
                idx = _outbound_index_load()
                for _sn, v in idx.items():
                    folder = v.get("folder", "")
                    if folder and rel.startswith(folder + "/"):
                        fname = rel[len(folder) + 1:]
                        for fi in v.get("files", []):
                            if fi.get("name") == fname and not fi.get("sha256"):
                                fi["sha256"] = hashlib.sha256(data).hexdigest()
                                _outbound_index_persist()
                        break
        except Exception:
            pass
        self._img_cache = True   # end_headers 据此发可缓存头
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_parts_thumb(self, qs):
        """GET /api/parts-thumb?path=<rel> — 缩略图按需生成/下载（支持 ?token=）"""
        rel = (qs.get("path") or [""])[0]
        if not rel:
            self.send_error_json(400, "ERR_BAD_REQUEST", "缺少 path 参数")
            return
        try:
            data, mime = _parts_thumb_read(rel)
        except LookupError:
            self.send_error_json(403, "ERR_FORBIDDEN", "路径不合法")
            return
        except FileNotFoundError:
            self.send_error_json(404, "ERR_NOT_FOUND", "图片不存在")
            return
        except OSError as e:
            self.send_error_json(500, "ERR_IO", f"读取失败: {e}")
            return
        self._img_cache = True
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # -------------------- 主机配件档案（[2026-09-29 PARTS] APK 拍照识别上传） --------------------
    def handle_parts_archive_get(self, qs):
        """GET /api/parts-archive — 不带 folder：全量记录列表；带 folder：单条明细（含图片 URL）。"""
        folder = (qs.get("folder") or [None])[0]
        if folder is None:
            idx = _parts_index_reconcile()
            records = sorted(idx.values(), key=lambda r: r.get("uploadedAt", ""), reverse=True)
            # 每条记录做磁盘真实性校验（幽灵档案自愈）
            alive = []
            for rec in records:
                checked = _parts_record_alive(rec["folder"], rec)
                if checked:
                    alive.append(checked)
            self.send_json({"records": alive})
            return
        if not _PA_FOLDER_RE.match(folder):
            self.send_error_json(400, "ERR_BAD_REQUEST", "folder 参数不合法")
            return
        idx = _parts_index_reconcile()
        rec = idx.get(folder)
        detail = _parts_record_alive(folder, rec) if rec else None
        self.send_json(detail if detail else {"exists": False})

    def handle_parts_archive_post(self):
        """POST /api/parts-archive — multipart 上传

        fields: sn（必填）+ machineModel（主机型号）+ cpuModel/cpuBatch/cpuCode
                + ramInfo/ssdInfo/nicInfo/otherInfo + note（可选文本）
        files : cpuFile*/hostFile*/ramFile*/ssdFile*/nicFile*/otherFile*（每类 ≤6 张，照片整体可选）
        校验：Content-Length 预检（36 张 35MB + 余量）→ SN 白名单 → 文本字段长度 →
        每类型 ≤6 张 → 魔数嗅探 + 单张 35MB（落盘前完成）。
        """
        try:
            clen = int(self.headers.get("Content-Length", 0))
        except ValueError:
            clen = 0
        if clen > PARTS_MAX_IMAGE_BYTES * 36 + 64 * 1024:
            self.close_connection = True
            self.send_error_json(413, "ERR_TOO_LARGE", "请求体超过上限")
            return
        body = self._read_body()
        raw = _parse_multipart_multi(body, self.headers.get("Content-Type", ""))
        if raw is None:
            self.send_error_json(400, "ERR_BAD_REQUEST", "multipart 解析失败")
            return

        def _decode(v):
            return v[0][1].decode("utf-8", "replace").strip() if v and v[0][1] else ""

        fields = {}
        sn = _decode(raw.get("sn"))
        # [2026-10-13 OPTIONAL-SN] SN 不再必填（用户要求：只要有照片即可上传）；
        # 有值时仍走白名单校验，为空由 _parts_archive_upsert 生成 NOSN-<时间> 兜底文件夹名
        if sn and not _ob_sn_ok(sn):
            self.send_error_json(400, "ERR_BAD_REQUEST",
                                 "主机编号（sn）含非法字符（仅允许字母数字、-、_）")
            return
        fields["sn"] = sn
        for key in PARTS_TEXT_FIELDS:
            val = _decode(raw.get(key))
            if len(val) > PARTS_TEXT_MAXLEN[key]:
                self.send_error_json(400, "ERR_BAD_REQUEST", f"{key} 超过长度上限")
                return
            fields[key] = val
        # 归并文件字段：cpuFile / hostFile / ramFile / ssdFile / nicFile / otherFile（含 _N 后缀变体）
        files_input = {t: [] for t in PARTS_FILE_TYPES}
        for name, items in raw.items():
            base = name.rstrip("0123456789_")
            if not base.endswith("File"):
                continue
            ftype = base[:-4]
            if ftype not in PARTS_FILE_TYPES:
                continue
            for item in items:
                if item and item[1]:
                    files_input[ftype].append(item)
        for ftype in PARTS_FILE_TYPES:
            files_input[ftype] = files_input[ftype][:PARTS_MAX_FILES_PER_TYPE]
        # [2026-09-29 PHOTO-OPTIONAL] 照片可选：仅保存识别参数也允许（有照片则一并归档）
        ok, payload = _parts_archive_upsert(fields, files_input)
        if ok:
            self.send_json(payload)
        else:
            status = 413 if payload.get("code") == "ERR_TOO_LARGE" else 400
            self.send_error_json(status, payload.get("code", "ERR_UPLOAD"),
                                 payload.get("message", "上传失败"))

    def handle_parts_archive_delete(self, qs):
        """DELETE /api/parts-archive?folder=&admin= — 永久删除档案文件夹

        [2026-10-13 DELETE-ADMIN] 需管理员密码（与登录 token 双重防线）：
        登录用户可浏览/上传/编辑，删除必须再输入管理员密码（默认 4328085）。
        """
        folder = (qs.get("folder") or [""])[0]
        admin = (qs.get("admin") or [""])[0]
        if admin != PARTS_ADMIN_PASSWORD:
            self.send_error_json(403, "ERR_ADMIN", "管理员密码错误，无法删除")
            return
        ok, payload = _parts_archive_delete(folder)
        if ok:
            self.send_json(payload)
        else:
            status = 404 if payload.get("code") == "ERR_NOT_FOUND" else 400
            self.send_error_json(status, payload.get("code", "ERR_DELETE"),
                                 payload.get("message", "删除失败"))

    def handle_parts_archive_analyze(self):
        """POST /api/parts-archive/analyze — [2026-10-12 AI-COMPLETE] 照片参数补全

        JSON body：{ "folder": "2026/9/29/J16Z144" }
        Windows 离线 OCR 识别档案照片并返回建议；不保存、不追加字段。
        用户必须在修改弹窗确认后，通过 update 接口保存。
        """
        try:
            data = json.loads(self._read_body())
        except Exception:
            self.send_error_json(400, "ERR_BAD_REQUEST", "请求格式错误")
            return
        folder = data.get("folder") if isinstance(data, dict) else None
        if not isinstance(folder, str) or not folder:
            self.send_error_json(400, "ERR_BAD_REQUEST", "缺少 folder")
            return
        # [2026-10-12 ROTATE] 可选 rotations：{"cpu":90,...} 该类型照片旋转后重 OCR
        rotations = data.get("rotations") if isinstance(data, dict) else None
        ok, payload = _parts_analyze(folder, rotations)
        if ok:
            self.send_json(payload)
        else:
            status = 404 if payload.get("code") == "ERR_NOT_FOUND" else 400
            self.send_error_json(status, payload.get("code", "ERR_ANALYZE"),
                                 payload.get("message", "分析失败"))

    def handle_parts_archive_ai_suggest(self):
        """POST /api/parts-archive/ai-suggest — AI 识别建议（不写库，网页修改弹窗左右对比用）

        JSON body：{ "folder": "..." } → { ok, folder, ai: {sn, machineModel, ...}, ocr }
        """
        try:
            data = json.loads(self._read_body())
        except Exception:
            self.send_error_json(400, "ERR_BAD_REQUEST", "请求格式错误")
            return
        folder = data.get("folder") if isinstance(data, dict) else None
        if not isinstance(folder, str) or not folder:
            self.send_error_json(400, "ERR_BAD_REQUEST", "缺少 folder")
            return
        # [2026-10-12 ROTATE] 可选 rotations：{"cpu":90,...} 该类型照片旋转后重 OCR
        rotations = data.get("rotations") if isinstance(data, dict) else None
        ok, payload = _parts_analyze_scan(folder, rotations)
        if ok:
            self.send_json({"ok": True, "folder": folder,
                            "ai": payload["suggestions"], "ocr": payload["ocr"]})
        else:
            status = 404 if payload.get("code") == "ERR_NOT_FOUND" else 400
            self.send_error_json(status, payload.get("code", "ERR_ANALYZE"),
                                 payload.get("message", "识别失败"))

    def handle_parts_archive_photo(self):
        """POST /api/parts-archive/photo — [2026-10-13 PHOTO-APPEND] 向已有档案补传照片

        multipart：folder + type（cpu/host/ram/ssd/nic/other）+ <type>File*（每类 ≤6 张总量）。
        网页编辑弹窗「＋ 补传照片」用；魔数/大小校验 + 2560px 重编码，与上传同标准。
        """
        try:
            clen = int(self.headers.get("Content-Length", 0))
        except ValueError:
            clen = 0
        if clen > PARTS_MAX_IMAGE_BYTES * (PARTS_MAX_FILES_PER_TYPE + 1) + 64 * 1024:
            self.close_connection = True
            self.send_error_json(413, "ERR_TOO_LARGE", "请求体超过上限")
            return
        body = self._read_body()
        raw = _parse_multipart_multi(body, self.headers.get("Content-Type", ""))
        if raw is None:
            self.send_error_json(400, "ERR_BAD_REQUEST", "multipart 解析失败")
            return

        def _decode(v):
            return v[0][1].decode("utf-8", "replace").strip() if v and v[0][1] else ""

        folder = _decode(raw.get("folder"))
        ftype = _decode(raw.get("type"))
        items = []
        for name, lst in raw.items():
            base = name.rstrip("0123456789_")
            if base == ftype + "File":
                items.extend(lst)
        ok, payload = _parts_archive_photo_append(folder, ftype, items)
        if ok:
            self.send_json(payload)
        else:
            status = 404 if payload.get("code") == "ERR_NOT_FOUND" else 400
            self.send_error_json(status, payload.get("code", "ERR_PHOTO"),
                                 payload.get("message", "补传失败"))

    def handle_parts_archive_update(self):
        """POST /api/parts-archive/update — 修改档案参数（[2026-10-08 EDIT] 网页端编辑纠错）

        JSON body：{ "folder": "2026/9/29/J16Z144",
                     "fields": { "cpuCode": "01627", ... } }
        可编辑白名单见 _parts_archive_update；照片/上传时间不动。
        """
        try:
            data = json.loads(self._read_body())
        except Exception:
            self.send_error_json(400, "ERR_BAD_REQUEST", "请求格式错误")
            return
        folder = data.get("folder") if isinstance(data, dict) else None
        fields = data.get("fields") if isinstance(data, dict) else None
        if not isinstance(folder, str) or not isinstance(fields, dict):
            self.send_error_json(400, "ERR_BAD_REQUEST", "缺少 folder 或 fields")
            return
        ok, payload = _parts_archive_update(folder, fields)
        if ok:
            self.send_json(payload)
        else:
            status = 404 if payload.get("code") == "ERR_NOT_FOUND" else 400
            self.send_error_json(status, payload.get("code", "ERR_UPDATE"),
                                 payload.get("message", "修改失败"))

    def handle_parts_image(self, qs):
        """GET /api/parts-image?path=<rel> — 按需下载单张原图（路径白名单校验，支持 ?token=）"""
        rel = (qs.get("path") or [""])[0]
        if not rel:
            self.send_error_json(400, "ERR_BAD_REQUEST", "缺少 path 参数")
            return
        try:
            data, mime = _parts_image_read(rel)
        except LookupError:
            self.send_error_json(403, "ERR_FORBIDDEN", "路径不合法")
            return
        except FileNotFoundError:
            self.send_error_json(404, "ERR_NOT_FOUND", "图片不存在")
            return
        except OSError as e:
            self.send_error_json(500, "ERR_IO", f"读取失败: {e}")
            return
        self._img_cache = True   # end_headers 据此发可缓存头
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# ======================== 多线程服务器 ========================
class ThreadingServer(ThreadingHTTPServer):
    """ThreadingHTTPServer + daemon_threads，确保 Ctrl+C 时线程不会阻塞退出"""
    daemon_threads = True
    allow_reuse_address = True


# ======================== 启动 ========================
def test_ftp_connection():
    """启动时测试 FTP 连接，返回 (success, message)。

    逐个尝试 FTP_SCAN_DIRS 中的目录，统计可访问目录的 .json 文件总数。
    """
    try:
        ftp = ftp_connect()
        total = 0
        dirs_ok = 0
        try:
            for subdir in FTP_SCAN_DIRS:
                try:
                    files = list_dir_json(ftp, subdir)
                    total += len(files)
                    dirs_ok += 1
                except Exception:
                    continue
        finally:
            ftp_safe_close(ftp)
        return True, f"FTP 连接成功，{dirs_ok}/{len(FTP_SCAN_DIRS)} 个目录可访问，共 {total} 个日志文件"
    except Exception as e:
        code, msg = ftp_error_code(e)
        return False, f"FTP 连接失败 [{code}]: {msg}"


def check_single_instance():
    """检测是否已有服务端实例在运行。返回 (is_running, detail_msg)。"""
    # 方式1：尝试连接本地端口
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(("127.0.0.1", PORT))
        s.close()
        return True, f"端口 {PORT} 已被占用，可能已有实例在运行"
    except (ConnectionRefusedError, OSError, socket.timeout):
        pass

    # 方式2：检查 PID 文件
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                old_pid = int(f.read().strip())
            # 尝试向旧进程发送信号 0（仅检测进程是否存在，不实际终止）
            os.kill(old_pid, 0)
            return True, f"发现运行中的服务端进程 (PID={old_pid})"
        except (ValueError, FileNotFoundError):
            # PID 文件损坏或进程已退出 → 清理残留文件
            try:
                os.remove(PID_FILE)
            except OSError:
                pass
        except OSError:
            # 进程不存在 → 清理残留文件
            try:
                os.remove(PID_FILE)
            except OSError:
                pass

    return False, ""


def write_pid():
    """写入当前进程 PID 到文件。"""
    try:
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except OSError as e:
        log_main.warning(f"写入 PID 文件失败: {e}")


def remove_pid():
    """清理 PID 文件。"""
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except OSError:
        pass


def get_lan_ip():
    """获取本机内网 IP（通过连接 UDP socket 让 OS 选出出口 IP）"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def main():
    # ---- 日志系统初始化 ----
    setup_logging()
    log_main.info("=" * 55)
    log_main.info("  LDTools 日志查看器服务 启动")
    log_main.info("=" * 55)

    # ---- 单实例检测 ----
    running, msg = check_single_instance()
    if running:
        log_main.error(f"  检测到已有实例运行: {msg}")
        print(f"\n  [ERROR] {msg}")
        print("  请先关闭已有实例后再启动。\n")
        sys.exit(1)
    write_pid()
    log_main.info(f"  PID: {os.getpid()}")

    lan_ip = get_lan_ip()
    log_main.info(f"  静态文件目录 : {SCRIPT_DIR}")
    log_main.info(f"  FTP 服务器   : {FTP_HOST}{FTP_DIR}")
    log_main.info(f"  检索目录     : {', '.join((FTP_DIR if not d else f'{FTP_DIR}/{d}') for d in FTP_SCAN_DIRS)}")
    log_main.info(f"  监听地址     : 0.0.0.0:{PORT}")
    log_main.info(f"  数据缓存     : 内存（进程退出即清空）")
    log_main.info("=" * 55)

    # [2026-08-22 startup-sync → 2026-08-24 OUTBOUND] 启动时强制对齐 cache + 磁盘 + index.json
    # 避免用户手动删除文件夹后 cache 残留幽灵条目（detail 元数据存在但 cpu-image 404）
    try:
        with _outbound_write_lock:
            _outbound_index_cache = _outbound_index_rebuild()
            _outbound_index_persist()
        log_main.info(f"  出库档案索引已对齐磁盘：{len(_outbound_index_cache)} 条")
    except Exception as e:
        log_main.warning(f"  出库索引启动对齐失败（不影响服务启动）: {e}")

    # 配件档案索引启动补齐；由加载函数维护模块缓存，避免局部变量写回空索引。
    try:
        parts_index = _parts_index_reconcile()
        log_main.info(f"  配件档案索引已对齐磁盘：{len(parts_index)} 条")
    except Exception as e:
        log_main.warning(f"  配件档案索引启动对齐失败（不影响服务启动）: {e}")

    # ---- 启动 HTTP 服务器（后台线程）----
    global _server
    _server = ThreadingServer(("0.0.0.0", PORT), LogViewerHandler)
    http_thread = threading.Thread(target=_server.serve_forever, daemon=True, name="http-server")
    http_thread.start()
    log_main.info(f"  HTTP 服务已启动 → {SERVICE_URL}")
    if lan_ip:
        log_main.info(f"  内网访问 → http://{lan_ip}:{PORT}")

    # ---- 启动后台 FTP 轮询线程 ----
    poll_thread = threading.Thread(target=background_ftp_poll, daemon=True, name="ftp-poll")
    poll_thread.start()

    # ---- 启动统计摘要线程 ----
    stats_t = threading.Thread(target=_stats_loop, daemon=True, name="stats")
    stats_t.start()

    # ---- 测试 FTP 连接 ----
    log_main.info("  正在测试 FTP 连接...")
    ok, msg = test_ftp_connection()
    state_symbol = "[OK]" if ok else "[FAIL]"
    if ok:
        log_main.info(f"  {state_symbol} {msg}")
    else:
        log_main.error(f"  {state_symbol} {msg}")
    set_ftp_state(ok=ok)
    if not ok:
        log_main.warning("  ! FTP 不可用，页面仍可打开但会显示连接错误。")

    # 获取首次文件列表数量
    try:
        files = get_file_list()
        set_ftp_state(file_count=len(files))
    except Exception:
        pass

    # ---- 启动系统托盘（阻塞主线程）----
    log_main.info("  系统托盘已启动 — 右键托盘图标查看菜单")
    log_main.info("=" * 55)

    # 启动气泡通知
    def _startup_notify():
        time.sleep(0.8)  # 等托盘初始化完成
        if _tray_icon:
            ftp_status = "FTP 已连接" if get_ftp_state()["ok"] else "⚠ FTP 未连接"
            _tray_icon.notify(f"服务已就绪 — {ftp_status}", "LDTools")
    threading.Thread(target=_startup_notify, daemon=True).start()

    try:
        start_tray()
    except Exception as e:
        log_main.error(f"  托盘异常: {e}")
    finally:
        log_main.info("  正在关闭服务...")
        clear_cache()
        _server.shutdown()
        _server.server_close()
        remove_pid()
        log_main.info("  服务已停止，内存缓存已清空。")


if __name__ == "__main__":
    main()
