# 校园网助手（Campus Connect）

面向 **Dr.COM / 新版 ePortal（`GET :801/eportal/portal/login` JSONP 接口）** 校园网的
自动认证工具。纯 Python 标准库，**零第三方依赖**，带图形界面。

> ⚠️ 免责声明：本工具只自动化你自己账号的网页登录流程，不含任何破解或绕过行为。
> 是否允许使用请遵守所在学校网络管理规定，后果自负。

## 界面

左侧导航 + 卡片布局，四个页面：

| 页面 | 内容 |
|---|---|
| 网络概览 | 实时网络状态（绿点=已连接外网 / 红点=未认证），立即连接、刷新、自动守护开关 |
| 账号管理 | **每个运营商一组独立的账号密码**，可指定默认运营商 |
| 学校设置 | 门户地址、端口、AC IP、探测间隔、运营商账号模板 |
| 运行日志 | 认证与守护的全部记录，可清空 |

不同用户在同一台电脑上使用时，各自在对应运营商下填自己的账号即可，互不覆盖。

## 运行

```
python gui.py
```

需要**带 tkinter 的 Python**（官方安装包默认自带；精简版会报
`ModuleNotFoundError: No module named 'tkinter'`，换官方安装版即可）。

Windows 也可以直接双击 **`启动助手.bat`**（内部用 `cd /d "%~dp0"` 定位，路径含中文也没问题）。

高分屏下界面清晰：程序启动时会声明 DPI 感知（`SetProcessDpiAwareness`），
不声明的话 Windows 会把窗口拉伸放大，看起来发虚。

## 隐私设计：学校地址不会进仓库

工具把「学校专属参数」和「个人凭据」都放在**不入库**的文件里：

| 文件 | 是否入库 | 内容 |
|---|---|---|
| `config.example.json` | ✅ 入库 | 示例参数，占位地址 `10.0.0.1` |
| `config.json` | ❌ 不入库 | 你学校真实的门户地址、端口、运营商模板 |
| `credentials.json` | ❌ 不入库 | 你的账号与加密密码 |

两者都写进了 `.gitignore`。程序首次运行时会自动用 `config.example.json` 生成一份
`config.json`，并跳到「学校设置」页提示填写。所以：

- **公开仓库里不含任何学校内网地址**，校友克隆下来后各自填自己学校的参数
- 想直接给校友用，把你的 `config.json` 私发给他即可

## 文件说明

| 文件 | 用途 |
|---|---|
| `gui.py` | 图形界面主入口 |
| `daemon.py` | 无界面守护（Termux / 计划任务用） |
| `portal.py` | 协议核心库（连通检测、登录、守护循环） |
| `secure_store.py` | 按运营商的密码 DPAPI 加密存储 |
| `config.example.json` | 示例学校参数（入库） |
| `config.json` | 真实学校参数（运行时生成，不入库） |
| `credentials.json` | 个人账号密码（运行时生成，不入库） |

## 账号与密码怎么存

密码在 Windows 上用 **DPAPI** 加密（`CryptProtectData`），绑定当前系统用户，
换个用户或换台机器就读不出来；`credentials.json` 里只有密文。

## 适配其他学校

打开「学校设置」页填写即可，不用手改文件：

- **门户地址 / 端口**：校园网认证页的 IP，新版 ePortal 一般是 `801`
- **AC IP**：抓包跳转地址里的 `wlanacip`，可留空
- **运营商模板**：JSON 对象，`{user}` 会替换成你填的账号

```json
{
  "中国移动": ",0,{user}@yidong",
  "中国联通": ",0,{user}@unicom",
  "中国电信": ",0,{user}@telecom",
  "专用网络": ",0,{user}"
}
```

**只有中国电信的格式经过抓包验证**，其余按同类学校惯例推测。若某运营商登录后提示
账号密码错误，用浏览器 F12 抓一次该运营商的登录请求，把模板改成实际值。

## 开机自启（可选）

任务计划程序 → 创建基本任务 → 触发器「登录时」→ 操作「启动程序」：

- 程序：`pythonw.exe` 的完整路径（`pythonw` 不弹黑窗口）
- 参数：`gui.py` 的完整路径
- 起始于：本目录

```
schtasks /Create /TN CampusLogin /SC ONLOGON /TR "pythonw.exe D:\path\to\gui.py" /F
```

## Android（Termux）

1. 装 Termux（F-Droid 版），`pkg install python`
2. 拷贝整个目录，手机上看不到图形界面，用无界面守护：`python daemon.py`
   （后台：`nohup python daemon.py &`）
3. 在系统设置里给 Termux 关掉电池优化，否则后台会被杀

## iPad（快捷指令，只能手动）

iPadOS 不允许后台常驻，做不到自动重连，只能做一个「快捷指令」按钮：

```
http://<门户地址>:801/eportal/portal/login?callback=dr1003&login_method=1&user_account=%2C0%2C学号%40telecom&user_password=密码&wlan_user_ip=&wlan_user_ipv6=&wlan_user_mac=000000000000&wlan_ac_ip=<AC IP>&wlan_ac_name=&jsVersion=4.2.1&terminal_type=1&lang=zh-cn&v=12345
```

掉线时下拉点一下即可。若提示参数错误，先用 Safari 打开任意网页让它跳到 `a79.htm`，
把跳转地址里 `userip=` 后面的 IP 填进 `wlan_user_ip=` 再试。

## 其他提醒

- 抓包截图里**密码是明文**的，外发前务必打码。
- 门户地址属于局域网私有地址，但既然要分享给校友，填进 `config.json` 就够了——
  不要写进 README 或示例代码。

## 许可

MIT License
