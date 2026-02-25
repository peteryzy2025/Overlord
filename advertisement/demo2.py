import asyncio
from asgiref.sync import sync_to_async
from api.lingxing.Y_OpenApi import get_api_resp


async def demo():
    #获取 活动id 无需去重
    req_body = {
        "sid": "508575", #吴晓云-04李尧尧-US
        "report_date": "2026-02-24"
    }
    resp = await get_api_resp(req_body, api_path="/pb/openapi/newad/spCampaignReports", app_id="", app_secret="")
    for data in resp.data:
        print(data)
        print(data.get("campaign_id")) #167060198167068


async def demo4():
    #SP投放小时数据
    req_body= {
        "campaign_id": "167060198167068",
        "report_date": "2026-02-24",
        "agg_dimension": "both_ad_target"
    }
    resp = await get_api_resp(req_body, api_path="/pb/openapi/newad/spTargetHourData", app_id="", app_secret="")
    # print(resp)
    for data in resp.data:
        print(data)
        print("---" * 30)



async def demo5():
    #获取 活动id,完整的，
    req_body = {
        "sid": "508575", #吴晓云-04李尧尧-US
        "length":200,

    }
    resp = await get_api_resp(req_body, api_path="/pb/openapi/newad/spCampaigns", app_id="", app_secret="")
    for data in resp.data:
        print(data)
        print(data.get("campaign_id")) #167060198167068
        print("---" * 30)
    print(resp.total)

if __name__ == '__main__':
    # asyncio.run(demo())
    # print("===="*30)
    asyncio.run(demo4())
    # print("====" * 30)
    # asyncio.run(demo5())

