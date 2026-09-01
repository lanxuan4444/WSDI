# -*- coding: utf-8 -*-
"""测试 Word 转 PDF 再打印。"""
import os
import tempfile
import win32com.client

base = os.path.dirname(os.path.abspath(__file__))
docx_path = os.path.join(base, "_t2.docx")
pdf_path = os.path.join(base, "_t2_conv.pdf")

# 1. 创建 docx
w = win32com.client.DispatchEx("Word.Application")
try:
    w.Visible = False
except Exception:
    pass
d = w.Documents.Add()
d.Content.Text = "WSDI Word to PDF test\nSecond line"
d.SaveAs(docx_path)
# 2. 导出 PDF
try:
    d.ExportAsFixedFormat(pdf_path, 17)  # 17 = wdExportFormatPDF
    print("Word -> PDF export OK")
except Exception as e:
    print("Word->PDF export failed:", e)
d.Close(False)
try:
    w.Quit()
except Exception:
    pass

# 3. 用 GDI 打印 PDF
if os.path.exists(pdf_path):
    import printer
    ok, msg = printer.print_file(pdf_path, "IPRT IP-801")
    print("PDF print:", ok, msg)
    os.remove(pdf_path)
if os.path.exists(docx_path):
    try:
        os.remove(docx_path)
    except Exception:
        pass
