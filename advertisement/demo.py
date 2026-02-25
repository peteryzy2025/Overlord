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
        print(data.get("campaign_id"))


async def demo2():
    #获取 活动id，记得去重哦
    req_body = {
        "campaign_id": "167060198167068", #吴晓云-04李尧尧-US
        "report_date": "2026-02-24"
    }
    resp = await get_api_resp(req_body, api_path="/pb/openapi/newad/spCampaignHourData", app_id="", app_secret="")
    print(">>"*20)
    for data in resp.data:
        hour = data.get("hour")
        cost = data.get("cost")
        cpc = data.get("cpc")
        print(f"{hour}点: 花费 {cost} 美元，平均点击成本 {cpc} 美元")
        print("---"*30)

async def demo3():
    #获取 活动id+asin
    req_body = {
        "sid": "508575", #吴晓云-04李尧尧-US
        "report_date": "2026-02-24"
    }
    resp = await get_api_resp(req_body, api_path="/pb/openapi/newad/spProductAds", app_id="", app_secret="")
    print(">>"*20)
    for data in resp.data:
        campaign_id = data.get("campaign_id")
        ad_group_id = data.get("ad_group_id")
        ad_id = data.get("ad_id")
        sku = data.get("sku")
        asin = data.get("asin")
        print(f"活动id: {campaign_id}, 广告组id: {ad_group_id}, 广告id: {ad_id}, sku: {sku}, asin: {asin}")

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


if __name__ == '__main__':
    # asyncio.run(demo())
    print("===="*30)
    asyncio.run(demo4())

