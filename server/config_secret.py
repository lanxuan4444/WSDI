# -*- coding: utf-8 -*-
"""
WSDI 敏感配置（本文件不入库，见 .gitignore）
================================================
把密钥/账号/本地路径等敏感信息集中放在这里，
server/b2.py 等模块会优先从这个文件读取。

如果本文件不存在或字段缺失，模块会回退到环境变量读取，
请勿把真实密钥写进任何入库的 .py 文件。
"""

# ---- B2 凭据 ----
B2_KEY_ID = '004a547fb4332250000000001'
B2_APP_KEY = 'K004twY1jKdG2ToSqg00Xq8OBs/ms80'
B2_BUCKET_NAME = 'wsdi-drivers'
B2_BUCKET_ID = 'bab594876f4be45393f20215'
B2_API_BASE = 'https://api004.backblazeb2.com'

# ---- 本地 rclone 路径 ----
RCLONE_PATH = r"D:\WSDI\tools\rclone-v1.67.0-windows-amd64\rclone.exe"
RCLONE_CONF = r"D:\WSDI\tools\rclone.conf"
REMOTE = "wsdi-b2:wsdi-drivers"

# ---- 服务器本地路径（部署环境相关，不入库）----
DRIVERS_DIR = r"D:\SDI\Drivers"
INDEX_DIR = r"D:\SDI\Index\SDI"
SDI_LITE_PATH = r"D:\WSDI\cache\sdi_lite\SDI_R2601.7z"
ZIP_7Z_PATH = r"D:\WSDI\cache\tools\7z_portable.zip"
