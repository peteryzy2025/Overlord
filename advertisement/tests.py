#这是获取profile_id，好像不是必填


import os
import sys
import asyncio
import time
import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Callable, Any

# ========== Django 环境初始化 ==========
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.append(PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")
import django
django.setup()

import asyncio
from asgiref.sync import sync_to_async
from general.models import Project  # 根据你的实际路径调整
from api.lingxing.Y_OpenApi import get_api_resp


async def fetch_all_projects_accounts():
    """
    1. 查询所有项目，去重 lingxing_app_id
    2. 对每个唯一凭证拉取全部账号
    3. 汇总并检测跨凭证重复
    """
    # 1. 获取所有有效凭证并去重
    projects = await sync_to_async(list)(
        Project.objects.exclude(
            lingxing_app_id__isnull=True
        ).exclude(
            lingxing_app_id=''
        ).values('lingxing_app_id', 'lingxing_app_secret')
    )

    # 去重：以 app_id 为 key（不同项目可能共享同一套领星凭证）
    credentials = {}
    for p in projects:
        app_id = p['lingxing_app_id']
        app_secret = p['lingxing_app_secret']
        if app_id and app_id not in credentials:
            credentials[app_id] = app_secret

    print(f"📦 发现 {len(projects)} 个项目，去重后 {len(credentials)} 个唯一凭证")

    # 2. 对每个凭证循环获取（顺序执行，避免并发触发限流）
    all_accounts = []
    for idx, (app_id, app_secret) in enumerate(credentials.items(), 1):
        print(f"\n🔑 [{idx}/{len(credentials)}] 正在处理: {app_id[:15]}...")
        accounts = await fetch_accounts_by_credential(app_id, app_secret)
        all_accounts.extend(accounts)
        print(f"   该凭证获取 {len(accounts)} 个账号，累计 {len(all_accounts)}")

    # 3. 全局去重检测（跨凭证可能重复绑定同一个亚马逊账号）
    analyze_duplicates(all_accounts)

    return all_accounts


async def fetch_accounts_by_credential(app_id, app_secret):
    """单个凭证分页获取（length=100）"""
    length = 100
    req_body = {
        "type": "seller",
        "offset": 0,
        "length": length
    }

    # 第一页（获取 total）
    resp = await get_api_resp(
        req_body=req_body,
        api_path="/basicOpen/baseData/account/list",
        app_id=app_id,
        app_secret=app_secret
    )

    if resp.code != 0:
        print(f"   ❌ 首请求失败: {resp.message}")
        return []

    total = resp.total
    accounts = list(resp.data)  # 假设 resp.data 是 list
    print(f"   进度: {len(accounts)}/{total}")

    # 剩余页
    for offset in range(length, total, length):
        resp = await get_api_resp(
            req_body={"type": "seller", "offset": offset, "length": length},
            api_path="/basicOpen/baseData/account/list",
            app_id=app_id,
            app_secret=app_secret
        )

        if resp.code == 0:
            accounts.extend(resp.data)
            print(f"   进度: {len(accounts)}/{total}")
        else:
            print(f"   ⚠️  offset={offset} 失败: {resp.message}")
            break

    return accounts


def analyze_duplicates(accounts):
    """检测 profile_id 和 sid 的重复情况"""
    from collections import defaultdict

    # 兼容 dict 或 object
    def get_val(acc, key):
        return acc.get(key) if isinstance(acc, dict) else getattr(acc, key, None)

    profile_map = defaultdict(list)
    sid_map = defaultdict(list)

    for acc in accounts:
        pid = get_val(acc, 'profile_id')
        sid = get_val(acc, 'sid')
        name = get_val(acc, 'name')

        if pid:
            profile_map[pid].append(f"{name}({sid})")
        if sid:
            sid_map[sid].append(name)

    dup_profiles = {k: v for k, v in profile_map.items() if len(v) > 1}
    dup_sids = {k: v for k, v in sid_map.items() if len(v) > 1}

    print(f"\n📊 汇总统计:")
    print(f"  - 总账号数: {len(accounts)}")
    print(f"  - 唯一 Profile ID: {len(profile_map)}")
    print(f"  - 唯一 SID: {len(sid_map)}")

    if dup_profiles:
        print(f"\n⚠️  跨凭证重复 Profile ID: {len(dup_profiles)} 个")
        for pid, names in list(dup_profiles.items())[:3]:  # 只显示前3个
            print(f"    {pid}: {', '.join(names)}")

    if dup_sids:
        print(f"\n⚠️  重复 SID: {len(dup_sids)} 个")

def demo():
    accounts = asyncio.run(fetch_all_projects_accounts())

    print(f"\n✅ 完成，共处理 {len(accounts)} 个账号")


demo()