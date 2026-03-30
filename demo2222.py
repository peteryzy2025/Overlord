import os
import shutil
from pathlib import Path
from typing import List, Dict


def reorganize_excel_files(source_dir: str, dry_run: bool = False) -> List[Dict]:
    """
    重组影刀输出目录下的Excel文件

    规则：
    原文件：承诺希航-16蔡婉婷_2223_0330-1650.xlsx
    新路径：承诺希航-16蔡婉婷/16蔡婉婷_2223_0330-1650.xlsx

    Args:
        source_dir: 源目录路径，如 r"D:\影刀\output_0330-1650\output_0330-1650"
        dry_run: 是否为预览模式（True只打印不移动，False实际执行移动）

    Returns:
        操作结果列表，包含 original, target, status 等信息
    """
    source_path = Path(source_dir)

    if not source_path.exists():
        raise FileNotFoundError(f"❌ 路径不存在: {source_dir}")

    if not source_path.is_dir():
        raise NotADirectoryError(f"❌ 不是有效目录: {source_dir}")

    results = []
    xlsx_files = list(source_path.glob("*.xlsx"))

    print(f"📁 扫描目录: {source_dir}")
    print(f"📊 发现 {len(xlsx_files)} 个Excel文件")
    print("-" * 60)

    for idx, file_path in enumerate(xlsx_files, 1):
        file_name = file_path.name

        # 跳过临时文件（以~$开头的隐藏文件）
        if file_name.startswith("~$"):
            continue

        # 解析文件名规则
        if "_" not in file_name or "-" not in file_name:
            print(f"⚠️  [{idx}] 跳过（不符合命名格式）: {file_name}")
            continue

        # 提取文件夹名：第一个下划线前的所有内容
        # 例：承诺希航-16蔡婉婷_2223_0330-1650.xlsx -> 承诺希航-16蔡婉婷
        folder_name = file_name.split("_")[0]

        # 提取新文件名：第一个减号后的所有内容
        # 例：承诺希航-16蔡婉婷_2223_0330-1650.xlsx -> 16蔡婉婷_2223_0330-1650.xlsx
        try:
            new_file_name = file_name.split("-", 1)[1]
        except IndexError:
            print(f"⚠️  [{idx}] 跳过（无法解析减号分隔）: {file_name}")
            continue

        # 构建目标路径
        target_folder = source_path / folder_name
        target_path = target_folder / new_file_name

        result = {
            "index": idx,
            "original": str(file_path),
            "target_folder": str(target_folder),
            "target_path": str(target_path),
            "folder_name": folder_name,
            "new_file_name": new_file_name
        }

        if dry_run:
            # 预览模式：只打印不执行
            print(f"👁️  [{idx}] 预览: {file_name}")
            print(f"    创建目录: {folder_name}")
            print(f"    重命名为: {new_file_name}")
            result["status"] = "preview"
        else:
            # 执行模式
            try:
                # 创建子目录（如果不存在）
                target_folder.mkdir(exist_ok=True)

                # 如果目标文件已存在，先删除（避免报错）
                if target_path.exists():
                    target_path.unlink()
                    print(f"    🗑️  已覆盖旧文件")

                # 移动文件
                shutil.move(str(file_path), str(target_path))

                print(f"✅  [{idx}] 成功: {file_name}")
                print(f"    📂 移动至: {folder_name}/{new_file_name}")
                result["status"] = "success"

            except Exception as e:
                print(f"❌  [{idx}] 失败: {file_name} - 错误: {e}")
                result["status"] = "failed"
                result["error"] = str(e)

        results.append(result)
        if not dry_run or idx < len(xlsx_files):
            print()  # 空行分隔

    # 统计摘要
    print("-" * 60)
    success_count = sum(1 for r in results if r.get("status") == "success")
    preview_count = sum(1 for r in results if r.get("status") == "preview")
    failed_count = sum(1 for r in results if r.get("status") == "failed")

    if dry_run:
        print(f"🔍 预览完成: {preview_count} 个文件待处理（未实际移动）")
        print("💡 提示: 将 dry_run=False 传入函数以执行实际移动")
    else:
        print(f"🎉 处理完成: 成功 {success_count} 个, 失败 {failed_count} 个")

    return results


# ==================== 使用示例 ====================
if __name__ == "__main__":
    # 配置路径
    SOURCE_DIR = r"D:\影刀\output_0330-1650\output_0330-1650"

    # 步骤1：先预览（不实际移动，确认无误后再执行）
    print("=" * 60)
    print("第一步：预览模式（安全查看变更计划）")
    print("=" * 60)
    # reorganize_excel_files(SOURCE_DIR, dry_run=True)

    print("\n" + "=" * 60)
    print("第二步：确认无误后，注释掉上方预览代码，运行下方实际代码")
    print("=" * 60)

    # 步骤2：实际执行（取消下方注释以启用）
    reorganize_excel_files(SOURCE_DIR, dry_run=False)