#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WSDI 服务托盘宿主
功能：
  - 同时托管 WSDI 主服务、LDTH5 日志服务、Cloudflare Tunnel
  - 所有子进程隐藏窗口，输出被捕获到内存日志
  - 系统托盘图标，右键菜单可查看各服务日志、重启、退出
"""

import os
import sys
import time
import json
import subprocess
import threading
import tkinter as tk
from tkinter import scrolledtext, messagebox
from datetime import datetime
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

# ==================== 配置 ====================
BASE_DIR = Path("D:/WSDI")
PYTHON = Path("C:/Users/Administrator/AppData/Local/Programs/Python/Python315/python.exe")
CLOUDFLARED = Path("D:/Cloudflar/cloudflared.exe")
CONFIG = BASE_DIR / "cloudflared-config.yml"

# 日志窗口默认大小
WINDOW_SIZE = (900, 500)

# 每个服务的配置
SERVICES = {
    "WSDI": {
        "title": "WSDI 主服务 (端口 80)",
        "cmd": [str(PYTHON), str(BASE_DIR / "server" / "server.py")],
        "cwd": str(BASE_DIR / "server"),
        "color": "#4a90e2",
        "log_max": 30000,
    },
    "LDTH5": {
        "title": "LDTH5 日志服务 (端口 9876)",
        "cmd": [str(PYTHON), str(BASE_DIR / "LDTH5" / "server.py")],
        "cwd": str(BASE_DIR / "LDTH5"),
        "color": "#27ae60",
        "log_max": 30000,
    },
    "JKGuard": {
        "title": "JK守护云端 (端口 8765)",
        "cmd": [str(PYTHON), "D:/JK/server/server.py"],
        "cwd": "D:/JK/server",
        "color": "#e74c3c",
        "log_max": 30000,
    },
    "Tunnel": {
        "title": "Cloudflare Tunnel",
        "cmd": [str(CLOUDFLARED), "tunnel", "--config", str(CONFIG), "run"],
        "cwd": str(BASE_DIR),
        "color": "#f39c12",
        "log_max": 30000,
    },
}


class ServiceProcess:
    """封装一个托管子进程"""

    def __init__(self, name, cfg):
        self.name = name
        self.cfg = cfg
        self.proc = None
        self.log_lines = []
        self.lock = threading.Lock()
        self.started_at = None
        self._stop_event = threading.Event()
        self._reader_thread = None

    def start(self):
        if self.proc and self.proc.poll() is None:
            return
        self._stop_event.clear()
        self.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        # 隐藏窗口
        creationflags = subprocess.CREATE_NO_WINDOW
        self.proc = subprocess.Popen(
            self.cfg["cmd"],
            cwd=self.cfg["cwd"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            startupinfo=startupinfo,
            creationflags=creationflags,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._reader_thread = threading.Thread(target=self._reader, daemon=True)
        self._reader_thread.start()
        self._append_log(f"[{self.name}] 服务启动 PID={self.proc.pid}\n")

    def _reader(self):
        try:
            for line in self.proc.stdout:
                self._append_log(line)
        except Exception as e:
            self._append_log(f"[{self.name}] 日志读取异常: {e}\n")
        finally:
            self._append_log(f"[{self.name}] 日志读取结束\n")

    def _append_log(self, line):
        ts = datetime.now().strftime("%H:%M:%S")
        with self.lock:
            self.log_lines.append(f"{ts} {line.rstrip()}\n")
            # 限制内存中的日志行数
            max_lines = self.cfg.get("log_max", 30000)
            if len(self.log_lines) > max_lines:
                self.log_lines = self.log_lines[-max_lines:]
        # 触发 UI 刷新（如果窗口打开）
        ui = getattr(self, "ui_text", None)
        if ui:
            try:
                ui.after(0, lambda: self._update_ui(ui))
            except Exception:
                pass

    def _update_ui(self, ui_text):
        try:
            ui_text.configure(state="normal")
            # 追加新增行而不是全量重写
            with self.lock:
                # 简单策略：只显示最近 5000 行，避免 UI 卡顿
                display_lines = self.log_lines[-5000:]
                current_count = int(ui_text.index("end-1c").split(".")[0])
                total_lines = len(display_lines)
                if total_lines > current_count:
                    for i in range(current_count, total_lines):
                        ui_text.insert("end", display_lines[i])
                    ui_text.see("end")
            ui_text.configure(state="disabled")
        except Exception:
            pass

    def stop(self, timeout=5):
        self._append_log(f"[{self.name}] 正在停止...\n")
        self._stop_event.set()
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2)
            except Exception as e:
                self._append_log(f"[{self.name}] 停止异常: {e}\n")
        self.proc = None

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None


class TrayApp:
    def __init__(self):
        self.services = {name: ServiceProcess(name, cfg) for name, cfg in SERVICES.items()}
        self.windows = {}
        self.icon = None
        self._exit_flag = False

    def _create_icon_image(self):
        # 绘制一个简洁的托盘图标
        width = 64
        height = 64
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        dc = ImageDraw.Draw(image)
        # 外圆
        dc.ellipse([4, 4, width - 4, height - 4], fill="#2c3e50", outline="#34495e", width=2)
        # 内部 "W" 字样
        dc.text((width // 2, height // 2), "W", fill="white", anchor="mm",
                font=None)
        return image

    def start_all(self):
        for svc in self.services.values():
            svc.start()
            time.sleep(0.5)

    def stop_all(self):
        for svc in self.services.values():
            svc.stop()

    def restart_all(self):
        for svc in self.services.values():
            svc.stop()
        time.sleep(1)
        self.start_all()

    def show_log_window(self, name):
        if name in self.windows and self.windows[name].winfo_exists():
            self.windows[name].deiconify()
            self.windows[name].lift()
            return

        svc = self.services[name]
        cfg = svc.cfg

        win = tk.Toplevel()
        win.title(f"{cfg['title']} - 日志")
        win.geometry(f"{WINDOW_SIZE[0]}x{WINDOW_SIZE[1]}")
        win.protocol("WM_DELETE_WINDOW", lambda: win.withdraw())

        # 顶部状态栏
        frame_top = tk.Frame(win, bg=cfg["color"])
        frame_top.pack(fill="x")
        status = tk.Label(frame_top, text=f"运行中 | PID: {svc.proc.pid if svc.proc else '-'}",
                          fg="white", bg=cfg["color"], padx=10, pady=4)
        status.pack(side="left")

        # 日志文本框
        text = scrolledtext.ScrolledText(win, wrap=tk.NONE, state="disabled",
                                          font=("Consolas", 10))
        text.pack(fill="both", expand=True)

        # 底部按钮
        frame_bottom = tk.Frame(win)
        frame_bottom.pack(fill="x", padx=5, pady=5)
        tk.Button(frame_bottom, text="清空",
                  command=lambda: self._clear_text(text)).pack(side="right", padx=5)
        tk.Button(frame_bottom, text="复制全部",
                  command=lambda: self._copy_text(text, win)).pack(side="right", padx=5)
        tk.Button(frame_bottom, text="刷新",
                  command=lambda: svc._update_ui(text)).pack(side="right", padx=5)

        # 绑定 service 到 UI，让 _append_log 自动刷新
        svc.ui_text = text
        # 首次填充
        svc._update_ui(text)

        # 定时刷新状态
        def refresh_status():
            if win.winfo_exists():
                if svc.is_running():
                    status.config(text=f"运行中 | PID: {svc.proc.pid} | 启动于 {svc.started_at}")
                else:
                    status.config(text="已停止")
                win.after(1000, refresh_status)

        refresh_status()
        self.windows[name] = win

    def _clear_text(self, text):
        text.configure(state="normal")
        text.delete(1.0, "end")
        text.configure(state="disabled")

    def _copy_text(self, text, win):
        content = text.get(1.0, "end")
        win.clipboard_clear()
        win.clipboard_append(content)
        messagebox.showinfo("已复制", "日志已复制到剪贴板", parent=win)

    def _make_show_log(self, name):
        """创建固定 name 的日志窗口显示函数"""
        def handler(icon, item):
            self.show_log_window(name)
        return handler

    def build_menu(self):
        # 动态生成菜单
        menu_items = []
        for name in SERVICES.keys():
            svc = self.services[name]
            running = "✓" if svc.is_running() else "✗"
            menu_items.append(
                pystray.MenuItem(
                    f"{running} 查看 {name} 日志",
                    self._make_show_log(name)
                )
            )
        menu_items.append(pystray.Menu.SEPARATOR)
        menu_items.append(pystray.MenuItem("重启所有服务", self._on_restart))
        menu_items.append(pystray.MenuItem("退出", self._on_exit))
        return pystray.Menu(*menu_items)

    def _on_restart(self, icon, item):
        self.restart_all()

    def _on_exit(self, icon, item):
        self.exit_app()

    def update_menu(self):
        if self.icon:
            try:
                self.icon.menu = self.build_menu()
            except Exception as e:
                print(f"update_menu error: {e}")

    def exit_app(self):
        self._exit_flag = True
        if self.icon:
            self.icon.stop()

    def _monitor_loop(self):
        while not self._exit_flag:
            time.sleep(2)
            # 自动重启崩溃的服务
            for svc in self.services.values():
                if not svc.is_running():
                    svc._append_log(f"[{svc.name}] 检测到服务已退出，正在自动重启...\n")
                    svc.start()
            self.update_menu()

    def run(self):
        # 启动所有服务
        self.start_all()

        # 监控线程：自动重启 + 菜单刷新
        monitor = threading.Thread(target=self._monitor_loop, daemon=True)
        monitor.start()

        # 创建托盘图标
        self.icon = pystray.Icon(
            "WSDI_Tray",
            icon=self._create_icon_image(),
            title="WSDI 服务托盘\n点击右键查看日志",
            menu=self.build_menu(),
        )

        # 启动托盘（阻塞）
        self.icon.run()

        # 退出时停止所有服务
        self.stop_all()


def main():
    # 隐藏自身控制台窗口
    if os.name == "nt":
        try:
            import ctypes
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
        except Exception:
            pass

    # 创建 tkinter 根窗口但不显示
    root = tk.Tk()
    root.withdraw()

    app = TrayApp()
    try:
        app.run()
    except Exception as e:
        messagebox.showerror("WSDI Tray 错误", f"托盘程序异常: {e}")
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
