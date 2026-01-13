# Task/utils/task_utils.py

import re
from datetime import datetime

from django.db.models import Q

from general.models import User, AmazonShop, TemuShop


def parse_permissions(permission_str):
    """
    解析权限字符串为列表
    """
    if not permission_str:
        return []
    return [p.strip() for p in permission_str.split(',') if p.strip()]


def generate_task_no(user):
    """
    生成任务单号：名字拼音缩写 + 日期时间
    格式：ZF2026-0105-1153-30
    """
    # 获取名字（使用first_name）
    first_name = user.first_name or user.username

    # 提取名字拼音首字母
    # 假设first_name是中文名，取每个字的首字母
    initials = []
    for char in first_name:
        if '\u4e00' <= char <= '\u9fff':
            # 这里是简化处理，实际项目中可能需要拼音库
            initials.append(char[0].upper())
        elif char.isalpha():
            initials.append(char[0].upper())

    if not initials:
        # 如果没有有效首字母，使用用户名前2-4位
        pinyin_initials = user.username[:4].upper()
    else:
        pinyin_initials = ''.join(initials[:4])  # 最多4位

    # 生成日期时间字符串
    now = datetime.now()
    datetime_str = now.strftime('%Y%m%d-%H%M-%S')

    return f"{pinyin_initials}{datetime_str}"


def get_visible_shops(user, shop_type='amazon'):
    """
    获取用户可见的店铺列表（权限逻辑参考邮件视图）
    """
    permissions = parse_permissions(getattr(user, 'permission', ''))

    # 基础查询
    base_filter = Q()

    if 'ops_all' in permissions:
        # 管理员：所有店铺
        if shop_type == 'amazon':
            return AmazonShop.objects.filter(ops__isnull=False).select_related('ops')
        else:
            return TemuShop.objects.filter(ops_id__isnull=False).select_related('ops_id')

    elif 'ops_group' in permissions and hasattr(user, 'operational_account'):
        # 组长：组内所有店铺
        group_name = user.operational_account.ops_group
        if group_name:
            if shop_type == 'amazon':
                return AmazonShop.objects.filter(
                    ops__operational_account__ops_group=group_name
                ).select_related('ops')
            else:
                return TemuShop.objects.filter(
                    ops_id__operational_account__ops_group=group_name
                ).select_related('ops_id')

    # 普通用户：只能看自己的店铺
    if shop_type == 'amazon':
        return AmazonShop.objects.filter(ops=user).select_related('ops')
    else:
        return TemuShop.objects.filter(ops_id=user.id).select_related('ops_id')


def validate_subtask_params(subtask_type, params, user):
    """
    验证子任务参数
    返回: {'valid': True/False, 'message': '...'}
    """
    try:
        if subtask_type == 'custom_upload':
            # 必填字段
            required_fields = ['product_ids', 'mode', 'gallery_account',
                               'gallery_path', 'craft_type', 'export_quantity', 'export_shop_ids']

            for field in required_fields:
                if field not in params:
                    return {'valid': False, 'message': f'缺少必填参数: {field}'}

            # 验证产品ID
            product_ids = params.get('product_ids', [])
            if not isinstance(product_ids, list) or not product_ids:
                return {'valid': False, 'message': '产品ID必须为非空数组'}

            for pid in product_ids:
                if not re.match(r'^\d+$', str(pid)):
                    return {'valid': False, 'message': f'产品ID必须是数字: {pid}'}

            # 验证模式
            if params.get('mode') not in ['adapt', 'fill']:
                return {'valid': False, 'message': '模式必须是"adapt"或"fill"'}

            # 验证工艺类型
            if params.get('craft_type') not in ['print', 'emboss', 'laser']:
                return {'valid': False, 'message': '工艺类型无效'}

            # 验证数量
            quantity = params.get('export_quantity', 0)
            if not isinstance(quantity, int) or quantity < 1:
                return {'valid': False, 'message': '汇出数量必须是大于0的整数'}

            # 验证店铺ID
            shop_ids = params.get('export_shop_ids', [])
            if not isinstance(shop_ids, list) or not shop_ids:
                return {'valid': False, 'message': '必须选择至少一个汇出店铺'}

            # 权限验证：用户是否有权操作这些店铺
            visible_shop_ids = get_visible_shops(user, 'amazon').values_list('id', flat=True)
            for shop_id in shop_ids:
                if shop_id not in visible_shop_ids:
                    return {'valid': False, 'message': f'无权操作店铺ID: {shop_id}'}

        elif subtask_type == 'temu_export':
            # 验证店铺ID
            shop_ids = params.get('export_shop_ids', [])
            if not isinstance(shop_ids, list) or not shop_ids:
                return {'valid': False, 'message': '必须选择至少一个导单店铺'}

            # 权限验证
            visible_shop_ids = get_visible_shops(user, 'temu').values_list('id', flat=True)
            for shop_id in shop_ids:
                if shop_id not in visible_shop_ids:
                    return {'valid': False, 'message': f'无权操作店铺ID: {shop_id}'}

        elif subtask_type == 'amazon_upload':
            # 验证文件路径
            file_paths = params.get('file_paths', [])
            if not isinstance(file_paths, list) or not file_paths:
                return {'valid': False, 'message': '必须上传至少一个文件'}

        else:
            return {'valid': False, 'message': f'未知的子任务类型: {subtask_type}'}

        return {'valid': True, 'message': '验证通过'}

    except Exception as e:
        return {'valid': False, 'message': f'参数验证异常: {str(e)}'}