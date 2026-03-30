import os
import shutil


def flatten_files(source_dir):
    """
    将 source_dir 下所有子目录中的文件移动到 source_dir 根目录，
    并在文件名前添加子目录名作为前缀。
    
    例如: D:\output_0330-1057\承诺希航-43张子新\CR20260330-1040-08-1292-1.xlsx
    改为: D:\output_0330-1057\承诺希航-43张子新_CR20260330-1040-08-1292-1.xlsx
    
    :param source_dir: 源目录路径
    """
    if not os.path.exists(source_dir):
        print(f"目录不存在: {source_dir}")
        return
    
    moved_count = 0
    
    # 遍历 source_dir 下的所有子目录（不递归深层子目录）
    for item in os.listdir(source_dir):
        item_path = os.path.join(source_dir, item)
        
        # 只处理子目录
        if os.path.isdir(item_path):
            folder_name = item  # 子目录名，如 "承诺希航-43张子新"
            
            # 遍历子目录中的所有文件
            for filename in os.listdir(item_path):
                file_path = os.path.join(item_path, filename)
                
                # 只处理文件（不处理子目录）
                if os.path.isfile(file_path):
                    # 构造新文件名: 子目录名_原文件名
                    new_filename = f"{folder_name}_{filename}"
                    new_path = os.path.join(source_dir, new_filename)
                    
                    # 如果目标文件已存在，添加数字后缀避免覆盖
                    counter = 1
                    original_new_path = new_path
                    while os.path.exists(new_path):
                        name, ext = os.path.splitext(new_filename)
                        new_filename = f"{name}_{counter}{ext}"
                        new_path = os.path.join(source_dir, new_filename)
                        counter += 1
                    
                    try:
                        shutil.move(file_path, new_path)
                        print(f"已移动: {file_path} -> {new_path}")
                        moved_count += 1
                    except Exception as e:
                        print(f"移动失败: {file_path}, 错误: {e}")
            
            # 尝试删除空目录
            try:
                os.rmdir(item_path)
                print(f"已删除空目录: {item_path}")
            except OSError:
                pass  # 目录不为空，忽略
    
    print(f"\n完成! 共移动 {moved_count} 个文件")


if __name__ == "__main__":
    source_directory = r"D:\output_0330-1057"
    flatten_files(source_directory)
