# ykartwood_spider.py
import requests
import json
import time
import re


def fetch_product(product_id: int):
    """
    拉取 ykartwood 商品 JSON
    :param product_id: 商品数字 ID
    :return: dict / None
    """
    url = f"https://mapi.sdspod.com/products/{product_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "Referer": "http://www.ykartwood.com/",
        "Origin": "http://www.ykartwood.com",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[ERROR] 获取 {product_id} 失败: {e}")
        return None


def get_product_unit(title: str) -> str:
    """
    根据产品标题返回对应的计量单位

    :param title: 产品标题字符串
    :return: 计量单位（个/件/条/张/组/套/双/本/支/盒等）
    """
    title_lower = title.lower()

    # 关键词到单位的映射
    unit_mapping = {
        # 服装类 -> 件
        ('t恤', 'tshirt', 'shirt', '衬衫', '外套', '卫衣', '夹克', '毛衣', '针织衫', '连衣裙', '裙子', '裤子', '牛仔裤',
         '短裤', '长裤', '内裤', '内衣', '文胸', '睡衣', '泳衣', '运动服'): '件',
        # 袜子类 -> 双
        ('袜子', '袜', '长袜', '短袜', '中筒袜', '船袜', '丝袜'): '双',
        # 帽子类 -> 顶
        ('帽子', '帽', '棒球帽', '鸭舌帽', '遮阳帽', '贝雷帽', '渔夫帽'): '顶',
        # 围巾/腰带类 -> 条
        ('围巾', '丝巾', '腰带', '皮带', '领带'): '条',
        # 手套类 -> 双
        ('手套', '手套'): '双',
        # 鞋类 -> 双
        ('鞋子', '鞋', '运动鞋', '皮鞋', '凉鞋', '拖鞋', '靴子'): '双',
        # 包包类 -> 个
        ('包', '包包', '背包', '双肩包', '手提包', '钱包', '腰包'): '个',
        # 首饰类 -> 件
        ('项链', '手链', '手镯', '戒指', '耳环', '耳钉', '胸针', '发夹'): '件',
        # 家居用品 -> 个
        ('杯子', '杯', '碗', '盘', '碟', '壶', '瓶', '罐', '盆', '桶', '盒', '收纳盒', '抱枕', '靠垫'): '个',
        # 床上用品 -> 套/张
        ('床单', '被套', '枕套', '四件套', '床品'): '套',
        ('被子', '毯子', '毛巾', '浴巾', '窗帘'): '张',
        # 文具类
        ('笔', '铅笔', '钢笔', '圆珠笔', '马克笔'): '支',
        ('本子', '笔记本', '日记本', '便签'): '本',
        # 电子产品 -> 个/台
        ('手机', '耳机', '充电器', '充电宝', '数据线', '键盘', '鼠标', 'u盘'): '个',
        ('电脑', '平板', '笔记本', '显示器'): '台',
        # 印刷品类 -> 张
        ('贴纸', '标签', '卡片', '明信片', '海报', '画'): '张',
        # 组合装 -> 组/套
        ('套装', '组合', '组套', '礼包'): '组',
    }

    # 遍历映射，检查标题是否包含关键词
    for keywords, unit in unit_mapping.items():
        if any(keyword in title_lower for keyword in keywords):
            return unit

    # 默认返回"个"
    return '个'


def build_titles(declaration_name: str, pt: str, supplier: str = "艺之冠") -> tuple[str, str]:
    """
    根据平台返回 (title, sub_title)
    """
    pt = pt.lower()
    if pt == "amazon":
        title = f"{declaration_name} 美国发货（含运费）"
        sub_title = f"{declaration_name} {supplier}美国发货（含运费）"
    elif pt == "temu":
        title = f"{declaration_name} 美国发货（TEMU面单）"
        sub_title = f"{declaration_name} {supplier}美国发货（TEMU面单）"
    else:
        # 默认处理，避免未知平台报错
        title = f"{declaration_name} ({supplier})"
        sub_title = f"{declaration_name} {supplier}"
    return title, sub_title


def get_img_urls(data):
    '''
    从商品数据中提取产品图片URL列表。
    :param data: 商品数据，包含子产品信息。
    :param pid: 商品ID，用于错误日志记录。
    :return: 产品图片URL列表。
    '''
    subproducts = data.get("subproducts", {})
    items = subproducts.get("items", {})
    prototypeResultGroups = items[0].get("designPrototype", {}).get("prototypeResultGroups", [])
    img_urls_list = []
    for group in prototypeResultGroups:
        img_urls_list.append(group.get("resultImage", ""))
    return img_urls_list


def get_color_name(data):
    subproducts = data.get("subproducts", {})
    items = subproducts.get("items", {})
    color_name_list = []
    for item in items:
        color_name_list.append(item.get("color_name", ""))
    # 去重
    return list(set(color_name_list))

def get_size_list(data):
    subproducts = data.get("subproducts", {})
    items = subproducts.get("items", {})
    size_list = []
    for item in items:
        size_list.append(item.get("size_name", ""))
    # 去重并排序 (简单去重，不排序)
    return list(set(size_list))


def test(flat, target):
    idx = next((i for i, d in enumerate(flat) if d.get("content") == target), -1)
    print(idx)  # 找不到就是 -1


def get_ykartwood_product(pid, platform, select_platform):
    """
    获取艺之冠产品信息
    :param pid: 产品ID
    :param platform: 平台名称 amazon temu
    :param select_platform: 选择的平台 外采平台
    :return: 产品信息字典
    """
    data = fetch_product(pid)
    if data:
        declaration_name = data.get("declaration_name", "")  # 报关中文名称    360直喷全印中筒袜（男女同款）【TEMU,TK,SHEIN官方面单】
        declaration_name = re.sub(r"【.*?】", "", declaration_name).rstrip()  # 360直喷全印中筒袜（男女同款）  #?
        title, product_abbr = build_titles(declaration_name, platform, select_platform)  # 产品标题，产品简称
        english_name = data.get("english_name", "")  # 英文标题与报关英文名称
        product_details = data.get("product_details", {})
        material_description = product_details.get("material_description", "")  # 产品材质，
        design_explanation = product_details.get("design_explanation", "")  # 设计说明
        if "印花" in design_explanation:
            craft = "印花"  # 工艺类型
        else:
            craft = design_explanation
        unit = get_product_unit(title)  # 计量单位
        item = data.get("subproducts").get("items", [{}])[0]
        weight = item.get("weight", 0)  # 申报重量
        current_price = item.get("currentPrice", 0)  # 当前售价
        price = round(current_price / 7.3 + 1, 1)  # 海关申报单价

        product_performance = product_details.get("product_performance")  # 产品性能
        applicable_scenarios = product_details.get("applicable_scenarios")  # 适用情景
        washing_instructions = product_details.get("washing_instructions")  # 洗涤说明
        special_description = product_details.get("special_description")  # 特别说明
        reminder = product_details.get("reminder")
        design_explanation = product_details.get("design_explanation")  # 设计说明
        design_area = product_details.get("design_area")  # 设计区域

        color_name = get_color_name(data)
        size_list = get_size_list(data)
        product_details = data.get("product_details", {})
        packaging_specification = json.loads(product_details.get("packaging_specification", ""))  # 包装说明
        product_size = json.loads(product_details.get("product_size", ""))  # 产品尺码
        img_urls_list = get_img_urls(data)
        # -------------------------
        category = ''
        if platform == 'amazon':
            category = '美国本土直发'
        elif platform == 'temu':
            category = '美国TEMU面单'

        ykat_dict = {
            "product_name": title,
            "product_abbr": product_abbr,
            "english_name": english_name,
            "material": material_description,  # 产品材质
            "craft": craft,  # 生产工艺
            "unit": unit,  # 计量单位
            "customs_cn_name": declaration_name,  # 报关中文名称
            "customs_en_name": english_name,  # 报关英文名称
            "declared_weight": weight,  # 申报重量
            "declared_price": price,  # 海关申报单价
            # "customs_code":"", 海关编码,这个不写入，
            "material_cn": material_description,  # 报关产品材质（中文）
            # "material_en": "",# 报关产品材质（英文）这个不写入，
            "material_desc": material_description,  # 材质说明
            "accessory_struct": f"{declaration_name}+{craft}",  # 配件构造
            "product_performance": product_performance,  # 适用情景
            "applicable_scenario": applicable_scenarios,  # 适用情景 (修复字段名: applicable_scenarios -> applicable_scenario)
            "washing_instructions": washing_instructions,  # 洗涤说明
            "special_note": special_description,  # 特别说明
            "reminder": reminder,  # 温馨提醒
            "design_desc": design_explanation,  # 设计说明
            "design_area": design_area,  # 设计区域

            "color_name": color_name,  # 颜色
            "size_list": size_list,    # 尺码
            "img_urls_list": img_urls_list,  # 产品图片链接列表
            "packaging_specification": packaging_specification,  # 包装说明
            "product_size": product_size,  # 产品尺码

            # ----------------
            "category": category,
            "special_cargo_type": "是否USPS",
            "product_label": "北美生产",
            # "trademark_category": "", # 商标类目，爬虫不修改
        }

        print(ykat_dict)
        return ykat_dict

    return None


# print(get_ykartwood_product("216484", "amazon", "艺之冠"))
