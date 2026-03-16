"""
亚马逊巡店 API 模块
提供给外部（如影刀）调用的接口
"""

import json
from datetime import date, datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from decimal import Decimal, InvalidOperation
from general.models import AmazonShop
from amazon.models import AmazonShopDailyCheck


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


@csrf_exempt
@require_http_methods(["POST"])
def init_daily_shop_check(request):
    """
    初始化今日亚马逊巡店日报
    
    请求参数（JSON 格式）:
        - shop_status (str, 可选): 店铺状态，如 "正常"
        - browser (str, 可选): 浏览器，如 "闪店"
        - project_id (int, 可选): 项目 ID
        - check_date (str, 可选): 巡店日期，格式 "YYYY-MM-DD"，默认今天
    
    返回示例:
        {
            "success": true,
            "message": "初始化完成",
            "data": {
                "check_date": "2026-03-16",
                "total_shops": 100,
                "inserted": 80,
                "skipped": 20
            }
        }
    """
    try:
        # 1. 解析请求参数
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return json_response(False, message="请求体必须是有效的 JSON 格式", status_code=400)
        
        shop_status = body.get("shop_status", "").strip() or None
        browser = body.get("browser", "").strip() or None
        project_id = body.get("project_id")
        check_date_str = body.get("check_date", "").strip()
        
        # 2. 处理日期参数
        if check_date_str:
            try:
                check_date = datetime.strptime(check_date_str, "%Y-%m-%d").date()
            except ValueError:
                return json_response(False, message="日期格式错误，请使用 YYYY-MM-DD 格式", status_code=400)
        else:
            check_date = date.today()
        
        # 3. 构建查询条件
        filters = {}
        if shop_status:
            filters["shop_status"] = shop_status
        if browser:
            filters["browser"] = browser
        if project_id is not None:
            try:
                filters["project_id"] = int(project_id)
            except (ValueError, TypeError):
                return json_response(False, message="project_id 必须是整数", status_code=400)
        
        # 4. 查询符合条件的店铺
        shops = AmazonShop.objects.filter(**filters)
        total_shops = shops.count()
        
        if total_shops == 0:
            return json_response(
                True, 
                data={
                    "check_date": check_date.isoformat(),
                    "total_shops": 0,
                    "inserted": 0,
                    "skipped": 0
                },
                message="未找到符合条件的店铺"
            )
        
        # 5. 批量创建巡店记录（跳过已存在的）
        inserted_count = 0
        skipped_count = 0
        
        for shop in shops:
            # 使用 atomic 隔离每个插入操作，避免事务污染
            with transaction.atomic():
                try:
                    AmazonShopDailyCheck.objects.create(
                        shop=shop,
                        check_date=check_date,
                        visited=False,
                        performance_checked=False,
                        withdrawal_processed=False
                    )
                    inserted_count += 1
                except IntegrityError:
                    # 唯一约束冲突，记录已存在
                    skipped_count += 1
        
        # 6. 返回结果
        result_data = {
            "check_date": check_date.isoformat(),
            "total_shops": total_shops,
            "inserted": inserted_count,
            "skipped": skipped_count
        }
        
        return json_response(
            True,
            data=result_data,
            message=f"初始化完成，新增 {inserted_count} 条记录，跳过 {skipped_count} 条已有记录"
        )
        
    except Exception as e:
        return json_response(False, message=f"服务器错误: {str(e)}", status_code=500)


@csrf_exempt
@require_http_methods(["GET"])
def get_daily_check_list(request):
    """
    获取巡店日报列表
    
    请求参数（Query String）:
        - check_date (str, 可选): 巡店日期，格式 "YYYY-MM-DD"，默认今天
        - shop_status (str, 可选): 按店铺状态筛选
        - browser (str, 可选): 按浏览器筛选
        - project_id (int, 可选): 按项目 ID 筛选
        - visited (bool, 可选): 按是否已访问筛选
        - performance_checked (bool, 可选): 按是否已检查绩效筛选
        - withdrawal_processed (bool, 可选): 按是否已处理提现筛选
    
    返回示例:
        {
            "success": true,
            "message": "",
            "data": {
                "check_date": "2026-03-16",
                "total": 100,
                "checked": 50,
                "unchecked": 50,
                "records": [
                    {
                        "id": 1,
                        "shop_id": 123,
                        "shop_name": "店铺A",
                        "check_date": "2026-03-16",
                        "visited": true,
                        "performance_checked": false,
                        "withdrawal_processed": false,
                        "withdrawal_amount": null,
                        "last_restock_date": null,
                        "shop_status": ""
                    }
                ]
            }
        }
    """
    try:
        # 1. 解析参数
        check_date_str = request.GET.get("check_date", "").strip()
        shop_status = request.GET.get("shop_status", "").strip() or None
        browser = request.GET.get("browser", "").strip() or None
        project_id = request.GET.get("project_id")
        visited = request.GET.get("visited")
        performance_checked = request.GET.get("performance_checked")
        withdrawal_processed = request.GET.get("withdrawal_processed")
        
        # 2. 处理日期
        if check_date_str:
            try:
                check_date = datetime.strptime(check_date_str, "%Y-%m-%d").date()
            except ValueError:
                return json_response(False, message="日期格式错误，请使用 YYYY-MM-DD 格式", status_code=400)
        else:
            check_date = date.today()
        
        # 3. 构建查询条件
        filters = {"check_date": check_date}
        
        # 店铺相关筛选
        shop_filters = {}
        if shop_status:
            shop_filters["shop__shop_status"] = shop_status
        if browser:
            shop_filters["shop__browser"] = browser
        if project_id is not None:
            try:
                shop_filters["shop__project_id"] = int(project_id)
            except (ValueError, TypeError):
                return json_response(False, message="project_id 必须是整数", status_code=400)
        
        filters.update(shop_filters)
        
        # 巡店状态筛选
        if visited is not None:
            filters["visited"] = visited.lower() == "true"
        if performance_checked is not None:
            filters["performance_checked"] = performance_checked.lower() == "true"
        if withdrawal_processed is not None:
            filters["withdrawal_processed"] = withdrawal_processed.lower() == "true"
        
        # 4. 查询记录
        records = AmazonShopDailyCheck.objects.filter(**filters).select_related("shop")
        
        # 5. 构建返回数据
        record_list = []
        for record in records:
            record_list.append({
                "id": record.id,
                "shop_id": record.shop_id,
                "shop_name": record.shop.shop_name if record.shop else None,
                "check_date": record.check_date.isoformat(),
                "visited": record.visited,
                "performance_checked": record.performance_checked,
                "withdrawal_processed": record.withdrawal_processed,
                "withdrawal_amount": record.withdrawal_amount,
                "last_restock_date": record.last_restock_date.isoformat() if record.last_restock_date else None,
                "shop_status": record.shop_status or "",
                "created_at": record.created_at,
                "updated_at": record.updated_at
            })
        
        # 6. 统计信息
        checked_count = sum(1 for r in record_list if r["visited"])
        
        result_data = {
            "check_date": check_date.isoformat(),
            "total": len(record_list),
            "checked": checked_count,
            "unchecked": len(record_list) - checked_count,
            "records": record_list
        }
        
        return json_response(True, data=result_data)
        
    except Exception as e:
        return json_response(False, message=f"服务器错误: {str(e)}", status_code=500)


@csrf_exempt
@require_http_methods(["POST"])
def update_daily_check(request):
    """
    更新巡店日报记录
    
    请求参数（JSON 格式）:
        - id (int, 必填): 巡店记录 ID
        - visited (bool, 可选): 是否进入店铺
        - performance_checked (bool, 可选): 是否检查绩效
        - withdrawal_processed (bool, 可选): 是否处理提现
        - withdrawal_amount (float, 可选): 提现金额
        - last_restock_date (str, 可选): 最后上货日期，格式 "YYYY-MM-DD"
        - shop_status (str, 可选): 店铺状况
        - is_restricted (bool, 可选): 是否受限
        - restricted_regions (list, 可选): 受限地区列表，如 ["加拿大", "美国", "墨西哥"]
    
    返回示例:
        {
            "success": true,
            "message": "更新成功",
            "data": {
                "id": 1,
                "visited": true,
                "performance_checked": true,
                "withdrawal_processed": false
            }
        }
    """
    try:
        # 1. 解析请求参数
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return json_response(False, message="请求体必须是有效的 JSON 格式", status_code=400)
        
        record_id = body.get("id")
        if not record_id:
            return json_response(False, message="缺少必填参数: id", status_code=400)
        
        try:
            record = AmazonShopDailyCheck.objects.get(id=record_id)
        except AmazonShopDailyCheck.DoesNotExist:
            return json_response(False, message="巡店记录不存在", status_code=404)
        
        # 2. 更新字段
        update_fields = []
        
        if "visited" in body:
            record.visited = bool(body["visited"])
            update_fields.append("visited")
        
        if "performance_checked" in body:
            record.performance_checked = bool(body["performance_checked"])
            update_fields.append("performance_checked")
        
        if "withdrawal_processed" in body:
            record.withdrawal_processed = bool(body["withdrawal_processed"])
            update_fields.append("withdrawal_processed")
        
        if "withdrawal_amount" in body:
            amount = body["withdrawal_amount"]
            if amount is None:
                record.withdrawal_amount = None
            else:
                try:
                    record.withdrawal_amount = Decimal(str(amount))
                except Exception:
                    return json_response(False, message="withdrawal_amount 格式错误", status_code=400)
            update_fields.append("withdrawal_amount")
        
        if "last_restock_date" in body:
            date_str = body["last_restock_date"]
            if date_str:
                try:
                    record.last_restock_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    return json_response(False, message="last_restock_date 格式错误，请使用 YYYY-MM-DD", status_code=400)
            else:
                record.last_restock_date = None
            update_fields.append("last_restock_date")
        
        if "shop_status" in body:
            record.shop_status = body["shop_status"] or ""
            update_fields.append("shop_status")
        
        if "is_restricted" in body:
            record.is_restricted = bool(body["is_restricted"])
            update_fields.append("is_restricted")
        
        if "restricted_regions" in body:
            regions = body["restricted_regions"]
            if regions is None:
                record.restricted_regions = None
            elif isinstance(regions, list):
                record.restricted_regions = regions
            else:
                return json_response(False, message="restricted_regions 必须是列表格式", status_code=400)
            update_fields.append("restricted_regions")
        
        # 3. 保存更新
        if update_fields:
            record.save(update_fields=update_fields)
        
        # 4. 返回结果
        result_data = {
            "id": record.id,
            "shop_id": record.shop_id,
            "check_date": record.check_date.isoformat(),
            "visited": record.visited,
            "performance_checked": record.performance_checked,
            "withdrawal_processed": record.withdrawal_processed,
            "withdrawal_amount": record.withdrawal_amount,
            "last_restock_date": record.last_restock_date.isoformat() if record.last_restock_date else None,
            "shop_status": record.shop_status or "",
            "is_restricted": record.is_restricted,
            "restricted_regions": record.restricted_regions
        }
        
        return json_response(True, data=result_data, message="更新成功")
        
    except Exception as e:
        return json_response(False, message=f"服务器错误: {str(e)}", status_code=500)



@csrf_exempt
@require_http_methods(["POST"])
def save_upload_record(request):
    """
    保存亚马逊店铺上货记录（新建或更新）
    
    请求参数（JSON 格式）:
        - batch_id (str, 必填): 批次编号，如 "UP20250316001"
        - file_name (str, 必填): 文件名，如 "products.xlsx"
        - status (str, 必填): 中文状态，如 "需操作"、"完成" 等
        - upload_time (str, 必填): 中文时间，如 "2026年2月28日 上午10:56"
        - shop_id (int, 必填): 店铺ID
        - sku_success (int, 可选): SKU成功数量
        - submitted (int, 可选): 已提交数量
    
    返回示例:
        {
            "success": true,
            "message": "保存成功",
            "data": {
                "batch_id": "UP20250316001",
                "operation": "created"  // 或 "updated"
            }
        }
    """
    
    # 状态映射：中文 → 英文
    STATUS_MAP = {
        '进行中': 'processing',
        '完成': 'completed',
        '需操作': 'needs_action',
        '已保存为草稿': 'draft',
        '已发布': 'published',
        '失败': 'failed',
    }
    
    try:
        # 1. 解析请求参数
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return json_response(False, message="请求体必须是有效的 JSON 格式", status_code=400)
        
        batch_id = body.get("batch_id", "").strip()
        file_name = body.get("file_name", "").strip()
        status_cn = body.get("status", "").strip()
        upload_time_str = body.get("upload_time", "").strip()
        shop_id = body.get("shop_id")
        sku_success = body.get("sku_success")
        submitted = body.get("submitted")
        
        # 2. 校验必填参数
        missing_fields = []
        if not batch_id:
            missing_fields.append("batch_id")
        if not file_name:
            missing_fields.append("file_name")
        if not status_cn:
            missing_fields.append("status")
        if not upload_time_str:
            missing_fields.append("upload_time")
        if shop_id is None:
            missing_fields.append("shop_id")
        
        if missing_fields:
            return json_response(False, message=f"缺少必填参数: {', '.join(missing_fields)}", status_code=400)
        
        # 3. 转换状态（中文 → 英文）
        if status_cn not in STATUS_MAP:
            valid_status = '、'.join(STATUS_MAP.keys())
            return json_response(False, message=f"无效的状态值 '{status_cn}'，可选: {valid_status}", status_code=400)
        status_en = STATUS_MAP[status_cn]
        
        # 4. 解析上传时间（中文格式 → datetime）
        # 格式示例: "2026年2月28日 上午10:56" 或 "2026年2月18日 下午5:51"
        import re
        time_pattern = r'(\d{4})年(\d{1,2})月(\d{1,2})日\s+(上午|下午)(\d{1,2}):(\d{2})'
        match = re.match(time_pattern, upload_time_str)
        
        if not match:
            return json_response(
                False, 
                message="时间格式错误，正确格式如: '2026年2月28日 上午10:56' 或 '2026年2月18日 下午5:51'", 
                status_code=400
            )
        
        year, month, day, period, hour, minute = match.groups()
        year, month, day = int(year), int(month), int(day)
        hour, minute = int(hour), int(minute)
        
        # 下午时间 +12
        if period == '下午' and hour != 12:
            hour += 12
        # 上午12点应该是0点（凌晨）
        elif period == '上午' and hour == 12:
            hour = 0
        
        try:
            upload_time = datetime(year, month, day, hour, minute)
        except ValueError as e:
            return json_response(False, message=f"无效的日期时间: {e}", status_code=400)
        
        # 5. 检查店铺是否存在
        try:
            shop = AmazonShop.objects.get(id=shop_id)
        except AmazonShop.DoesNotExist:
            return json_response(False, message=f"店铺不存在: shop_id={shop_id}", status_code=404)
        
        # 6. 保存记录（UPSERT：存在则更新，不存在则创建）
        from amazon.models import AmazonShopUploadRecord
        
        # 构建 defaults 字典
        defaults = {
            'file_name': file_name,
            'status': status_en,
            'upload_time': upload_time,
            'shop': shop
        }
        
        # 添加可选字段（如果有值）
        if sku_success is not None:
            try:
                defaults['sku_success'] = int(sku_success)
            except (ValueError, TypeError):
                return json_response(False, message="sku_success 必须是整数", status_code=400)
        
        if submitted is not None:
            try:
                defaults['submitted'] = int(submitted)
            except (ValueError, TypeError):
                return json_response(False, message="submitted 必须是整数", status_code=400)
        
        record, created = AmazonShopUploadRecord.objects.update_or_create(
            batch_id=batch_id,
            defaults=defaults
        )
        
        # 7. 返回结果
        operation = 'created' if created else 'updated'
        return json_response(
            True,
            data={
                'batch_id': batch_id,
                'operation': operation
            },
            message=f"保存成功，{'新建' if created else '更新'}记录"
        )
        
    except Exception as e:
        return json_response(False, message=f"服务器错误: {str(e)}", status_code=500)
