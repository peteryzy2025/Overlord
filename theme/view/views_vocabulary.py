from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Q
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
from theme.models import TroTable, TrademarkInfo, NiceClassification
from general.models import AmazonShop
import os
from django.http import FileResponse, Http404
from django.conf import settings
import pandas as pd

# ============================================
# 1. 页面渲染视图
# ============================================

def is_admin(user):
    """判断用户是否为管理员（拥有code=555的权限）"""
    if not user.is_authenticated:
        return False
    # 超级管理员默认是管理员
    if user.is_superuser:
        return True
    try:
        return user.permission_configs.filter(code=555).exists()
    except Exception:
        return False


@login_required
def tro_table_page(request):
    """
    侵权词库页面
    """
    return render(request, 'tro_table.html', {
        'page_title': '侵权词库',
        'active_nav': 'theme_tro_table',
        'is_admin': is_admin(request.user),  # 传递管理员状态到前端
        'current_user': request.user.first_name or request.user.username,  # 传递当前用户名
    })


@login_required
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
    10: '知名IP'
}


@csrf_exempt
@require_POST
@login_required
def api_tro_table_list(request):
    """
    获取侵权词库列表
    """
    try:
        data = json.loads(request.body)

        # 基础查询集
        queryset = TroTable.objects.all()

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
            
            data_list.append({
                'id': item.id,
                'theme_name': item.theme_name,
                'name_type': item.name_type,
                'name_type_desc': NAME_TYPE_MAPPING.get(item.name_type, str(item.name_type)),
                'international_classes': intl_classes,
                'shop_id': item.shop_id,
                'shop_name': item.shop.name if item.shop else '-',
                'creator_name': item.creator.first_name if item.creator else (item.creator.username if item.creator else '-'),
                'creator_id': item.creator.id if item.creator else None,
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
@login_required
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

        # 创建记录
        record = TroTable.objects.create(
            theme_name=theme_name,
            name_type=name_type,
            creator=request.user,
            shop_id=data.get('shop_id') or None
        )
        
        # 设置国际类关联（传入空列表则清空）
        intl_class_codes = data.get('international_classes')
        if intl_class_codes is not None:
            record.international_classes.set(intl_class_codes)

        return JsonResponse({
            'success': True,
            'message': '创建成功'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'创建失败: {str(e)}'
        }, status=500)


@csrf_exempt
@require_POST
@login_required
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
            record = TroTable.objects.get(id=record_id)
        except TroTable.DoesNotExist:
            return JsonResponse({'success': False, 'message': '记录不存在'}, status=404)

        # 权限检查：只有创建人或管理员可编辑
        is_creator = record.creator_id == request.user.id if record.creator else False
        is_admin_user = is_admin(request.user)

        if not (is_creator or is_admin_user):
            return JsonResponse({'success': False, 'message': '无权限编辑此记录'}, status=403)

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

        # 获取国际类列表
        intl_class_codes = data.get('international_classes')
        
        # 更新记录
        record.theme_name = theme_name
        record.name_type = name_type
        record.shop_id = data.get('shop_id') or None
        record.save()
        
        # 更新国际类关联（传入空列表会清空所有关联）
        if intl_class_codes is not None:
            record.international_classes.set(intl_class_codes)

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
@login_required
def api_delete_tro_record(request):
    """
    删除侵权词记录
    """
    try:
        data = json.loads(request.body)
        record_id = data.get('id')

        if not record_id:
            return JsonResponse({'success': False, 'message': 'ID不能为空'}, status=400)

        # 权限检查：只有管理员可删除
        if not is_admin(request.user):
            return JsonResponse({'success': False, 'message': '只有管理员可以删除记录'}, status=403)

        try:
            record = TroTable.objects.get(id=record_id)
            record.delete()
        except TroTable.DoesNotExist:
            return JsonResponse({'success': False, 'message': '记录不存在'}, status=404)

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
@login_required
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
def download_templates(request):
    file_path = os.path.join(settings.BASE_DIR, 'theme/static/media/templates/侵权词上传.xlsx')
    if os.path.exists(file_path):
        #触发下载
        response = FileResponse(open(file_path, 'rb'), as_attachment=True, filename='侵权词上传模板.xlsx')
        return response
    else:
        raise Http404("文件不存在")


#====================更新：批量导入侵权词（2026.2.4）==========================
@login_required
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


@login_required
def api_shop_list(request):
    """
    获取店铺列表
    """
    try:
        shops = AmazonShop.objects.all().order_by('shop_name')
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
@login_required
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
        df = pd.read_excel(uploaded_file)

        # 验证必要的列
        required_columns = ['侵权词', '侵权类型码(数字)']
        if not all(col in df.columns for col in required_columns):
            return JsonResponse({
                'success': False,
                'message': 'Excel 格式错误，需要包含"侵权词"和"侵权类型码(数字)"两列'
            }, status=400)

        # 获取当前用户
        user_name = request.user.first_name or request.user.username

        # 获取数据库中已有的侵权词列表（用于去重）
        existing_records = TroTable.objects.values_list('theme_name', flat=True)
        existing_set = set(existing_records)

        # 统计变量
        success_count = 0      # 新增成功
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
                    errors.append(f'第 {idx + 2} 行: 无效的类型码 {name_type}（需在1-10之间）')
                    continue

                # 去重检查：是否已存在
                if theme_name in existing_set:
                    skip_count += 1
                    skipped_items.append(theme_name)
                    continue

                # 创建新记录
                TroTable.objects.create(
                    theme_name=theme_name,
                    name_type=name_type,
                    creator=request.user
                )
                success_count += 1
                # 添加到已存在集合，避免同一批次内重复
                existing_set.add(theme_name)

            except Exception as e:
                error_count += 1
                errors.append(f'第 {idx + 2} 行: {str(e)}')

        # 构建返回消息
        message_parts = []
        if success_count > 0:
            message_parts.append(f'新增 {success_count} 条')
        if skip_count > 0:
            message_parts.append(f'跳过 {skip_count} 条（已存在）')
        if error_count > 0:
            message_parts.append(f'失败 {error_count} 条')

        return JsonResponse({
            'success': True,
            'message': '导入完成：' + '，'.join(message_parts),
            'data': {
                'success_count': success_count,
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
