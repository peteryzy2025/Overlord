
from api.lingxing.openapi import OpenApiBase
from api.lingxing.resp_schema import ResponseResult

# 默认配置（向后兼容）
DEFAULT_LINGXING_APP_ID = "ak_P211HcxRxAZ8x"
DEFAULT_LINGXING_APP_SECRET = "KZ3Eu6Q9qpVCLPEv1tx/aQ=="


async def get_api_resp(
    req_body: dict,
    api_path: str,
    method: str = "POST",
    app_id: str = None,
    app_secret: str = None
) -> ResponseResult:
    """
    领星API通用请求函数
    
    Args:
        req_body: 请求体
        api_path: API路径
        method: 请求方法
        app_id: 领星AppID（可选，默认使用全局配置）
        app_secret: 领星AppSecret（可选，默认使用全局配置）
    """
    # 使用传入的配置或默认配置
    use_app_id = app_id or DEFAULT_LINGXING_APP_ID
    use_app_secret = app_secret or DEFAULT_LINGXING_APP_SECRET
    
    if not use_app_id or not use_app_secret:
        raise ValueError("领星AppID或AppSecret未配置")
    
    op_api = OpenApiBase(
        host="https://openapi.lingxing.com",
        app_id=use_app_id,
        app_secret=use_app_secret
    )

    token_resp = await op_api.generate_access_token()
    access_token = token_resp.access_token
    resp = await op_api.request(
        access_token=access_token,
        route_name=api_path,
        method=method,
        req_body=req_body
    )
    return resp
