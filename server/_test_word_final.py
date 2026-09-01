# -*- coding: utf-8 -*-
"""最终测试：printer.print_file 处理 Word 文档。"""
import os
import win32com.client

base = os.path.dirname(os.path.abspath(__file__))
docx_path = os.path.join(base, "_t3.docx")

# 创建 docx
w = win32com.client.DispatchEx("Word.Application")
try:
    w.Visible = False
except Exception:
    pass
d = w.Documents.Add()
d.Content.Text = "WSDI Word final print test"
d.SaveAs(docx_path)
d.Close(False)
try:
    w.Quit()
except Exception:
    pass

import printer
ok, msg = printer.print_file(docx_path, "IPRT IP-801")
print("Word via print_file:", ok, msg)

try:
    os.remove(docx_path)
except Exception:
    pass
