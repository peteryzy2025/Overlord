from api.lingxing.Y_OpenApi import get_api_resp


async def demo1():
    req_body = {
        "global_order_no": "103675375488062980",
    }
    resp = await get_api_resp(
        req_body=req_body,
        api_path="/basicOpen/openapi/multiplatform/order/review",
        method="POST"
    )
    print(f"接口返回: {resp}")


