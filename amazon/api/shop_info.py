"""
亚马逊店铺信息查询 API 模块
提供给外部调用的店铺信息查询接口
"""

import json
from datetime import date, datetime
from decimal import Decimal

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from general.models import AmazonShop


class DateTimeEncoder(json.JSONEncoder):
    """处理 datetime 和 date 类型的 JSON 编码器"""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def json_response(success: bool, data=None, message: str = "", status_code: int = 200):
    """
    统一返回 JSON 格式响应
    """
    response_data = {
        "success": success,
        "message": message,
        "data": data if data is not None else {}
    }
    return JsonResponse(
        response_data,
        encoder=DateTimeEncoder,
        status=status_code
    )


def filter_sensitive_fields(shop: AmazonShop) -> dict:
    """
    过滤敏感字段，返回安全的店铺信息字典
    """
    # 定义敏感字段列表（不返回给外部）
    sensitive_fields = {
        'shop_password',
        'email_password',
        'credit_card_number',
        'credit_card_cvv',
        'payment_password',
        'login_password',
        'bind_phone',
        'legal_person_phone',
        'collection_card_number',
        'registered_phone',
        'backup_email_or_phone',
        'id_number',
        'credit_card_expiry',
    }
    
    # 构建返回数据
    result = {}
    
    # 基础字段
    result['id'] = shop.id
    result['shop_name'] = shop.shop_name
    result['shop_number'] = shop.shop_number
    result['amazon_shop_name'] = shop.amazon_shop_name
    result['seller_mark'] = shop.seller_mark
    result['email_account'] = shop.email_account
    result['customer'] = shop.customer
    result['shop_status'] = shop.shop_status
    result['whitelist'] = shop.whitelist
    result['remark'] = shop.remark
    result['additional_remark'] = shop.additional_remark
    result['browser'] = shop.browser
    result['ip_address'] = shop.ip_address
    result['shop_date'] = shop.shop_date
    
    # 公司/项目/运营信息
    result['company_id'] = shop.company_id if shop.company else None
    result['company_name'] = shop.company.name if shop.company else None
    result['project_id'] = shop.project_id if shop.project else None
    result['project_name'] = shop.project.name if shop.project else None
    result['ops_id'] = shop.ops_id if shop.ops else None
    result['ops_name'] = shop.ops.username if shop.ops else None
    
    # 渠道信息
    result['qu_dao'] = shop.qu_dao
    result['channel_risk_id'] = shop.channel_risk_id
    result['divi_shop_id'] = shop.divi_shop_id
    
    # 收款信息（脱敏）
    result['is_consolidated'] = shop.is_consolidated
    result['bind_collection'] = shop.bind_collection
    result['collection_channel'] = shop.collection_channel
    result['xunhui_login_account'] = shop.xunhui_login_account
    
    # 信用卡信息（仅返回渠道）
    result['credit_card_channel'] = shop.credit_card_channel
    
    # 公司信息
    result['company_name_detail'] = shop.company_name
    result['license_number'] = shop.license_number
    result['business_license_date'] = shop.business_license_date
    result['birth_date'] = shop.birth_date
    result['id_expiry_date'] = shop.id_expiry_date
    
    # 状态标记
    result['ling_xing_if'] = shop.ling_xing_if
    result['qupital_if'] = shop.qupital_if
    result['img1'] = shop.img1
    result['voucher_163'] = shop.voucher_163
    result['email_163_account'] = shop.email_163_account
    
    # 时间戳
    result['created_at'] = shop.created_at
    result['updated_at'] = shop.updated_at
    
    return result


@csrf_exempt
@require_http_methods(["GET", "POST"])
def get_shop_info_by_name(request):
    """
    根据店铺名称查询亚马逊店铺信息
    
    请求参数:
        - shopname (str, 必填): 店铺名称，精确匹配
    
    GET 请求示例:
        GET /amazon/api/shop-info/?shopname=店铺A
    
    POST 请求示例:
        POST /amazon/api/shop-info/
        Content-Type: application/json
        {
            "shopname": "店铺A"
        }
    
    返回示例:
        {
            "success": true,
            "message": "查询成功",
            "data": {
                "id": 1,
                "shop_name": "店铺A",
                "shop_number": 1001,
                "amazon_shop_name": "Amazon-Shop-A",
                "email_account": "shop@example.com",
                "shop_status": "status-active",
                "browser": "闪店",
                "ops_name": "运营人员",
                "company_name": "公司A",
                ...
            }
        }
    
    错误返回:
        {
            "success": false,
            "message": "未找到店铺名为 'xxx' 的店铺",
            "data": {}
        }
    """
    try:
        # 1. 获取参数（支持 GET 和 POST）
        if request.method == "GET":
            shop_name = request.GET.get("shopname", "").strip()
        else:
            try:
                body = json.loads(request.body)
                shop_name = body.get("shopname", "").strip()
            except json.JSONDecodeError:
                return json_response(False, message="请求体必须是有效的 JSON 格式", status_code=400)
        
        # 2. 校验参数
        if not shop_name:
            return json_response(False, message="缺少必填参数: shopname", status_code=400)
        
        # 3. 查询店铺（精确匹配，返回第一个）
        shop = AmazonShop.objects.filter(
            shop_name=shop_name
        ).select_related(
            'company', 'project', 'ops', 'channel_risk'
        ).first()
        
        if not shop:
            return json_response(
                False, 
                message=f"未找到店铺名为 '{shop_name}' 的店铺", 
                status_code=404
            )
        
        # 4. 过滤敏感字段并返回
        data = filter_sensitive_fields(shop)
        
        return json_response(True, data=data, message="查询成功")
        
    except Exception as e:
        return json_response(False, message=f"服务器错误: {str(e)}", status_code=500)
