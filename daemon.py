# -*- coding: utf-8 -*-
"""无界面守护进程（Termux / 后台 / 开机自启用）
用法：python daemon.py
使用 credentials.json 中 active_carrier 对应运营商的账号密码。
"""
import threading

import portal

CFG = portal.load_config()
user, password, carrier = portal.read_active_creds()

if not user or not password:
    print("没有可用的账号密码，请先运行 gui.py，在「账号管理」里填写并保存。")
    raise SystemExit(1)

running = threading.Event()
running.set()

print("守护进程已启动：%s（%s）" % (user, carrier))
print("Ctrl+C 退出")
try:
    portal.monitor_loop(CFG, portal.read_active_creds, running, print)
except KeyboardInterrupt:
    print("\n已退出")
