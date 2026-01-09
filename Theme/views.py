# views.py
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Q, Count, Max, Min, OuterRef, Subquery
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import datetime, timedelta
import json
import csv
from io import StringIO
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment

# 导入你的模型
from .models import AmazonProduct, ProductRankHistory


# ============================================
# 1. 页面渲染视图
# ============================================

@login_required
def product_list_page(request):
    """
    产品列表页面 - 渲染产品管理界面
    访问地址: /amazon/products/
    """
    # 获取当前用户的权限信息（可根据需要扩展）
    user = request.user

    # 获取一些统计数据用于页面展示
    total_products = AmazonProduct.objects.count()

    # 近七日新增主题（根据上架日期），统计去重主题数量
    seven_days_ago = timezone.now().date() - timedelta(days=7)
    recent_subjects_7d = AmazonProduct.objects.filter(
        launch_date__gte=seven_days_ago
    ).exclude(
        subject__isnull=True
    ).exclude(
        subject=''
    ).values('subject').distinct().count()

    # 本月新增产品数量
    now = timezone.now()
    first_day_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    recent_products = AmazonProduct.objects.filter(
        created_at__gte=first_day_of_month
    ).count()

    stats = {
        'total_products': total_products,
        'recent_subjects_7d': recent_subjects_7d,
        'recent_products': recent_products,
    }

    # 获取产品类型分布
    product_types = AmazonProduct.objects.values('product_type').annotate(
        count=Count('product_type')
    ).order_by('-count')

    # 获取产品上市日期范围（用于筛选器）
    date_range = AmazonProduct.objects.aggregate(
        min_launch_date=Min('launch_date'),
        max_launch_date=Max('launch_date'),
        min_created_at=Min('created_at'),
        max_created_at=Max('created_at')
    )

    context = {
        'page_title': 'Amazon产品管理',
        'stats': stats,
        'product_types': product_types,
        'date_range': date_range,
        'current_user': user,
        'product_type_choices': AmazonProduct.PRODUCT_TYPE_CHOICES,
    }

    return render(request, 'amazon_products_display.html', context)


# ============================================
# 2. 产品数据API接口
# ============================================

@csrf_exempt
@require_POST
def api_amazon_products(request):
    """
    产品数据API接口 - 提供产品列表数据（支持筛选、排序、分页）
    请求方法: POST
    请求地址: /api/amazon-products/
    请求体: JSON格式的筛选、排序、分页参数
    """
    try:
        # 1. 解析请求数据
        data = json.loads(request.body)

        # 2. 基础查询集：基于排名历史
        queryset = ProductRankHistory.objects.select_related('product').all()

        # 3. 应用筛选条件

        # ASIN筛选（精确或模糊）
        asin_filter = data.get('asin', '').strip()
        if asin_filter:
            queryset = queryset.filter(product__asin__icontains=asin_filter)

        # 标题筛选（支持中英文）
        title_filter = data.get('title', '').strip()
        if title_filter:
            queryset = queryset.filter(
                Q(product__title__icontains=title_filter) |
                Q(product__title_translation__icontains=title_filter)
            )

        # 主题筛选
        subject_filter = data.get('subject', '').strip()
        if subject_filter:
            queryset = queryset.filter(
                Q(product__subject__icontains=subject_filter) |
                Q(product__subject_translation__icontains=subject_filter)
            )

        # 产品类型筛选
        product_type = data.get('product_type', '').strip()
        if product_type:
            queryset = queryset.filter(product__product_type=product_type)

        # 上市日期范围筛选
        launch_date_start = data.get('launch_date_start', '').strip()
        launch_date_end = data.get('launch_date_end', '').strip()

        if launch_date_start:
            try:
                start_date = datetime.strptime(launch_date_start, '%Y-%m-%d').date()
                queryset = queryset.filter(product__launch_date__gte=start_date)
            except ValueError:
                pass

        if launch_date_end:
            try:
                end_date = datetime.strptime(launch_date_end, '%Y-%m-%d').date()
                queryset = queryset.filter(product__launch_date__lte=end_date)
            except ValueError:
                pass

        # 爬取日期范围筛选 (created_at_start/end 实际对应 crawl_date)
        crawled_at_start = data.get('created_at_start', '').strip()
        crawled_at_end = data.get('created_at_end', '').strip()

        if crawled_at_start:
            try:
                start_date = datetime.strptime(crawled_at_start, '%Y-%m-%d').date()
                queryset = queryset.filter(crawl_date__gte=start_date)
            except ValueError:
                pass

        if crawled_at_end:
            try:
                end_date = datetime.strptime(crawled_at_end, '%Y-%m-%d').date()
                queryset = queryset.filter(crawl_date__lte=end_date)
            except ValueError:
                pass

        # 4. 应用排序
        sort_field = data.get('sort_field', 'crawl_date')
        sort_order = data.get('sort_order', 'desc')

        # 映射前端排序字段到模型字段
        sort_map = {
            'asin': 'product__asin',
            'title': 'product__title',
            'subject': 'product__subject',
            'launch_date': 'product__launch_date',
            'created_at': 'crawl_date', # 兼容旧字段名
            'latest_crawled_at': 'crawled_at', # 对应具体记录的抓取时间
            'product_type': 'product__product_type',
            'latest_rank': 'rank' # 对应具体记录的排名
        }
        
        real_sort_field = sort_map.get(sort_field, 'crawl_date')

        # 处理降序排序
        if sort_order == 'desc':
            real_sort_field = f'-{real_sort_field}'

        queryset = queryset.order_by(real_sort_field)

        # 5. 分页处理
        page = data.get('page', 1)
        page_size = data.get('page_size', 20)

        # 验证页码和页大小
        try:
            page = int(page)
            if page < 1:
                page = 1
        except (ValueError, TypeError):
            page = 1

        try:
            page_size = int(page_size)
            if page_size not in [10, 20, 50, 100]:
                page_size = 20
        except (ValueError, TypeError):
            page_size = 20

        paginator = Paginator(queryset, page_size)

        try:
            current_page = paginator.page(page)
        except PageNotAnInteger:
            current_page = paginator.page(1)
        except EmptyPage:
            current_page = paginator.page(paginator.num_pages)

        # 6. 序列化数据
        history_list = []
        for history in current_page:
            product = history.product
            
            # 获取产品类型显示名称
            product_type_display = product.get_product_type_display()

            # 格式化日期字段
            launch_date = None
            if product.launch_date:
                launch_date = product.launch_date.strftime('%Y-%m-%d')

            # 构建排名信息
            rank_info = {
                'rank': history.rank,
                'category': history.rank_category,
                'crawl_date': history.crawl_date.strftime('%Y-%m-%d'),
                'crawled_at': history.crawled_at.strftime('%Y-%m-%d %H:%M:%S') if history.crawled_at else None,
            }

            history_list.append({
                'id': history.id,       # 记录ID
                'asin': product.asin,   # 产品ASIN
                'title': product.title or '',
                'title_translation': product.title_translation or '',
                'subject': product.subject or '',
                'subject_translation': product.subject_translation or '',
                'image_url': product.image_url or '',
                'launch_date': launch_date,
                'created_at': product.created_at.strftime('%Y-%m-%d %H:%M:%S') if product.created_at else None, # 产品首次抓取时间
                'latest_crawled_at': history.crawled_at.strftime('%Y-%m-%d %H:%M:%S') if history.crawled_at else None, # 当前记录抓取时间
                'product_type': product.product_type or '',
                'product_type_display': product_type_display,
                'latest_rank': rank_info, # 复用字段名以减少前端改动
            })

        # 7. 计算统计数据 (保持产品维度的统计，除了列表总数)
        total_records = paginator.count
        
        # 产品总数 (独立查询)
        total_products = AmazonProduct.objects.count()

        # 本月新增产品数量 (独立查询)
        now = timezone.now()
        first_day_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_count = AmazonProduct.objects.filter(
            created_at__gte=first_day_of_month
        ).count()

        # 产品类型分布 (独立查询)
        product_types_distribution = list(
            AmazonProduct.objects.values('product_type').annotate(
                count=Count('product_type')
            ).order_by('-count')
        )

        # 为每个产品类型添加显示名称
        for item in product_types_distribution:
            product_type_code = item['product_type']
            try:
                product_obj = AmazonProduct(product_type=product_type_code)
                item['product_type_display'] = product_obj.get_product_type_display()
            except:
                item['product_type_display'] = product_type_code

        # 8. 返回响应
        return JsonResponse({
            'success': True,
            'data': {
                'products': history_list, # 列表现在是历史记录
                'total': total_records,
                'total_pages': paginator.num_pages,
                'current_page': current_page.number,
                'page_size': page_size,
                'has_next': current_page.has_next(),
                'has_previous': current_page.has_previous(),
                'next_page': current_page.next_page_number() if current_page.has_next() else None,
                'previous_page': current_page.previous_page_number() if current_page.has_previous() else None,

                # 统计信息
                'stats': {
                    'total_products': total_products, # 仍显示产品总数
                    'recent_subjects_7d': AmazonProduct.objects.filter(
                        launch_date__gte=(timezone.now().date() - timedelta(days=7))
                    ).exclude(subject__isnull=True).exclude(subject='').values('subject').distinct().count(),
                    'monthly_count': monthly_count,
                    'product_types': len(product_types_distribution),
                },

                # 分布信息
                'distribution': {
                    'product_types': product_types_distribution,
                }
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': '无效的JSON数据格式'
        }, status=400)
    except Exception as e:
        # 记录错误日志
        print(f"API错误: {str(e)}")
        import traceback
        traceback.print_exc()

        return JsonResponse({
            'success': False,
            'message': f'服务器内部错误: {str(e)}',
            'debug_info': {
                'error_type': type(e).__name__,
            }
        }, status=500)


# ============================================
# 3. 产品详情API
# ============================================

@login_required
def api_product_detail(request, asin):
    """
    获取单个产品的详细信息
    请求方法: GET
    请求地址: /api/amazon-products/<asin>/
    """
    try:
        product = get_object_or_404(AmazonProduct, asin=asin)

        # 获取产品的排名历史
        rank_history = product.rank_history.order_by('-crawl_date').values(
            'crawl_date', 'rank', 'rank_category', 'crawled_at'
        )[:30]  # 只取最近30天的数据

        # 将排名历史转换为列表并格式化日期
        rank_history_list = []
        for rank in rank_history:
            rank_history_list.append({
                'crawl_date': rank['crawl_date'].strftime('%Y-%m-%d'),
                'rank': rank['rank'],
                'rank_category': rank['rank_category'],
                'crawled_at': rank['crawled_at'].strftime('%Y-%m-%d %H:%M:%S'),
            })

        # 获取产品类型显示名称
        product_type_display = product.get_product_type_display()

        # 格式化数据
        data = {
            'asin': product.asin,
            'title': product.title or '',
            'title_translation': product.title_translation or '',
            'subject': product.subject or '',
            'subject_translation': product.subject_translation or '',
            'image_url': product.image_url or '',
            'launch_date': product.launch_date.strftime('%Y-%m-%d') if product.launch_date else '',
            'created_at': product.created_at.strftime('%Y-%m-%d %H:%M:%S') if product.created_at else '',
            'product_type': product.product_type or '',
            'product_type_display': product_type_display,
            'rank_history': rank_history_list,
            'rank_history_count': len(rank_history_list),
        }

        return JsonResponse({
            'success': True,
            'data': data
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取产品详情失败: {str(e)}'
        }, status=500)


# ============================================
# 4. 产品操作API
# ============================================

@csrf_exempt
@require_POST
@login_required
def api_create_product(request):
    """
    创建新产品
    请求方法: POST
    请求地址: /api/amazon-products/create/
    """
    try:
        data = json.loads(request.body)

        # 验证必填字段
        required_fields = ['asin', 'title']
        for field in required_fields:
            if not data.get(field):
                return JsonResponse({
                    'success': False,
                    'message': f'缺少必填字段: {field}'
                }, status=400)

        # 检查ASIN是否已存在
        asin = data['asin'].strip().upper()
        if AmazonProduct.objects.filter(asin=asin).exists():
            return JsonResponse({
                'success': False,
                'message': f'ASIN {asin} 已存在'
            }, status=400)

        # 验证产品类型是否在可选范围内
        product_type = data.get('product_type', '')
        valid_product_types = [choice[0] for choice in AmazonProduct.PRODUCT_TYPE_CHOICES]
        if product_type and product_type not in valid_product_types:
            return JsonResponse({
                'success': False,
                'message': f'无效的产品类型: {product_type}'
            }, status=400)

        # 创建新产品
        product = AmazonProduct(
            asin=asin,
            title=data['title'].strip(),
            title_translation=data.get('title_translation', '').strip(),
            subject=data.get('subject', '').strip(),
            subject_translation=data.get('subject_translation', '').strip(),
            image_url=data.get('image_url', '').strip(),
            product_type=product_type,
        )

        # 处理上市日期
        launch_date = data.get('launch_date', '').strip()
        if launch_date:
            try:
                product.launch_date = datetime.strptime(launch_date, '%Y-%m-%d').date()
            except ValueError:
                return JsonResponse({
                    'success': False,
                    'message': '上市日期格式无效，请使用YYYY-MM-DD格式'
                }, status=400)

        product.save()

        return JsonResponse({
            'success': True,
            'message': '产品创建成功',
            'data': {
                'asin': product.asin,
                'title': product.title
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': '无效的JSON数据格式'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'创建产品失败: {str(e)}'
        }, status=500)


@csrf_exempt
@require_POST
@login_required
def api_update_product(request, asin):
    """
    更新产品信息
    请求方法: POST
    请求地址: /api/amazon-products/<asin>/update/
    """
    try:
        product = get_object_or_404(AmazonProduct, asin=asin)
        data = json.loads(request.body)

        # 验证产品类型是否在可选范围内
        if 'product_type' in data:
            product_type = data.get('product_type', '').strip()
            valid_product_types = [choice[0] for choice in AmazonProduct.PRODUCT_TYPE_CHOICES]
            if product_type and product_type not in valid_product_types:
                return JsonResponse({
                    'success': False,
                    'message': f'无效的产品类型: {product_type}'
                }, status=400)

        # 更新字段
        update_fields = []

        if 'title' in data:
            product.title = data['title'].strip()
            update_fields.append('title')

        if 'title_translation' in data:
            product.title_translation = data['title_translation'].strip()
            update_fields.append('title_translation')

        if 'subject' in data:
            product.subject = data['subject'].strip()
            update_fields.append('subject')

        if 'subject_translation' in data:
            product.subject_translation = data['subject_translation'].strip()
            update_fields.append('subject_translation')

        if 'image_url' in data:
            product.image_url = data['image_url'].strip()
            update_fields.append('image_url')

        if 'product_type' in data:
            product.product_type = data['product_type'].strip()
            update_fields.append('product_type')

        # 更新上市日期
        if 'launch_date' in data:
            launch_date = data['launch_date'].strip()
            if launch_date:
                try:
                    product.launch_date = datetime.strptime(launch_date, '%Y-%m-%d').date()
                    update_fields.append('launch_date')
                except ValueError:
                    return JsonResponse({
                        'success': False,
                        'message': '上市日期格式无效，请使用YYYY-MM-DD格式'
                    }, status=400)
            else:
                product.launch_date = None
                update_fields.append('launch_date')

        # 保存更新
        if update_fields:
            product.save(update_fields=update_fields)

        return JsonResponse({
            'success': True,
            'message': '产品更新成功',
            'data': {
                'asin': product.asin,
                'title': product.title
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': '无效的JSON数据格式'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'更新产品失败: {str(e)}'
        }, status=500)


@csrf_exempt
@require_POST
@login_required
def api_delete_product(request, asin):
    """
    删除产品
    请求方法: POST
    请求地址: /api/amazon-products/<asin>/delete/
    """
    try:
        product = get_object_or_404(AmazonProduct, asin=asin)

        # 删除产品及其关联的排名历史
        product.delete()

        return JsonResponse({
            'success': True,
            'message': '产品删除成功'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'删除产品失败: {str(e)}'
        }, status=500)


# ============================================
# 5. 导出功能
# ============================================

@login_required
def export_products_csv(request):
    try:
        scope = request.GET.get('scope', 'all')
        queryset = ProductRankHistory.objects.select_related('product').all()

        if scope == 'selected':
            # 这里的asins现在可能是历史记录的ID，或者产品的ASIN。
            # 鉴于列表是历史记录，如果选中也是历史记录ID。
            # 但前端之前的选中逻辑是产品ASIN。如果前端改了，这里也要改。
            # 假设前端现在选中传递的是 ASIN (因为批量操作通常针对产品)，那么这里可能需要调整。
            # 如果列表显示多条记录，同一个ASIN可能出现多次。
            # 既然是“导出历史记录”，且列表按历史记录展示，选中的应该是历史记录ID。
            ids = request.GET.get('asins', '') # 参数名暂时保持为asins，实际传id
            id_list = [i.strip() for i in ids.split(',') if i.strip()]
            if id_list:
                # 尝试判断是ASIN还是数字ID。ASIN通常是字母数字混合，ID是数字。
                # 简单起见，如果列表行的checkbox value是history.id，那么这里接收的就是history.id
                queryset = queryset.filter(id__in=id_list)
            else:
                queryset = queryset.none()
        elif scope == 'filtered':
            asin_filter = request.GET.get('asin', '').strip()
            if asin_filter:
                queryset = queryset.filter(product__asin__icontains=asin_filter)
            title_filter = request.GET.get('title', '').strip()
            if title_filter:
                queryset = queryset.filter(Q(product__title__icontains=title_filter) | Q(product__title_translation__icontains=title_filter))
            subject_filter = request.GET.get('subject', '').strip()
            if subject_filter:
                queryset = queryset.filter(Q(product__subject__icontains=subject_filter) | Q(product__subject_translation__icontains=subject_filter))
            product_type = request.GET.get('product_type', '').strip()
            if product_type:
                queryset = queryset.filter(product__product_type=product_type)
            launch_date_start = request.GET.get('launch_date_start', '').strip()
            launch_date_end = request.GET.get('launch_date_end', '').strip()
            if launch_date_start:
                try:
                    start_date = datetime.strptime(launch_date_start, '%Y-%m-%d').date()
                    queryset = queryset.filter(product__launch_date__gte=start_date)
                except ValueError:
                    pass
            if launch_date_end:
                try:
                    end_date = datetime.strptime(launch_date_end, '%Y-%m-%d').date()
                    queryset = queryset.filter(product__launch_date__lte=end_date)
                except ValueError:
                    pass
            # 爬取日期
            crawled_at_start = request.GET.get('created_at_start', '').strip()
            crawled_at_end = request.GET.get('created_at_end', '').strip()
            if crawled_at_start:
                try:
                    start_date = datetime.strptime(crawled_at_start, '%Y-%m-%d').date()
                    queryset = queryset.filter(crawl_date__gte=start_date)
                except ValueError:
                    pass
            if crawled_at_end:
                try:
                    end_date = datetime.strptime(crawled_at_end, '%Y-%m-%d').date()
                    queryset = queryset.filter(crawl_date__lte=end_date)
                except ValueError:
                    pass

        sort_field = request.GET.get('sort_field', 'crawl_date')
        sort_order = request.GET.get('sort_order', 'asc')
        
        sort_map = {
            'asin': 'product__asin',
            'title': 'product__title',
            'subject': 'product__subject',
            'launch_date': 'product__launch_date',
            'created_at': 'crawl_date',
            'latest_crawled_at': 'crawled_at',
            'product_type': 'product__product_type',
            'latest_rank': 'rank'
        }
        real_sort_field = sort_map.get(sort_field, 'crawl_date')
        if sort_order == 'desc':
            real_sort_field = f'-{real_sort_field}'
        queryset = queryset.order_by(real_sort_field)

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="amazon_products_history.csv"'

        writer = csv.writer(response)

        writer.writerow([
            'ASIN', '产品标题', '标题翻译', '产品主题', '主题翻译',
            '图片链接', '上架时间', '首次抓取时间', '产品类型',
            '排名', '排名大类', '数据日期', '爬取时间'
        ])

        for history in queryset:
            product = history.product
            writer.writerow([
                product.asin,
                product.title,
                product.title_translation,
                product.subject,
                product.subject_translation,
                product.image_url,
                product.launch_date.strftime('%Y-%m-%d') if product.launch_date else '',
                product.created_at.strftime('%Y-%m-%d %H:%M:%S') if product.created_at else '',
                product.get_product_type_display(),
                history.rank,
                history.rank_category,
                history.crawl_date.strftime('%Y-%m-%d'),
                history.crawled_at.strftime('%Y-%m-%d %H:%M:%S') if history.crawled_at else '',
            ])

        return response

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'导出CSV失败: {str(e)}'
        }, status=500)


@login_required
def export_products_json(request):
    """
    导出产品数据为JSON文件
    请求方法: GET
    请求地址: /amazon/products/export/json/
    """
    try:
        # 获取所有产品
        products = AmazonProduct.objects.all().order_by('asin')

        # 序列化数据
        products_data = []
        for product in products:
            products_data.append({
                'asin': product.asin,
                'title': product.title,
                'title_translation': product.title_translation,
                'subject': product.subject,
                'subject_translation': product.subject_translation,
                'image_url': product.image_url,
                'launch_date': product.launch_date.strftime('%Y-%m-%d') if product.launch_date else None,
                'created_at': product.created_at.strftime('%Y-%m-%d %H:%M:%S') if product.created_at else None,
                'product_type': product.product_type,
                'product_type_display': product.get_product_type_display(),
            })

        # 创建JSON响应
        response = JsonResponse({
            'success': True,
            'data': products_data,
            'count': len(products_data),
            'exported_at': timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        })

        # 设置响应头，使其作为文件下载
        response['Content-Disposition'] = 'attachment; filename="amazon_products.json"'

        return response

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'导出JSON失败: {str(e)}'
        }, status=500)


# ============================================
# 6. 批量操作
# ============================================

@csrf_exempt
@require_POST
@login_required
def api_bulk_update_product_type(request):
    """
    批量更新产品类型
    请求方法: POST
    请求地址: /api/amazon-products/bulk-update-type/
    """
    try:
        data = json.loads(request.body)

        # 验证必填字段
        if not data.get('asins') or not data.get('product_type'):
            return JsonResponse({
                'success': False,
                'message': '缺少必填字段: asins 或 product_type'
            }, status=400)

        asins = data['asins']  # ASIN列表
        product_type = data['product_type'].strip()

        # 验证产品类型是否在可选范围内
        valid_product_types = [choice[0] for choice in AmazonProduct.PRODUCT_TYPE_CHOICES]
        if product_type not in valid_product_types:
            return JsonResponse({
                'success': False,
                'message': f'无效的产品类型: {product_type}'
            }, status=400)

        # 批量更新
        updated_count = AmazonProduct.objects.filter(asin__in=asins).update(
            product_type=product_type
        )

        return JsonResponse({
            'success': True,
            'message': f'成功更新 {updated_count} 个产品的类型',
            'data': {
                'updated_count': updated_count,
                'product_type': product_type
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': '无效的JSON数据格式'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'批量更新失败: {str(e)}'
        }, status=500)


# ============================================
# 7. 统计报表API
# ============================================

@login_required
def api_product_statistics(request):
    """
    获取产品统计报表数据
    请求方法: GET
    请求地址: /api/amazon-products/statistics/
    """
    try:
        # 基础统计
        total_products = AmazonProduct.objects.count()

        # 按产品类型统计
        type_stats = list(AmazonProduct.objects.values('product_type').annotate(
            count=Count('product_type')
        ).order_by('-count'))

        # 为每个产品类型添加显示名称
        for stat in type_stats:
            product_type_code = stat['product_type']
            try:
                product_obj = AmazonProduct(product_type=product_type_code)
                stat['product_type_display'] = product_obj.get_product_type_display()
            except:
                stat['product_type_display'] = product_type_code

        # 按月份统计新增产品数
        monthly_stats = list(AmazonProduct.objects.extra(
            select={'month': "DATE_FORMAT(created_at, '%%Y-%%m')"}
        ).values('month').annotate(
            count=Count('asin')
        ).order_by('-month')[:12])  # 最近12个月

        # 图片统计
        with_images = AmazonProduct.objects.exclude(
            image_url__isnull=True
        ).exclude(
            image_url=''
        ).count()

        without_images = total_products - with_images

        # 上市日期统计
        with_launch_date = AmazonProduct.objects.exclude(
            launch_date__isnull=True
        ).count()

        without_launch_date = total_products - with_launch_date

        return JsonResponse({
            'success': True,
            'data': {
                'total_products': total_products,
                'type_statistics': type_stats,
                'monthly_statistics': monthly_stats,
                'image_statistics': {
                    'with_images': with_images,
                    'without_images': without_images,
                    'with_images_percentage': round((with_images / total_products * 100),
                                                    2) if total_products > 0 else 0,
                },
                'launch_date_statistics': {
                    'with_launch_date': with_launch_date,
                    'without_launch_date': without_launch_date,
                    'with_launch_date_percentage': round((with_launch_date / total_products * 100),
                                                         2) if total_products > 0 else 0,
                },
                'updated_at': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取统计信息失败: {str(e)}'
        }, status=500)


# ============================================
# 8. 搜索建议API
# ============================================

@login_required
def api_product_suggestions(request):
    """
    获取产品搜索建议（用于自动完成）
    请求方法: GET
    请求地址: /api/amazon-products/suggestions/?q=搜索词
    """
    try:
        query = request.GET.get('q', '').strip()

        if not query or len(query) < 2:
            return JsonResponse({
                'success': True,
                'data': {
                    'suggestions': []
                }
            })

        # 搜索ASIN
        asin_suggestions = AmazonProduct.objects.filter(
            asin__icontains=query
        ).values('asin', 'title')[:10]

        # 搜索标题
        title_suggestions = AmazonProduct.objects.filter(
            title__icontains=query
        ).values('asin', 'title')[:10]

        # 合并结果，去重
        suggestions_set = set()
        suggestions = []

        # 添加ASIN建议
        for item in asin_suggestions:
            key = item['asin']
            if key not in suggestions_set:
                suggestions_set.add(key)
                suggestions.append({
                    'type': 'ASIN',
                    'asin': item['asin'],
                    'title': item['title'],
                    'display': f"{item['asin']} - {item['title'][:50]}"
                })

        # 添加标题建议
        for item in title_suggestions:
            key = item['asin']
            if key not in suggestions_set:
                suggestions_set.add(key)
                suggestions.append({
                    'type': '标题',
                    'asin': item['asin'],
                    'title': item['title'],
                    'display': f"{item['asin']} - {item['title'][:50]}"
                })

        return JsonResponse({
            'success': True,
            'data': {
                'query': query,
                'suggestions': suggestions[:20],  # 最多返回20条
                'count': len(suggestions)
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'获取搜索建议失败: {str(e)}'
        }, status=500)


# ============================================
# 9. 健康检查API
# ============================================

def api_health_check(request):
    """
    健康检查接口
    请求方法: GET
    请求地址: /api/health-check/
    """
    try:
        # 检查数据库连接
        db_status = 'ok'
        try:
            AmazonProduct.objects.count()
        except:
            db_status = 'error'

        # 检查时间
        current_time = timezone.now()

        return JsonResponse({
            'success': True,
            'data': {
                'status': 'healthy',
                'database': db_status,
                'timestamp': current_time.strftime('%Y-%m-%d %H:%M:%S'),
                'version': '1.0.0'
            }
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'status': 'unhealthy',
            'message': f'健康检查失败: {str(e)}'
        }, status=500)


@login_required
def export_products_excel(request):
    try:
        scope = request.GET.get('scope', 'all')
        queryset = AmazonProduct.objects.all()

        if scope == 'selected':
            asins = request.GET.get('asins', '')
            asin_list = [a.strip() for a in asins.split(',') if a.strip()]
            if asin_list:
                queryset = queryset.filter(asin__in=asin_list)
            else:
                queryset = queryset.none()
        elif scope == 'filtered':
            asin_filter = request.GET.get('asin', '').strip()
            if asin_filter:
                queryset = queryset.filter(asin__icontains=asin_filter)
            title_filter = request.GET.get('title', '').strip()
            if title_filter:
                queryset = queryset.filter(Q(title__icontains=title_filter) | Q(title_translation__icontains=title_filter))
            subject_filter = request.GET.get('subject', '').strip()
            if subject_filter:
                queryset = queryset.filter(Q(subject__icontains=subject_filter) | Q(subject_translation__icontains=subject_filter))
            product_type = request.GET.get('product_type', '').strip()
            if product_type:
                queryset = queryset.filter(product_type=product_type)
            launch_date_start = request.GET.get('launch_date_start', '').strip()
            launch_date_end = request.GET.get('launch_date_end', '').strip()
            if launch_date_start:
                try:
                    start_date = datetime.strptime(launch_date_start, '%Y-%m-%d').date()
                    queryset = queryset.filter(launch_date__gte=start_date)
                except ValueError:
                    pass
            if launch_date_end:
                try:
                    end_date = datetime.strptime(launch_date_end, '%Y-%m-%d').date()
                    queryset = queryset.filter(launch_date__lte=end_date)
                except ValueError:
                    pass
            created_at_start = request.GET.get('created_at_start', '').strip()
            created_at_end = request.GET.get('created_at_end', '').strip()
            if created_at_start:
                try:
                    start_datetime = datetime.strptime(created_at_start, '%Y-%m-%d')
                    queryset = queryset.filter(created_at__gte=start_datetime)
                except ValueError:
                    pass
            if created_at_end:
                try:
                    end_datetime = datetime.strptime(created_at_end, '%Y-%m-%d') + timedelta(days=1)
                    queryset = queryset.filter(created_at__lt(end_datetime))
                except ValueError:
                    pass

        sort_field = request.GET.get('sort_field', 'asin')
        sort_order = request.GET.get('sort_order', 'asc')
        if sort_order == 'desc':
            sort_field = f'-{sort_field}'
        queryset = queryset.order_by(sort_field)

        wb = Workbook()
        ws = wb.active
        ws.title = "Amazon产品"

        headers = [
            'ASIN', '产品标题', '标题翻译', '产品主题', '主题翻译',
            '图片链接', '上架时间', '首次抓取时间', '产品类型'
        ]
        ws.append(headers)

        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center")

        for product in queryset:
            ws.append([
                product.asin,
                product.title or '',
                product.title_translation or '',
                product.subject or '',
                product.subject_translation or '',
                product.image_url or '',
                product.launch_date.strftime('%Y-%m-%d') if product.launch_date else '',
                product.created_at.strftime('%Y-%m-%d %H:%M:%S') if product.created_at else '',
                product.get_product_type_display() or '',
            ])

        ws.column_dimensions['A'].width = 16
        ws.column_dimensions['B'].width = 36
        ws.column_dimensions['C'].width = 24
        ws.column_dimensions['D'].width = 24
        ws.column_dimensions['E'].width = 24
        ws.column_dimensions['F'].width = 40
        ws.column_dimensions['G'].width = 14
        ws.column_dimensions['H'].width = 20
        ws.column_dimensions['I'].width = 14

        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename="amazon_products.xlsx"'

        wb.save(response)
        return response
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'导出Excel失败: {str(e)}'
        }, status=500)
