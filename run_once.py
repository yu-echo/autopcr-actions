#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
autopcr 一次性执行脚本（供 GitHub Actions 使用）

用途：在 CI 环境里跑一遍「日常」，跑完即退出。
      本地 Web 面板模式请继续用 _httpserver_test.py。

凭据全部从环境变量读取（由 workflow 注入 GitHub Secrets），
不写入代码、不写入日志、不进 git 历史。

必需环境变量：
  AUTOPCR_QID        面板账号，纯数字（手机号或 QQ 号，5~12 位）
  BILI_USERNAME      B站账号（手机号）
  BILI_PASSWORD      B站密码

可选环境变量：
  AUTOPCR_ALIAS      角色别名，默认 main
  AUTOPCR_PASSWORD   面板用户密码（仅占位，不用于登录），默认自动生成
  AUTOPCR_CHANNEL    渠道，默认 bl（B服）
  PUSHPLUS_TOKEN     配了就推微信
  AUTOPCR_DRY_RUN    =1 时只检查环境与登录，不执行日常
"""
import asyncio
import datetime
import json
import os
import sys
import urllib.request
from collections import Counter

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from autopcr.constants import CACHE_DIR, RESULT_DIR, LOG_PATH, BSDK  # noqa: E402
from autopcr.module.accountmgr import UserManager, AccountException, UserException  # noqa: E402
from autopcr.module import accountmgr as am  # noqa: E402
from autopcr.util.logger import instance as logger  # noqa: E402

# ---------- 环境变量 ----------
QID = (os.environ.get('AUTOPCR_QID') or '').strip()
ALIAS = (os.environ.get('AUTOPCR_ALIAS') or 'main').strip()
BILI_USER = (os.environ.get('BILI_USERNAME') or '').strip()
BILI_PASS = (os.environ.get('BILI_PASSWORD') or '').strip()
USER_PASS = (os.environ.get('AUTOPCR_PASSWORD') or '').strip() or 'autopcr-ci-placeholder'
CHANNEL = (os.environ.get('AUTOPCR_CHANNEL') or BSDK).strip()
PUSHPLUS = (os.environ.get('PUSHPLUS_TOKEN') or '').strip()
DRY_RUN = os.environ.get('AUTOPCR_DRY_RUN') == '1'


def mask(value, keep=4):
    """脱敏：只留首尾，永不打印完整凭据"""
    if not value:
        return '(空)'
    if len(value) <= keep * 2:
        return '*' * len(value)
    return value[:keep] + '*' * (len(value) - keep * 2) + value[-keep:]


def die(msg, code=1):
    print(f'[FATAL] {msg}')
    sys.exit(code)


def push(title, content):
    """PushPlus 推送；未配置则只打印"""
    if not PUSHPLUS:
        print('[推送] 未配置 PUSHPLUS_TOKEN，跳过')
        return
    body = json.dumps({'token': PUSHPLUS, 'title': title, 'content': content,
                       'template': 'txt'}).encode('utf-8')
    req = urllib.request.Request('https://www.pushplus.plus/send', data=body,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read().decode('utf-8', 'replace'))
        ok = res.get('code') == 200
        print(f"[推送{'成功' if ok else '失败'}] {title}")
        if not ok:
            print('  ' + str(res.get('msg'))[:120])
    except Exception as e:
        print(f'[推送失败] {type(e).__name__}: {str(e)[:120]}')


def env_footer():
    """推送尾部：来源 + 运行记录（与签到脚本风格保持一致）"""
    lines = ['----------------------']
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        src = 'GitHub Actions'
        wf = os.environ.get('GITHUB_WORKFLOW')
        if wf:
            src += f' · {wf}'
        lines.append(f'来源：{src}')
        lines.append(
            '运行记录：%s/%s/actions/runs/%s' % (
                os.environ.get('GITHUB_SERVER_URL', 'https://github.com'),
                os.environ.get('GITHUB_REPOSITORY', ''),
                os.environ.get('GITHUB_RUN_ID', '')))
    else:
        lines.append('来源：本地运行')
    lines.append('运行时间：' + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    return '\n'.join(lines)


def summarize_result(path):
    """把结果 JSON 汇总成人能看的中文摘要"""
    try:
        data = json.load(open(path, encoding='utf-8'))
    except Exception as e:
        return None, f'(结果文件解析失败: {e})'

    res = data.get('result') or {}
    rows = [(v.get('status', '?'), v.get('name', k), (v.get('log') or '').replace('\n', ' / '))
            for k, v in res.items() if isinstance(v, dict)]
    stat = Counter(r[0] for r in rows)

    interesting = [r for r in rows if r[0] in ('成功', '警告', '错误')]
    lines = []
    if interesting:
        for st, name, log in interesting[:20]:
            icon = {'成功': '✅', '警告': '⚠️', '错误': '❌'}.get(st, '•')
            lines.append(f'{icon} {name}：{log[:70]}')

    warned = [r for r in rows if r[0] == '警告']
    summary = '  '.join(f'{k} {v}' for k, v in stat.most_common())
    return {
        'stat': summary,
        'lines': lines,
        'has_warn': bool(warned),
        'warn_lines': [f'{n}：{l[:80]}' for _, n, l in warned],
        'total': len(rows),
    }, None


async def main():
    # ---- 参数校验 ----
    missing = [k for k, v in (('AUTOPCR_QID', QID), ('BILI_USERNAME', BILI_USER),
                              ('BILI_PASSWORD', BILI_PASS)) if not v]
    if missing:
        die('缺少环境变量: ' + ', '.join(missing) + '（请在仓库 Secrets 里配置）')
    if not QID.isdigit() or not (5 <= len(QID) <= 12):
        die('AUTOPCR_QID 必须是 5~12 位纯数字')

    print('=' * 60)
    print('autopcr 一次性日常执行')
    print('=' * 60)
    print(f'  面板账号   : {mask(QID)}')
    print(f'  角色别名   : {ALIAS}')
    print(f'  B站账号    : {mask(BILI_USER)}')
    print(f'  B站密码    : {"已配置(%d位)" % len(BILI_PASS)}')
    print(f'  渠道       : {CHANNEL}')
    print(f'  推送       : {"已配置" if PUSHPLUS else "未配置"}')
    print(f'  模式       : {"仅检查(DRY_RUN)" if DRY_RUN else "执行日常"}')
    print()

    # ---- 用户与账号 ----
    usermgr = am.instance
    if QID not in usermgr.qids():
        usermgr.create(QID, USER_PASS)
        print(f'[初始化] 已创建面板用户 {mask(QID)}')
    else:
        print(f'[初始化] 面板用户已存在')

    async with usermgr.load(QID) as acctmgr:
        if ALIAS not in set(acctmgr.accounts()):
            acctmgr.create_account(ALIAS)
            print(f'[初始化] 已创建角色 {ALIAS}')
        else:
            print(f'[初始化] 角色 {ALIAS} 已存在')

        # 写入/更新游戏凭据
        acct = acctmgr.load(ALIAS)
        changed = (acct.data.username != BILI_USER
                   or acct.data.password != BILI_PASS
                   or acct.data.channel != CHANNEL)
        acct.data.username = BILI_USER
        acct.data.password = BILI_PASS
        acct.data.channel = CHANNEL
        if changed:
            print('[凭据] 已更新（内容不打印）')
        else:
            print('[凭据] 与上次一致')

    if DRY_RUN:
        print('[DRY_RUN] 环境与账号检查通过，未执行日常')
        return

    # ---- 执行日常 ----
    now = datetime.datetime.now()
    print(f'[执行] 开始跑日常 {now.strftime("%Y-%m-%d %H:%M:%S")}')
    print('-' * 60)

    # 初始化游戏数据库。
    # Web 面板模式下这是后台异步加载的，用户点运行时早就绪了；
    # 一次性脚本必须显式等待，否则 do_daily 会抛
    # ValueError: 数据库未初始化完成，请稍等片刻
    print('[初始化] 加载游戏数据库...')
    try:
        from autopcr.db.dbstart import db_start
        await db_start()
        print('[初始化] 数据库就绪')
    except Exception as e:
        err = f'{type(e).__name__}: {str(e)[:200]}'
        print(f'[失败] 数据库初始化失败: {err}')
        push('❌ autopcr 数据库初始化失败',
             f'无法加载游戏数据库：\n\n{err}\n\n'
             f'常见原因：数据资源未下载成功（_download_data.py 失败）。\n\n{env_footer()}')
        raise

    async with usermgr.load(QID) as acctmgr:
        async with acctmgr.load(ALIAS) as mgr:
            try:
                await mgr.pre_cron_run(now.hour, now.minute)
            except Exception as e:
                print(f'[警告] pre_cron_run 异常（继续执行）: {type(e).__name__}: {str(e)[:120]}')
            try:
                result = await mgr.do_daily()
                status = getattr(result, 'status', 'unknown')
                print(f'[完成] 日常执行结束，状态: {status}')
            except Exception as e:
                err = f'{type(e).__name__}: {str(e)[:300]}'
                print(f'[失败] 日常执行异常: {err}')
                push('❌ autopcr 日常执行失败', f'执行过程中出错：\n\n{err}\n\n{env_footer()}')
                raise

    # ---- 汇总结果 ----
    os.makedirs(RESULT_DIR, exist_ok=True)
    files = [os.path.join(RESULT_DIR, f) for f in os.listdir(RESULT_DIR)
             if f.endswith('.json') and f'{QID}_{ALIAS}_daily' in f]
    if not files:
        print('[汇总] 未找到结果文件')
        push('ℹ️ autopcr 日常已执行', f'执行完成，但未找到结果文件。\n\n{env_footer()}')
        return

    latest = max(files, key=os.path.getmtime)
    info, err = summarize_result(latest)
    print('-' * 60)
    if err:
        print('[汇总] ' + err)
        push('ℹ️ autopcr 日常已执行', f'{err}\n\n{env_footer()}')
        return

    print(f"[汇总] {info['stat']}")
    for line in info['lines']:
        print('  ' + line)

    title = '⚠️ autopcr 日常完成（有提醒）' if info['has_warn'] else '✅ autopcr 日常完成'
    body = [f"共 {info['total']} 项任务：{info['stat']}", '']
    if info['warn_lines']:
        body.append('⚠️ 需要注意：')
        body.extend('  ' + w for w in info['warn_lines'])
        body.append('')
    body.append('本次有产出的任务：')
    body.extend(info['lines'][:15] if info['lines'] else ['（本次没有成功/警告项）'])
    body.append('')
    body.append(env_footer())
    push(title, '\n'.join(body))

    # 有错误项则以非零码退出，避免「绿色勾掩盖失败」
    if any(l.startswith('❌') for l in info['lines']):
        print('[退出] 存在失败项，返回码 1')
        sys.exit(1)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('已中断')
