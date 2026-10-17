# -*- coding: utf-8 -*-
"""校园网助手 · 桌面控制台（Tkinter）

左侧导航（网络概览 / 账号管理 / 学校设置 / 运行日志）+ 卡片式主区。
账号管理为每个运营商保存各自不同的账号密码。
学校参数存在 config.json（不入库），仓库只提供 config.example.json。

用法：python gui.py
"""
import ctypes
import json
import math
import queue
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import scrolledtext

# Windows 下必须先声明 DPI 感知，再创建 Tk 窗口，否则高分屏会模糊
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)      # Win8.1+ per-monitor
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()       # Win7
    except Exception:
        pass

import portal  # noqa: E402
import secure_store  # noqa: E402

CFG = portal.load_config()
CARRIERS = list(CFG.get("carriers", {}).keys()) or ["中国电信"]

# ---- 配色 ----
BG = "#f2f5f9"
CARD = "#ffffff"
BORDER = "#e4e9f0"
SHADOW = "#dfe5ee"
PRIMARY = "#0e9488"
PRIMARY_DARK = "#0a7a70"
PRIMARY_BG = "#e8f5f3"
TEXT = "#1f2937"
MUTED = "#7c8899"
GREEN = "#16a34a"
RED = "#dc2626"
FIELD = "#f7f9fb"


# ------------------------------------------------------------ 绘制工具

def round_polygon(canvas, x1, y1, x2, y2, r, **kw):
    """圆角矩形（Canvas 多边形近似）"""
    pts = []
    for cx, cy, a0 in ((x2 - r, y1 + r, -90), (x2 - r, y2 - r, 0),
                       (x1 + r, y2 - r, 90), (x1 + r, y1 + r, 180)):
        for i in range(0, 91, 6):
            a = math.radians(a0 + i)
            pts += [cx + r * math.cos(a), cy + r * math.sin(a)]
    return canvas.create_polygon(pts, smooth=True, **kw)


class Card(tk.Canvas):
    """圆角白底卡片，带一层柔和阴影。内容用 .body 包。"""

    _all = []

    def __init__(self, parent, pad=18, radius=14, **pack):
        try:
            bg = parent.cget("bg")
        except Exception:
            bg = BG
        super().__init__(parent, bg=bg, highlightthickness=0, bd=0)
        self.pad, self.radius = pad, radius
        Card._all.append(self)
        self._drawing = False
        px = pack.get("padx", 0)
        self._padx = px if isinstance(px, int) else 0
        self.body = tk.Frame(self, bg=CARD)
        self.win = self.create_window(pad, pad, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self._redraw())
        if pack:
            self.pack(**pack)
        # Canvas 宽高与内容互相依赖，靠父容器宽度驱动，避免撑不开
        parent.bind("<Configure>", self._sync_width, add="+")
        self.after_idle(self._redraw)

    def _sync_width(self, event):
        w = max(event.width - self._padx * 2, 320)   # 保底宽度，按钮不被挤出
        if abs(w - self.winfo_width()) > 1:
            self.configure(width=w)
            self._redraw(w)      # 显式传入宽度，此刻 winfo_width 还是旧值

    @classmethod
    def relayout_all(cls):
        """首帧兜底重排：卡片创建时父容器宽度可能还没算出来"""
        for c in cls._all:
            try:
                if c.winfo_exists():
                    c._redraw()
            except tk.TclError:
                pass

    def _redraw(self, w=None):
        if self._drawing:
            return
        if w is None:
            w = self.winfo_width()
            if w <= 20:                  # 自身还没布局好，回退用父容器宽度
                try:
                    w = max(self.master.winfo_width() - self._padx * 2, 320)
                except Exception:
                    w = 0
        h = self.body.winfo_reqheight() + self.pad * 2 + 4
        if w <= 20 or h <= self.pad * 2:
            return
        self._drawing = True
        if abs(w - self.winfo_width()) > 1:
            self.configure(width=w)
        self.configure(height=h)
        self.delete("cardbg")
        round_polygon(self, 3, 4, w - 1, h - 1, self.radius,
                      fill=SHADOW, outline="", tags="cardbg")
        round_polygon(self, 3, 3, w - 3, h - 3, self.radius,
                      fill=CARD, outline=BORDER, tags="cardbg")
        self.itemconfig(self.win, width=max(w - self.pad * 2 - 6, 10))
        self.tag_raise(self.win)
        self._drawing = False


def hover(widget, normal, active, fg=None, fg_active=None):
    fg = fg or "white"
    fg_active = fg_active or fg
    widget.bind("<Enter>", lambda e: widget.configure(bg=active, fg=fg_active))
    widget.bind("<Leave>", lambda e: widget.configure(bg=normal, fg=fg))


def scrolled(parent):
    """带鼠标滚轮的滚动容器，返回 (outer, inner)；卡片 pack 到 inner。"""
    outer = tk.Frame(parent, bg=BG)
    canvas = tk.Canvas(outer, bg=BG, highlightthickness=0, bd=0)
    vsb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview,
                       bg=BG, bd=0, width=9, troughcolor=BG,
                       activebackground="#c8d1dc")
    inner = tk.Frame(canvas, bg=BG)
    inner.bind("<Configure>", lambda e: canvas.configure(
        scrollregion=canvas.bbox("all")))
    win = canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=vsb.set)
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))

    def _wheel(e):
        canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
    canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
    canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
    canvas.pack(side="left", fill="both", expand=True)
    return outer, inner, vsb


class App:
    def __init__(self, root):
        self.root = root
        root.title("校园网助手")
        root.geometry("940x660")
        root.minsize(840, 560)
        root.configure(bg=BG)

        self.log_q = queue.Queue()
        self.running = threading.Event()
        self.mon_thread = None
        self._busy = False

        tkfont.nametofont("TkDefaultFont").configure(
            family="Microsoft YaHei UI", size=10)
        self.f_big = tkfont.Font(family="Microsoft YaHei UI", size=19, weight="bold")
        self.f_h2 = tkfont.Font(family="Microsoft YaHei UI", size=12, weight="bold")
        self.f_body = tkfont.Font(family="Microsoft YaHei UI", size=10)
        self.f_small = tkfont.Font(family="Microsoft YaHei UI", size=9)
        self.f_logo = tkfont.Font(family="Microsoft YaHei UI", size=14, weight="bold")

        self._build_sidebar()
        self.body = tk.Frame(root, bg=BG)
        self.body.pack(side="left", fill="both", expand=True)

        self.pages = {}
        self._build_page_overview()
        self._build_page_accounts()
        self._build_page_school()
        self._build_page_logs()

        self._load_saved_accounts()
        self._poll_log()
        self.refresh_status()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(120, Card.relayout_all)   # 首帧卡片尺寸兜底
        root.after(400, Card.relayout_all)   # 二次兜底，避免与布局事件竞态

        if portal.is_placeholder(CFG):
            self._show("school")
            self.log("[提示] 首次使用：请先在「学校设置」填写你学校的门户地址与端口，保存后重启程序。")
        else:
            self._show("overview")

    # ================================================== 侧栏

    def _build_sidebar(self):
        bar = tk.Frame(self.root, bg=CARD, width=200)
        bar.pack(side="left", fill="y")
        bar.pack_propagate(False)
        tk.Frame(bar, bg=BORDER, width=1).place(relx=1, rely=0, relheight=1, anchor="ne")

        head = tk.Frame(bar, bg=CARD)
        head.pack(fill="x", pady=(26, 10))
        icon = tk.Canvas(head, width=30, height=30, bg=CARD, highlightthickness=0)
        icon.pack(side="left", padx=(22, 10))
        for i, (r, col) in enumerate(((12, PRIMARY), (8, PRIMARY), (4, "#5eead4"))):
            icon.create_oval(15 - r, 15 - r, 15 + r, 15 + r, outline="", fill=col)
        tk.Label(head, text="校园网助手", bg=CARD, fg=TEXT, font=self.f_logo)\
            .pack(side="left")

        self.nav = {}
        for key, label in (("overview", "网络概览"),
                           ("accounts", "账号管理"),
                           ("school", "学校设置"),
                           ("logs", "运行日志")):
            row = tk.Frame(bar, bg=CARD)
            row.pack(fill="x", pady=1)
            ind = tk.Frame(row, bg=CARD, width=4, height=40)
            ind.pack(side="left", fill="y")
            b = tk.Button(row, text=label, font=self.f_h2, bd=0, bg=CARD, fg=TEXT,
                          anchor="w", padx=20, pady=11, cursor="hand2",
                          activebackground=PRIMARY_BG, activeforeground=PRIMARY_DARK,
                          command=lambda k=key: self._show(k))
            b.pack(side="left", fill="x", expand=True)
            self.nav[key] = (ind, b)

        foot = tk.Frame(bar, bg=CARD)
        foot.pack(side="bottom", fill="x", pady=14)
        tk.Label(foot, text="● 本地运行", bg=CARD, fg=MUTED,
                 font=self.f_small).pack(anchor="w", padx=24)
        tk.Label(foot, text="账号密码加密保存", bg=CARD, fg=MUTED,
                 font=self.f_small, wraplength=158).pack(anchor="w", padx=24)
        tk.Label(foot, text="v1.0 · MIT", bg=CARD, fg=MUTED,
                 font=self.f_small).pack(anchor="w", padx=24)

    def _show(self, key):
        for k, (ind, b) in self.nav.items():
            on = (k == key)
            ind.configure(bg=PRIMARY if on else CARD)
            b.configure(bg=PRIMARY_BG if on else CARD,
                        fg=PRIMARY_DARK if on else TEXT)
        self.pages[key].tkraise()
        if key == "logs":
            self.txt_logs.yview("end")

    def _header(self, p, title, sub):
        tk.Label(p, text=title, bg=BG, fg=TEXT, font=self.f_big)\
            .pack(anchor="w", padx=30, pady=(26, 3))
        tk.Label(p, text=sub, bg=BG, fg=MUTED, font=self.f_small)\
            .pack(anchor="w", padx=30)

    # ================================================== 概览页

    def _build_page_overview(self):
        p = tk.Frame(self.body, bg=BG)
        p.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.pages["overview"] = p
        self._header(p, "网络概览", "检测外网连通情况，掉线后按默认运营商自动重新认证。")

        c1 = Card(p, padx=30, pady=(20, 0), fill="x")
        inner = tk.Frame(c1.body, bg=CARD)
        inner.pack(fill="x", pady=4)
        self.cv_dot = tk.Canvas(inner, width=52, height=52, bg=CARD,
                                highlightthickness=0)
        self.cv_dot.pack(side="left", padx=(6, 16))
        self._draw_dot(MUTED)
        col = tk.Frame(inner, bg=CARD)
        col.pack(side="left", fill="x", expand=True)
        self.lb_status = tk.Label(col, text="检测中…", bg=CARD, fg=TEXT,
                                  font=self.f_big, anchor="w")
        self.lb_status.pack(anchor="w")
        self.lb_detail = tk.Label(col, text="", bg=CARD, fg=MUTED,
                                  font=self.f_small, anchor="w")
        self.lb_detail.pack(anchor="w")

        btns = tk.Frame(inner, bg=CARD)
        btns.pack(side="right", padx=6)
        self.btn_conn = tk.Button(btns, text="立即连接", font=self.f_h2, bd=0,
                                  bg=PRIMARY, fg="white", padx=20, pady=7,
                                  cursor="hand2", command=self.on_connect)
        self.btn_conn.pack(side="left", padx=(0, 10))
        hover(self.btn_conn, PRIMARY, PRIMARY_DARK)
        b2 = tk.Button(btns, text="刷新", font=self.f_small, bd=0, bg=FIELD,
                       fg=PRIMARY_DARK, padx=12, pady=8, cursor="hand2",
                       command=self.refresh_status)
        b2.pack(side="left")
        hover(b2, FIELD, PRIMARY_BG, PRIMARY_DARK, PRIMARY_DARK)

        c2 = Card(p, padx=30, pady=(16, 0), fill="x")
        inner2 = tk.Frame(c2.body, bg=CARD)
        inner2.pack(fill="x", pady=4)
        col2 = tk.Frame(inner2, bg=CARD)
        col2.pack(side="left", fill="x", expand=True)
        tk.Label(col2, text="自动连接与认证", bg=CARD, fg=TEXT,
                 font=self.f_h2).pack(anchor="w")
        tk.Label(col2, text="发现掉线后，自动使用默认运营商的账号重新认证。",
                 bg=CARD, fg=MUTED, font=self.f_small).pack(anchor="w", pady=(2, 0))
        self.btn_mon = tk.Button(inner2, text="开启守护", font=self.f_small, bd=0,
                                 bg=PRIMARY_BG, fg=PRIMARY_DARK, padx=16, pady=7,
                                 cursor="hand2", command=self.on_toggle_mon)
        self.btn_mon.pack(side="right", padx=6)
        hover(self.btn_mon, PRIMARY_BG, PRIMARY)

        self.lb_param = tk.Label(p, text="", bg=BG, fg=MUTED, font=self.f_small)
        self.lb_param.pack(anchor="w", padx=38, pady=(16, 0))

    def _draw_dot(self, color):
        c = self.cv_dot
        c.delete("all")
        c.create_oval(4, 4, 48, 48, outline=color, width=2)
        c.create_oval(15, 15, 37, 37, fill=color, outline=color)

    # ================================================== 账号页

    def _build_page_accounts(self):
        p = tk.Frame(self.body, bg=BG)
        p.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.pages["accounts"] = p
        self._header(p, "账号管理",
                     "每个运营商可填不同的账号密码；选中的为默认运营商（立即连接和守护都用它）。")

        outer, inner, vsb = scrolled(p)
        outer.pack(fill="both", expand=True, pady=(14, 0))
        vsb.pack(side="right", fill="y")

        self.var_default = tk.StringVar(value=CARRIERS[0])
        self.acc_widgets = {}
        for carrier in CARRIERS:
            c = Card(inner, padx=30, pady=(16, 0), fill="x")
            box = tk.Frame(c.body, bg=CARD)
            box.pack(fill="x", pady=4)
            tk.Radiobutton(box, text=carrier, value=carrier,
                           variable=self.var_default, bg=CARD, fg=TEXT,
                           selectcolor=CARD, activebackground=CARD,
                           font=self.f_h2, cursor="hand2",
                           command=self.on_pick_default).pack(anchor="w")

            grid = tk.Frame(box, bg=CARD)
            grid.pack(fill="x", pady=(10, 0))
            # 两列输入框等宽拉伸；按钮列固定宽，窄窗口也不会被挤出
            grid.columnconfigure(0, weight=1, uniform="acct")
            grid.columnconfigure(1, weight=1, uniform="acct")
            tk.Label(grid, text="账号", bg=CARD, fg=MUTED,
                     font=self.f_small).grid(row=0, column=0, sticky="w")
            e_user = tk.Entry(grid, width=16, relief="flat", bg=FIELD,
                              highlightbackground=BORDER, highlightcolor=PRIMARY,
                              highlightthickness=1, font=("Microsoft YaHei UI", 10))
            e_user.grid(row=1, column=0, sticky="ew", padx=(0, 16),
                        pady=(3, 0), ipady=6)
            tk.Label(grid, text="密码", bg=CARD, fg=MUTED,
                     font=self.f_small).grid(row=0, column=1, sticky="w")
            e_pass = tk.Entry(grid, width=16, show="•", relief="flat", bg=FIELD,
                              highlightbackground=BORDER, highlightcolor=PRIMARY,
                              highlightthickness=1, font=("Microsoft YaHei UI", 10))
            e_pass.grid(row=1, column=1, sticky="ew", padx=(0, 16),
                        pady=(3, 0), ipady=6)
            self.acc_widgets[carrier] = {"user": e_user, "pass": e_pass}

            def _save(cr=carrier):
                self.on_save_account(cr)
            bs = tk.Button(grid, text="保存", font=self.f_small, bd=0,
                           bg=PRIMARY_BG, fg=PRIMARY_DARK, padx=16, pady=6,
                           cursor="hand2", command=_save)
            bs.grid(row=1, column=2, pady=(3, 0), sticky="e")
            hover(bs, PRIMARY_BG, PRIMARY, PRIMARY_DARK, "white")
            self.acc_widgets[carrier]["btn"] = bs

        tk.Label(inner, text="多人共用一台电脑时，各自在对应运营商下填自己的账号即可，互不覆盖。",
                 bg=BG, fg=MUTED, font=self.f_small).pack(anchor="w", padx=36, pady=18)

    # ================================================== 学校设置页

    def _build_page_school(self):
        p = tk.Frame(self.body, bg=BG)
        p.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.pages["school"] = p
        self._header(p, "学校设置",
                     "这些参数保存在 config.json（不会进 git 仓库），校友各自填自己学校的即可。")

        c = Card(p, padx=30, pady=(20, 0), fill="x")
        box = tk.Frame(c.body, bg=CARD)
        box.pack(fill="x", pady=4)

        self.v_host = tk.StringVar(value=CFG.get("portal_host", ""))
        self.v_port = tk.StringVar(value=str(CFG.get("portal_port", 801)))
        self.v_acip = tk.StringVar(value=CFG.get("default_ac_ip", ""))
        self.v_on = tk.StringVar(value=str(CFG.get("online_interval", 300)))
        self.v_off = tk.StringVar(value=str(CFG.get("offline_interval", 15)))

        fields = [("门户地址", self.v_host, "校园网认证页 IP，如 10.x.x.x"),
                  ("端口", self.v_port, "新版 ePortal 一般是 801"),
                  ("AC IP", self.v_acip, "抓包跳转地址里的 wlanacip，可留空"),
                  ("在线探测间隔(秒)", self.v_on, "联网时多久检查一次"),
                  ("离线重连间隔(秒)", self.v_off, "掉线时多久重试一次")]
        for i, (label, var, hint) in enumerate(fields):
            row = tk.Frame(box, bg=CARD)
            row.pack(fill="x", pady=(6 if i else 0, 6))
            # 提示列固定换行宽，输入框列拉伸填满剩余宽度
            row.columnconfigure(1, weight=1)
            tk.Label(row, text=label, bg=CARD, fg=TEXT, font=self.f_body,
                     width=16, anchor="w").grid(row=0, column=0, sticky="w")
            tk.Entry(row, textvariable=var, width=14, relief="flat", bg=FIELD,
                     highlightbackground=BORDER, highlightcolor=PRIMARY,
                     highlightthickness=1, font=("Microsoft YaHei UI", 10))\
                .grid(row=0, column=1, sticky="ew", ipady=5, padx=(0, 14))
            tk.Label(row, text=hint, bg=CARD, fg=MUTED, wraplength=170,
                     justify="left", font=self.f_small)\
                .grid(row=0, column=2, sticky="w")

        tk.Label(box, text="运营商账号模板（JSON，{user} 替换为账号）", bg=CARD,
                 fg=TEXT, font=self.f_body).pack(anchor="w", pady=(10, 4))
        self.txt_tpl = scrolledtext.ScrolledText(
            box, height=6, bg=FIELD, fg=TEXT, bd=0, font=("Consolas", 10),
            highlightbackground=BORDER, highlightcolor=PRIMARY,
            highlightthickness=1, padx=10, pady=8)
        self.txt_tpl.pack(fill="x")
        self.txt_tpl.insert("1.0", json.dumps(CFG.get("carriers", {}),
                                              ensure_ascii=False, indent=2))

        acts = tk.Frame(box, bg=CARD)
        acts.pack(fill="x", pady=(14, 0))
        bs = tk.Button(acts, text="保存学校设置", font=self.f_h2, bd=0, bg=PRIMARY,
                       fg="white", padx=20, pady=7, cursor="hand2",
                       command=self.on_save_school)
        bs.pack(side="left")
        hover(bs, PRIMARY, PRIMARY_DARK)
        tk.Label(acts, text="保存后重启程序生效", bg=CARD, fg=MUTED,
                 font=self.f_small).pack(side="left", padx=14)

    # ================================================== 日志页

    def _build_page_logs(self):
        p = tk.Frame(self.body, bg=BG)
        p.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.pages["logs"] = p

        top = tk.Frame(p, bg=BG)
        top.pack(fill="x", padx=30, pady=(26, 12))
        tk.Label(top, text="运行日志", bg=BG, fg=TEXT,
                 font=self.f_big).pack(side="left")
        bc = tk.Button(top, text="清空", font=self.f_small, bd=0, bg=FIELD,
                       fg=MUTED, padx=12, pady=6, cursor="hand2",
                       command=self._clear_logs)
        bc.pack(side="right")
        hover(bc, FIELD, PRIMARY_BG, MUTED, PRIMARY_DARK)

        wrap = Card(p, padx=30, pady=(0, 26), fill="both", expand=True)
        self.txt_logs = scrolledtext.ScrolledText(
            wrap.body, bg=CARD, fg=TEXT, bd=0, font=("Consolas", 9),
            state="disabled", padx=10, pady=8, spacing1=2, spacing3=2)
        self.txt_logs.pack(fill="both", expand=True)

    def _clear_logs(self):
        self.txt_logs.configure(state="normal")
        self.txt_logs.delete("1.0", "end")
        self.txt_logs.configure(state="disabled")

    def log(self, s):
        self.log_q.put(s)

    def _poll_log(self):
        while not self.log_q.empty():
            self.txt_logs.configure(state="normal")
            self.txt_logs.insert("end", self.log_q.get_nowait() + "\n")
            self.txt_logs.see("end")
            self.txt_logs.configure(state="disabled")
        self.root.after(300, self._poll_log)

    # ================================================== 账号逻辑

    def _load_saved_accounts(self):
        creds = portal.load_creds()
        accounts = creds.get("accounts", {})
        for carrier in CARRIERS:
            acc = accounts.get(carrier, {})
            if acc.get("user"):
                self.acc_widgets[carrier]["user"].insert(0, acc["user"])
            pw = secure_store.load_account_password(carrier)
            if pw:
                self.acc_widgets[carrier]["pass"].insert(0, pw)
        default = creds.get("active_carrier")
        if default in CARRIERS:
            self.var_default.set(default)

    def on_save_account(self, carrier):
        user = self.acc_widgets[carrier]["user"].get().strip()
        password = self.acc_widgets[carrier]["pass"].get()
        creds = portal.load_creds()
        creds.setdefault("accounts", {}).setdefault(carrier, {})["user"] = user
        portal.save_creds(creds)
        secure_store.save_account_password(carrier, password)
        self.log("[%s] 已保存「%s」的账号信息（密码已加密）"
                 % (time.strftime("%H:%M:%S"), carrier))

    def on_pick_default(self):
        creds = portal.load_creds()
        creds["active_carrier"] = self.var_default.get()
        portal.save_creds(creds)
        self.log("[%s] 默认运营商已切换为：%s"
                 % (time.strftime("%H:%M:%S"), self.var_default.get()))

    def on_save_school(self):
        try:
            carriers = json.loads(self.txt_tpl.get("1.0", "end"))
            if not isinstance(carriers, dict):
                raise ValueError
        except Exception:
            self.log("[%s] 运营商模板不是合法 JSON 对象，未保存"
                     % time.strftime("%H:%M:%S"))
            return
        try:
            cfg = {
                "portal_host": self.v_host.get().strip(),
                "portal_port": int(self.v_port.get()),
                "default_ac_ip": self.v_acip.get().strip(),
                "probe_timeout": CFG.get("probe_timeout", 4),
                "online_interval": int(self.v_on.get()),
                "offline_interval": int(self.v_off.get()),
                "carriers": carriers,
            }
        except ValueError:
            self.log("[%s] 端口 / 间隔必须是数字，未保存" % time.strftime("%H:%M:%S"))
            return
        portal.save_json(portal.CONFIG_PATH, cfg)
        self.log("[%s] 学校设置已保存，重启程序后生效" % time.strftime("%H:%M:%S"))

    # ================================================== 动作

    def refresh_status(self):
        def task():
            online = portal.check_online()
            ip = portal.get_local_ip()
            try:
                self.root.after(0, lambda: self._apply_status(online, ip))
            except tk.TclError:
                pass
        threading.Thread(target=task, daemon=True).start()

    def _apply_status(self, online, ip):
        if online:
            self._draw_dot(GREEN)
            self.lb_status.configure(text="已连接外网", fg=GREEN)
            self.lb_detail.configure(text="本机 IP %s · 认证门户 %s:%s"
                                          % (ip, CFG.get("portal_host"),
                                             CFG.get("portal_port")))
        else:
            self._draw_dot(RED)
            self.lb_status.configure(text="未认证或已离线", fg=RED)
            self.lb_detail.configure(text="点击「立即连接」完成认证")
        self.lb_param.configure(
            text="探测间隔：在线 %ss / 离线 %ss · 掉线自动重连已%s"
                 % (CFG.get("online_interval", 300),
                    CFG.get("offline_interval", 15),
                    "开启" if self.running.is_set() else "关闭"))

    def _active_creds(self):
        carrier = self.var_default.get()
        user = self.acc_widgets[carrier]["user"].get().strip()
        password = self.acc_widgets[carrier]["pass"].get()
        if not password:
            password = secure_store.load_account_password(carrier)
        return user, password, carrier

    def on_connect(self):
        if self._busy:
            return
        if portal.is_placeholder(CFG):
            self.log("[%s] 请先在「学校设置」填写门户地址，保存后重启程序"
                     % time.strftime("%H:%M:%S"))
            return
        user, password, carrier = self._active_creds()
        if not user:
            self.log("[%s] 请先在「账号管理」填写默认运营商的账号"
                     % time.strftime("%H:%M:%S"))
            return
        self._busy = True
        self.btn_conn.configure(text="认证中…", state="disabled")

        def task():
            ok, msg = portal.do_login(user, password, carrier, CFG, self.log)
            self.log("登录%s：%s" % ("成功" if ok else "失败", msg))
            online = portal.check_online()
            self.log("外网连通：%s" % ("是" if online else "否"))

            def done():
                self._busy = False
                self.btn_conn.configure(text="立即连接", state="normal")
                self._apply_status(online, portal.get_local_ip())
            try:
                self.root.after(0, done)
            except tk.TclError:
                pass
        threading.Thread(target=task, daemon=True).start()

    def on_toggle_mon(self):
        if self.running.is_set():
            self.running.clear()
            self.btn_mon.configure(text="开启守护", bg=PRIMARY_BG, fg=PRIMARY_DARK)
            hover(self.btn_mon, PRIMARY_BG, PRIMARY, PRIMARY_DARK, "white")
            self.log("守护已停止")
            self.refresh_status()
            return
        user, password, carrier = self._active_creds()
        if not user or not password:
            self.log("[%s] 开启守护前，请先填写默认运营商的账号密码并点保存"
                     % time.strftime("%H:%M:%S"))
            return
        self.on_save_account(carrier)
        creds = portal.load_creds()
        creds["active_carrier"] = carrier
        portal.save_creds(creds)
        self.running.set()
        self.btn_mon.configure(text="停止守护", bg="#fdecec", fg=RED)
        hover(self.btn_mon, "#fdecec", "#fbd5d5", RED, RED)
        self.mon_thread = threading.Thread(
            target=portal.monitor_loop,
            args=(CFG, portal.read_active_creds, self.running, self.log),
            daemon=True)
        self.mon_thread.start()
        self.log("[%s] 守护已启动（默认运营商：%s）"
                 % (time.strftime("%H:%M:%S"), carrier))
        self.refresh_status()

    def on_close(self):
        self.running.clear()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
