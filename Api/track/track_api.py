import requests
import logging
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from track.models import Tracking, Courier, TrackingDetail
from datetime import datetime
from amazon.models import AmazonOrders
from temu.models import TemuOrder
from general.models import User
logger = logging.getLogger(__name__)


def register_tracking(track_no_list, api_key="34546e68d4c74ab2849318a1b50be83d"):
    """
    调用Track123批量导入运单API 新增这个运单
    """
    url = "https://api.track123.com/gateway/open-api/tk/v2/track/import"
    headers = {
        "Track123-Api-Secret": api_key,
        "Content-Type": "application/json"
    }
    # payload = [{"trackNo": track_no} for track_no in track_no_list]
    payload = [{"trackNo": track_no.replace(" ", "")} for track_no in track_no_list]

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"API请求失败: {str(e)}")
        return {
            'code': 'E9999',
            'msg': f'API请求失败: {str(e)}',
            'data': {'accepted': [], 'rejected': []}
        }


def query_tracking_v2(track_nos, api_key="34546e68d4c74ab2849318a1b50be83d"):
    """
    调用Track123批量查询运单轨迹API
    """
    url = "https://api.track123.com/gateway/open-api/tk/v2.1/track/query"
    headers = {
        "Track123-Api-Secret": api_key,
        "Content-Type": "application/json"
    }
    payload = {"trackNos": track_nos}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"查询API请求失败: {str(e)}")
        return {
            'code': 'E9999',
            'msg': f'API请求失败: {str(e)}',
            'data': {'accepted': {}, 'rejected': []}
        }


def parse_datetime(dt_str):
    """解析时间字符串为datetime对象"""
    if not dt_str:
        return None
    try:
        return datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
    except Exception as e:
        logger.warning(f"时间解析失败 '{dt_str}': {e}")
        return None


def get_order_info(track_no):
    """
    根据运单号查找关联订单和运营信息
    返回: (order对象, platform, order_id, ops_group, ops_name) 或 None
    """
    # 1. 先查亚马逊订单
    amazon_order = AmazonOrders.objects.filter(divi_tracking_number=track_no).first()
    if amazon_order:
        # 获取运营信息
        ops_group = None
        ops_name = None

        if amazon_order.lingxing_shop and amazon_order.lingxing_shop.amazon_shop:
            ops_user = amazon_order.lingxing_shop.amazon_shop.ops
            if ops_user:
                ops_name = ops_user.first_name or '-'
                if hasattr(ops_user, 'operational_account') and ops_user.operational_account:
                    ops_group = ops_user.operational_account.ops_group or '-'

        return {
            'order': amazon_order,
            'platform': 'amazon',
            'order_id': amazon_order.amazon_order_id or amazon_order.order_no or '-',
            'ops_group': ops_group or '-',
            'ops_name': ops_name or '-',
            'content_type': ContentType.objects.get_for_model(AmazonOrders),
            'object_id': amazon_order.pk
        }

    # 2. 再查Temu订单
    temu_order = TemuOrder.objects.filter(tracking_number=track_no).first()
    if temu_order:
        # 获取运营信息
        ops_group = None
        ops_name = None

        if temu_order.lingxing_shop and temu_order.lingxing_shop.temu_shop:
            ops_id = temu_order.lingxing_shop.temu_shop.ops_id
            if ops_id:
                try:
                    ops_user = User.objects.get(id=ops_id)
                    ops_name = ops_user.first_name or '-'
                    if hasattr(ops_user, 'operational_account') and ops_user.operational_account:
                        ops_group = ops_user.operational_account.ops_group or '-'
                except User.DoesNotExist:
                    pass

        return {
            'order': temu_order,
            'platform': 'temu',
            'order_id': temu_order.global_order_no or '-',
            'ops_group': ops_group or '-',
            'ops_name': ops_name or '-',
            'content_type': ContentType.objects.get_for_model(TemuOrder),
            'object_id': temu_order.pk
        }

    # 3. 未找到订单
    return None
def create_or_update_courier(local_info):
    """创建或更新物流商信息"""
    courier_code = local_info.get('courierCode')
    if not courier_code:
        return None

    courier, created = Courier.objects.update_or_create(
        code=courier_code,
        defaults={
            'name_cn': local_info.get('courierNameCN', ''),
            'name_en': local_info.get('courierNameEN', ''),
            'homepage': local_info.get('courierHomePage', ''),
        }
    )
    if created:
        logger.info(f"创建新物流商: {courier_code}")
    return courier


def update_tracking_detail(tracking, details_data):
    """更新轨迹明细（先删除旧数据，再插入新数据）"""
    if not details_data:
        return

    try:
        # 删除该运单原有轨迹
        deleted_count, _ = TrackingDetail.objects.filter(tracking=tracking).delete()
        if deleted_count > 0:
            logger.info(f"删除 {tracking.track_no} 的旧轨迹 {deleted_count} 条")

        # 批量创建新轨迹
        detail_objects = []
        for detail in details_data:
            detail_obj = TrackingDetail(
                tracking=tracking,
                event_time=parse_datetime(detail.get('eventTime')),
                address=detail.get('address', ''),
                event_detail=detail.get('eventDetail', ''),
                transit_sub_status=detail.get('transitSubStatus', ''),
            )
            detail_objects.append(detail_obj)

        TrackingDetail.objects.bulk_create(detail_objects)
        logger.info(f"创建 {tracking.track_no} 的新轨迹 {len(detail_objects)} 条")

    except Exception as e:
        logger.error(f"更新轨迹明细失败 {tracking.track_no}: {e}")


def refresh_tracking_batch(items, api_key="34546e68d4c74ab2849318a1b50be83d"):
    """
    调用Track123批量刷新运单API
    items: [{"trackNo": "...", "courierCode": "..."}]
    """
    if not items:
        return

    url = "https://api.track123.com/gateway/open-api/tk/v2.1/track/refresh-batch"
    headers = {
        "Track123-Api-Secret": api_key,
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, json=items, headers=headers, timeout=60)
        response.raise_for_status()
        logger.info(f"成功刷新 {len(items)} 个运单的轨迹")
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"刷新API请求失败: {str(e)}")
        return None


def get_tracking_updates(track_nos):
    """
    批量查询并更新物流轨迹（新增填充冗余字段逻辑）
    """
    if not track_nos:
        return {
            'code': '00000',
            'success': True,
            'data': {
                'total': 0,
                'success_count': 0,
                'fail_count': 0,
                'errors': []
            }
        }

    print(f"准备更新 {len(track_nos)} 个物流单号的信息")
    results = {
        'code': '00000',
        'success': True,
        'data': {
            'total': len(track_nos),
            'success_count': 0,
            'fail_count': 0,
            'errors': []
        }
    }

    try:
        batch_size = 50
        for i in range(0, len(track_nos), batch_size):
            batch = track_nos[i:i + batch_size]
            print(f"处理第 {i // batch_size + 1} 批: {len(batch)} 个单号")

            try:
                # 刷新数据
                try:
                    trackings = Tracking.objects.filter(track_no__in=batch).select_related('courier')
                    refresh_items = []
                    for t in trackings:
                        if t.courier and t.courier.code:
                            refresh_items.append({
                                "trackNo": t.track_no,
                                "courierCode": t.courier.code
                            })
                    
                    if refresh_items:
                        print(f"尝试刷新 {len(refresh_items)} 个运单...")
                        refresh_tracking_batch(refresh_items)
                except Exception as e:
                    logger.error(f"刷新运单失败，但不影响查询: {e}")
                    print(f"刷新运单失败: {e}")

                api_result = query_tracking_v2(batch)

                if api_result.get('code') != '00000':
                    error_msg = api_result.get('msg', 'API返回错误')
                    print(f"API返回错误: {error_msg}")
                    results['data']['fail_count'] += len(batch)
                    results['data']['errors'].append({
                        'batch': batch,
                        'error': error_msg
                    })
                    continue

                content_list = api_result.get('data', {}).get('accepted', {}).get('content', [])

                with transaction.atomic():
                    for item in content_list:
                        try:
                            track_no = item.get('trackNo')
                            if not track_no:
                                continue

                            local_info = item.get('localLogisticsInfo', {})
                            courier = create_or_update_courier(local_info) if local_info else None

                            # ===== 新增：查找关联订单和运营信息 =====
                            order_info = get_order_info(track_no)

                            # 准备更新数据（包含冗余字段）
                            update_data = {
                                'transit_status': item.get('transitStatus', ''),
                                'transit_sub_status': item.get('transitSubStatus', ''),
                                'tracking_status': item.get('trackingStatus', ''),
                                'delivered_time': parse_datetime(item.get('deliveredTime')),
                                'last_update_time': parse_datetime(item.get('lastTrackingTime')),
                                'order_time': parse_datetime(item.get('orderTime')),
                                'next_update_time': parse_datetime(item.get('nextUpdateTime')),
                                'stay_days': item.get('stayDays'),
                                'transit_days': item.get('transitDays'),
                                'delivered_days': item.get('deliveredDays'),
                                'ship_from': item.get('shipFrom', ''),
                                'ship_to': item.get('shipTo', ''),
                                'shipment_type': item.get('shipmentType', ''),
                                'raw_data': item,
                            }

                            # 填充冗余字段
                            if order_info:
                                update_data.update({
                                    'platform': order_info['platform'],
                                    'order_id': order_info['order_id'],
                                    'ops_group': order_info['ops_group'],
                                    'ops_name': order_info['ops_name'],
                                    'content_type': order_info['content_type'],
                                    'object_id': order_info['object_id'],
                                })
                            else:
                                # 未找到订单
                                update_data.update({
                                    'platform': 'other',
                                    'order_id': None,
                                    'ops_group': None,
                                    'ops_name': None,
                                    'content_type': None,
                                    'object_id': None,
                                })

                            if courier:
                                update_data['courier'] = courier

                            tracking_obj, created = Tracking.objects.update_or_create(
                                track_no=track_no,
                                defaults=update_data
                            )

                            if created:
                                print(f"✅ 创建新运单: {track_no}")
                            else:
                                print(f"🔄 更新运单: {track_no} ({item.get('transitStatus')})")

                            details = local_info.get('trackingDetails', [])
                            if details:
                                update_tracking_detail(tracking_obj, details)

                            results['data']['success_count'] += 1

                        except Exception as e:
                            print(f"处理单号 {track_no} 失败: {e}")
                            results['data']['fail_count'] += 1
                            results['data']['errors'].append({
                                'track_no': track_no,
                                'error': str(e)
                            })
                            continue

                rejected = api_result.get('data', {}).get('rejected', [])
                for rejected_item in rejected:
                    print(f"❌ 单号被拒绝: {rejected_item}")
                    track_no = rejected_item.get('trackNo', '未知单号')
                    error_msg = rejected_item.get('error', {}).get('msg', '未知错误')
                    results['data']['fail_count'] += 1
                    results['data']['errors'].append({
                        'track_no': track_no,
                        'error': error_msg
                    })

            except Exception as e:
                print(f"批量查询失败: {e}")
                results['data']['fail_count'] += len(batch)
                results['data']['errors'].append({
                    'batch': batch,
                    'error': str(e)
                })
                continue

        print(f"批量更新完成！成功: {results['data']['success_count']}, 失败: {results['data']['fail_count']}")
        return results

    except Exception as e:
        print(f"更新过程中发生严重错误: {e}")
        return {
            'code': '99999',
            'success': False,
            'message': str(e),
            'data': {
                'total': len(track_nos),
                'success_count': 0,
                'fail_count': len(track_nos),
                'errors': [{
                    'error': str(e)
                }]
            }
        }
