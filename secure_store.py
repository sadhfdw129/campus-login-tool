# -*- coding: utf-8 -*-
"""多账号密码加密存储：按运营商分别保存。
Windows 下用 DPAPI（绑定当前系统用户），其他平台明文 + 权限收紧。"""
import base64
import ctypes
import os
import sys

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _to_blob(data):
        buf = ctypes.create_string_buffer(data, len(data))
        return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def dpapi_protect(plain: str) -> str:
    data = plain.encode("utf-8")
    out = _BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(_to_blob(data)), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("CryptProtectData 失败")
    try:
        enc = ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)
    return base64.b64encode(enc).decode("ascii")


def dpapi_unprotect(b64: str) -> str:
    enc = base64.b64decode(b64)
    out = _BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(_to_blob(enc)), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("CryptUnprotectData 失败（可能不是本机本用户加密的数据）")
    try:
        data = ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)
    return data.decode("utf-8")


def save_account_password(carrier: str, password: str):
    """加密保存某运营商的密码"""
    import portal
    creds = portal.load_creds()
    acc = creds.setdefault("accounts", {}).setdefault(carrier, {})
    acc.pop("password", None)
    if _IS_WINDOWS and password:
        acc["password_enc"] = dpapi_protect(password)
    else:
        acc["password"] = password  # Termux 等单用户环境
    portal.save_creds(creds)


def load_account_password(carrier: str) -> str:
    import portal
    acc = portal.load_creds().get("accounts", {}).get(carrier, {})
    if "password_enc" in acc:
        try:
            return dpapi_unprotect(acc["password_enc"])
        except OSError:
            return ""
    return acc.get("password", "")
