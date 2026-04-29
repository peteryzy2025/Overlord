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


def get_operation_permissions(user):
    """
    Return task operation permissions from both legacy and PermissionConfig data.
    """
    permissions = set(parse_permissions(getattr(user, 'permission', '')))

    try:
        codes = set(user.permission_configs.values_list('code', flat=True))
    except Exception:
        codes = set()

    if 555 in codes or 553 in codes:
        permissions.add('ops_all')

    account = getattr(user, 'operational_account', None)
    if 'ops_all' not in permissions and account and account.role == 'leader' and account.ops_group:
        permissions.add('ops_group')

    if not permissions:
        permissions.add('ops')

    return list(permissions)


def generate_task_no(user):
    """
    生成任务单号：名字拼音缩写 + 日期时间
    格式：YXD20260121-0846-17
    """
    # 获取名字（使用first_name）
    first_name = user.first_name or user.username

    # 提取名字拼音首字母
    from pypinyin import pinyin, Style

    # 获取拼音首字母
    initials_list = pinyin(first_name, style=Style.FIRST_LETTER, errors='default')
    # pinyin返回如 [['y'], ['x'], ['d']]

    initials = []
    for item in initials_list:
        if item:
            char = item[0]
            if char.isalnum():
                initials.append(char)

    if not initials:
        # 如果没有有效首字母，使用用户名前2-4位
        pinyin_initials = user.username[:4].upper()
    else:
        pinyin_initials = ''.join(initials[:4]).upper()  # 最多4位，转大写

    # 生成日期时间字符串
    now = datetime.now()
    datetime_str = now.strftime('%Y%m%d-%H%M-%S')

    return f"{pinyin_initials}{datetime_str}"


def get_visible_shops(user, shop_type='amazon'):
    """
    Company-scoped shop visibility for task creation and validation.
    """
    permissions = get_operation_permissions(user)
    company_id = getattr(user, 'company_id', None)

    if not company_id:
        return AmazonShop.objects.none() if shop_type == 'amazon' else TemuShop.objects.none()

    if shop_type == 'amazon':
        queryset = AmazonShop.objects.filter(
            company_id=company_id,
            ops__isnull=False
        ).select_related('ops')
    else:
        queryset = TemuShop.objects.filter(
            company_id=company_id,
            ops_id__isnull=False
        )

    if 'ops_all' in permissions:
        return queryset

    if 'ops_group' in permissions and hasattr(user, 'operational_account'):
        group_name = user.operational_account.ops_group
        if group_name:
            group_user_ids = User.objects.filter(
                company_id=company_id,
                operational_account__ops_group=group_name
            ).values_list('id', flat=True)
            if shop_type == 'amazon':
                return queryset.filter(
                    Q(ops_id__in=group_user_ids) |
                    Q(authorized_users=user)
                ).distinct()
            return queryset.filter(ops_id__in=group_user_ids)

    if shop_type == 'amazon':
        return queryset.filter(
            Q(ops=user) |
            Q(authorized_users=user)
        ).distinct()
    return queryset.filter(ops_id=user.id)


def _normalize_shop_name_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    value = str(value).strip()
    return [value] if value else []


def _get_visible_shop_names(user, shop_type='amazon'):
    return set(
        str(name).strip()
        for name in get_visible_shops(user, shop_type)
        .exclude(shop_name__isnull=True)
        .exclude(shop_name='')
        .values_list('shop_name', flat=True)
        if str(name).strip()
    )


def _invalid_shop_names(user, shop_type, names):
    visible_names = _get_visible_shop_names(user, shop_type)
    return sorted({
        name for name in _normalize_shop_name_list(names)
        if name not in visible_names
    })


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

        elif subtask_type == 'divi_multi_side_custom':
            # 迪唯多面定制验证逻辑
            required_fields = ['product_ids', 'mode', 'diwei_account', 'craft_type']

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

            # NAS路径和图库分类二选一验证
            nas_path = params.get('nas_path', '').strip()
            image_classify = params.get('image_classify', [])
            
            has_nas_path = bool(nas_path)
            has_image_classify = isinstance(image_classify, list) and len(image_classify) > 0
            
            if not has_nas_path and not has_image_classify:
                return {'valid': False, 'message': '必须填写NAS路径或选择图库分类（二选一）'}
            
            # 如果填写了NAS路径，验证格式
            if has_nas_path and not nas_path.upper().startswith('\\\\ZT-NAS'):
                return {'valid': False, 'message': 'NAS路径必须以 \\\\ZT-NAS 开头'}

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

        elif subtask_type == 'print_external':
            # 印花外采验证
            # url 为必填
            url = params.get('url', '').strip()
            if not url:
                return {'valid': False, 'message': '产品链接(URL)不能为空'}

            # platform 可选，默认 yizhiguan

        elif subtask_type == 'embroidery':

            # 刺绣验证
            # url 为必填

            url = params.get('url', '').strip()

            if not url:
                return {'valid': False, 'message': '产品链接(URL)不能为空'}


        elif subtask_type == 'amazon_upload':

            # Amazon上传商品验证
            # 用户ID=555可以跳过文件验证
            if user and user.id == 555:
                return {'valid': True, 'message': ''}

            file_list = params.get('file_list', [])

            file_paths = params.get('file_paths', [])

            has_valid_files = False

            if file_list and isinstance(file_list, list):
                has_valid_files = any(f.get('success') for f in file_list if isinstance(f, dict))

            if not has_valid_files and (not file_paths or not isinstance(file_paths, list) or len(file_paths) == 0):
                return {'valid': False, 'message': '请上传至少一个有效的Excel文件'}

            return {'valid': True, 'message': ''}

        elif subtask_type == 'divi_custom':
            # 迪唯定制验证
            diwei_account = params.get('diwei_account', '').strip()
            if not diwei_account:
                return {'valid': False, 'message': '迪唯账号不能为空'}

            # 必须填写NAS路径或图库分类之一
            nas_path = params.get('nas_path', '').strip()
            image_classify = params.get('image_classify', [])
            has_nas_path = nas_path != ''
            has_image_classify = isinstance(image_classify, list) and len(image_classify) > 0
            if not has_nas_path and not has_image_classify:
                return {'valid': False, 'message': '必须填写NAS路径或图库分类'}
            if has_nas_path and not nas_path.upper().startswith('\\\\ZT-NAS'):
                return {'valid': False, 'message': 'NAS路径必须以 \\\\ZT-NAS 开头'}

            return {'valid': True, 'message': ''}

        elif subtask_type == 'divi_export':
            # 迪唯汇出验证
            diwei_account = params.get('diwei_account', '').strip()
            if not diwei_account:
                return {'valid': False, 'message': '迪唯账号不能为空'}

            selected_shops = []
            for row in params.get('export_rows', []):
                selected_shops.extend(_normalize_shop_name_list(row.get('shops', [])))
                selected_shops.extend(_normalize_shop_name_list(row.get('\u5e97\u94fa\u5217\u8868', [])))
            invalid_shops = _invalid_shop_names(user, 'amazon', selected_shops)
            if invalid_shops:
                return {'valid': False, 'message': f'No permission for shop: {", ".join(invalid_shops[:5])}'}

            return {'valid': True, 'message': ''}

        elif subtask_type == 'divi_export_pro':
            # 迪唯汇出上架-Pro 验证
            diwei_account = params.get('diwei_account', '').strip()
            if not diwei_account:
                return {'valid': False, 'message': '迪唯账号不能为空'}

            # 验证平台
            platform = params.get('platform', '').strip()
            if not platform or platform not in ['amazon', 'temu']:
                return {'valid': False, 'message': '平台必须选择且必须是Amazon或Temu'}

            # 验证汇出行
            export_rows = params.get('export_rows', [])
            visible_shop_names = _get_visible_shop_names(user, platform)

            if not export_rows or len(export_rows) == 0:
                return {'valid': False, 'message': '请至少添加一个产品'}

            for i, row in enumerate(export_rows):
                # 验证产品ID
                product_id = row.get('product_id', '')
                if not product_id or str(product_id).strip() == '':
                    return {'valid': False, 'message': f'第 {i + 1} 行的产品不能为空'}

                # 验证上架店铺
                publish_shops = row.get('publish_shops', [])
                if not publish_shops or len(publish_shops) == 0:
                    return {'valid': False, 'message': f'第 {i + 1} 行的上架店铺不能为空'}

                # 验证汇出店铺
                export_shop = row.get('export_shop', '')
                if not export_shop or str(export_shop).strip() == '':
                    return {'valid': False, 'message': f'第 {i + 1} 行的汇出店铺不能为空'}
                
                # 如果开启设计日期筛选，验证日期
                selected_names = (
                    _normalize_shop_name_list(publish_shops) +
                    _normalize_shop_name_list(export_shop)
                )
                invalid_shops = sorted({name for name in selected_names if name not in visible_shop_names})
                if invalid_shops:
                    return {'valid': False, 'message': f'No permission for shop: {", ".join(invalid_shops[:5])}'}

                if row.get('design_date_filter'):
                    if not row.get('design_start_date'):
                        return {'valid': False, 'message': f'第 {i + 1} 行开启了设计日期筛选，设计开始日期不能为空'}
                    if not row.get('design_end_date'):
                        return {'valid': False, 'message': f'第 {i + 1} 行开启了设计日期筛选，设计结束日期不能为空'}
                
                # 验证汇出模板名称必须包含4位数字
                export_template_name = row.get('export_template_name', '')
                if not re.search(r'\d{4}', export_template_name):
                    return {'valid': False, 'message': f'第 {i + 1} 行选择模板不符合自动化规则，请重新选择'}

            return {'valid': True, 'message': ''}

        elif subtask_type == 'amazon_exempt':
            # Amazon资格豁免验证
            amazon_shop = params.get('amazon_shop', '').strip()
            if not amazon_shop:
                return {'valid': False, 'message': 'Amazon店铺不能为空'}

            # 验证豁免产品列表
            invalid_shops = _invalid_shop_names(user, 'amazon', [amazon_shop])
            if invalid_shops:
                return {'valid': False, 'message': f'No permission for shop: {", ".join(invalid_shops[:5])}'}

            exempt_rows = params.get('exempt_rows', [])
            if not exempt_rows or len(exempt_rows) == 0:
                return {'valid': False, 'message': '请至少添加一个豁免产品'}

            for i, row in enumerate(exempt_rows):
                # 验证产品名称
                product_name = row.get('product_name', '')
                if not product_name or str(product_name).strip() == '':
                    return {'valid': False, 'message': f'第 {i + 1} 行的产品名称不能为空'}

                # 验证产品类型
                product_type = row.get('product_type', '')
                if not product_type or str(product_type).strip() == '':
                    return {'valid': False, 'message': f'第 {i + 1} 行的产品类型不能为空'}

            return {'valid': True, 'message': ''}

        elif subtask_type == 'divi_gallery_upload':
            diwei_account = params.get('diwei_account', '').strip()
            if not diwei_account:
                return {'valid': False, 'message': '迪唯账号不能为空'}

            local_gallery_path = params.get('local_gallery_path', '').strip()
            if not local_gallery_path:
                return {'valid': False, 'message': 'DIVI图库上传的本地路径不能为空'}

            return {'valid': True, 'message': ''}

        else:

            return {'valid': False, 'message': f'未知的子任务类型: {subtask_type}'}

        return {'valid': True, 'message': '验证通过'}

    except Exception as e:
        return {'valid': False, 'message': f'参数验证异常: {str(e)}'}
