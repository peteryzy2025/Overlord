from django.shortcuts import render
from django.http import JsonResponse
from django.db import IntegrityError
from django.db.models import Q
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
from theme.models import TroTable, TrademarkInfo, NiceClassification
from general.models import AmazonShop, UserOperationLog
import os
from django.http import FileResponse, Http404
from django.conf import settings
import pandas as pd
from django.utils import timezone

from general.module_utils import module_access_required

# ============================================
# 1. 页面渲染视图
# ============================================

SYSTEM_SUPER_ADMIN_ID = 555


def is_system_super_admin(user):
    """平台总管理员：只能是 user.id == 555。"""
    return bool(user and user.is_authenticated and user.id == SYSTEM_SUPER_ADMIN_ID)


def is_admin(user):
    """兼容旧命名：系统级数据权限只认 user.id == 555。"""
    return is_system_super_admin(user)


def is_tro_admin(user):
    """判断用户是否为侵权词库页面管理员（拥有code=555或code=556的权限）"""
    if not user.is_authenticated:
        return False
    if is_system_super_admin(user):
        return True
    # 超级管理员默认是管理员
    if user.is_superuser:
        return True
    try:
        return user.permission_configs.filter(code__in=[555, 556]).exists()
    except Exception:
        return False


def system_tro_record_q():
    """系统级词库：无店铺，且无创建人或由平台总管理员创建。"""
    return Q(shop__isnull=True) & (
        Q(creator__isnull=True) | Q(creator_id=SYSTEM_SUPER_ADMIN_ID)
    )


def is_system_tro_record(record):
    return not record.shop_id and (
        record.creator_id is None or record.creator_id == SYSTEM_SUPER_ADMIN_ID
    )


def get_tro_queryset_for_user(user):
    """按用户返回可见词库。系统级词库只对 user.id == 555 可见。"""
    queryset = TroTable.objects.select_related('shop', 'creator', 'creator__company')
    if is_system_super_admin(user):
        return queryset

    return queryset.exclude(system_tro_record_q()).filter(
        Q(shop__company=getattr(user, 'company', None)) |
        Q(shop__isnull=True, creator__company=getattr(user, 'company', None))
    ).distinct()


def can_view_tro_record(user, record):
    if is_system_tro_record(record):
        return is_system_super_admin(user)

    company_id = getattr(user, 'company_id', None)
    if not company_id:
        return False

    if record.shop_id:
        return record.shop and record.shop.company_id == company_id

    if record.creator_id:
        return record.creator and record.creator.company_id == company_id

    return False


def can_edit_tro_record(user, record):
    if not can_view_tro_record(user, record):
        return False
    if is_system_tro_record(record):
        return is_system_super_admin(user)
    return record.creator_id == user.id or is_tro_admin(user)


def can_delete_tro_record(user, record):
    if not can_view_tro_record(user, record):
        return False
    if is_system_tro_record(record):
        return is_system_super_admin(user)
    return is_tro_admin(user)


def inaccessible_duplicate_response(user, record):
    if is_system_tro_record(record):
        message = '该侵权词已存在于系统级词库，仅平台总管理员可替换。'
    else:
        message = '该侵权词已存在于其他数据范围，无法重复创建。'
    return JsonResponse({
        'success': False,
        'code': 'duplicate_out_of_scope',
        'need_confirm': False,
        'message': message,
    }, status=403)


@module_access_required('infringement', '侵权板块')
def tro_table_page(request):
    """
    侵权词库页面
    """
    return render(request, 'tro_table.html', {
        'page_title': '侵权词库',
        'active_nav': 'theme_tro_table',
        'is_admin': is_tro_admin(request.user),  # 传递管理员状态到前端（支持555或556）
        'current_user': request.user.first_name or request.user.username,  # 传递当前用户名
    })


# @module_access_required('infringement', '侵权板块')
def trademark_info_page(request):
    """
    美标网词库页面
    """
    return render(request, 'trademark_info.html', {
        'page_title': '美标网词库',
        'active_nav': 'theme_trademark_info',
    })


# ============================================
# 2. API接口
# ============================================

# 侵权类型码映射
NAME_TYPE_MAPPING = {
    1: '系统白名单',
    2: '用户未指定',
    3: '观察名单',
    4: '亚马逊涉嫌侵权',
    5: '律师函',
    6: '权利人投诉',
    7: '违禁词',
    8: '商标侵权',
    9: '自定义白名单',
    10: '知名IP',
    11: '版权图片'
}

# 侵权分类映射
CATEGORY_MAPPING = {
    1: '文字侵权',
    2: '版权侵权'
}


@csrf_exempt
@require_POST
# @module_access_required('infringement', '侵权板块')
def api_tro_table_list(request):
    """
    获取侵权词库列表
    """
    try:
        data = json.loads(request.body)

        # 基础查询集：公司用户只看公司词库，系统级词库仅 user.id == 555 可见
        queryset = get_tro_queryset_for_user(request.user)

        # 筛选条件
        theme_name = data.get('theme_name', '').strip()
        fuzzy_search = data.get('fuzzy_search', True)  # 默认为True（模糊搜索）

        if theme_name:
            if fuzzy_search:
                # 模糊搜索：包含即可（不区分大小写）
                queryset = queryset.filter(theme_name__icontains=theme_name)
            else:
                # 精确搜索：忽略大小写完全匹配
                queryset = queryset.filter(theme_name__iexact=theme_name)

        # 类型码多选筛选
        name_types = data.get('name_types', [])
        if name_types:
            try:
                name_type_list = [int(nt) for nt in name_types if nt]
                if name_type_list:
                    queryset = queryset.filter(name_type__in=name_type_list)
            except (ValueError, TypeError):
                pass
        
        # 国际类多选筛选
        intl_classes = data.get('intl_classes', [])
        if intl_classes:
            try:
                queryset = queryset.filter(international_classes__code__in=intl_classes).distinct()
            except (ValueError, TypeError):
                pass

        # 排序
        sort_field = data.get('sort_field', 'update_time')
        sort_order = data.get('sort_order', 'desc')

        valid_sort_fields = ['id', 'theme_name', 'name_type', 'create_time', 'update_time']
        if sort_field not in valid_sort_fields:
            sort_field = 'update_time'

        if sort_order == 'desc':
            sort_field = f'-{sort_field}'

        queryset = queryset.order_by(sort_field)

        # 分页
        page = int(data.get('page', 1))
        page_size = int(data.get('page_size', 20))
        page_size = min(page_size, 100)

        paginator = Paginator(queryset, page_size)

        try:
            page_obj = paginator.page(page)
        except PageNotAnInteger:
            page_obj = paginator.page(1)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)

        # 序列化数据
        data_list = []
        for item in page_obj:
            # 获取国际类信息
            intl_classes = list(item.international_classes.values('code', 'name'))
            
            is_system_record = is_system_tro_record(item)
            creator_name = '-'
            if is_system_record and not item.creator_id:
                creator_name = '系统'
            elif item.creator:
                creator_name = item.creator.first_name or item.creator.username

            data_list.append({
                'id': item.id,
                'theme_name': item.theme_name,
                'replacement_word': item.replacement_word,
                'name_type': item.name_type,
                'name_type_desc': NAME_TYPE_MAPPING.get(item.name_type, str(item.name_type)),
                'category': item.category,
                'international_classes': intl_classes,
                'shop_id': item.shop_id,
                'shop_name': '系统词库' if is_system_record else (item.shop.shop_name if item.shop else '-'),
                'creator_name': creator_name,
                'creator_id': item.creator.id if item.creator else None,
                'is_system_record': is_system_record,
                'create_time': item.create_time.strftime('%Y-%m-%d %H:%M:%S') if item.create_time else '',
                'update_time': item.update_time.strftime('%Y-%m-%d %H:%M:%S') if item.update_time else '',
            })

        return JsonResponse({
            'success': True,
            'data': {
                'list': data_list,
                'total': paginator.count,
                'page': page_obj.number,
                'total_pages': paginator.num_pages,
                'page_size': page_size
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取数据失败: {str(e)}'
        }, status=500)


@csrf_exempt
@require_POST
# @module_access_required('infringement', '侵权板块')
def api_create_tro_record(request):
    """
    创建新的侵权词记录
    """
    try:
        data = json.loads(request.body)

        theme_name = data.get('theme_name', '').strip()
        name_type = data.get('name_type')

        if not theme_name:
            return JsonResponse({'success': False, 'message': '侵权词不能为空'}, status=400)

        if not name_type:
            return JsonResponse({'success': False, 'message': '请选择类型码'}, status=400)

        try:
            name_type = int(name_type)
            if name_type not in NAME_TYPE_MAPPING:
                return JsonResponse({'success': False, 'message': '无效的类型码'}, status=400)
        except ValueError:
            return JsonResponse({'success': False, 'message': '类型码必须为数字'}, status=400)

        replacement_word = data.get('replacement_word')
        replacement_word = replacement_word.strip() if replacement_word else None
        category = data.get('category')
        category = int(category) if category else None
        intl_class_codes = data.get('international_classes')
        force_replace = bool(data.get('force_replace'))
        shop_id = data.get('shop_id') or None

        if shop_id:
            if not AmazonShop.objects.filter(id=shop_id, company=request.user.company).exists():
                return JsonResponse({'success': False, 'message': '无权选择该店铺'}, status=403)

        existing_record = (
            TroTable.objects.select_related('shop', 'creator', 'creator__company')
            .filter(theme_name__iexact=theme_name)
            .first()
        )
        if existing_record and not can_view_tro_record(request.user, existing_record):
            return inaccessible_duplicate_response(request.user, existing_record)

        if existing_record and not force_replace:
            existing_name_type_desc = NAME_TYPE_MAPPING.get(existing_record.name_type, str(existing_record.name_type))
            return JsonResponse({
                'success': False,
                'code': 'duplicate_theme_name',
                'need_confirm': True,
                'message': f'{existing_record.theme_name}已存在，类型码为{existing_name_type_desc}。是否仍要替换。',
                'data': {
                    'id': existing_record.id,
                    'theme_name': existing_record.theme_name,
                    'name_type': existing_record.name_type,
                    'name_type_desc': existing_name_type_desc,
                }
            }, status=409)

        replaced = False
        try:
            if existing_record and force_replace:
                if not can_edit_tro_record(request.user, existing_record):
                    return JsonResponse({
                        'success': False,
                        'message': '无权限替换此记录',
                    }, status=403)
                # 按用户确认结果覆盖现有记录（theme_name 唯一）
                existing_record.theme_name = theme_name
                existing_record.replacement_word = replacement_word
                existing_record.name_type = name_type
                existing_record.category = category
                existing_record.shop_id = shop_id
                existing_record.save()
                record = existing_record
                replaced = True
            else:
                record = TroTable.objects.create(
                    theme_name=theme_name,
                    replacement_word=replacement_word,
                    name_type=name_type,
                    category=category,
                    creator=request.user,
                    shop_id=shop_id
                )
        except IntegrityError:
            duplicate = (
                TroTable.objects.select_related('shop', 'creator', 'creator__company')
                .filter(theme_name__iexact=theme_name)
                .first()
            )
            if duplicate:
                if not can_view_tro_record(request.user, duplicate):
                    return inaccessible_duplicate_response(request.user, duplicate)
                duplicate_name_type_desc = NAME_TYPE_MAPPING.get(duplicate.name_type, str(duplicate.name_type))
                return JsonResponse({
                    'success': False,
                    'code': 'duplicate_theme_name',
                    'need_confirm': True,
                    'message': f'{duplicate.theme_name}已存在，类型码为{duplicate_name_type_desc}。是否仍要替换。',
                    'data': {
                        'id': duplicate.id,
                        'theme_name': duplicate.theme_name,
                        'name_type': duplicate.name_type,
                        'name_type_desc': duplicate_name_type_desc,
                    }
                }, status=409)
            raise

        # 设置国际类关联（传入空列表则清空）
        if intl_class_codes is not None:
            record.international_classes.set(intl_class_codes)

        # 记录操作日志
        try:
            UserOperationLog.objects.create(
                user=request.user,
                operation_type=UserOperationLog.OperationType.TRO_UPDATE if replaced else UserOperationLog.OperationType.TRO_CREATE,
                operation_record=(f'替换侵权词: {theme_name}(ID:{record.id})'
                                  if replaced else f'新增侵权词: {theme_name}'),
                company=getattr(request.user, 'company', None)
            )
        except Exception as log_error:
            print(f'[日志记录失败] 新增: {log_error}')

        return JsonResponse({
            'success': True,
            'message': '替换成功' if replaced else '创建成功',
            'data': {
                'replaced': replaced,
                'id': record.id,
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'创建失败: {str(e)}'
        }, status=500)


@csrf_exempt
@require_POST
# @module_access_required('infringement', '侵权板块')
def api_update_tro_record(request):
    """
    编辑侵权词记录
    """
    try:
        data = json.loads(request.body)
        record_id = data.get('id')
        theme_name = data.get('theme_name', '').strip()
        name_type = data.get('name_type')

        if not record_id:
            return JsonResponse({'success': False, 'message': 'ID不能为空'}, status=400)

        try:
            record = TroTable.objects.select_related('shop', 'creator', 'creator__company').get(id=record_id)
        except TroTable.DoesNotExist:
            return JsonResponse({'success': False, 'message': '记录不存在'}, status=404)

        # 权限检查：只有创建人或管理员可编辑
        if not can_edit_tro_record(request.user, record):
            return JsonResponse({'success': False, 'message': '无权限编辑此记录'}, status=403)

        if not theme_name:
            return JsonResponse({'success': False, 'message': '侵权词不能为空'}, status=400)

        duplicate = (
            TroTable.objects.select_related('shop', 'creator', 'creator__company')
            .filter(theme_name__iexact=theme_name)
            .exclude(id=record.id)
            .first()
        )
        if duplicate:
            if not can_view_tro_record(request.user, duplicate):
                return inaccessible_duplicate_response(request.user, duplicate)
            return JsonResponse({
                'success': False,
                'message': f'{duplicate.theme_name}已存在，无法重复保存。',
            }, status=409)

        if not name_type:
            return JsonResponse({'success': False, 'message': '请选择类型码'}, status=400)

        try:
            name_type = int(name_type)
            if name_type not in NAME_TYPE_MAPPING:
                return JsonResponse({'success': False, 'message': '无效的类型码'}, status=400)
        except ValueError:
            return JsonResponse({'success': False, 'message': '类型码必须为数字'}, status=400)

        # 获取国际类列表
        intl_class_codes = data.get('international_classes')
        
        # 更新记录
        replacement_word = data.get('replacement_word')
        replacement_word = replacement_word.strip() if replacement_word else None
        category = data.get('category')
        category = int(category) if category else None
        shop_id = data.get('shop_id') or None
        if shop_id:
            if not AmazonShop.objects.filter(id=shop_id, company=request.user.company).exists():
                return JsonResponse({'success': False, 'message': '无权选择该店铺'}, status=403)
        record.theme_name = theme_name
        record.replacement_word = replacement_word
        record.name_type = name_type
        record.category = category
        record.shop_id = shop_id
        record.save()
        
        # 更新国际类关联（传入空列表会清空所有关联）
        if intl_class_codes is not None:
            record.international_classes.set(intl_class_codes)

        # 记录操作日志
        try:
            UserOperationLog.objects.create(
                user=request.user,
                operation_type=UserOperationLog.OperationType.TRO_UPDATE,
                operation_record=f'修改侵权词: {theme_name}(ID:{record_id})',
                company=getattr(request.user, 'company', None)
            )
        except Exception as log_error:
            print(f'[日志记录失败] 编辑: {log_error}')

        return JsonResponse({
            'success': True,
            'message': '更新成功'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'更新失败: {str(e)}'
        }, status=500)


@csrf_exempt
@require_POST
# @module_access_required('infringement', '侵权板块')
def api_delete_tro_record(request):
    """
    删除侵权词记录
    """
    try:
        data = json.loads(request.body)
        record_id = data.get('id')

        if not record_id:
            return JsonResponse({'success': False, 'message': 'ID不能为空'}, status=400)

        try:
            record = TroTable.objects.select_related('shop', 'creator', 'creator__company').get(id=record_id)
            theme_name = record.theme_name  # 先保存名称用于日志
            if not can_delete_tro_record(request.user, record):
                return JsonResponse({'success': False, 'message': '无权限删除此记录'}, status=403)
            record.delete()
        except TroTable.DoesNotExist:
            return JsonResponse({'success': False, 'message': '记录不存在'}, status=404)

        # 记录操作日志
        try:
            UserOperationLog.objects.create(
                user=request.user,
                operation_type=UserOperationLog.OperationType.TRO_DELETE,
                operation_record=f'删除侵权词: {theme_name}(ID:{record_id})',
                company=getattr(request.user, 'company', None)
            )
        except Exception as log_error:
            print(f'[日志记录失败] 删除: {log_error}')

        return JsonResponse({
            'success': True,
            'message': '删除成功'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'删除失败: {str(e)}'
        }, status=500)


@csrf_exempt
@require_POST
# @module_access_required('infringement', '侵权板块')
def api_trademark_info_list(request):
    """
    获取美标网词库列表
    """
    try:
        data = json.loads(request.body)

        # 基础查询集
        queryset = TrademarkInfo.objects.select_related(
            'status_code', 'mark_drawing_type', 'legal_entity_type'
        ).all()

        # 筛选条件
        word_mark = data.get('word_mark', '').strip()
        fuzzy_search = data.get('fuzzy_search', True)  # 默认为True（模糊搜索）

        if word_mark:
            if fuzzy_search:
                # 模糊搜索：包含即可（不区分大小写）
                queryset = queryset.filter(word_mark__icontains=word_mark)
            else:
                # 精确搜索：忽略大小写完全匹配
                queryset = queryset.filter(word_mark__iexact=word_mark)

        serial_number = data.get('serial_number', '').strip()
        if serial_number:
            queryset = queryset.filter(serial_number__icontains=serial_number)

        registration_number = data.get('registration_number', '').strip()
        if registration_number:
            queryset = queryset.filter(registration_number__icontains=registration_number)

        owner_name = data.get('owner_name', '').strip()
        if owner_name:
            queryset = queryset.filter(owner_name__icontains=owner_name)

        # 排序
        sort_field = data.get('sort_field', 'filing_date')
        sort_order = data.get('sort_order', 'desc')

        valid_sort_fields = ['serial_number', 'word_mark', 'filing_date', 'registration_date', 'transaction_date']
        if sort_field not in valid_sort_fields:
            sort_field = 'filing_date'

        if sort_order == 'desc':
            sort_field = f'-{sort_field}'

        queryset = queryset.order_by(sort_field)

        # 分页
        page = int(data.get('page', 1))
        page_size = int(data.get('page_size', 20))
        page_size = min(page_size, 100)

        paginator = Paginator(queryset, page_size)

        try:
            page_obj = paginator.page(page)
        except PageNotAnInteger:
            page_obj = paginator.page(1)
        except EmptyPage:
            page_obj = paginator.page(paginator.num_pages)

        # 序列化数据
        data_list = []
        for item in page_obj:
            data_list.append({
                'serial_number': item.serial_number,
                'word_mark': item.word_mark,
                'registration_number': item.registration_number or '',
                'filing_date': item.filing_date.strftime('%Y-%m-%d') if item.filing_date else '',
                'registration_date': item.registration_date.strftime('%Y-%m-%d') if item.registration_date else '',
                'transaction_date': item.transaction_date.strftime('%Y-%m-%d') if item.transaction_date else '',
                'status_code': str(item.status_code) if item.status_code else '',
                'mark_drawing_type': str(item.mark_drawing_type) if item.mark_drawing_type else '',
                'owner_name': item.owner_name or '',
                'intl_class': item.intl_class or '',
            })

        return JsonResponse({
            'success': True,
            'data': {
                'list': data_list,
                'total': paginator.count,
                'page': page_obj.number,
                'total_pages': paginator.num_pages,
                'page_size': page_size
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取数据失败: {str(e)}'
        }, status=500)

#====================更新：下载批量上传模板（2026.2.4）==========================
# @module_access_required('infringement', '侵权板块')
def download_templates(request):
    file_path = os.path.join(settings.BASE_DIR, 'theme/static/media/templates/侵权词上传.xlsx')
    if os.path.exists(file_path):
        #触发下载
        response = FileResponse(open(file_path, 'rb'), as_attachment=True, filename='侵权词上传模板.xlsx')
        return response
    else:
        raise Http404("文件不存在")


#====================更新：批量导入侵权词（2026.2.4）==========================
# @module_access_required('infringement', '侵权板块')
def api_nice_classification_list(request):
    """
    获取尼斯分类（国际类）列表
    """
    try:
        classifications = NiceClassification.objects.all().order_by('code')
        data_list = [
            {
                'code': item.code,
                'name': item.name,
                'category_type': item.category_type
            }
            for item in classifications
        ]
        return JsonResponse({
            'success': True,
            'data': data_list
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取国际类列表失败: {str(e)}'
        }, status=500)


# @module_access_required('infringement', '侵权板块')
def api_shop_list(request):
    """
    获取店铺列表
    """
    try:
        shops = AmazonShop.objects.filter(company=request.user.company).order_by('shop_name')
        data_list = [
            {
                'id': item.id,
                'name': item.shop_name or item.amazon_shop_name or f'店铺{item.id}',
            }
            for item in shops
        ]
        return JsonResponse({
            'success': True,
            'data': data_list
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取店铺列表失败: {str(e)}'
        }, status=500)


@csrf_exempt
@require_POST
# @module_access_required('infringement', '侵权板块')
def api_import_tro_records(request):
    """
    批量导入侵权词记录
    接收 Excel 文件，解析并批量插入到 TroTable
    支持去重：已存在的记录跳过，不重复写入
    """
    if 'file' not in request.FILES:
        return JsonResponse({'success': False, 'message': '请选择文件'}, status=400)

    uploaded_file = request.FILES['file']

    # 验证文件类型
    if not (uploaded_file.name.endswith('.xlsx') or uploaded_file.name.endswith('.xlsm')):
        return JsonResponse({'success': False, 'message': '仅支持 xlsx 或 xlsm 格式文件'}, status=400)

    try:
        # 读取 Excel 文件
        # 显式指定'侵权词'列为字符串类型，避免 pandas 将数字字符串解析为浮点数（例如 '100' 解析为 100.0）
        df = pd.read_excel(uploaded_file, dtype={'侵权词': str})

        # 验证必要的列
        required_columns = ['侵权词', '侵权类型码(数字)']
        if not all(col in df.columns for col in required_columns):
            return JsonResponse({
                'success': False,
                'message': 'Excel 格式错误，需要包含"侵权词"和"侵权类型码(数字)"两列'
            }, status=400)

        # 获取当前用户
        user_name = request.user.first_name or request.user.username

        # 获取数据库中已有侵权词；导入时也不能覆盖不可见的系统级词库
        existing_records = TroTable.objects.select_related('shop', 'creator', 'creator__company')
        existing_map = {item.theme_name: item for item in existing_records}

        # 统计变量
        success_count = 0      # 新增成功
        update_count = 0       # 更新成功
        skip_count = 0         # 已存在跳过
        error_count = 0        # 数据错误
        errors = []
        skipped_items = []     # 记录跳过的项

        for idx, row in df.iterrows():
            try:
                theme_name = str(row['侵权词']).strip() if pd.notna(row['侵权词']) else ''
                name_type = int(row['侵权类型码(数字)']) if pd.notna(row['侵权类型码(数字)']) else None

                # 如果两列都为空，则忽略该行（可能是Excel中的其他无关数据导致的空行）
                if not theme_name and name_type is None:
                    continue

                # 数据完整性检查
                if not theme_name or not name_type:
                    error_count += 1
                    errors.append(f'第 {idx + 2} 行: 数据不完整')
                    continue

                # 类型码合法性检查（1-10）
                if name_type not in NAME_TYPE_MAPPING:
                    error_count += 1
                    errors.append(f'第 {idx + 2} 行: 无效的类型码 {name_type}（需在1-11之间）')
                    continue

                # 检查是否已存在
                if theme_name in existing_map:
                    existing_record = existing_map[theme_name]
                    if not can_view_tro_record(request.user, existing_record):
                        error_count += 1
                        if is_system_tro_record(existing_record):
                            errors.append(f'第 {idx + 2} 行: 已存在于系统级词库，仅平台总管理员可替换')
                        else:
                            errors.append(f'第 {idx + 2} 行: 已存在于其他数据范围，无法导入')
                        continue

                    old_name_type = existing_record.name_type
                    # 如果类型码一致，跳过
                    if old_name_type == name_type:
                        skip_count += 1
                        skipped_items.append(theme_name)
                        continue

                    if not can_edit_tro_record(request.user, existing_record):
                        error_count += 1
                        errors.append(f'第 {idx + 2} 行: 无权限更新已有记录')
                        continue

                    existing_record.name_type = name_type
                    existing_record.update_time = timezone.now()
                    existing_record.save(update_fields=['name_type', 'update_time'])
                    update_count += 1
                    continue
            
                # 创建新记录
                record = TroTable.objects.create(
                    theme_name=theme_name,
                    name_type=name_type,
                    creator=request.user
                )
                success_count += 1
                # 添加到已存在集合，避免同一批次内重复
                existing_map[theme_name] = TroTable.objects.select_related(
                    'shop', 'creator', 'creator__company'
                ).get(id=record.id)

            except Exception as e:
                error_count += 1
                errors.append(f'第 {idx + 2} 行: {str(e)}')

        # 构建返回消息
        message_parts = []
        if success_count > 0:
            message_parts.append(f'新增 {success_count} 条')
        if update_count > 0:
            message_parts.append(f'更新 {update_count} 条')
        if skip_count > 0:
            message_parts.append(f'跳过 {skip_count} 条（已存在且类型一致）')
        if error_count > 0:
            message_parts.append(f'失败 {error_count} 条')

        # 记录操作日志（只有有成功导入或更新的时候才记录）
        if success_count > 0 or update_count > 0:
            try:
                UserOperationLog.objects.create(
                    user=request.user,
                    operation_type=UserOperationLog.OperationType.TRO_IMPORT,
                    operation_record=f'批量导入侵权词: 成功{success_count}条, 更新{update_count}条, 跳过{skip_count}条, 失败{error_count}条',
                    company=getattr(request.user, 'company', None)
                )
            except Exception as log_error:
                print(f'[日志记录失败] 导入: {log_error}')

        return JsonResponse({
            'success': True,
            'message': '导入完成：' + '，'.join(message_parts),
            'data': {
                'success_count': success_count,
                'update_count': update_count,
                'skip_count': skip_count,
                'error_count': error_count,
                'errors': errors[:10],
                'skipped_items': skipped_items[:10]  # 返回前10条跳过的项
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'导入失败: {str(e)}'
        }, status=500)
