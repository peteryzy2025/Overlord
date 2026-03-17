# Task/views/task_upload_views.py
"""
Amazon文件上传专用视图
处理Excel文件上传、店名校验、临时存储和正式归档
"""

import os
import shutil
import uuid
from django.conf import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods


@login_required
@require_http_methods(["GET"])
def get_amazon_shops_api(request):
    """
    获取Amazon店铺名称列表（用于前端校验文件名）
    GET /api/tasks/amazon-shops/
    """
    try:
        from general.models import AmazonShop

        shops = AmazonShop.objects.all().values_list('shop_name', flat=True)
        return JsonResponse({
            'success': True,
            'data': list(shops)
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取店铺列表失败: {str(e)}'
        }, status=500)


@login_required
@require_http_methods(["POST"])
def upload_temp_file_api(request):
    """
    临时上传文件（校验文件名是否包含店铺名）
    POST /api/tasks/upload-temp/

    Returns:
        {
            'success': True/False,
            'temp_path': 'temp_uploads/{uuid}/文件名.xlsx',
            'shop_name': '店铺名',
            'filename': '原始文件名',
            'error': '错误信息'
        }
    """
    try:
        if 'file' not in request.FILES:
            return JsonResponse({
                'success': False,
                'error': '未找到上传的文件'
            }, status=400)

        uploaded_file = request.FILES['file']

        # 检查文件类型
        if not uploaded_file.name.endswith(('.xlsx', '.xls')):
            return JsonResponse({
                'success': False,
                'error': '仅支持Excel文件(.xlsx, .xls)'
            }, status=400)

        # 检查文件大小（10MB = 10*1024*1024）
        if uploaded_file.size > 10 * 1024 * 1024:
            return JsonResponse({
                'success': False,
                'error': '文件大小不能超过10MB'
            }, status=400)

        # 获取所有店铺名进行校验
        from general.models import AmazonShop
        shop_names = list(AmazonShop.objects.all().values_list('shop_name', flat=True))

        # 检查文件名是否包含任意店铺名（去掉扩展名后检查）
        filename_without_ext = os.path.splitext(uploaded_file.name)[0]
        matched_shop = None

        for shop_name in shop_names:
            if shop_name in filename_without_ext:
                matched_shop = shop_name
                break

        if not matched_shop:
            return JsonResponse({
                'success': False,
                'error': f'未找到对应店铺：文件名必须包含有效的店铺名称',
                'filename': uploaded_file.name
            }, status=400)

        # 生成临时目录（使用UUID避免冲突）
        temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp_uploads', str(uuid.uuid4()))
        os.makedirs(temp_dir, exist_ok=True)

        # 保存文件到临时目录
        temp_file_path = os.path.join(temp_dir, uploaded_file.name)
        with open(temp_file_path, 'wb+') as destination:
            for chunk in uploaded_file.chunks():
                destination.write(chunk)

        # 返回相对路径（用于后续移动）
        relative_path = os.path.join('temp_uploads', os.path.basename(temp_dir), uploaded_file.name)

        return JsonResponse({
            'success': True,
            'temp_path': relative_path.replace('\\', '/'),  # 统一使用正斜杠
            'shop_name': matched_shop,
            'filename': uploaded_file.name
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'上传失败: {str(e)}'
        }, status=500)


def process_amazon_upload_files(subtask_params, task_no, task_instance=None, subtask_instance=None):
    """
    处理Amazon上传文件：从临时目录移动到共享目录，并创建数据库记录
    在任务创建成功后调用

    Args:
        subtask_params: 子任务的params字典
        task_no: 任务单号
        task_instance: Task对象（新增参数）
        subtask_instance: SubTask对象（新增参数）
    """
    processed_files = []

    try:
        file_paths = subtask_params.get('file_paths', [])

        if not file_paths:
            return processed_files

        # 目标根目录（UNC路径）
        target_root = r'\\192.168.110.54\overlord_555\自动化\amazon上货\待上货文件'

        # 获取所有店铺名用于匹配
        from general.models import AmazonShop
        from task.models import AmazonUploadFile  # 新增导入

        shop_names = list(AmazonShop.objects.all().values_list('shop_name', flat=True))

        for temp_path in file_paths:
            try:
                # 临时文件的完整路径
                full_temp_path = os.path.join(settings.MEDIA_ROOT, temp_path)

                if not os.path.exists(full_temp_path):
                    continue

                # 从文件名中提取店铺名
                original_filename = os.path.basename(temp_path)
                filename_without_ext = os.path.splitext(original_filename)[0]

                matched_shop = None
                matched_shop_name = None

                for shop_name in shop_names:
                    if shop_name in filename_without_ext:
                        matched_shop = AmazonShop.objects.get(shop_name=shop_name)
                        matched_shop_name = shop_name
                        break

                if not matched_shop:
                    continue

                # 构建目标目录
                target_dir = os.path.join(target_root, matched_shop_name)
                os.makedirs(target_dir, exist_ok=True)

                # 提取店铺后缀（数字法人部分）
                if '-' in matched_shop_name:
                    shop_suffix = matched_shop_name.split('-', 1)[1]
                else:
                    shop_suffix = matched_shop_name

                # 生成唯一文件名：数字法人_任务号_序号.xlsx
                # 检查该店铺已处理的文件数，生成递增序号
                existing_files_count = sum(1 for p in processed_files if p['shop'] == matched_shop_name)
                sequence_num = existing_files_count + 1
                
                new_filename = f'{shop_suffix}_{task_no}_{sequence_num}.xlsx'
                target_path = os.path.join(target_dir, new_filename)

                # 如果目标文件已存在（理论上不会发生），添加额外序号
                while os.path.exists(target_path):
                    sequence_num += 1
                    new_filename = f'{shop_suffix}_{task_no}_{sequence_num}.xlsx'
                    target_path = os.path.join(target_dir, new_filename)

                # 移动文件
                shutil.move(full_temp_path, target_path)

                # ===== 关键新增：创建数据库记录 =====
                if task_instance and subtask_instance:
                    AmazonUploadFile.objects.create(
                        task=task_instance,
                        subtask=subtask_instance,
                        amazon_shop=matched_shop,
                        shop_name_suffix=shop_suffix,
                        excel_filename=new_filename,
                        target_path=target_path,
                        status=AmazonUploadFile.STATUS_PENDING
                    )
                # ===================================

                processed_files.append({
                    'shop': matched_shop_name,
                    'target_path': target_path,
                    'filename': new_filename
                })

                # 清理空临时目录
                temp_dir = os.path.dirname(full_temp_path)
                if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                    os.rmdir(temp_dir)

            except Exception as file_error:
                print(f"处理单个文件失败 {temp_path}: {str(file_error)}")
                continue

        # 更新params记录处理结果
        subtask_params['processed_files'] = processed_files

    except Exception as e:
        print(f"处理Amazon上传文件整体失败: {str(e)}")
        import traceback
        traceback.print_exc()

    return processed_files

