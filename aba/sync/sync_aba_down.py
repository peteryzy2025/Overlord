import os
import sys
import gzip
import shutil
import requests
import asyncio
from pathlib import Path
from datetime import datetime
from tqdm import tqdm

# 添加项目根目录到模块搜索路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from api.lingxing.Y_OpenApi import get_api_resp

# ============ 配置 ============
BASE_DIR = Path(__file__).parent
JSON_DIR = BASE_DIR / "json"  # GZ 临时文件和最终 JSON 都放这里
delete_gz_after_decompress = True  # 解压后是否删除 GZ 文件


def ensure_dirs():
    """确保目录存在"""
    JSON_DIR.mkdir(parents=True, exist_ok=True)


def download_with_progress(url: str, filepath: Path):
    """带进度条下载大文件"""
    print(f"⬇️ 开始下载...")
    response = requests.get(url, stream=True, timeout=600)
    response.raise_for_status()

    total_size = int(response.headers.get('content-length', 0))
    block_size = 1024 * 1024  # 1MB 块

    with open(filepath, 'wb') as f, tqdm(
            total=total_size,
            unit='iB',
            unit_scale=True,
            desc='下载',
            ncols=80
    ) as pbar:
        for data in response.iter_content(chunk_size=block_size):
            size = f.write(data)
            pbar.update(size)


def decompress_gz_to_json(gz_path: Path, json_path: Path):
    """解压 GZ 并验证 JSON 格式，带进度条"""
    print(f"📦 正在解压为 JSON...")

    gz_size = gz_path.stat().st_size

    # 流式解压带进度条（适合大文件，不占内存）
    with gzip.open(gz_path, 'rb') as f_in:
        with open(json_path, 'wb') as f_out:
            with tqdm(total=gz_size, unit='B', unit_scale=True, desc='解压', ncols=80) as pbar:
                while True:
                    chunk = f_in.read(1024 * 1024)  # 每次读取 1MB
                    if not chunk:
                        break
                    f_out.write(chunk)
                    pbar.update(len(chunk))

    # 验证生成的 JSON 文件头
    with open(json_path, 'rb') as f:
        header = f.read(50).decode('utf-8', errors='ignore').strip()
        if not (header.startswith('{') or header.startswith('[')):
            raise ValueError(f"文件内容不是 JSON 格式，头: {header[:50]}...")
        print(f"✅ JSON 文件头验证: {header[:50]}...")


async def down_aba(data_start_time: str):
    """主流程：下载 ABA 报告并解压为 JSON"""
    ensure_dirs()

    req_body = {
        "country": "US",
        "data_start_time": data_start_time,
    }

    print("🚀 正在请求领星 ABA 报告接口...")
    resp = await get_api_resp(req_body=req_body, api_path="/pb/openapi/newad/abaReport")

    if resp.code != 0:
        print(f"❌ API 调用失败: {resp.message}")
        return None

    data = resp.data
    url = data.get("url")
    if not url:
        print("❌ 响应中未找到下载链接")
        return None

    print(f"✅ 获取链接成功")
    print(f"   数据周期: {data.get('data_start_time')} | 国家: {data.get('country')}")

    # 生成文件名（使用数据日期）
    date_str = data.get('data_start_time', datetime.now().strftime("%Y-%m-%d"))

    gz_name = f"{date_str}.gz"
    json_name = f"{date_str}.json"

    gz_path = JSON_DIR / gz_name
    json_path = JSON_DIR / json_name

    try:
        # 下载
        download_with_progress(url, gz_path)
        print(f"✅ 下载完成: {gz_path.stat().st_size / 1024 / 1024:.1f} MB")

        # 解压为 JSON
        decompress_gz_to_json(gz_path, json_path)
        json_size_mb = json_path.stat().st_size / 1024 / 1024
        print(f"📄 JSON 文件大小: {json_size_mb:.1f} MB")

        # 解压完成后删除 GZ 临时文件
        if delete_gz_after_decompress and gz_path.exists():
            gz_path.unlink()
            print(f"🗑️ 已删除 GZ 临时文件")

        print(f"\n🎉 全部完成！")
        print(f"   JSON 文件: {json_path}")

        # 提示：大文件处理建议
        if json_size_mb > 1000:
            print(f"\n⚠️ 提示：JSON 文件超过 1GB，建议用流式方式导入数据库")
            print(f"   python sync_import_to_db.py {json_path} {date_str}")

        return str(json_path)

    except Exception as e:
        print(f"\n❌ 处理失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def download_aba_report(data_start_time: str) -> str:
    """
    同步调用：下载 ABA 报告

    参数:
        data_start_time: 日期字符串 (YYYY-MM-DD)

    返回:
        json 文件路径，失败返回 None
    """
    return asyncio.run(down_aba(data_start_time))


if __name__ == "__main__":
    result = asyncio.run(down_aba("2026-02-01"))
    if not result:
        exit(1)