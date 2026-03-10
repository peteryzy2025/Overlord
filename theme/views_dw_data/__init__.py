"""
迪唯产业大数据模型 - 视图
"""
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.db.models import Q

from theme.models import MarketCategory, NicheMarket


def dw_data_page(request):
    """
    迪唯产业大数据模型页面
    """
    return render(request, 'dw_data/dw_data.html', {'active_page': 'dw_data'})


@require_http_methods(["GET"])
def api_market_categories(request):
    """
    获取市场分类列表 API
    
    返回所有叶子分类（有细分市场的分类）
    """
    try:
        # 获取所有有细分市场的分类
        categories = MarketCategory.objects.filter(
            niche_markets__isnull=False
        ).distinct().order_by('path', 'name')
        
        category_list = []
        for cat in categories:
            # 构建完整路径名称
            path_names = []
            if cat.path:
                path_ids = cat.path.strip('/').split('/')
                for pid in path_ids:
                    try:
                        parent = MarketCategory.objects.get(id=int(pid))
                        path_names.append(parent.name)
                    except (MarketCategory.DoesNotExist, ValueError):
                        continue
            path_names.append(cat.name)
            full_path = ' › '.join(path_names)
            
            category_list.append({
                'value': str(cat.id),
                'label': full_path
            })
        
        return JsonResponse({
            'success': True,
            'data': category_list
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_http_methods(["GET"])
def api_niche_markets(request):
    """
    获取细分市场数据列表 API
    
    参数:
        category: 分类ID
        search: 搜索关键词（匹配市场名称或中文名称）
        page: 页码，默认 1
        page_size: 每页条数，默认 50
    """
    try:
        # 获取参数
        category_id = request.GET.get('category', '').strip()
        search = request.GET.get('search', '').strip()
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 50))
        
        # 验证 page_size
        if page_size not in [20, 50, 100, 200]:
            page_size = 50
        
        # 基础查询
        queryset = NicheMarket.objects.select_related('leaf_category')
        
        # 按分类筛选
        if category_id:
            queryset = queryset.filter(leaf_category_id=category_id)
        
        # 按搜索词筛选
        if search:
            queryset = queryset.filter(
                Q(market_name__icontains=search) |
                Q(market_name_cn__icontains=search)
            )
        
        # 排序：按ID升序
        queryset = queryset.order_by('id')
        
        # 分页
        paginator = Paginator(queryset, page_size)
        total = paginator.count
        total_pages = paginator.num_pages
        
        try:
            page_obj = paginator.page(page)
        except Exception:
            page_obj = paginator.page(1)
            page = 1
        
        # 构建返回数据
        data_list = []
        for item in page_obj:
            # 构建分类路径
            category_path = []
            if item.leaf_category:
                cat = item.leaf_category
                if cat.path:
                    path_ids = cat.path.strip('/').split('/')
                    for pid in path_ids:
                        try:
                            parent = MarketCategory.objects.get(id=int(pid))
                            category_path.append(parent.name)
                        except (MarketCategory.DoesNotExist, ValueError):
                            continue
                category_path.append(cat.name)
            
            data_list.append({
                'id': item.id,
                'market_name': item.market_name,
                'market_name_cn': item.market_name_cn,
                'monthly_sales': item.monthly_sales,
                'monthly_revenue': str(item.monthly_revenue) if item.monthly_revenue else None,
                'category_path': category_path,
                'leaf_category_id': item.leaf_category_id,
            })
        
        return JsonResponse({
            'success': True,
            'data': data_list,
            'total': total,
            'page': page,
            'total_pages': total_pages,
            'page_size': page_size
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
