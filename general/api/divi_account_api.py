import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from general.models import OperationalAccount


@csrf_exempt
@require_POST
def divi_account_query_api(request):
    """
    外部接口：查询迪唯账号信息
    入参：{"query": "xxx"} （可以是 divi_username 或 diwei_account）
    返回：divi_username, diwei_account, diwei_password
    """
    try:
        data = json.loads(request.body)
        query = data.get('query', '').strip()

        if not query:
            return JsonResponse({
                'success': False,
                'error': '查询参数不能为空'
            }, status=400)

        # 优先匹配 divi_username，再匹配 diwei_account
        account = OperationalAccount.objects.filter(
            divi_username=query
        ).first()

        if not account:
            account = OperationalAccount.objects.filter(
                diwei_account=query
            ).first()

        if not account:
            return JsonResponse({
                'success': False,
                'error': '未找到匹配的迪唯账号信息'
            }, status=404)

        return JsonResponse({
            'success': True,
            'data': {
                'divi_username': account.divi_username or '',
                'diwei_account': account.diwei_account or '',
                'diwei_password': account.diwei_password or ''
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': '请求体格式错误，需要 JSON 格式'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f'服务器错误: {str(e)}'
        }, status=500)
