
from Api.lingxing.openapi import OpenApiBase
from Api.lingxing.resp_schema import ResponseResult

async def get_api_resp(req_body:dict, api_path:str, method:str="POST") -> ResponseResult:
    op_api = OpenApiBase(
        host="https://openapi.lingxing.com",  # 替换为你的 API 网关地址
        app_id="ak_P211HcxRxAZ8x",  # 替换为你的 appId
        app_secret="KZ3Eu6Q9qpVCLPEv1tx/aQ=="  # 替换为你的 appSecret
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
