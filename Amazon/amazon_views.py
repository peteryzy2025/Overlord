# Amazon/amazon_views.py
from django.http import JsonResponse
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncDate
from datetime import datetime, timedelta
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
import json

from django.shortcuts import render

# 模型导入
from General.models import User, AmazonShop, OperationalAccount, TemuShop
from Amazon.models import LingXingAmazonShop, AmazonOrders, AmazonOrderItem
from Temu.models import TemuOrder, TemuOrderItem, LingXingTemuShop


@login_required
def get_operator_pie_chart_api(request):
    """
    运营人员业绩饼图数据
    GET参数:
      - date_range / start_date / end_date: 日期范围
      - operator_id / group: 筛选条件
    返回: {name: '张三', value: 45} 格式的列表
    """
    if request.method != 'GET':
        return JsonResponse({'success': False, 'message': '只支持GET请求'}, status=405)

    try:
        # 解析参数
        data = {
            'date_range': request.GET.get('date_range', 'yesterday'),
            'start_date': request.GET.get('start_date', ''),
            'end_date': request.GET.get('end_date', ''),
            'operator_id': request.GET.get('operator_id', ''),
            'group': request.GET.get('group', '')
        }

        user = request.user
        permissions = parse_permissions(getattr(user, 'permission', []))

        # 权限判断 + 平台识别
        filter_type, filter_value, platform_info = determine_filter_type_and_value_with_platform(
            request, data, permissions
        )

        # 日期范围
        current_start, current_end = None, None
        if data['start_date'] and data['end_date']:
            try:
                current_start = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
                current_end = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
            except:
                pass

        if not current_start or not current_end:
            current_start, current_end = get_date_range_from_option(data['date_range'])

        if not current_start or not current_end:
            return JsonResponse({'success': False, 'message': '无效日期'}, status=400)

        # 获取店铺ID（平台区分）
        shop_ids_by_platform = {}
        if filter_type != 'none':
            shop_ids_by_platform = get_shop_ids_by_filter_with_platform(
                filter_type, filter_value, platform_info
            )

        # 根据filter_type决定聚合维度
        pie_data = []

        # ========== 场景1：全部分组/全部人员 ==========
        if filter_type == 'all' or (filter_type == 'ops_id' and filter_value == 'all'):
            # 返回所有一级分组（ops_group）的单量占比
            groups = OperationalAccount.objects.exclude(
                ops_group__isnull=True
            ).exclude(
                ops_group=''
            ).values_list('ops_group', flat=True).distinct()

            for group in groups:
                # 获取组内所有用户ID
                user_ids = OperationalAccount.objects.filter(
                    ops_group=group
                ).values_list('user_id', flat=True)

                # 分别统计Amazon和Temu
                amazon_count = 0
                temu_count = 0

                if shop_ids_by_platform.get('amazon'):
                    amazon_shops = AmazonShop.objects.filter(ops_id__in=user_ids)
                    amazon_shop_ids = list(amazon_shops.values_list('id', flat=True))
                    lingxing_shops = LingXingAmazonShop.objects.filter(
                        amazon_shop_id__in=amazon_shop_ids
                    )
                    lingxing_shop_ids = list(lingxing_shops.values_list('sid', flat=True))

                    amazon_count = AmazonOrders.objects.filter(
                        lingxing_shop_id__in=lingxing_shop_ids,
                        purchase_date_local__date__gte=current_start,
                        purchase_date_local__date__lte=current_end
                    ).count()

                if shop_ids_by_platform.get('temu'):
                    temu_shops = TemuShop.objects.filter(ops_id__in=user_ids)
                    temu_shop_ids = list(temu_shops.values_list('id', flat=True))

                    temu_count = TemuOrder.objects.filter(
                        lingxing_shop__temu_shop_id__in=temu_shop_ids,
                        global_purchase_time__date__gte=current_start,
                        global_purchase_time__date__lte=current_end
                    ).count()

                total = amazon_count + temu_count
                if total > 0:
                    pie_data.append({
                        'name': group,
                        'value': total
                    })

        # ========== 场景2：具体分组 ==========
        elif filter_type == 'ops_group':
            # 返回组内每个人员的单量占比
            user_ids = OperationalAccount.objects.filter(
                ops_group=filter_value
            ).values_list('user_id', flat=True)

            users = User.objects.filter(id__in=user_ids)

            for u in users:
                # 统计该成员的订单
                amazon_count = 0
                temu_count = 0

                if shop_ids_by_platform.get('amazon'):
                    amazon_shops = AmazonShop.objects.filter(ops_id=u.id)
                    amazon_shop_ids = list(amazon_shops.values_list('id', flat=True))
                    lingxing_shops = LingXingAmazonShop.objects.filter(
                        amazon_shop_id__in=amazon_shop_ids
                    )
                    lingxing_shop_ids = list(lingxing_shops.values_list('sid', flat=True))

                    amazon_count = AmazonOrders.objects.filter(
                        lingxing_shop_id__in=lingxing_shop_ids,
                        purchase_date_local__date__gte=current_start,
                        purchase_date_local__date__lte=current_end
                    ).count()

                if shop_ids_by_platform.get('temu'):
                    temu_shops = TemuShop.objects.filter(ops_id=u.id)
                    temu_shop_ids = list(temu_shops.values_list('id', flat=True))

                    temu_count = TemuOrder.objects.filter(
                        lingxing_shop__temu_shop_id__in=temu_shop_ids,
                        global_purchase_time__date__gte=current_start,
                        global_purchase_time__date__lte=current_end
                    ).count()

                total = amazon_count + temu_count
                if total > 0:
                    pie_data.append({
                        'name': u.first_name or u.username,
                        'value': total
                    })

        # ========== 场景3：具体人员 ==========
        elif filter_type == 'ops_id':
            # 返回该人员的店铺单量占比
            amazon_count = 0
            temu_count = 0

            # Amazon店铺
            if shop_ids_by_platform.get('amazon'):
                amazon_shops = AmazonShop.objects.filter(ops_id=filter_value)
                for shop in amazon_shops:
                    lingxing_shop = LingXingAmazonShop.objects.filter(
                        amazon_shop_id=shop.id
                    ).first()
                    if lingxing_shop:
                        count = AmazonOrders.objects.filter(
                            lingxing_shop_id=lingxing_shop.sid,
                            purchase_date_local__date__gte=current_start,
                            purchase_date_local__date__lte=current_end
                        ).count()
                        if count > 0:
                            pie_data.append({
                                'name': shop.shop_name,
                                'value': count
                            })

            # Temu店铺
            if shop_ids_by_platform.get('temu'):
                temu_shops = TemuShop.objects.filter(ops_id=filter_value)
                for shop in temu_shops:
                    count = TemuOrder.objects.filter(
                        lingxing_shop__temu_shop_id=shop.id,
                        global_purchase_time__date__gte=current_start,
                        global_purchase_time__date__lte=current_end
                    ).count()
                    if count > 0:
                        pie_data.append({
                            'name': shop.shop_name,
                            'value': count
                        })

        # 无饼图数据时返回空列表
        if not pie_data:
            return JsonResponse({
                'success': True,
                'data': [],
                'message': '暂无数据'
            })

        # 按值降序排序
        pie_data.sort(key=lambda x: x['value'], reverse=True)

        return JsonResponse({
            'success': True,
            'data': pie_data,
            'filter_info': {
                'filter_type': filter_type,
                'filter_value': filter_value,
                'platform_source': platform_info.get('source')
            }
        })

    except Exception as e:
        print(f"\n❌ 饼图API错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }, status=500)
def detect_platform_by_user(user):
    """
    检测用户的主运营平台
    返回: "亚马逊" | "Temu" | "unknown"
    """
    if not hasattr(user, 'department') or user.department != "运营部门":
        return "unknown"

    # platform字段可能是 "亚马逊" 或 "Temu" 或逗号分隔的多值
    # 这里简单判断包含关系
    platform_str = (user.platform or "").strip()

    if "Temu" in platform_str:
        return "Temu"
    elif "亚马逊" in platform_str:
        return "亚马逊"
    return "unknown"


def determine_filter_type_and_value_with_platform(request, data, permissions):
    """
    增强版：返回 (filter_type, filter_value, platform_info)
    platform_info: {"source": "amazon_only" | "temu_only" | "mixed", "detected": "亚马逊|Temu"}
    """
    user = request.user
    base_result = determine_filter_type_and_value(request, data, permissions)
    filter_type, filter_value = base_result

    # ops_all且选择"全部" → 混合查询
    if 'ops_all' in permissions:
        if filter_type == 'all' or (not data.get('group') and not data.get('operator_id')):
            # 用户选择了"全部"
            return filter_type, filter_value, {"source": "mixed"}

    # 其他情况，自动识别平台
    platform = detect_platform_by_user(user)

    # 如果是按人员/组筛选，需要验证目标对象的平台
    if filter_type == 'ops_id':
        # ==================== 修复核心：基于实际店铺判断平台 ====================
        # 直接查询数据库，看该用户实际绑定了哪些平台的店铺
        has_amazon = AmazonShop.objects.filter(ops_id=filter_value).exists()
        has_temu = TemuShop.objects.filter(ops_id=filter_value).exists()

        # 根据实际绑定情况决定查询范围
        if has_amazon and has_temu:
            platform_info = {"source": "mixed"}
        elif has_amazon:
            platform_info = {"source": "amazon_only", "detected": "亚马逊"}
        elif has_temu:
            platform_info = {"source": "temu_only", "detected": "Temu"}
        else:
            # 用户无绑定店铺时，兜底策略：查两个平台（都会返回空，但不会漏数据）
            platform_info = {"source": "mixed"}
        # ===================================================================

    elif filter_type == 'ops_group':
        # 检查组内是否全是Temu/亚马逊运营（MVP简化：默认mixed，让后续查询自行处理）
        platform_info = {"source": "mixed"}
    else:
        platform_info = {"source": f"{platform.lower()}_only", "detected": platform}

    return filter_type, filter_value, platform_info


def parse_permissions(user_permission):
    """
    统一权限解析函数
    处理多种格式的权限数据：
    - 字符串："ops,555,k1,k2" → ["ops", "555", "k1", "k2"]
    - 列表：["ops", "k1"] → 保持不变
    - 其他：返回空列表
    """
    if not user_permission:
        return []

    # 如果是字符串，按逗号分割并去除空白
    if isinstance(user_permission, str):
        return [perm.strip() for perm in user_permission.split(',') if perm.strip()]

    # 如果是列表，直接返回
    if isinstance(user_permission, list):
        return user_permission

    # 其他情况返回空列表
    return []


def determine_filter_type_and_value(request, data, permissions):
    """
    统一权限控制逻辑
    返回: (filter_type, filter_value)
    """
    user = request.user

    # 权限1: ops_all - 信任并使用前端传递的筛选参数
    if 'ops_all' in permissions:
        # print("✅ 权限校验通过: ops_all，使用前端传递的筛选参数")
        ops_id_raw = data.get('operator_id') or data.get('ops_id')
        ops_group_raw = data.get('group') or data.get('ops_group')

        if ops_group_raw and ops_group_raw not in ['all', '全部分组']:
            return 'ops_group', ops_group_raw.strip()
        elif ops_id_raw and ops_id_raw not in ['all', '全部人员']:
            return 'ops_id', int(ops_id_raw)
        else:
            return 'all', None

    # 权限2: ops_group - 可查询自己分组，支持组内筛选具体人员
    elif 'ops_group' in permissions:
        # print("✅ 权限校验通过: ops_group")
        try:
            ops_account = user.operational_account
            user_group = ops_account.ops_group if ops_account else None

            if not user_group:
                # print("⚠️ 用户未配置运营分组，返回空数据")
                return 'none', None

            ops_id_raw = data.get('operator_id') or data.get('ops_id')
            ops_group_raw = data.get('group') or data.get('ops_group')

            # 情况1：组内筛选具体人员（带权限验证）
            if ops_id_raw and ops_id_raw not in ['all', '全部人员']:
                try:
                    target_user_id = int(ops_id_raw)
                    # 验证目标用户是否在用户所在分组内
                    target_user = User.objects.filter(
                        id=target_user_id,
                        operational_account__ops_group=user_group
                    ).first()

                    if target_user:
                        print(f"  组内筛选具体人员: {target_user.first_name} (ID: {target_user_id})")
                        return 'ops_id', target_user_id
                    else:
                        print(f"  ⚠️ 越权警告：用户 {user.id} 试图查询非本组成员 {target_user_id}")
                        return 'none', None
                except (ValueError, TypeError):
                    return 'none', None

            # 情况2：筛选具体分组（验证是否是自己的组）
            elif ops_group_raw and ops_group_raw not in ['all', '全部分组']:
                if ops_group_raw.strip() == user_group:
                    # print(f"  筛选自己分组: {user_group}")
                    return 'ops_group', user_group
                else:
                    print(f"  ⚠️ 越权警告：用户 {user.id} 试图查询非本组 '{ops_group_raw}'")
                    return 'none', None

            # 情况3：默认查询全组
            else:
                # print(f"  默认查询全组: {user_group}")
                return 'ops_group', user_group

        except Exception as e:
            print(f"  获取用户信息异常: {e}")
            return 'none', None

    # 权限3: ops - 强制查询自己
    elif 'ops' in permissions:
        # print("✅ 权限校验通过: ops，强制查询自己")
        return 'ops_id', user.id

    # 无权限
    else:
        print("❌ 权限校验失败: 用户无任何运营权限，返回空数据")
        return 'none', None


@login_required(login_url='/login/')
def amazon_dashboard_page(request):
    """Amazon驾驶舱页面渲染"""
    theme = request.COOKIES.get('theme', 'light')
    return render(request, 'dashboard.html', {
        'theme': theme,
        'active_nav': 'amazon'
    })


def get_date_range_from_option(date_range_option):
    """
    根据快捷选项获取日期范围
    返回: (start_date, end_date) 日期对象
    """
    today = datetime.now().date()

    if date_range_option == 'today':
        return today, today
    elif date_range_option == 'yesterday':
        yesterday = today - timedelta(days=1)
        return yesterday, yesterday
    elif date_range_option == 'last7days':
        # 包含今天，共7天
        start = today - timedelta(days=6)
        return start, today
    elif date_range_option == 'last30days':
        # 包含今天，共30天
        start = today - timedelta(days=29)
        return start, today
    else:
        return None, None


def get_previous_period(start_date, end_date):
    """
    计算同期日期范围（往前推相同天数）
    """
    days = (end_date - start_date).days + 1
    previous_start = start_date - timedelta(days=days)
    previous_end = end_date - timedelta(days=days)
    return previous_start, previous_end


def get_order_statistics(lingxing_shop_ids, start_date, end_date):
    """
    核心函数：计算指定店铺和日期范围的统计数据
    返回包含所有6个指标的字典
    """
    # 日期筛选
    order_filter = Q(lingxing_shop_id__in=lingxing_shop_ids)
    order_filter &= Q(purchase_date_local__date__gte=start_date)
    order_filter &= Q(purchase_date_local__date__lte=end_date)

    # 性能优化：只查询需要的字段
    orders = AmazonOrders.objects.filter(order_filter).only(
        'amazon_order_id', 'order_total_amount', 'fulfillment_channel'
    )

    order_count = orders.count()

    if order_count == 0:
        return {
            'order_count': 0,
            'total_sales_quantity': 0,
            'total_revenue': 0.0,
            'avg_order_value': 0.0,
            'fba_count': 0,
            'fbm_count': 0,
            'fba_percentage': '0.0%',
            'fbm_percentage': '0.0%',
        }

    # 修复1：使用订单自增ID（不是amazon_order_id）关联查询，解决模型结构变更问题
    order_ids = list(orders.values_list('id', flat=True))

    # 修复2：使用正确的关联字段查询订单明细，大幅提升性能
    quantity_agg = AmazonOrderItem.objects.filter(
        order_id__in=order_ids  # 关联的是AmazonOrders.id（自增主键）
    ).aggregate(total_quantity=Sum('quantity_ordered'))
    total_sales_quantity = quantity_agg['total_quantity'] or 0

    # 计算营业额
    revenue_agg = orders.aggregate(total_revenue=Sum('order_total_amount'))
    total_revenue = float(revenue_agg['total_revenue'] or 0)

    # 计算客单价（营业额/订单量）
    avg_order_value = total_revenue / order_count if order_count > 0 else 0

    # 计算FBA和FBM（保持逻辑不变）
    fulfillment_stats = orders.values('fulfillment_channel').annotate(
        count=Count('fulfillment_channel')
    )

    fba_count = 0
    fbm_count = 0
    for stat in fulfillment_stats:
        channel = stat['fulfillment_channel']
        count = stat['count']
        if channel == 'AFN':
            fba_count = count
        elif channel == 'MFN':
            fbm_count = count

    # 计算占比
    fba_percentage = (fba_count / order_count * 100) if order_count > 0 else 0
    fbm_percentage = (fbm_count / order_count * 100) if order_count > 0 else 0

    return {
        'order_count': order_count,
        'total_sales_quantity': total_sales_quantity,
        'total_revenue': round(total_revenue, 2),
        'avg_order_value': round(avg_order_value, 2),
        'fba_count': fba_count,
        'fbm_count': fbm_count,
        'fba_percentage': f"{fba_percentage:.1f}%",
        'fbm_percentage': f"{fbm_percentage:.1f}%",
    }


def calculate_change_rate(current, previous):
    """
    计算环比变化率
    返回: "+12.3%" 或 "-8.5%" 或 "0.0%"
    """
    if previous == 0:
        return "+100.0%" if current > 0 else "0.0%"

    change = ((current - previous) / previous) * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.1f}%"


def calculate_all_change_rates(current_stats, previous_stats):
    """计算所有指标的环比变化率"""
    comparison = {}

    # 数值型指标
    numeric_keys = ['order_count', 'total_sales_quantity', 'total_revenue', 'avg_order_value']
    for key in numeric_keys:
        comparison[f'{key}_change'] = calculate_change_rate(
            current_stats[key], previous_stats[key]
        )

    # 百分比指标（去掉%号）
    pct_keys = ['fba_percentage', 'fbm_percentage']
    for key in pct_keys:
        current_val = float(current_stats[key].rstrip('%'))
        previous_val = float(previous_stats[key].rstrip('%'))
        comparison[f'{key}_change'] = calculate_change_rate(current_val, previous_val)

    # print("\n环比变化率:")
    # for key, value in comparison.items():
    #     print(f"  {key}: {value}")

    return comparison


def merge_trend_data(amazon_trend, temu_trend, shop_ids_by_platform):
    """
    合并Amazon和Temu趋势数据，返回三条线
    格式: [{'date': '2025-11-18', 'amazon_sales': 156, 'temu_sales': 89, 'total_sales': 245}, ...]
    """
    # 将两个列表转为字典 {date: sales}
    amazon_dict = {item['date']: item['sales'] for item in (amazon_trend or [])}
    temu_dict = {item['date']: item['sales'] for item in (temu_trend or [])}

    # 获取所有日期
    all_dates = set(amazon_dict.keys()) | set(temu_dict.keys())
    all_dates = sorted(list(all_dates))

    result = []
    for date_str in all_dates:
        amazon_sales = amazon_dict.get(date_str, 0)
        temu_sales = temu_dict.get(date_str, 0)
        result.append({
            'date': date_str,
            'amazon_sales': amazon_sales,
            'temu_sales': temu_sales,
            'total_sales': amazon_sales + temu_sales
        })

    # 如果没有日期，返回14天空数据
    if not result:
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=13)
        for i in range(14):
            date = start_date + timedelta(days=i)
            result.append({
                'date': date.strftime('%Y-%m-%d'),
                'amazon_sales': 0,
                'temu_sales': 0,
                'total_sales': 0
            })

    return result

def get_shop_ids_by_filter(filter_type, filter_value):
    """
    根据筛选类型获取AmazonShop的ID列表（支持权限控制）
    Args:
        filter_type: 'ops_id', 'ops_group', 'all', 'none'
        filter_value: 对应的值
    Returns:
        QuerySet: AmazonShop的ID列表
    """
    if filter_type == 'ops_id':
        print(f"按运营ID筛选: ops_id={filter_value}")
        return AmazonShop.objects.filter(ops_id=filter_value).values_list('id', flat=True)

    elif filter_type == 'ops_group':
        # print(f"查询分组 '{filter_value}' 的成员...")
        user_ids = OperationalAccount.objects.filter(
            ops_group=filter_value
        ).values_list('user_id', flat=True)

        user_ids_list = list(user_ids)
        print(f"✅ 找到用户ID: {user_ids_list}")

        if user_ids_list:
            shop_ids = AmazonShop.objects.filter(
                ops_id__in=user_ids_list
            ).values_list('id', flat=True)
            print(f"✅ 找到店铺ID: {list(shop_ids)}")
            return shop_ids
        else:
            print(f"⚠️ 分组 '{filter_value}' 没有成员")
            return AmazonShop.objects.none().values_list('id', flat=True)

    elif filter_type == 'all':
        # print("查询所有AmazonShop")
        return AmazonShop.objects.all().values_list('id', flat=True)

    elif filter_type == 'none':
        print("⚠️ 权限不足，返回空QuerySet")
        return AmazonShop.objects.none().values_list('id', flat=True)

    else:
        print(f"⚠️ 未知的筛选类型: {filter_type}")
        return AmazonShop.objects.none().values_list('id', flat=True)
def get_shop_ids_by_filter_with_platform(filter_type, filter_value, platform_info):
    """
    重构版：返回平台区分的店铺ID
    返回: {
        'amazon': [1, 2, ...],  # AmazonShop.id列表
        'temu': [101, 102, ...]  # TemuShop.id列表（注意是BigInteger）
    }
    """
    result = {'amazon': [], 'temu': []}

    # ========== 亚马逊店铺 ==========
    if platform_info['source'] in ['amazon_only', 'mixed']:
        if filter_type == 'ops_id':
            # 通过 ops_id 查找 AmazonShop
            result['amazon'] = list(AmazonShop.objects.filter(
                ops_id=filter_value
            ).values_list('id', flat=True))

        elif filter_type == 'ops_group':
            # 查找组内所有用户的AmazonShop
            user_ids = OperationalAccount.objects.filter(
                ops_group=filter_value
            ).values_list('user_id', flat=True)
            result['amazon'] = list(AmazonShop.objects.filter(
                ops_id__in=list(user_ids)
            ).values_list('id', flat=True))

        elif filter_type == 'all':
            result['amazon'] = list(AmazonShop.objects.all().values_list('id', flat=True))

    # ========== Temu店铺 ==========
    if platform_info['source'] in ['temu_only', 'mixed']:
        if filter_type == 'ops_id':
            # 通过 ops_id 查找 TemuShop
            result['temu'] = list(TemuShop.objects.filter(
                ops_id=filter_value
            ).values_list('id', flat=True))

        elif filter_type == 'ops_group':
            # 查找组内所有用户的TemuShop
            user_ids = OperationalAccount.objects.filter(
                ops_group=filter_value
            ).values_list('user_id', flat=True)
            result['temu'] = list(TemuShop.objects.filter(
                ops_id__in=list(user_ids)
            ).values_list('id', flat=True))

        elif filter_type == 'all':
            result['temu'] = list(TemuShop.objects.all().values_list('id', flat=True))

    return result


def get_sales_trend_data(lingxing_shop_ids):
    """
    获取最近14天每日销量数据
    返回: [{date: '2025-11-18', sales: 156}, ...] 格式
    """
    # 计算14天日期范围
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=13)

    # print(f"\n{'=' * 60}")
    # print("📈 计算销量趋势数据...")
    # print(f"统计日期范围: {start_date} 至 {end_date}")

    if not lingxing_shop_ids:
        print("⚠️ 没有店铺数据，返回空趋势数据")
        return []

    # 性能优化：使用更高效的查询，避免N+1问题
    daily_sales_raw = AmazonOrderItem.objects.filter(
        order__lingxing_shop_id__in=lingxing_shop_ids,
        order__purchase_date_local__date__gte=start_date,
        order__purchase_date_local__date__lte=end_date
    ).values(
        date=TruncDate('order__purchase_date_local')
    ).annotate(
        sales=Sum('quantity_ordered')
    ).order_by('date')

    # 将查询结果转换为字典 {date: sales}
    sales_dict = {}
    for item in daily_sales_raw:
        date_obj = item['date']
        sales_dict[date_obj] = item['sales'] or 0

    # print(f"查询到 {len(sales_dict)} 天的销量数据")

    # 组装14天完整数据（补全缺失日期）
    result = []
    for i in range(14):
        date = start_date + timedelta(days=i)
        sales = sales_dict.get(date, 0)
        result.append({
            'date': date.strftime('%Y-%m-%d'),
            'sales': sales
        })

    print(f"✅ 返回 {len(result)} 天的完整销量数据")
    print(f"{'=' * 60}\n")

    return result


@login_required
def filter_amazon_data_api(request):
    """
    筛选亚马逊订单数据（支持多平台合并）
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': '只支持POST请求'}, status=405)

    try:
        # 解析请求数据
        data = json.loads(request.body)
        user = request.user
        permissions = parse_permissions(getattr(user, 'permission', []))

        # ========== 增强版权限判断 + 平台识别 ==========
        filter_type, filter_value, platform_info = determine_filter_type_and_value_with_platform(
            request, data, permissions
        )

        # 处理日期参数
        date_range_option = data.get('date_range', '')
        start_date_str = data.get('start_date', '')
        end_date_str = data.get('end_date', '')

        current_start, current_end = None, None
        if start_date_str and end_date_str:
            try:
                current_start = datetime.strptime(start_date_str.split(' ')[0], '%Y-%m-%d').date()
                current_end = datetime.strptime(end_date_str.split(' ')[0], '%Y-%m-%d').date()
            except:
                pass

        if not current_start or not current_end:
            current_start, current_end = get_date_range_from_option(date_range_option)

        if not current_start or not current_end:
            return JsonResponse({
                'success': False,
                'message': '请提供有效的日期范围或选择日期快捷选项'
            }, status=400)

        previous_start, previous_end = get_previous_period(current_start, current_end)

        # ========== 获取平台区分的店铺ID ==========
        if filter_type == 'none':
            shop_ids_by_platform = {'amazon': [], 'temu': []}
        else:
            shop_ids_by_platform = get_shop_ids_by_filter_with_platform(
                filter_type, filter_value, platform_info
            )

        # ========== 分别统计两个平台 ==========
        # Amazon统计
        amazon_stats = {
            'current': {
                'order_count': 0, 'total_sales_quantity': 0, 'total_revenue': 0.0,
                'avg_order_value': 0.0, 'fba_percentage': '0.0%', 'fbm_percentage': '0.0%'
            },
            'previous': {
                'order_count': 0, 'total_sales_quantity': 0, 'total_revenue': 0.0,
                'avg_order_value': 0.0, 'fba_percentage': '0.0%', 'fbm_percentage': '0.0%'
            },
            'trend': []
        }

        # 如果有亚马逊店铺
        if shop_ids_by_platform['amazon']:
            lingxing_shops = LingXingAmazonShop.objects.filter(
                amazon_shop_id__in=shop_ids_by_platform['amazon']
            )
            lingxing_shop_ids = list(lingxing_shops.values_list('sid', flat=True))

            if lingxing_shop_ids:
                amazon_stats['current'] = get_order_statistics(
                    lingxing_shop_ids, current_start, current_end
                )
                amazon_stats['previous'] = get_order_statistics(
                    lingxing_shop_ids, previous_start, previous_end
                )
                amazon_stats['trend'] = get_sales_trend_data(lingxing_shop_ids)

        # Temu统计
        temu_stats = {
            'current': {
                'order_count': 0, 'total_sales_quantity': 0, 'total_revenue': 0.0,
                'avg_order_value': 0.0, 'fba_percentage': '0.0%', 'fbm_percentage': '0.0%'
            },
            'previous': {
                'order_count': 0, 'total_sales_quantity': 0, 'total_revenue': 0.0,
                'avg_order_value': 0.0, 'fba_percentage': '0.0%', 'fbm_percentage': '0.0%'
            },
            'trend': []
        }

        # 如果有Temu店铺
        if shop_ids_by_platform['temu']:
            temu_stats['current'] = get_temu_order_statistics(
                shop_ids_by_platform['temu'], current_start, current_end
            )
            temu_stats['previous'] = get_temu_order_statistics(
                shop_ids_by_platform['temu'], previous_start, previous_end
            )
            temu_stats['trend'] = get_temu_sales_trend_data(shop_ids_by_platform['temu'])

        # 合并统计结果
        def merge_stats(current, previous):
            return {
                'order_count': current['order_count'] + previous['order_count'],
                'total_sales_quantity': current['total_sales_quantity'] + previous['total_sales_quantity'],
                'total_revenue': round(current['total_revenue'] + previous['total_revenue'], 2),
                'avg_order_value': round(
                    (current['total_revenue'] + previous['total_revenue']) /
                    (current['order_count'] + previous['order_count'])
                    if (current['order_count'] + previous['order_count']) > 0 else 0, 2
                ),
                'fba_percentage': current['fba_percentage'],
                'fbm_percentage': current['fbm_percentage'],
            }

        merged_current = merge_stats(amazon_stats['current'], temu_stats['current'])
        merged_previous = merge_stats(amazon_stats['previous'], temu_stats['previous'])

        # 计算环比
        comparison = calculate_all_change_rates(merged_current, merged_previous)

        # 合并趋势数据
        merged_trend = merge_trend_data(
            amazon_stats['trend'],
            temu_stats['trend'],
            shop_ids_by_platform
        )

        # 判断平台来源类型
        platform_source = "unknown"
        if shop_ids_by_platform['amazon'] and shop_ids_by_platform['temu']:
            platform_source = "mixed"
        elif shop_ids_by_platform['amazon']:
            platform_source = "amazon_only"
        elif shop_ids_by_platform['temu']:
            platform_source = "temu_only"
        else:
            platform_source = "none"

        # 组装响应
        return assemble_and_print_response(
            merged_current, merged_previous, comparison, merged_trend,
            filter_type, filter_value, current_start, current_end,
            previous_start, previous_end,
            shop_count=len(shop_ids_by_platform['amazon']) + len(shop_ids_by_platform['temu']),
            lingxing_shop_count=len(lingxing_shop_ids) if 'lingxing_shop_ids' in locals() else 0,
            platform_source=platform_source
        )

    except Exception as e:
        print(f"\n{'=' * 60}")
        print(f"❌ 错误发生: {str(e)}")
        import traceback
        traceback.print_exc()
        print(f"{'=' * 60}\n")

        return JsonResponse({
            'success': False,
            'message': f'服务器错误: {str(e)}',
            'debug_info': {
                'error_type': type(e).__name__,
                'error_detail': str(e)
            }
        }, status=500)

def get_temu_order_statistics(temu_shop_ids, start_date, end_date):
    """
    Temu核心统计函数（仅订单量+件数）
    """
    if not temu_shop_ids:
        return {
            'order_count': 0,
            'total_sales_quantity': 0,
            'total_revenue': 0.0,
            'avg_order_value': 0.0,
            'fba_count': 0,
            'fbm_count': 0,
            'fba_percentage': '0.0%',
            'fbm_percentage': '0.0%',
        }

    # Temu订单筛选
    order_filter = Q(lingxing_shop__temu_shop_id__in=temu_shop_ids)
    order_filter &= Q(global_purchase_time__date__gte=start_date)
    order_filter &= Q(global_purchase_time__date__lte=end_date)

    # 订单量
    orders = TemuOrder.objects.filter(order_filter)
    order_count = orders.count()

    if order_count == 0:
        return {
            'order_count': 0,
            'total_sales_quantity': 0,
            'total_revenue': 0.0,
            'avg_order_value': 0.0,
            'fba_count': 0,
            'fbm_count': 0,
            'fba_percentage': '0.0%',
            'fbm_percentage': '0.0%',
        }

    # 件数（通过订单项汇总）
    order_nos = list(orders.values_list('global_order_no', flat=True))
    quantity_agg = TemuOrderItem.objects.filter(
        order__global_order_no__in=order_nos
    ).aggregate(total_quantity=Sum('quantity'))
    total_sales_quantity = quantity_agg['total_quantity'] or 0

    # Temu不计算金额，保持为0
    return {
        'order_count': order_count,
        'total_sales_quantity': total_sales_quantity,
        'total_revenue': 0.0,
        'avg_order_value': 0.0,
        'fba_count': 0,
        'fbm_count': 0,
        'fba_percentage': '0.0%',
        'fbm_percentage': '0.0%',
    }


def get_temu_sales_trend_data(temu_shop_ids):
    """
    Temu最近14天销量趋势
    """
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=13)

    if not temu_shop_ids:
        return []

    # 按天聚合销量
    daily_sales_raw = TemuOrderItem.objects.filter(
        order__lingxing_shop__temu_shop_id__in=temu_shop_ids,
        order__global_purchase_time__date__gte=start_date,
        order__global_purchase_time__date__lte=end_date
    ).values(
        date=TruncDate('order__global_purchase_time')
    ).annotate(
        sales=Sum('quantity')
    ).order_by('date')

    sales_dict = {item['date']: item['sales'] or 0 for item in daily_sales_raw}

    # 补全14天
    result = []
    for i in range(14):
        date = start_date + timedelta(days=i)
        sales = sales_dict.get(date, 0)
        result.append({
            'date': date.strftime('%Y-%m-%d'),
            'sales': sales
        })

    return result


def assemble_and_print_response(current_stats, previous_stats, comparison, trend_data,
                                filter_type, filter_value, current_start, current_end,
                                previous_start, previous_end, shop_count, lingxing_shop_count,
                                platform_source="unknown"):
    """
    组装响应数据并打印完整日志
    platform_source: 新增参数，标识数据来源平台
    """
    # 组装完整响应
    response_data = {
        'success': True,
        'data': {
            'current': {
                'order_count': current_stats['order_count'],
                'total_sales_quantity': current_stats['total_sales_quantity'],
                'total_revenue': current_stats['total_revenue'],
                'avg_order_value': current_stats['avg_order_value'],
                'fba_percentage': current_stats['fba_percentage'],
                'fbm_percentage': current_stats['fbm_percentage'],
            },
            'previous': {
                'order_count': previous_stats['order_count'],
                'total_sales_quantity': previous_stats['total_sales_quantity'],
                'total_revenue': previous_stats['total_revenue'],
                'avg_order_value': previous_stats['avg_order_value'],
                'fba_percentage': previous_stats['fba_percentage'],
                'fbm_percentage': previous_stats['fbm_percentage'],
            },
            'comparison': comparison,
            'trend_data': trend_data,
            'filter_info': {
                'filter_type': filter_type,
                'filter_value': filter_value,
                'current_date_range': f"{current_start} to {current_end}",
                'previous_date_range': f"{previous_start} to {previous_end}",
                'days': (current_end - current_start).days + 1,
                'shop_count': shop_count,
                'lingxing_shop_count': lingxing_shop_count,
                'platform_source': platform_source  # 新增：平台来源标识
            }
        }
    }

    # 打印完整响应（包含filter_info）
    # print(f"\n{'=' * 60}")
    # print("🎯 最终返回数据（完整版）:")
    # print(json.dumps(response_data, indent=2, ensure_ascii=False))
    # print(f"{'=' * 60}\n")

    return JsonResponse(response_data)


def assemble_response_data(filter_type, filter_value, current_start, current_end,
                           previous_start, previous_end, shop_count=0,
                           lingxing_shop_count=0, trend_data=None):
    """快速组装空数据响应"""
    if trend_data is None:
        trend_data = []

    response_data = {
        'success': True,
        'data': {
            'current': {
                'order_count': 0, 'total_sales_quantity': 0, 'total_revenue': 0.0,
                'avg_order_value': 0.0, 'fba_percentage': '0.0%', 'fbm_percentage': '0.0%'
            },
            'previous': {
                'order_count': 0, 'total_sales_quantity': 0, 'total_revenue': 0.0,
                'avg_order_value': 0.0, 'fba_percentage': '0.0%', 'fbm_percentage': '0.0%'
            },
            'comparison': {
                'order_count_change': '0.0%', 'total_sales_quantity_change': '0.0%',
                'total_revenue_change': '0.0%', 'avg_order_value_change': '0.0%',
                'fba_percentage_change': '0.0%', 'fbm_percentage_change': '0.0%'
            },
            'trend_data': trend_data,
            'filter_info': {
                'filter_type': filter_type,
                'filter_value': filter_value,
                'current_date_range': f"{current_start} to {current_end}",
                'previous_date_range': f"{previous_start} to {previous_end}",
                'days': (current_end - current_start).days + 1 if current_start and current_end else 0,
                'shop_count': shop_count,
                'lingxing_shop_count': lingxing_shop_count
            }
        }
    }

    print(f"\n{'=' * 60}")
    print("⚠️ 返回空数据（未找到符合条件的记录）:")
    print(json.dumps(response_data, indent=2, ensure_ascii=False))
    print(f"{'=' * 60}\n")

    return JsonResponse(response_data)
