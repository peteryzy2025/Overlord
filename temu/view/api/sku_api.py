# -*- coding: utf-8 -*-
"""
Temu SKU API
处理 SKU 规格的新增/更新/查询
"""
import json
from decimal import Decimal
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction

from temu.models import TemuSKU


@csrf_exempt
@require_http_methods(["POST"])
def batch_upsert_sku_api(request):
    """
    批量新增/更新 SKU 规格 API
    
    入参格式（JSON）：
    {
        "data": [
            {
                "temu_sku": "SKU001",
                "length_cm": "10.00",
                "width_cm": "5.00",
                "height_cm": "3.00",
                "weight_g": "100.000"
            },
            {
                "temu_sku": "SKU002",
                "length_cm": "20.00",
                "width_cm": "15.00",
                "height_cm": "10.00",
                "weight_g": "500.000"
            }
        ]
    }
    
    返回格式：
    {
        "success": true,
        "message": "处理完成",
        "data": {
            "created": ["SKU001"],      # 新增的 SKU
            "updated": ["SKU002"],      # 更新的 SKU
            "skipped": ["SKU003"],      # 数据相同跳过的 SKU
            "failed": []                 # 失败的 SKU
        }
    }
    """
    try:
        body = json.loads(request.body)
        data = body.get('data', [])
        
        if not data or not isinstance(data, list):
            return JsonResponse({
                'success': False,
                'message': '参数错误：data 必须是非空列表'
            }, status=400)
        
        created_list = []
        updated_list = []
        skipped_list = []
        failed_list = []
        
        with transaction.atomic():
            for item in data:
                sku_code = item.get('temu_sku')
                if not sku_code:
                    failed_list.append({
                        'sku': None,
                        'error': '缺少 temu_sku 字段'
                    })
                    continue
                
                try:
                    result = _upsert_single_sku(sku_code, item)
                    if result == 'created':
                        created_list.append(sku_code)
                    elif result == 'updated':
                        updated_list.append(sku_code)
                    elif result == 'skipped':
                        skipped_list.append(sku_code)
                except Exception as e:
                    failed_list.append({
                        'sku': sku_code,
                        'error': str(e)
                    })
        
        return JsonResponse({
            'success': True,
            'message': f'处理完成：新增 {len(created_list)} 个，更新 {len(updated_list)} 个，跳过 {len(skipped_list)} 个，失败 {len(failed_list)} 个',
            'data': {
                'created': created_list,
                'updated': updated_list,
                'skipped': skipped_list,
                'failed': failed_list
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'JSON 解析错误'
        }, status=400)
    except Exception as e:
        import traceback
        return JsonResponse({
            'success': False,
            'message': str(e),
            'detail': traceback.format_exc()
        }, status=500)


def _upsert_single_sku(sku_code, sku_data):
    """
    处理单个 SKU 的新增/更新
    
    Returns:
        'created': 新增
        'updated': 更新
        'skipped': 跳过（数据相同）
    """
    # 提取字段值
    length_cm = _parse_decimal(sku_data.get('length_cm'))
    width_cm = _parse_decimal(sku_data.get('width_cm'))
    height_cm = _parse_decimal(sku_data.get('height_cm'))
    weight_g = _parse_decimal(sku_data.get('weight_g'), decimal_places=3)
    
    try:
        # 尝试获取已存在的 SKU
        sku = TemuSKU.objects.get(temu_sku=sku_code)
        
        # 检查数据是否有变化
        if (_decimal_eq(sku.length_cm, length_cm) and
            _decimal_eq(sku.width_cm, width_cm) and
            _decimal_eq(sku.height_cm, height_cm) and
            _decimal_eq(sku.weight_g, weight_g)):
            # 数据相同，跳过
            return 'skipped'
        
        # 数据不同，更新
        sku.length_cm = length_cm
        sku.width_cm = width_cm
        sku.height_cm = height_cm
        sku.weight_g = weight_g
        sku.save()
        return 'updated'
        
    except TemuSKU.DoesNotExist:
        # SKU 不存在，创建
        TemuSKU.objects.create(
            temu_sku=sku_code,
            length_cm=length_cm,
            width_cm=width_cm,
            height_cm=height_cm,
            weight_g=weight_g
        )
        return 'created'


def _parse_decimal(value, decimal_places=2):
    """
    将值解析为 Decimal
    """
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value))
    except (ValueError, TypeError):
        return None


def _decimal_eq(a, b):
    """
    比较两个 Decimal 值是否相等（处理 None 情况）
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return a == b


@csrf_exempt
@require_http_methods(["POST"])
def get_temu_shop_password_api(request):
    """
    根据店铺名称获取店铺登录账号和密码 API
    
    入参格式（JSON）：
    {
        "shop_name": "店铺名称"
    }
    
    返回格式：
    {
        "success": true,
        "data": {
            "shop_name": "店铺名称",
            "shop_account": "登录账号/手机号",
            "shop_password": "密码"
        }
    }
    或
    {
        "success": false,
        "message": "店铺不存在"
    }
    """
    try:
        body = json.loads(request.body)
        shop_name = body.get('shop_name', '').strip()
        
        if not shop_name:
            return JsonResponse({
                'success': False,
                'message': '参数错误：shop_name 不能为空'
            }, status=400)
        
        from general.models import TemuShop
        
        try:
            shop = TemuShop.objects.get(shop_name=shop_name)
            return JsonResponse({
                'success': True,
                'data': {
                    'shop_name': shop.shop_name,
                    'shop_account': shop.shop_account or '',
                    'shop_password': shop.shop_password or ''
                }
            })
        except TemuShop.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': f'店铺 "{shop_name}" 不存在'
            }, status=404)
        except TemuShop.MultipleObjectsReturned:
            # 如果有多个同名店铺，返回第一个
            shop = TemuShop.objects.filter(shop_name=shop_name).first()
            return JsonResponse({
                'success': True,
                'data': {
                    'shop_name': shop.shop_name,
                    'shop_account': shop.shop_account or '',
                    'shop_password': shop.shop_password or ''
                }
            })
            
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'JSON 解析错误'
        }, status=400)
    except Exception as e:
        import traceback
        return JsonResponse({
            'success': False,
            'message': str(e),
            'detail': traceback.format_exc()
        }, status=500)
