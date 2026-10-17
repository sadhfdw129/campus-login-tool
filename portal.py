# -*- coding: utf-8 -*-
"""校园网认证核心库（无界面，供 gui.py / daemon.py 共用）

协议：新版 ePortal JSONP 接口
  GET http://<host>:<port>/eportal/portal/login
      ?callback=dr1003&login_method=1
      &user_account=,0,<学号>@telecom
      &user_password=<明文密码>
      &wlan_user_ip=<本机IP>&wlan_user_ipv6=
      &wlan_user_mac=<MAC或000000000000>
      &wlan_ac_ip=<AC IP>&wlan_ac_name=
      &jsVersion=4.2.1&terminal_type=1&lang=zh-cn&v=<随机数>
返回：dr1003({"result":1,"msg":"...","valid":1})
"""
import json
import os
import random
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")
EXAMPLE_PATH = os.path.join(BASE, "config.example.json")
CRED_PATH = os.path.join(BASE, "credentials.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36")

# 用于判断是否真的连通外网（204 端点 + 内容校验端点，全部国内可达）
_PROBE_204 = [
    "http://connect.rom.miui.com/generate_204",
    "http://wifi.vivo.com.cn/generate_204",
]
_PROBE_BODY = "http://www.msftconnecttest.com/connecttest.txt"
_PROBE_BODY_MARK = "Microsoft Connect Test"
_PROBE_REDIRECT = "http://www.msftconnecttest.com/redirect"


# ---------------------------------------------------------------- 配置读写

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(path, 0o600)  # 非 Windows 生效；Windows 靠目录权限
    except OSError:
        pass


def is_placeholder(cfg):
    """配置还是示例占位值（未填写本校地址）"""
    host = cfg.get("portal_host", "")
    return not host or host.startswith("10.0.0.")


def load_config():
    """读取 config.json；不存在时用 config.example.json 生成一份。
    这样仓库里可以只放示例配置，不含任何学校真实内网地址。"""
    cfg = load_json(CONFIG_PATH, None)
    if cfg is None:
        cfg = load_json(EXAMPLE_PATH, {})
        if cfg:
            save_json(CONFIG_PATH, cfg)
    return cfg or {}


def load_creds():
    return load_json(CRED_PATH, {})


def read_active_creds():
    """读取默认运营商的 (user, password, carrier)，供 GUI/守护/后台共用。
    从文件读而不是从 UI 控件读，保证线程安全。"""
    import secure_store
    creds = load_creds()
    accounts = creds.get("accounts", {})
    carrier = creds.get("active_carrier")
    if carrier not in accounts and accounts:
        carrier = next(iter(accounts))
    carrier = carrier or "中国电信"
    acc = accounts.get(carrier, {})
    password = acc.get("password", "")
    if not password:
        password = secure_store.load_account_password(carrier)
    return acc.get("user", ""), password, carrier


def save_creds(creds):
    save_json(CRED_PATH, creds)


# ---------------------------------------------------------------- 网络检测

def get_local_ip():
    """取本机出口 IP（不真正发包）"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("223.5.5.5", 80))
        return s.getsockname()[0]
    except OSError:
        return "0.0.0.0"
    finally:
        s.close()


def check_online(timeout=None):
    """True = 已连通外网；False = 掉线 / 未认证 / 被劫持到门户"""
    if timeout is None:
        timeout = load_config().get("probe_timeout", 4)
    for url in _PROBE_204:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status == 204:
                    return True
        except Exception:
            continue
    try:
        req = urllib.request.Request(_PROBE_BODY, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(256).decode("utf-8", "ignore")
            if r.status == 200 and _PROBE_BODY_MARK in body:
                return True
    except Exception:
        pass
    return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get_portal_params(cfg=None, timeout=None):
    """未认证时，任意 http 请求会被 302 到门户页；从 Location 里提取
    userip / wlanacip / usermac。已在线或拿不到时返回尽力猜测的值。"""
    if cfg is None:
        cfg = load_config()
    if timeout is None:
        timeout = cfg.get("probe_timeout", 4)
    params = {}
    try:
        req = urllib.request.Request(_PROBE_REDIRECT, headers={"User-Agent": UA})
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            resp = opener.open(req, timeout=timeout)
            resp.close()  # 没被重定向，说明可能已在线
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location", "") if e.headers else ""
            e.close()
            if loc and ("usermac=" in loc or "wlanac" in loc):
                q = urllib.parse.urlparse(loc).query
                params = {k: v[0] for k, v in urllib.parse.parse_qs(q).items()}
    except Exception:
        pass
    # 兜底：拿不到就用本机 IP + 配置里的默认 AC IP
    params.setdefault("userip", get_local_ip())
    params.setdefault("wlanacip", cfg.get("default_ac_ip", ""))
    mac = params.get("usermac", "").replace("-", "").lower()
    params["usermac"] = mac if re.fullmatch(r"[0-9a-f]{12}", mac) else "000000000000"
    return params


# ---------------------------------------------------------------- 登录

def _jsonp_parse(text, callback="dr1003"):
    m = re.search(re.escape(callback) + r"\s*\((.*)\)\s*;?\s*$", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def build_login_url(cfg, user_account, password, params):
    q = {
        "callback": "dr1003",
        "login_method": "1",
        "user_account": user_account,
        "user_password": password,
        "wlan_user_ip": params.get("userip", ""),
        "wlan_user_ipv6": "",
        "wlan_user_mac": params.get("usermac", "000000000000"),
        "wlan_ac_ip": params.get("wlanacip", ""),
        "wlan_ac_name": params.get("wlanacname", ""),
        "jsVersion": "4.2.1",
        "terminal_type": "1",
        "lang": "zh-cn",
        "v": str(random.randint(10000, 99999)),
    }
    return "http://%s:%s/eportal/portal/login?%s" % (
        cfg.get("portal_host", "172.22.1.46"),
        cfg.get("portal_port", 801),
        urllib.parse.urlencode(q),
    )


def build_account(cfg, carrier, user):
    tpl = cfg.get("carriers", {}).get(carrier, ",0,{user}")
    return tpl.format(user=user)


def do_login(user, password, carrier, cfg=None, log=print):
    """执行一次认证，返回 (是否成功, 消息)"""
    if cfg is None:
        cfg = load_config()
    if not user or not password:
        return False, "账号或密码为空"
    account = build_account(cfg, carrier, user)
    params = get_portal_params(cfg)
    url = build_login_url(cfg, account, password, params)
    log("[%s] 认证中（运营商：%s）..." % (time.strftime("%H:%M:%S"), carrier))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "http://172.22.1.46/a79.htm"})
        with urllib.request.urlopen(req, timeout=cfg.get("probe_timeout", 4)) as r:
            text = r.read().decode("utf-8", "ignore")
    except Exception as e:
        return False, "请求失败：%s" % e
    data = _jsonp_parse(text)
    if data is None:
        return False, "响应无法解析（未认证网络异常？）：%s" % text[:120]
    ok = data.get("result") in (1, "1", "success", "ok")
    msg = str(data.get("msg", data))
    return ok, msg


# ---------------------------------------------------------------- 守护

def monitor_loop(cfg, creds_getter, running, log):
    """守护线程主体：掉线自动重连。
    creds_getter() -> (user, password, carrier)，便于 GUI 热更新凭据。"""
    off_iv = cfg.get("offline_interval", 15)
    on_iv = cfg.get("online_interval", 300)
    while running.is_set():
        if check_online(cfg.get("probe_timeout", 4)):
            log("[%s] 网络正常" % time.strftime("%H:%M:%S"))
            running.wait(on_iv)
            continue
        log("[%s] 检测到离线，尝试重新认证..." % time.strftime("%H:%M:%S"))
        user, password, carrier = creds_getter()
        ok, msg = do_login(user, password, carrier, cfg, log)
        log("[%s] %s" % (time.strftime("%H:%M:%S"), "重连成功" if ok else "重连失败：" + msg))
        running.wait(off_iv if ok else min(off_iv * 2, 120))
