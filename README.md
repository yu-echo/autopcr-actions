<div align="center">
  <h1>autopcr · GitHub Actions 部署</h1>
  <img alt="platform" src="https://img.shields.io/badge/platform-GitHub%20Actions-blueviolet">
  <img alt="python" src="https://img.shields.io/badge/Python-3.10-3776AB?logo=python&logoColor=white">
  <img alt="core" src="https://img.shields.io/badge/核心-cc004%2Fautopcr-orange">
</div>

---

把 [cc004/autopcr](https://github.com/cc004/autopcr) 搬到 GitHub Actions 上：
**不用开电脑、不用挂模拟器、不用常驻服务**，每天定时跑一遍公主连结的日常，结果推到微信。

---

## 它是怎么跑的

```
每天 08:00（北京时间）
    ↓
拉取 autopcr 最新版 → 装依赖 → 下载游戏数据
    ↓
从 GitHub Secrets 注入你的账号凭据（只存在于内存与 Secret）
    ↓
登录 B服（验证码由 gtlv 本地自动识别）
    ↓
执行日常 → 汇总结果 → PushPlus 推微信
```

核心脚本是仓库根目录的 `run_once.py`：把 autopcr 的 Web 面板模式改成
「跑一次就退出」，其余逻辑完全复用 autopcr 本体。

---

## 配置（4 个 Secret，约 2 分钟）

`Settings → Secrets and variables → Actions → New repository secret`：

| Secret | 必填 | 说明 |
| --- | --- | --- |
| `AUTOPCR_QID` | ✅ | 面板账号，**纯数字**（手机号或 QQ 号，5~12 位）。只是个标识，随便填数字也行 |
| `BILI_USERNAME` | ✅ | **B站登录账号**（手机号） |
| `BILI_PASSWORD` | ✅ | **B站登录密码** |
| `PUSHPLUS_TOKEN` | ⭕ | 配了才推微信，不配只写日志 |

可选：在 `Settings → Variables` 加一个 `AUTOPCR_ALIAS` 指定角色别名（默认 `main`）。

配完到 `Actions → autopcr 日常 → Run workflow` 手动触发一次。
建议第一次勾上 **dry_run**，只验证环境与登录，不真跑日常。

---

## 脱敏与安全

这个仓库是公开的，所以凭据处理遵循以下原则：

| 做法 | 说明 |
| --- | --- |
| 🔒 **凭据只进 Secret** | `BILI_USERNAME` / `BILI_PASSWORD` 仅由 workflow 注入环境变量，从不写入仓库文件 |
| 🚫 **不使用 Actions cache 存账号数据** | autopcr 的账号文件里是**明文 B站账密**，而公开仓库的 cache 对能触发 workflow 的人可读 → 因此每次运行都从 Secret 重新注入，不落缓存 |
| 🚫 **不上传 artifact** | 结果文件名含面板账号与角色名、日志可能含账号片段，公开仓库的 artifact 任何登录用户可下载 → 结果只走微信推送 |
| 🙈 **控制台输出脱敏** | `run_once.py` 打印的账号只留首尾（`1380***0000`），密码只报长度，从不打印内容 |
| 🧹 **不外传接口响应** | autopcr 自带 `sanitize_payload()`，打印前抹掉 token 类字段 |

> ⚠️ **Actions 日志在公开仓库中对任何登录 GitHub 的用户可见。**
> 因此脚本里所有的账号输出都做了脱敏 —— 如果你要改脚本，请保持这一点。

---

## 常见问题

### 第一次运行失败，提示缺少 Secret
正常 —— 说明还没配凭据。按上面的表格配好即可。

### 登录失败 / 提示验证码错误
autopcr 用 `gtlv` 自动识别极验验证码，偶尔会失败。重跑一次通常就好。
如果连续失败，检查 B站密码是否正确（很多人平时用验证码登录，早忘了密码）。

### 为什么每次都要重新登录，不能缓存 session？
出于安全 —— autopcr 的 session 与账号文件里含明文账密，
缓存到 Actions cache 会让公开仓库的凭据暴露面变大。
代价是每次多花十几秒登录，这个取舍是刻意的。

### 执行日志里看不到任务明细
明细会被汇总成中文清单推到微信。
想看得更细，就用 `workflow_dispatch` 手动触发并观察控制台输出（已脱敏）。

### 每日执行时间
`cron: '0 0 * * *'`（UTC）= 北京时间 **08:00**。
GitHub 的定时任务可能延迟几分钟到几十分钟，属正常现象。

---

## 说明

- 核心功能来自 [cc004/autopcr](https://github.com/cc004/autopcr)（ISC）。
  本仓库只提供 Actions 包装脚本与工作流，不含 autopcr 源码本体，每次运行时动态拉取最新版。
- 游戏自动化可能违反游戏服务条款，请自行评估风险，建议用小号。
- 本项目为个人自动化配置，未声明为通用工具；如需复用请自行确认合规性。
