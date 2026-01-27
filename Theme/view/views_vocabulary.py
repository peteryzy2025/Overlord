from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Q
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
from theme.models import TroTable, TrademarkInfo


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

        name_type = data.get('name_type')
        if name_type:
            try:
                queryset = queryset.filter(name_type=int(name_type))
            except ValueError:
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
            data_list.append({
                'id': item.id,
                'theme_name': item.theme_name,
                'name_type': item.name_type,
                'name_type_desc': NAME_TYPE_MAPPING.get(item.name_type, str(item.name_type)),
                'created_by': item.created_by or '-',
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
        user_name = request.user.first_name or request.user.username
        TroTable.objects.create(
            theme_name=theme_name,
            name_type=name_type,
            created_by=user_name
        )

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
        current_user_name = request.user.first_name or request.user.username
        is_creator = record.created_by == current_user_name
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

        # 更新记录
        record.theme_name = theme_name
        record.name_type = name_type
        record.save()

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

