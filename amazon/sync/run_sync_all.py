#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Amazon Listing 数据同步统一入口
===========================
依次执行：
1. sync_listing_ingest.py - 同步基础数据（ASIN、标题、销量、销售额等）
2. sync_listing_risk_worker.py - 分析侵权风险

用法：
    python amazon/sync/run_sync_all.py
    python amazon/sync/run_sync_all.py --sid 12345
    python amazon/sync/run_sync_all.py --max-pages 5
"""

import os
import sys
import subprocess
import argparse
from datetime import datetime

# ====== Django 初始化 ======
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))
sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Overlord.settings")


def log(message: str):
    """打印带时间戳的日志"""
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] {message}")


def run_script(script_name: str, extra_args: list = None) -> bool:
    """
    运行子脚本（直接输出到控制台）
    """
    script_path = os.path.join(CURRENT_DIR, script_name)
    
    if not os.path.exists(script_path):
        print(f"❌ 脚本不存在: {script_path}")
        return False
    
    cmd = [sys.executable, script_path]
    if extra_args:
        cmd.extend(extra_args)
    
    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=False,  # 直接输出到控制台，显示进度条
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        return result.returncode == 0
    except Exception as e:
        print(f"❌ 执行异常: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Amazon Listing 数据同步统一入口（ ingest + 风险分析 ）"
    )
    parser.add_argument("--sid", type=int, default=None, help="仅处理指定店铺 sid")
    parser.add_argument("--max-pages", type=int, default=None, help="ingest: 每店铺最大页数")
    parser.add_argument("--max-shops", type=int, default=None, help="ingest: 最大店铺数")
    parser.add_argument("--skip-risk", action="store_true", help="跳过风险分析步骤")
    parser.add_argument("--include-known", action="store_true", help="risk: 包含已分析过的记录")
    parser.add_argument("--include-inactive", action="store_true", help="risk: 包含非在售listing")
    parser.add_argument("--workers", type=int, default=1, help="risk: 并发worker数（默认1，大于1时不显示详细进度）")
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("🚀 Amazon Listing 同步任务")
    print("=" * 70)
    
    # ========== 步骤1: 基础数据同步 ==========
    log("步骤 1/2: 同步基础数据（ASIN、标题、销量、销售额...）")
    
    ingest_args = []
    if args.sid:
        ingest_args.extend(["--sid", str(args.sid)])
    if args.max_pages:
        ingest_args.extend(["--max-pages", str(args.max_pages)])
    if args.max_shops:
        ingest_args.extend(["--max-shops", str(args.max_shops)])
    
    success = run_script("sync_listing_ingest.py", ingest_args)
    
    if not success:
        log("❌ 基础数据同步失败")
        sys.exit(1)
    
    # ========== 步骤2: 风险分析 ==========
    if args.skip_risk:
        log("⏭️  跳过风险分析（--skip-risk）")
    else:
        log("步骤 2/2: 分析侵权风险")
        
        risk_args = []
        if args.sid:
            risk_args.extend(["--sid", str(args.sid)])
        if args.include_known:
            risk_args.append("--include-known")
        if args.include_inactive:
            risk_args.append("--include-inactive")
        if args.workers:
            risk_args.extend(["--workers", str(args.workers)])
        
        success = run_script("sync_listing_risk_worker.py", risk_args)
        
        if not success:
            log("⚠️ 风险分析步骤失败，但基础数据已同步")
    
    log("🎉 所有任务执行完毕")
    print("=" * 70)


if __name__ == "__main__":
    main()
