#!/usr/bin/python3
import pytest
from openapi import OpenApiBase


@pytest.mark.asyncio
async def test_generate_access_token():
    op_api = OpenApiBase("fake_host", "fake_app_id", "fake_app_secret")     # 请在此处填写真实数据
    resp = await op_api.generate_access_token()
    print(resp.dict())
    assert resp.access_token


@pytest.mark.asyncio
async def test_refresh_token():
    op_api = OpenApiBase("fake_host", "fake_app_id", "fake_app_secret")     # 请在此处填写真实数据
    refresh_token = "fake_refresh_token"
    resp = await op_api.refresh_token(refresh_token)
    print(resp.dict())
    assert resp.access_token


@pytest.mark.asyncio
async def test_seller_lists():
    op_api = OpenApiBase("fake_host", "fake_app_id", "fake_app_secret")     # 请在此处填写真实数据
    access_token = "fake_access_token"      # 请在此处填写真实数据
    resp = await op_api.request(access_token, "/erp/sc/data/seller/lists", "GET")
    print(resp.dict())
    assert resp.code == 0


@pytest.mark.asyncio
async def test_category_set():
    op_api = OpenApiBase("fake_host", "fake_app_id", "fake_app_secret")  # 请在此处填写真实数据
    access_token = "fake_access_token"  # 请在此处填写真实数据
    req_body = {
            "data": {
                "title": "华为2",
                "parent_cid": ""
            }
        }
    resp = await op_api.request(access_token, "/erp/sc/routing/storage/category/set", "POST",
                                req_body=req_body)
    print(resp.dict())
    assert resp.code == 0


@pytest.mark.asyncio
async def test_add_providers():
    op_api = OpenApiBase("fake_host", "fake_app_id", "fake_app_secret")  # 请在此处填写真实数据
    access_token = "fake_access_token"  # 请在此处填写真实数据
    req_body = {
            "providersData": [
                {"logistics_provider_name": "test1009"}
            ]
        }
    resp = await op_api.request(access_token, "/erp/sc/routing/tms/FirstVessel/addProviders", "POST",
                                req_body=req_body)
    print(resp.dict())
    assert resp.code == 0
