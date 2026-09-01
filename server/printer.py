# -*- coding: utf-8 -*-
"""
WSDI 网络打印机模块
====================
让外网用户通过 HTTP 上传文件，用本机打印机完成打印。

支持文件类型（全部走静默 GDI 光栅打印，无 GUI 弹窗）：
  - PDF (.pdf)            -> PyMuPDF 渲染每页为图像，GDI 光栅打印
  - 图片 (.png/.jpg/.jpeg/.bmp/.gif) -> PIL 打开，GDI 光栅打印
  - Word (.doc/.docx)     -> Office COM 导出 PDF，再 GDI 打印
  - Excel (.xls/.xlsx)    -> Office COM 导出 PDF，再 GDI 打印
  - 文本 (.txt/.log)      -> PIL 渲染为图片，GDI 光栅打印

所有打印都串行执行（一次只处理一个任务），避免并发冲突。
"""

import os
import sys
import time
import ctypes
import threading
import tempfile
import subprocess
from urllib.parse import unquote
from ctypes import wintypes as _wt

try:
    import win32print
    import win32api
    import win32con
    HAS_WIN32 = True
except Exception:
    HAS_WIN32 = False

# ---- ctypes 访问 Windows 打印 API（用于应用 DEVMODE：纸张/单双面/份数等）----
_spool = ctypes.WinDLL('winspool.drv')
_gdi32 = ctypes.WinDLL('gdi32')


class _DEVMODEW(ctypes.Structure):
    """Windows DEVMODEW 结构体（打印机相关字段）。"""
    _fields_ = [
        ('dmDeviceName', ctypes.c_wchar * 32),
        ('dmSpecVersion', _wt.WORD), ('dmDriverVersion', _wt.WORD),
        ('dmSize', _wt.WORD), ('dmDriverExtra', _wt.WORD),
        ('dmFields', _wt.DWORD),
        # union 取打印机分支
        ('dmOrientation', ctypes.c_short), ('dmPaperSize', ctypes.c_short),
        ('dmPaperLength', ctypes.c_short), ('dmPaperWidth', ctypes.c_short),
        ('dmScale', ctypes.c_short), ('dmCopies', ctypes.c_short),
        ('dmDefaultSource', ctypes.c_short), ('dmPrintQuality', ctypes.c_short),
        ('dmColor', ctypes.c_short), ('dmDuplex', ctypes.c_short),
        ('dmYResolution', ctypes.c_short), ('dmTTOption', ctypes.c_short),
        ('dmCollate', ctypes.c_short),
        ('dmFormName', ctypes.c_wchar * 32),
        ('dmLogPixels', _wt.WORD), ('dmBitsPerPel', _wt.DWORD),
        ('dmPelsWidth', _wt.DWORD), ('dmPelsHeight', _wt.DWORD),
    ]


# DEVMODE 字段掩码
_DM_ORIENTATION = 0x00000001
_DM_PAPERSIZE = 0x00000002
_DM_PAPERLENGTH = 0x00000004
_DM_PAPERWIDTH = 0x00000008
_DM_COPIES = 0x00000100
_DM_DUPLEX = 0x00001000
_DM_FORMNAME = 0x00010000

# 双面常量
_DMDUP_SIMPLEX = 1    # 单面
_DMDUP_VERTICAL = 2   # 长边翻页（对开本式）
_DMDUP_HORIZONTAL = 3 # 短边翻页（记事本式）

# 常用纸张：DMPAPER_*
_DMPAPER_A3 = 8
_DMPAPER_A4 = 9
_DMPAPER_A5 = 11
_DMPAPER_LETTER = 1
_DMPAPER_LEGAL = 5

# 纸张名 -> (dmPaperSize, 宽度mm, 高度mm)
_PAPER_MAP = {
    'A4':     (_DMPAPER_A4, 210, 297),
    'A5':     (_DMPAPER_A5, 148, 210),
    'A3':     (_DMPAPER_A3, 297, 420),
    'Letter': (_DMPAPER_LETTER, 216, 279),
    'Legal':  (_DMPAPER_LEGAL, 216, 356),
    'Auto':   (0, 0, 0),
}

# 横向/纵向
_ORIENTATION_PORTRAIT = 1  # DMORIENT_PORTRAIT
_ORIENTATION_LANDSCAPE = 2  # DMORIENT_LANDSCAPE


def _get_devmode(printer):
    """用 DocumentPropertiesW 获取打印机的 DEVMODEW 对象。"""
    handle = _wt.HANDLE()
    if not _spool.OpenPrinterW(ctypes.c_wchar_p(printer), ctypes.byref(handle), None):
        return None
    try:
        size = _spool.DocumentPropertiesW(
            None, handle, ctypes.c_wchar_p(printer), None, None, 0)
        if size <= 0:
            return None
        buf = ctypes.create_string_buffer(size)
        dm = ctypes.cast(buf, ctypes.POINTER(_DEVMODEW)).contents
        out = _spool.DocumentPropertiesW(
            None, handle, ctypes.c_wchar_p(printer), buf, buf, 2)  # DM_OUT_BUFFER
        if out != 1:
            return None
        return dm
    finally:
        _spool.ClosePrinter(handle)


def _apply_settings_to_devmode(dm, settings):
    """把 settings 里的打印设置写入 DEVMODEW。"""
    if not dm:
        return

    # 份数
    copies = (settings or {}).get('copies')
    if copies and 1 <= int(copies) <= 999:
        dm.dmCopies = int(copies)
        dm.dmFields |= _DM_COPIES

    # 横向/纵向
    orient = (settings or {}).get('orientation', 'portrait')
    if orient == 'landscape':
        dm.dmOrientation = _ORIENTATION_LANDSCAPE
        dm.dmFields |= _DM_ORIENTATION
    elif orient == 'portrait':
        dm.dmOrientation = _ORIENTATION_PORTRAIT
        dm.dmFields |= _DM_ORIENTATION

    # 纸张
    paper = (settings or {}).get('paper', 'Auto')
    if paper in _PAPER_MAP:
        paper_size, w_mm, h_mm = _PAPER_MAP[paper]
        if paper_size:
            dm.dmPaperSize = paper_size
            dm.dmFields |= _DM_PAPERSIZE
            # 300 dpi 下 1mm = 11.81，取整
            dm.dmPaperWidth = int(w_mm * 300 / 25.4)
            dm.dmPaperLength = int(h_mm * 300 / 25.4)
            dm.dmFields |= _DM_PAPERWIDTH | _DM_PAPERLENGTH

    # 单双面
    duplex = (settings or {}).get('duplex', 'off')
    if duplex == 'long-edge':
        dm.dmDuplex = _DMDUP_VERTICAL
        dm.dmFields |= _DM_DUPLEX
    elif duplex == 'short-edge':
        dm.dmDuplex = _DMDUP_HORIZONTAL
        dm.dmFields |= _DM_DUPLEX
    elif duplex == 'off':
        dm.dmDuplex = _DMDUP_SIMPLEX
        dm.dmFields |= _DM_DUPLEX


def _create_print_dc(printer, settings):
    """用 ctypes CreateDCW 创建应用了 settings 的打印机 DC，返回 HDC 整数句柄。"""
    dm = _get_devmode(printer)
    if dm is not None:
        _apply_settings_to_devmode(dm, settings)
        return _gdi32.CreateDCW(None, ctypes.c_wchar_p(printer), None, ctypes.byref(dm))
    # 拿不到 devmode 就退化为默认
    return _gdi32.CreateDCW(None, ctypes.c_wchar_p(printer), None, None)

# 打印任务全局锁（串行化，防止默认打印机切换并发冲突）
_print_lock = threading.Lock()

# 允许打印的文件扩展名 -> (说明, 类别)
ALLOWED_EXT = {
    '.pdf':  ('PDF 文档', 'pdf'),
    '.png':  ('PNG 图片', 'image'),
    '.jpg':  ('JPG 图片', 'image'),
    '.jpeg': ('JPEG 图片', 'image'),
    '.bmp':  ('BMP 图片', 'image'),
    '.gif':  ('GIF 图片', 'image'),
    '.doc':  ('Word 文档', 'word'),
    '.docx': ('Word 文档', 'word'),
    '.xls':  ('Excel 表格', 'excel'),
    '.xlsx': ('Excel 表格', 'excel'),
    '.txt':  ('文本文件', 'text'),
    '.log':  ('日志文件', 'text'),
}

# 单文件大小上限：20MB（防止上传超大文件恶意占用磁盘）
MAX_FILE_SIZE = 20 * 1024 * 1024


def printers_available():
    """返回 win32print 是否可用。"""
    return HAS_WIN32


def list_printers():
    """枚举本机所有打印机（含网络打印机连接）。

    Returns:
        list[str]: 打印机名称列表；库不可用时返回 []
    """
    if not HAS_WIN32:
        return []
    try:
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        printers = win32print.EnumPrinters(flags)
        names = [p[2] for p in printers]
        # 去重保序
        seen = set()
        out = []
        for n in names:
            if n not in seen:
                seen.add(n)
                out.append(n)
        return out
    except Exception as e:
        print(f"[!] list_printers failed: {e}")
        return []


def get_default_printer():
    """获取当前默认打印机名称。"""
    try:
        return win32print.GetDefaultPrinter()
    except Exception:
        return None


def _printer_exists(name):
    """判断打印机名称是否有效。"""
    try:
        return name in list_printers()
    except Exception:
        return False


def _set_default_printer(name):
    """把某打印机设为系统默认（用于 ShellExecute 打印）。"""
    win32print.SetDefaultPrinter(name)


def print_file(file_path, printer=None, settings=None):
    """打印一个已保存到本地的文件到指定打印机（默认用系统默认打印机）。

    Args:
        file_path: 文件绝对路径
        printer:   目标打印机名称；None 表示用当前默认打印机
        settings:  打印设置 dict，可含：
            copies: int         份数，默认 1
            orientation: str    'portrait' / 'landscape'
            paper: str          'A4' / 'A5' / 'A3' / 'Letter' / 'Legal' / 'Auto'
            duplex: str         'off' / 'long-edge' / 'short-edge'
            page_range: str     页码范围，如 '1-3,5'，空串=全部

    Returns:
        (ok: bool, message: str)
    """
    if not os.path.isfile(file_path):
        return False, "文件不存在"
    if not HAS_WIN32:
        return False, "本机打印库(win32print)未安装"

    ext = os.path.splitext(file_path)[1].lower()
    if ext not in ALLOWED_EXT:
        return False, f"不支持的文件类型: {ext or '(无扩展名)'}"
    ftype = ALLOWED_EXT[ext][1]

    # 目标打印机
    target = printer
    if target and not _printer_exists(target):
        # 打印机名可能包含大小写/空格差异，尝试精确匹配
        exact = next((p for p in list_printers() if p.lower() == target.lower()), None)
        if exact:
            target = exact
        else:
            return False, f"打印机不存在: {target}"
    if not target:
        target = get_default_printer()
        if not target:
            return False, "本机没有可用的默认打印机"

    # 串行执行打印
    with _print_lock:
        try:
            if ftype in ('word', 'excel'):
                ok, msg = _print_office(file_path, ext, target, settings)
            elif ftype == 'pdf':
                ok, msg = _print_pdf(file_path, target, settings)
            elif ftype == 'image':
                ok, msg = _print_image(file_path, target, settings)
            else:  # text
                ok, msg = _print_text(file_path, target, settings)
            return ok, msg
        except Exception as e:
            return False, f"打印异常: {e}"


def _print_pdf(file_path, printer, settings=None):
    """PDF 打印：用 PyMuPDF 渲染每页为图像，再用 GDI 光栅打印。"""
    try:
        try:
            import pymupdf as fitz  # PyMuPDF 新版
        except Exception:
            import fitz  # 旧版
        from PIL import Image
    except Exception:
        return False, "本机未安装 PyMuPDF 库，无法打印 PDF"

    pages = []
    try:
        doc = fitz.open(file_path)
        total = doc.page_count
        sel = _parse_page_range((settings or {}).get('page_range'), total)
        # 渲染选中页码（sel 为 0 基索引）
        for idx in sel:
            page = doc[idx]
            zoom = 150 / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            pages.append(img)
        doc.close()
    except Exception as e:
        return False, f"PDF 解析失败: {e}"

    if not pages:
        return False, "PDF 没有可打印的页面（页码范围可能超出文档）"

    # 用 GDI 打印每一页
    return _print_raster_pages(pages, printer, settings)


def _parse_page_range(range_str, total_pages):
    """解析页码范围字符串（1 基，如 '1-3,5'）为 0 基索引列表。

    Args:
        range_str: 如 '1-3,5'，空串或 None 表示全部
        total_pages: 文档总页数

    Returns:
        list[int]: 0 基索引，按升序去重
    """
    if not range_str or not str(range_str).strip():
        return list(range(total_pages))

    result = set()
    parts = str(range_str).replace(' ', '').split(',')
    for part in parts:
        if not part:
            continue
        if '-' in part:
            a, b = part.split('-', 1)
            try:
                start = int(a) if a else 1
                end = int(b) if b else total_pages
            except ValueError:
                continue
            start = max(1, start)
            end = min(total_pages, end)
            if start <= end:
                for p in range(start, end + 1):
                    result.add(p - 1)
        else:
            try:
                p = int(part)
                if 1 <= p <= total_pages:
                    result.add(p - 1)
            except ValueError:
                continue
    return sorted(result)


def _print_image(file_path, printer, settings=None):
    """图片打印：用 PIL 打开图片，GDI 光栅打印（静默、可靠）。"""
    try:
        from PIL import Image
    except Exception:
        return False, "本机未安装 Pillow 库，无法打印图片"
    try:
        img = Image.open(file_path)
        img.load()
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        return _print_raster_pages([img], printer, settings)
    except Exception as e:
        return False, f"图片打开失败: {e}"


def _print_raster_pages(images, printer, settings=None):
    """把一页或多页 PIL 图像用 GDI 打印到指定打印机。

    通过 ctypes CreateDCW 应用打印设置（份数/纸张/单双面/横向纵向），
    再用 PIL.ImageWin.Dib 绘制到打印机 HDC，完全静默无弹窗。

    Args:
        images: PIL.Image 列表
        printer: 打印机名
        settings: 打印设置 dict（copies/orientation/paper/duplex）
    """
    try:
        from PIL import Image, ImageWin
    except Exception as e:
        return False, f"缺少打印组件: {e}"

    settings = settings or {}
    copies = int(settings.get('copies', 1) or 1)
    copies = max(1, min(999, copies))

    hdc = None
    try:
        # 用 ctypes CreateDCW 创建应用了 settings 的打印机 DC
        hdc = _create_print_dc(printer, settings)
        if not hdc:
            return False, f"无法创建打印机 {printer} 的打印上下文"

        # 页面物理尺寸（1/1000 英寸 -> 用 gdi32 GetDeviceCaps）
        page_w = _gdi32.GetDeviceCaps(hdc, 110)  # HORZRES
        page_h = _gdi32.GetDeviceCaps(hdc, 111)  # VERTRES

        # DOCINFO
        class _DOCINFO(ctypes.Structure):
            _fields_ = [('cbSize', _wt.DWORD), ('lpszDocName', _wt.LPCWSTR),
                        ('lpszOutput', _wt.LPCWSTR), ('lpszDatatype', _wt.LPCWSTR),
                        ('fwType', _wt.DWORD)]
        di = _DOCINFO()
        di.cbSize = ctypes.sizeof(_DOCINFO)
        di.lpszDocName = "WSDI Remote Print"

        total_printed = 0
        for _ in range(copies):
            doc_id = _gdi32.StartDocW(hdc, ctypes.byref(di))
            if doc_id <= 0:
                continue
            for img in images:
                img = img.convert("RGB")
                bw, bh = img.size

                # 居中缩放（保持宽高比，留 5% 边距）
                margin_w = int(page_w * 0.05)
                margin_h = int(page_h * 0.05)
                max_w = page_w - 2 * margin_w
                max_h = page_h - 2 * margin_h
                scale = min(max_w / bw, max_h / bh)
                draw_w = int(bw * scale)
                draw_h = int(bh * scale)
                x0 = margin_w + (max_w - draw_w) // 2
                y0 = margin_h + (max_h - draw_h) // 2

                dib = ImageWin.Dib(img)
                _gdi32.StartPage(hdc)
                dib.draw(hdc, (x0, y0, x0 + draw_w, y0 + draw_h))
                _gdi32.EndPage(hdc)
                total_printed += 1
            _gdi32.EndDoc(hdc)

        if total_printed == 0:
            return False, "打印任务未生成任何页"

        dup = settings.get('duplex', 'off')
        dup_txt = {None: '', 'off': '', 'long-edge': ' 双面(长边)', 'short-edge': ' 双面(短边)'}.get(dup, '')
        return True, f"已提交到打印机: {printer} ({len(images)} 页 × {copies} 份{dup_txt})"
    except Exception as e:
        return False, f"打印失败: {e}"
    finally:
        if hdc:
            try:
                _gdi32.DeleteDC(hdc)
            except Exception:
                pass


def _print_office(file_path, ext, printer, settings=None):
    """打印 Word/Excel 文档。

    方案：先用 Office COM 把文档静默导出为 PDF，再走 GDI 光栅打印。
    这样绕开脆弱的 PrintOut 直接打印（易弹窗/被拒），统一用 PDF 渲染链路。

    需要本机安装 Microsoft Office。
    """
    try:
        import win32com.client
    except Exception:
        return False, "本机未安装 pywin32，无法打印 Office 文档"

    app = None
    doc = None
    pdf_tmp = None
    try:
        pdf_tmp = os.path.join(tempfile.gettempdir(), f"_wsdi_office_{os.getpid()}.pdf")
        # 删除可能残留的临时文件
        if os.path.exists(pdf_tmp):
            try:
                os.remove(pdf_tmp)
            except Exception:
                pass

        if ext in ('.doc', '.docx'):
            # DispatchEx 强制创建新实例，避免复用已有 Word 实例导致 Visible 只读
            app = win32com.client.DispatchEx("Word.Application")
            try:
                app.Visible = False  # 非致命：某些环境不允许设置
            except Exception:
                pass
            doc = app.Documents.Open(file_path, ReadOnly=True)
            # 导出 PDF：17 = wdExportFormatPDF
            doc.ExportAsFixedFormat(pdf_tmp, 17)
            doc.Close(False)
        else:
            app = win32com.client.DispatchEx("Excel.Application")
            try:
                app.Visible = False
                app.DisplayAlerts = False
            except Exception:
                pass
            wb = app.Workbooks.Open(file_path, ReadOnly=True)
            # 导出 PDF：0 = xlTypePDF
            wb.ExportAsFixedFormat(0, pdf_tmp)
            wb.Close(False)

        try:
            app.Quit()
        except Exception:
            pass

        if not os.path.exists(pdf_tmp):
            return False, "Office 文档转 PDF 失败"

        # 复用 PDF 渲染打印链路
        return _print_pdf(pdf_tmp, printer, settings)
    except Exception as e:
        try:
            if doc is not None:
                doc.Close(False)
        except Exception:
            pass
        try:
            if app is not None:
                app.Quit()
        except Exception:
            pass
        if "retrieving the COM class factory" in str(e) or "class not registered" in str(e).lower():
            return False, "本机未安装 Microsoft Office，无法打印 Word/Excel 文档"
        return False, f"Office 文档处理失败: {e}"
    finally:
        # 清理临时 PDF
        if pdf_tmp and os.path.exists(pdf_tmp):
            try:
                os.remove(pdf_tmp)
            except Exception:
                pass


def _print_text(file_path, printer, settings=None):
    """文本文件打印：渲染成图片后用 GDI 打印。

    直接把原始文本写打印队列对很多打印机（如热敏、PCL 专用机）不兼容，
    渲染成图片可确保所有打印机都能正常输出。
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return False, "本机未安装 Pillow 库，无法打印文本"

    try:
        # 读取文本（尝试 UTF-8，失败则用 GBK）
        raw = open(file_path, 'rb').read()
        text = None
        for enc in ('utf-8-sig', 'utf-8', 'gbk', 'latin-1'):
            try:
                text = raw.decode(enc)
                break
            except Exception:
                continue
        if text is None:
            text = raw.decode('latin-1', errors='replace')

        lines = text.splitlines() or ['(空文件)']

        # 字体设置：优先用等宽/系统字体，fallback 到默认
        try:
            # Windows 常见中文字体
            font = ImageFont.truetype("msyh.ttc", 24)
        except Exception:
            try:
                font = ImageFont.truetype("simhei.ttf", 24)
            except Exception:
                try:
                    font = ImageFont.truetype("arial.ttf", 24)
                except Exception:
                    font = ImageFont.load_default()

        # 计算每行尺寸，用最大宽度 + 累计高度
        margin = 60
        line_height = 36
        max_w = 0
        for line in lines:
            bbox = font.getbbox(line)
            w = bbox[2] - bbox[0] if bbox else 0
            max_w = max(max_w, w)

        img_w = max(max_w + 2 * margin, 600)
        img_h = max(len(lines) * line_height + 2 * margin, 200)

        img = Image.new('RGB', (img_w, img_h), 'white')
        draw = ImageDraw.Draw(img)

        # 绘制边框和文本
        draw.rectangle([0, 0, img_w - 1, img_h - 1], outline='#cccccc', width=1)
        y = margin
        for line in lines:
            draw.text((margin, y), line, fill='black', font=font)
            y += line_height

        return _print_raster_pages([img], printer, settings)
    except Exception as e:
        return False, f"文本打印失败: {e}"


def cleanup_temp(file_path):
    """删除临时文件。"""
    try:
        if file_path and os.path.isfile(file_path):
            os.remove(file_path)
    except Exception:
        pass


if __name__ == "__main__":
    # 单独测试
    print("=== 本机打印机 ===")
    for p in list_printers():
        print("  -", p)
    print("默认打印机:", get_default_printer())
