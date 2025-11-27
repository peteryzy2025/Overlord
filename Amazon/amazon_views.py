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
            # Amazon店铺
            if shop_ids_by_platform.get('amazon'):
                amazon_shop_ids = shop_ids_by_platform['amazon']
                lingxing_shops = LingXingAmazonShop.objects.filter(
                    amazon_shop_id__in=amazon_shop_ids
                )
                lingxing_shop_ids = list(lingxing_shops.values_list('sid', flat=True))

                if lingxing_shop_ids:
                    # 一次性聚合统计（性能优化）
                    orders = AmazonOrders.objects.filter(
                        lingxing_shop_id__in=lingxing_shop_ids,
                        purchase_date_local__date__gte=current_start,
                        purchase_date_local__date__lte=current_end
                    ).values('lingxing_shop__sid', 'lingxing_shop__name').annotate(
                        count=Count('id')
                    )

                    for item in orders:
                        pie_data.append({
                            'name': item['lingxing_shop__name'] or f'店铺({item["lingxing_shop__sid"]})',
                            'value': item['count']
                        })

            # Temu店铺（修复：正确缩进，使用主键字段）
            if shop_ids_by_platform.get('temu'):
                temu_shop_ids = shop_ids_by_platform['temu']

                orders = TemuOrder.objects.filter(
                    lingxing_shop__temu_shop_id__in=temu_shop_ids,
                    global_purchase_time__date__gte=current_start,
                    global_purchase_time__date__lte=current_end
                ).values('lingxing_shop__store_id', 'lingxing_shop__store_name').annotate(
                    count=Count('global_order_no')  # 正确：使用Temu主键字段
                )

                for item in orders:
                    pie_data.append({
                        'name': item['lingxing_shop__store_name'] or f'店铺({item["lingxing_shop__store_id"]})',
                        'value': item['count']
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
    修复了 ops_all 权限下选择单个组/人员时错误标记为 mixed 的问题
    """
    user = request.user
    base_result = determine_filter_type_and_value(request, data, permissions)
    filter_type, filter_value = base_result

    # ========== 权限1: ops_all - 信任并使用前端传递的筛选参数 ==========
    if 'ops_all' in permissions:
        ops_id_raw = data.get('operator_id') or data.get('ops_id')
        ops_group_raw = data.get('group') or data.get('ops_group')

        # 场景 A：查询全部 → mixed
        if filter_type == 'all' or (not ops_group_raw and not ops_id_raw):
            return filter_type, filter_value, {"source": "mixed"}

        # 场景 B：查询具体分组 → 动态检测组内平台
        elif filter_type == 'ops_group':
            user_ids = OperationalAccount.objects.filter(
                ops_group=filter_value
            ).values_list('user_id', flat=True)

            has_amazon = AmazonShop.objects.filter(ops_id__in=user_ids).exists()
            has_temu = TemuShop.objects.filter(ops_id__in=user_ids).exists()

            if has_amazon and has_temu:
                return filter_type, filter_value, {"source": "mixed"}
            elif has_amazon:
                return filter_type, filter_value, {"source": "amazon_only", "detected": "亚马逊"}
            elif has_temu:
                return filter_type, filter_value, {"source": "temu_only", "detected": "Temu"}
            else:
                return filter_type, filter_value, {"source": "amazon_only"}

        # 场景 C：查询具体人员 → 动态检测个人平台
        elif filter_type == 'ops_id':
            has_amazon = AmazonShop.objects.filter(ops_id=filter_value).exists()
            has_temu = TemuShop.objects.filter(ops_id=filter_value).exists()

            if has_amazon and has_temu:
                return filter_type, filter_value, {"source": "mixed"}
            elif has_amazon:
                return filter_type, filter_value, {"source": "amazon_only", "detected": "亚马逊"}
            elif has_temu:
                return filter_type, filter_value, {"source": "temu_only", "detected": "Temu"}
            else:
                return filter_type, filter_value, {"source": "amazon_only"}

        else:
            return filter_type, filter_value, {"source": "mixed"}

    # ========== 权限2: ops_group - 可查询自己分组 ==========
    elif 'ops_group' in permissions:
        try:
            ops_account = user.operational_account
            user_group = ops_account.ops_group if ops_account else None

            if not user_group:
                return filter_type, filter_value, {"source": "amazon_only"}

            ops_id_raw = data.get('operator_id') or data.get('ops_id')
            ops_group_raw = data.get('group') or data.get('ops_group')

            # 情况1：组内筛选具体人员（带权限验证）
            if ops_id_raw and ops_id_raw not in ['all', '全部人员']:
                try:
                    target_user_id = int(ops_id_raw)
                    target_user = User.objects.filter(
                        id=target_user_id,
                        operational_account__ops_group=user_group
                    ).first()

                    if target_user:
                        # 检测目标用户平台
                        has_amazon = AmazonShop.objects.filter(ops_id=target_user_id).exists()
                        has_temu = TemuShop.objects.filter(ops_id=target_user_id).exists()

                        if has_amazon and has_temu:
                            platform_info = {"source": "mixed"}
                        elif has_amazon:
                            platform_info = {"source": "amazon_only", "detected": "亚马逊"}
                        elif has_temu:
                            platform_info = {"source": "temu_only", "detected": "Temu"}
                        else:
                            platform_info = {"source": "amazon_only"}

                        return 'ops_id', target_user_id, platform_info
                    else:
                        return 'none', None, {"source": "amazon_only"}
                except (ValueError, TypeError):
                    return 'none', None, {"source": "amazon_only"}

            # 情况2：筛选具体分组（验证是否是自己的组）
            elif ops_group_raw and ops_group_raw not in ['all', '全部分组']:
                if ops_group_raw.strip() == user_group:
                    # 检测组内平台
                    user_ids = OperationalAccount.objects.filter(
                        ops_group=user_group
                    ).values_list('user_id', flat=True)

                    has_amazon = AmazonShop.objects.filter(ops_id__in=user_ids).exists()
                    has_temu = TemuShop.objects.filter(ops_id__in=user_ids).exists()

                    if has_amazon and has_temu:
                        platform_info = {"source": "mixed"}
                    elif has_amazon:
                        platform_info = {"source": "amazon_only", "detected": "亚马逊"}
                    elif has_temu:
                        platform_info = {"source": "temu_only", "detected": "Temu"}
                    else:
                        platform_info = {"source": "amazon_only"}

                    return 'ops_group', user_group, platform_info
                else:
                    return 'none', None, {"source": "amazon_only"}

            # 情况3：默认查询全组
            else:
                user_ids = OperationalAccount.objects.filter(
                    ops_group=user_group
                ).values_list('user_id', flat=True)

                has_amazon = AmazonShop.objects.filter(ops_id__in=user_ids).exists()
                has_temu = TemuShop.objects.filter(ops_id__in=user_ids).exists()

                if has_amazon and has_temu:
                    platform_info = {"source": "mixed"}
                elif has_amazon:
                    platform_info = {"source": "amazon_only", "detected": "亚马逊"}
                elif has_temu:
                    platform_info = {"source": "temu_only", "detected": "Temu"}
                else:
                    platform_info = {"source": "amazon_only"}

                return 'ops_group', user_group, platform_info

        except Exception as e:
            return filter_type, filter_value, {"source": "amazon_only"}

    # ========== 权限3: ops - 强制查询自己 ==========
    elif 'ops' in permissions:
        user_id = user.id
        has_amazon = AmazonShop.objects.filter(ops_id=user_id).exists()
        has_temu = TemuShop.objects.filter(ops_id=user_id).exists()

        if has_amazon and has_temu:
            platform_info = {"source": "mixed"}
        elif has_amazon:
            platform_info = {"source": "amazon_only", "detected": "亚马逊"}
        elif has_temu:
            platform_info = {"source": "temu_only", "detected": "Temu"}
        else:
            platform_info = {"source": "amazon_only"}

        return 'ops_id', user_id, platform_info

    # ========== 无权限 ==========
    else:
        return 'none', None, {"source": "amazon_only"}

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
    核心函数：计算指定店铺和日期范围的统计数据（含退货指标）
    返回包含8个指标的字典
    """
    # 日期筛选
    order_filter = Q(lingxing_shop_id__in=lingxing_shop_ids)
    order_filter &= Q(purchase_date_local__date__gte=start_date)
    order_filter &= Q(purchase_date_local__date__lte=end_date)

    # 所有订单（含退货）
    orders = AmazonOrders.objects.filter(order_filter).only(
        'id', 'amazon_order_id', 'order_total_amount', 'fulfillment_channel', 'order_status'
    )

    # 总订单量（含退货）
    total_order_count = orders.count()

    # 退货订单量（状态='Canceled'）
    cancelled_orders = orders.filter(order_status='Canceled')
    return_order_count = cancelled_orders.count()

    # 有效订单量（扣除退货）
    order_count = total_order_count - return_order_count

    if order_count == 0:
        return {
            'order_count': 0, 'total_sales_quantity': 0, 'total_revenue': 0.0,
            'avg_order_value': 0.0, 'fba_count': 0, 'fbm_count': 0,
            'fba_percentage': '0.0%', 'fbm_percentage': '0.0%',
            'return_order_count': 0, 'return_rate': '0.0%',
        }

    # 获取订单ID列表
    order_ids = list(orders.values_list('id', flat=True))
    valid_order_ids = list(orders.exclude(order_status='Canceled').values_list('id', flat=True))

    # 总销量（所有订单项）
    total_quantity_agg = AmazonOrderItem.objects.filter(
        order_id__in=order_ids
    ).aggregate(total_quantity=Sum('quantity_ordered'))
    total_sales_quantity_raw = total_quantity_agg['total_quantity'] or 0

    # 退货销量
    return_quantity_agg = AmazonOrderItem.objects.filter(
        order_id__in=cancelled_orders.values_list('id', flat=True)
    ).aggregate(total_quantity=Sum('quantity_ordered'))
    return_sales_quantity = return_quantity_agg['total_quantity'] or 0

    # 有效销量（扣除退货）
    total_sales_quantity = total_sales_quantity_raw - return_sales_quantity

    # 总营业额（所有订单）
    total_revenue_agg = orders.aggregate(total_revenue=Sum('order_total_amount'))
    total_revenue_raw = float(total_revenue_agg['total_revenue'] or 0)

    # 退货营业额
    return_revenue_agg = cancelled_orders.aggregate(total_revenue=Sum('order_total_amount'))
    return_revenue = float(return_revenue_agg['total_revenue'] or 0)

    # 有效营业额（扣除退货）
    total_revenue = total_revenue_raw - return_revenue

    # 客单价
    avg_order_value = total_revenue / order_count if order_count > 0 else 0

    # FBA/FBM（仅有效订单）
    fulfillment_stats = orders.exclude(order_status='Canceled').values('fulfillment_channel').annotate(
        count=Count('fulfillment_channel')
    )
    fba_count = sum(s['count'] for s in fulfillment_stats if s['fulfillment_channel'] == 'AFN')
    fbm_count = sum(s['count'] for s in fulfillment_stats if s['fulfillment_channel'] == 'MFN')

    # 计算占比
    fba_percentage = f"{fba_count / order_count * 100:.1f}%" if order_count > 0 else "0.0%"
    fbm_percentage = f"{fbm_count / order_count * 100:.1f}%" if order_count > 0 else "0.0%"

    # 退货率
    return_rate = f"{return_order_count / total_order_count * 100:.1f}%" if total_order_count > 0 else "0.0%"

    return {
        'order_count': order_count,
        'total_sales_quantity': total_sales_quantity,
        'total_revenue': round(total_revenue, 2),
        'avg_order_value': round(avg_order_value, 2),
        'fba_count': fba_count, 'fbm_count': fbm_count,
        'fba_percentage': fba_percentage, 'fbm_percentage': fbm_percentage,
        'return_order_count': return_order_count,  # 新增
        'return_rate': return_rate,  # 新增
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
    """计算所有指标的环比变化率（含退货）"""
    comparison = {}

    # 数值型指标（新增return_order_count）
    numeric_keys = [
        'order_count', 'total_sales_quantity', 'total_revenue',
        'avg_order_value', 'return_order_count'
    ]
    for key in numeric_keys:
        comparison[f'{key}_change'] = calculate_change_rate(
            current_stats[key], previous_stats[key]
        )

    # 百分比指标（新增return_rate）
    pct_keys = ['fba_percentage', 'fbm_percentage', 'return_rate']
    for key in pct_keys:
        current_val = float(current_stats[key].rstrip('%'))
        previous_val = float(previous_stats[key].rstrip('%'))
        comparison[f'{key}_change'] = calculate_change_rate(current_val, previous_val)

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
    """
    result = {'amazon': [], 'temu': []}

    # 调试日志（部署后可注释掉）
    print(f"\n{'=' * 60}")
    print(f"🔍 get_shop_ids_by_filter_with_platform:")
    print(f"   filter_type: {filter_type}")
    print(f"   filter_value: {filter_value} (type: {type(filter_value)})")
    print(f"   platform_info: {platform_info}")
    print(f"{'=' * 60}\n")

    # ========== 亚马逊店铺 ==========
    if platform_info['source'] in ['amazon_only', 'mixed']:
        if filter_type == 'ops_id':
            # 强制转换为int，避免类型不匹配
            shops = AmazonShop.objects.filter(ops_id=int(filter_value))
            result['amazon'] = list(shops.values_list('id', flat=True))
            print(f"✅ Amazon查询: ops_id={filter_value} → 找到 {len(result['amazon'])} 个店铺")
        elif filter_type == 'ops_group':
            user_ids = OperationalAccount.objects.filter(
                ops_group=filter_value
            ).values_list('user_id', flat=True)
            result['amazon'] = list(AmazonShop.objects.filter(
                ops_id__in=list(user_ids)
            ).values_list('id', flat=True))
            print(f"✅ Amazon组查询: {filter_value} → 找到 {len(result['amazon'])} 个店铺")
        elif filter_type == 'all':
            result['amazon'] = list(AmazonShop.objects.all().values_list('id', flat=True))
            print(f"⚠️ Amazon全量查询: 找到 {len(result['amazon'])} 个店铺")

    # ========== Temu店铺 ==========
    if platform_info['source'] in ['temu_only', 'mixed']:
        if filter_type == 'ops_id':
            shops = TemuShop.objects.filter(ops_id=int(filter_value))
            result['temu'] = list(shops.values_list('id', flat=True))
            print(f"✅ Temu查询: ops_id={filter_value} → 找到 {len(result['temu'])} 个店铺")
        elif filter_type == 'ops_group':
            user_ids = OperationalAccount.objects.filter(
                ops_group=filter_value
            ).values_list('user_id', flat=True)
            result['temu'] = list(TemuShop.objects.filter(
                ops_id__in=list(user_ids)
            ).values_list('id', flat=True))
            print(f"✅ Temu组查询: {filter_value} → 找到 {len(result['temu'])} 个店铺")
        elif filter_type == 'all':
            result['temu'] = list(TemuShop.objects.all().values_list('id', flat=True))
            print(f"⚠️ Temu全量查询: 找到 {len(result['temu'])} 个店铺")

    # 最终日志
    print(f"\n📊 最终结果: Amazon={len(result['amazon'])}个, Temu={len(result['temu'])}个\n")
    return result


def get_sales_trend_data(lingxing_shop_ids):
    """
    获取最近14天每日销量数据（排除退货订单）
    返回: [{date: '2025-11-18', sales: 156}, ...] 格式
    """
    # 计算14天日期范围
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=13)

    print(f"\n{'=' * 60}")
    print("📈 计算销量趋势数据(排除退货)...")
    print(f"统计日期范围: {start_date} 至 {end_date}")
    print(f"领星店铺IDs: {lingxing_shop_ids}")

    if not lingxing_shop_ids:
        print("⚠️ 没有店铺数据，返回空趋势数据")
        return []

    # ========== 修复：排除退货订单（使用 exclude） ==========
    # 退货订单的状态为 'Canceled'
    daily_sales_raw = AmazonOrderItem.objects.filter(
        order__lingxing_shop_id__in=lingxing_shop_ids,
        order__purchase_date_local__date__gte=start_date,
        order__purchase_date_local__date__lte=end_date,
    ).exclude(
        order__order_status='Canceled'  # 关键：排除退货订单
    ).values(
        date=TruncDate('order__purchase_date_local')
    ).annotate(
        sales=Sum('quantity_ordered')
    ).order_by('date')
    # ========== 修复结束 ==========

    # 将查询结果转换为字典 {date: sales}
    sales_dict = {}
    for item in daily_sales_raw:
        date_obj = item['date']
        sales_dict[date_obj] = item['sales'] or 0

    print(f"查询到 {len(sales_dict)} 天的有效销量数据（已排除退货）")

    # 组装14天完整数据（补全缺失日期）
    result = []
    for i in range(14):
        date = start_date + timedelta(days=i)
        sales = sales_dict.get(date, 0)
        result.append({
            'date': date.strftime('%Y-%m-%d'),
            'sales': sales
        })

    print(f"✅ 返回 {len(result)} 天的完整销量数据（已排除退货）")
    print(f"{'=' * 60}\n")

    return result

@login_required
def filter_amazon_data_api(request):
    """
    筛选亚马逊订单数据（支持多平台合并）
    修复了 ops_all 权限下数据混乱的问题
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

        # ========== 调试日志：输出实际查询的店铺明细 ==========
        print(f"\n{'='*60}")
        print(f"🔍 实际查询的店铺明细:")
        print(f"  用户: {user.first_name} (ID: {user.id})")
        print(f"  权限: {permissions}")
        print(f"  筛选类型: {filter_type}")
        print(f"  筛选值: {filter_value}")
        print(f"  平台类型: {platform_info['source']}")
        print(f"  Amazon 店铺ID: {shop_ids_by_platform['amazon']}")
        print(f"  Temu 店铺ID: {shop_ids_by_platform['temu']}")

        # 输出店铺名称以便识别
        if shop_ids_by_platform['amazon']:
            amazon_shops = AmazonShop.objects.filter(id__in=shop_ids_by_platform['amazon'])
            print(f"  Amazon 店铺名称: {list(amazon_shops.values_list('shop_name', flat=True))}")

        if shop_ids_by_platform['temu']:
            temu_shops = TemuShop.objects.filter(id__in=shop_ids_by_platform['temu'])
            print(f"  Temu 店铺名称: {list(temu_shops.values_list('shop_name', flat=True))}")

        print(f"{'='*60}\n")
        # ========== 调试日志结束 ==========

        # ========== 分别统计两个平台 ==========
        # Amazon统计
        amazon_stats = {
            'current': {
                'order_count': 0, 'total_sales_quantity': 0, 'total_revenue': 0.0,
                'avg_order_value': 0.0, 'fba_percentage': '0.0%', 'fbm_percentage': '0.0%',
                'return_order_count': 0, 'return_rate': '0.0%',
            },
            'previous': {
                'order_count': 0, 'total_sales_quantity': 0, 'total_revenue': 0.0,
                'avg_order_value': 0.0, 'fba_percentage': '0.0%', 'fbm_percentage': '0.0%',
                'return_order_count': 0, 'return_rate': '0.0%',
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
                'avg_order_value': 0.0, 'fba_percentage': '0.0%', 'fbm_percentage': '0.0%',
                'return_order_count': 0, 'return_rate': '0.0%',
            },
            'previous': {
                'order_count': 0, 'total_sales_quantity': 0, 'total_revenue': 0.0,
                'avg_order_value': 0.0, 'fba_percentage': '0.0%', 'fbm_percentage': '0.0%',
                'return_order_count': 0, 'return_rate': '0.0%',
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
            """合并两个平台的统计数据（支持退货指标）"""
            # 基础字段直接相加
            order_count = current['order_count'] + previous['order_count']
            total_sales_quantity = current['total_sales_quantity'] + previous['total_sales_quantity']
            total_revenue = current['total_revenue'] + previous['total_revenue']

            # 退货字段
            return_order_count = current.get('return_order_count', 0) + previous.get('return_order_count', 0)

            # 客单价
            avg_order_value = round(total_revenue / order_count, 2) if order_count > 0 else 0.0

            # FBA/FBM
            fba_count = current.get('fba_count', 0) + previous.get('fba_count', 0)
            fbm_count = current.get('fbm_count', 0) + previous.get('fbm_count', 0)
            fba_percentage = f"{fba_count / order_count * 100:.1f}%" if order_count > 0 else "0.0%"
            fbm_percentage = f"{fbm_count / order_count * 100:.1f}%" if order_count > 0 else "0.0%"

            # 退货率
            total_order_combined = order_count + return_order_count
            return_rate = f"{return_order_count / total_order_combined * 100:.1f}%" if total_order_combined > 0 else "0.0%"

            result = {
                'order_count': order_count,
                'total_sales_quantity': total_sales_quantity,
                'total_revenue': round(total_revenue, 2),
                'avg_order_value': avg_order_value,
                'fba_count': fba_count, 'fbm_count': fbm_count,
                'fba_percentage': fba_percentage, 'fbm_percentage': fbm_percentage,
                'return_order_count': return_order_count,
                'return_rate': return_rate,
            }

            return result

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
    Temu核心统计函数（含退货指标）
    """
    if not temu_shop_ids:
        return {
            'order_count': 0, 'total_sales_quantity': 0, 'total_revenue': 0.0,
            'avg_order_value': 0.0, 'fba_count': 0, 'fbm_count': 0,
            'fba_percentage': '0.0%', 'fbm_percentage': '0.0%',
            'return_order_count': 0, 'return_rate': '0.0%',
        }

    # 基础筛选
    order_filter = Q(lingxing_shop__temu_shop_id__in=temu_shop_ids)
    order_filter &= Q(global_purchase_time__date__gte=start_date)
    order_filter &= Q(global_purchase_time__date__lte=end_date)

    # 所有订单（含退货）
    orders = TemuOrder.objects.filter(order_filter).only(
        'global_order_no', 'platform_info'
    )
    total_order_count = orders.count()

    # 退货订单（platform_info[0]['status'] == 'CANCELED'）
    # 由于JSONField查询特性，采用Python过滤
    all_orders_list = list(orders.values('global_order_no', 'platform_info'))
    cancelled_order_nos = [
        o['global_order_no'] for o in all_orders_list
        if o.get('platform_info') and len(o['platform_info']) > 0
           and o['platform_info'][0].get('status') == 'CANCELED'
    ]
    return_order_count = len(cancelled_order_nos)

    # 有效订单量
    order_count = total_order_count - return_order_count

    if order_count == 0:
        return {
            'order_count': 0, 'total_sales_quantity': 0, 'total_revenue': 0.0,
            'avg_order_value': 0.0, 'fba_count': 0, 'fbm_count': 0,
            'fba_percentage': '0.0%', 'fbm_percentage': '0.0%',
            'return_order_count': return_order_count,
            'return_rate': '0.0%',
        }

    # 所有订单项
    all_items = TemuOrderItem.objects.filter(
        order__global_order_no__in=[o['global_order_no'] for o in all_orders_list]
    )

    # 总销量
    total_sales_quantity_raw = all_items.aggregate(total=Sum('quantity'))['total'] or 0

    # 退货销量
    return_sales_quantity = all_items.filter(
        order__global_order_no__in=cancelled_order_nos
    ).aggregate(total=Sum('quantity'))['total'] or 0

    # 有效销量
    total_sales_quantity = total_sales_quantity_raw - return_sales_quantity

    # 退货率
    return_rate = f"{return_order_count / total_order_count * 100:.1f}%" if total_order_count > 0 else "0.0%"

    return {
        'order_count': order_count,
        'total_sales_quantity': total_sales_quantity,
        'total_revenue': 0.0, 'avg_order_value': 0.0,
        'fba_count': 0, 'fbm_count': 0,
        'fba_percentage': '0.0%', 'fbm_percentage': '0.0%',
        'return_order_count': return_order_count,
        'return_rate': return_rate,
    }


def get_temu_sales_trend_data(temu_shop_ids):
    """
    Temu最近14天销量趋势（排除退货订单）
    """
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=13)

    if not temu_shop_ids:
        return []

    print(f"\n{'=' * 60}")
    print("📈 计算Temu销量趋势(排除退货)...")
    print(f"统计日期范围: {start_date} 至 {end_date}")
    print(f"Temu店铺IDs: {temu_shop_ids}")

    # ========== 修复：排除退货订单 ==========
    # Temu退货订单的 platform_info[0]['status'] == 'CANCELED'
    # 我们需要先找出所有退货订单的订单号，然后在查询中排除
    from django.db.models import Subquery

    # 获取日期范围内的所有订单
    all_orders_in_range = TemuOrder.objects.filter(
        lingxing_shop__temu_shop_id__in=temu_shop_ids,
        global_purchase_time__date__gte=start_date,
        global_purchase_time__date__lte=end_date
    ).values('global_order_no', 'platform_info')

    # 找出退货订单号
    cancelled_order_nos = [
        o['global_order_no'] for o in all_orders_in_range
        if o.get('platform_info') and len(o.get('platform_info', [])) > 0
           and o['platform_info'][0].get('status') == 'CANCELED'
    ]

    print(f"找到 {len(cancelled_order_nos)} 个退货订单，将排除")

    # 查询销量，排除退货订单
    daily_sales_raw = TemuOrderItem.objects.filter(
        order__lingxing_shop__temu_shop_id__in=temu_shop_ids,
        order__global_purchase_time__date__gte=start_date,
        order__global_purchase_time__date__lte=end_date
    ).exclude(
        order__global_order_no__in=cancelled_order_nos  # 关键：排除退货订单
    ).values(
        date=TruncDate('order__global_purchase_time')
    ).annotate(
        sales=Sum('quantity')
    ).order_by('date')
    # ========== 修复结束 ==========

    sales_dict = {item['date']: item['sales'] or 0 for item in daily_sales_raw}
    print(f"查询到 {len(sales_dict)} 天的有效销量数据（已排除退货）")

    # 补全14天
    result = []
    for i in range(14):
        date = start_date + timedelta(days=i)
        sales = sales_dict.get(date, 0)
        result.append({
            'date': date.strftime('%Y-%m-%d'),
            'sales': sales
        })

    print(f"✅ 返回 {len(result)} 天的完整销量数据（已排除退货）")
    print(f"{'=' * 60}\n")

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
                'return_order_count': current_stats['return_order_count'],  # 新增
                'return_rate': current_stats['return_rate'],  # 新增
            },
            'previous': {
                'order_count': previous_stats['order_count'],
                'total_sales_quantity': previous_stats['total_sales_quantity'],
                'total_revenue': previous_stats['total_revenue'],
                'avg_order_value': previous_stats['avg_order_value'],
                'fba_percentage': previous_stats['fba_percentage'],
                'fbm_percentage': previous_stats['fbm_percentage'],
                'return_order_count': previous_stats['return_order_count'],  # 新增
                'return_rate': previous_stats['return_rate'],  # 新增
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
