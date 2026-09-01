# -*- coding: utf-8 -*-
"""测试 Word 文档打印。"""
import os
import win32com.client

out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_t.docx")
w = win32com.client.DispatchEx("Word.Application")
try:
    w.Visible = False
except Exception as e:
    print("Visible set failed (non-fatal):", e)
doc = w.Documents.Add()
rng = doc.Content
rng.Text = "WSDI Word print test\nSecond line"
doc.SaveAs(out_path)
doc.Close(False)
w.Quit()
print("docx created")

import printer
ok, msg = printer.print_file(out_path, "IPRT IP-801")
print("Word print:", ok, msg)
os.remove(out_path)
