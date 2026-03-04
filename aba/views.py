"""
ABA 数据管理视图
"""
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from datetime import datetime, timedelta

from aba.models import SearchTerm, SearchTermMetric


def aba_data_page(request):
    """
    ABA 数据管理页面
    """
    return render(request, 'aba/aba_data.html', {'active_page': 'aba_data'})


@require_http_methods(["GET"])
def get_aba_data_api(request):
    """
    获取 ABA 数据列表 API
    
    参数:
        week: 周期（日期，如 2026-02-15）
        search_term: 搜索词（模糊搜索）
        page: 页码，默认 1
        page_size: 每页条数，默认 50
    """
    try:
        # 获取参数
        week = request.GET.get('week', '')
        search_term = request.GET.get('search_term', '').strip()
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 50))
        
        # 验证 page_size
        if page_size not in [20, 50, 100, 200]:
            page_size = 50
        
        # 基础查询 - 使用 aba_db 数据库
        queryset = SearchTermMetric.objects.using('aba_db').select_related('search_term')
        
        # 按周期筛选
        if week:
            try:
                week_date = datetime.strptime(week, "%Y-%m-%d").date()
                queryset = queryset.filter(report_week=week_date)
            except ValueError:
                pass
        else:
            # 默认显示最新一周
            latest_week = SearchTermMetric.objects.using('aba_db').order_by('-report_week').values_list('report_week', flat=True).first()
            if latest_week:
                queryset = queryset.filter(report_week=latest_week)
        
        # 按搜索词筛选（支持不同匹配模式）
        search_mode = request.GET.get('search_mode', '0')
        if search_term:
            if search_mode == '0':  # 精准查询 - 完全匹配
                queryset = queryset.filter(search_term__term__iexact=search_term)
            elif search_mode == '2':  # 广泛匹配 - 空格分隔关键词，AND关系，整词匹配
                keywords = search_term.strip().split()
                if keywords:
                    # 必须同时包含所有关键词（AND关系），每个都是整词匹配
                    for keyword in keywords:
                        # 使用正则表达式实现整词匹配
                        # \y 是 PostgreSQL 的单词边界，匹配独立单词
                        queryset = queryset.filter(search_term__term__iregex=rf'\y{keyword}\y')
            else:  # 默认模糊查询 - 子串匹配
                queryset = queryset.filter(search_term__term__icontains=search_term)
        
        # 排序：按排名升序
        queryset = queryset.order_by('search_frequency_rank')
        
        # 分页
        paginator = Paginator(queryset, page_size)
        total = paginator.count
        total_pages = paginator.num_pages
        
        try:
            page_obj = paginator.page(page)
        except Exception:
            page_obj = paginator.page(1)
            page = 1
        
        # 获取趋势数据（最近4周）
        metrics_with_trend = []
        for metric in page_obj:
            # 查询该搜索词最近13周的趋势（共14周数据）
            trend_data = SearchTermMetric.objects.using('aba_db').filter(
                search_term=metric.search_term,
                report_week__gte=metric.report_week - timedelta(days=91)
            ).order_by('report_week').values('report_week', 'search_frequency_rank')
            
            trend_list = [
                {
                    'week': t['report_week'].strftime('%Y-%m-%d'),  # 传递完整日期，包含年份
                    'rank': t['search_frequency_rank']
                }
                for t in trend_data
            ]
            
            # 计算前三商品总份额
            total_click_share = (
                (metric.asin_1_click_share or 0) +
                (metric.asin_2_click_share or 0) +
                (metric.asin_3_click_share or 0)
            )
            total_conversion_share = (
                (metric.asin_1_conversion_share or 0) +
                (metric.asin_2_conversion_share or 0) +
                (metric.asin_3_conversion_share or 0)
            )
            
            metrics_with_trend.append({
                'id': metric.id,
                'search_term': metric.search_term.term,
                'search_term_id': metric.search_term.id,
                'search_frequency_rank': metric.search_frequency_rank,
                'rank_change': metric.rank_change,
                'trend': trend_list,
                'total_click_share': round(total_click_share * 100, 2),  # 转为百分比
                'total_conversion_share': round(total_conversion_share * 100, 2),
                'report_week': metric.report_week.strftime('%Y-%m-%d'),
                # ASIN 详情
                'asin_1': {
                    'code': metric.asin_1_code,
                    'title': metric.asin_1_title,
                    'click_share': round((metric.asin_1_click_share or 0) * 100, 2),
                    'conversion_share': round((metric.asin_1_conversion_share or 0) * 100, 2),
                },
                'asin_2': {
                    'code': metric.asin_2_code,
                    'title': metric.asin_2_title,
                    'click_share': round((metric.asin_2_click_share or 0) * 100, 2) if metric.asin_2_click_share else None,
                    'conversion_share': round((metric.asin_2_conversion_share or 0) * 100, 2) if metric.asin_2_conversion_share else None,
                },
                'asin_3': {
                    'code': metric.asin_3_code,
                    'title': metric.asin_3_title,
                    'click_share': round((metric.asin_3_click_share or 0) * 100, 2) if metric.asin_3_click_share else None,
                    'conversion_share': round((metric.asin_3_conversion_share or 0) * 100, 2) if metric.asin_3_conversion_share else None,
                },
            })
        
        return JsonResponse({
            'success': True,
            'data': metrics_with_trend,
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


@require_http_methods(["GET"])
def get_available_weeks_api(request):
    """
    获取可用的周期（周）列表
    格式：2026年第8周 (02.22-02.28)
    """
    try:
        weeks = SearchTermMetric.objects.using('aba_db').values_list('report_week', flat=True).distinct().order_by('-report_week')
        
        week_list = []
        for w in weeks:
            # 计算年度第几周
            week_number = w.isocalendar()[1]
            # 计算周期结束日期（周六）
            end_date = w + timedelta(days=6)
            # 格式化标签
            label = f"{w.year}年第{week_number}周 ({w.strftime('%m.%d')}-{end_date.strftime('%m.%d')})"
            
            week_list.append({
                'value': w.strftime('%Y-%m-%d'),
                'label': label
            })
        
        return JsonResponse({
            'success': True,
            'data': week_list
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
