from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from django.core.cache import cache
import nltk
import string
from collections import defaultdict
from nltk.tokenize import TweetTokenizer
# from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
from theme.models import *
from general.module_utils import company_module_access_required
from general.models import UserOperationLog

# 中风险状态码集合（美标网）
# 包含：已注册、注册后维护、申请中、审查中、公告期、延期请求、已放弃、已取消等
# 即：除白名单外，只要命中美标网且状态码在此集合中，均视为中风险
MEDIUM_RISK_STATUS_CODES = {
    # ===== 已注册及注册后维护状态（本次新增）=====
    700,  # 已注册
    701,  # 第8条使用声明已接受(5-6年维护)
    702,  # 第8&15条声明已接受并确认
    703,  # 第15条不可争议性声明已确认
    704,  # 部分第8条使用声明已接受
    705,  # 部分第8&15条声明已接受并确认
    706,  # 第71条声明已接受(马德里商标维护)
    707,  # 部分第71条声明已接受
    708,  # 部分第71&15条声明已接受并确认
    739,  # 第71&15条声明已接受并确认(马德里)
    800,  # 已注册并续展(10年续展完成)
    # 注册后异议/上诉中（权利不稳定但已注册）
    801,  # 异议文件已提交(被第三方异议)
    804,  # 上诉已提交至TTAB

    # ===== 申请中/审查中/公告期（原有）=====
    630,  # 新申请-待分配审查员
    631,  # 新申请-分案初步处理中
    632,  # 非正式申请
    638,  # 新申请-已分配审查员
    640,  # 非最终审查意见(OA)-待发
    641,  # 非最终审查意见(OA)-已发出
    642,  # 已归档为驳回
    643,  # 先前审查意见/核准已撤回
    644,  # 最终驳回(Final OA)-待发
    645,  # 最终驳回(Final OA)-已发出
    646,  # 审查员修改建议-待发
    647,  # 审查员修改建议-已发出
    648,  # 延续最终审查-待发
    649,  # 延续最终审查-已发出
    650,  # 暂停审查查询-待发
    651,  # 暂停审查查询-已发出
    652,  # 暂停信函-待发
    653,  # 暂停信函-已发出
    654,  # （保留）
    655,  # 审查员修改/优先处理-待发
    656,  # 审查员修改/优先处理-已发出
    657,  # 优先处理-待发
    658,  # 优先处理-已发出
    659,  # 后续最终驳回-待发
    660,  # 后续最终驳回-已发出
    661,  # 非终审查意见答复已录入
    663,  # 最终驳回答复已录入
    664,  # （保留）
    665,  # 不具答复性的修改通知-待发
    666,  # 不具答复性的修改通知-已发出
    667,  # 驳回撤回信-待发
    668,  # 驳回撤回信-已发出
    672,  # 已恢复-等待进一步处理
    673,  # 复审请求获准-等待进一步处理
    680,  # 已核准公告(准注册)
    681,  # 公告/发证审查完成
    682,  # 需额外审查-返回公告周期
    686,  # 已公告征询异议(公告期)
    688,  # 核准通知书已发出(Notice of Allowance)
    689,  # 核准通知书已撤回
    690,  # 核准通知书已取消
    692,  # 公告前撤回
    693,  # 发证前撤回-管辖权已恢复
    694,  # 发证前撤回

    # ===== 延期请求（原有）=====
    718,  # 首次延期请求已提交(ITU)
    719,  # 第二次延期请求已提交(ITU)
    720,  # 第三次延期请求已提交(ITU)
    721,  # 第四次延期请求已提交(ITU)
    722,  # 第五次延期请求已提交(ITU)
    724,  # 延期请求驳回-待发
    725,  # 延期请求驳回-已发出
    730,  # 首次延期已批准(ITU)
    731,  # 第二次延期已批准(ITU)
    732,  # 第三次延期已批准(ITU)
    733,  # 第四次延期已批准(ITU)
    734,  # 第五次延期已批准(ITU)

    # ===== 使用声明(SOU)审查（原有）=====
    744,  # 使用声明(SOU)已提交
    745,  # 使用声明-非正式-已发函
    746,  # 使用声明-非正式-答复已录入
    748,  # 使用声明-转交审查员
    752,  # 使用声明-审查员意见-待发
    753,  # 使用声明-审查员意见-已发出
    756,  # 审查员意见-待发
    757,  # 审查员意见-已发出
    806,  # 使用声明-非终审意见已计数-待发
    807,  # 使用声明-非终审意见-已邮寄
    808,  # 使用声明-最终驳回已计数-待发
    809,  # 使用声明-最终驳回-已邮寄
    810,  # 使用声明-审查员修改建议已计数-待发
    811,  # 使用声明-审查员修改建议-已邮寄
    812,  # 使用声明-延续最终审查已计数-待发
    813,  # 使用声明-延续最终审查-已邮寄
    814,  # 使用声明-非终审意见答复已录入
    815,  # 使用声明-最终驳回答复已录入
    816,  # 使用声明-不具答复性修改通知-待发
    817,  # 使用声明-不具答复性修改通知-已邮寄
    818,  # 使用声明已接受-已核准注册(SOU通过)
    819,  # 使用声明-注册审查已完成
    820,  # 使用声明-审查员修改/优先处理已计数-待发
    821,  # 使用声明-审查员修改/优先处理-已邮寄
    822,  # 使用声明-优先处理已计数-待发
    823,  # 使用声明-优先处理-已邮寄
    824,  # 使用声明-后续最终驳回已撰写
    825,  # 使用声明-后续最终驳回已邮寄

    # ===== 上诉/异议/并存使用（原有）=====
    760,  # 单方上诉待决
    762,  # 单方上诉已终止
    763,  # 单方上诉-驳回决定维持
    764,  # 单方上诉-因无实际意义被驳回
    765,  # 并存使用程序终止-已批准
    766,  # 并存使用程序终止-已驳回
    771,  # 并存使用程序待决
    772,  # 干扰程序待决
    773,  # 异议期限延长程序已终止
    774,  # 异议待决(被异议中)
    775,  # 异议被驳回
    777,  # 异议已终止-详见TTAB记录
    778,  # 注销申请被驳回
    779,  # 异议成立
    780,  # 注销程序已终止
    790,  # 注销程序待决
    794,  # 管辖权已恢复至审查员

    # ===== 已放弃/已取消/过期（原有）=====
    0,    # 未知状态
    401,  # 国际注册取消-未提交转换申请
    404,  # 国际注册取消-美国注册已取消
    600,  # 已放弃-答复不完整
    601,  # 已放弃-主动放弃
    602,  # 已放弃-未答复或逾期答复
    604,  # 已放弃-双方裁决后
    605,  # 已放弃-公告后主动放弃
    606,  # 已放弃-未提交使用声明(ITU)
    610,  # 制裁后终止
    616,  # 已恢复-等待进一步处理
    618,  # 历史档案-已放弃
    620,  # 历史档案-状态未记录
    622,  # 序列号分配错误
    624,  # 历史档案-已注册
    625,  # 注册已录入-状态不明
    626,  # 历史档案-已取消或过期
    709,  # 已取消-第71条(马德里)
    710,  # 已取消-第8条(未交使用声明)
    711,  # 已取消-第7条(注册修正)
    712,  # 法院命令取消(Section 37)
    713,  # 已取消-第18条(限制注册范围)
    714,  # 已取消-第24条(放弃部分权利)
    715,  # 已取消-恢复为待决状态
    717,  # 已注册-等待分案费用
    900,  # 已过期(错过10年续展)
    901,  # 已归档为驳回的失效申请
    968,  # 非注册数据已撤回
    969,  # 非注册数据
}
HIGH_RISK_NAME_TYPES = {4, 5, 6, 7, 10, 11}
LOW_RISK_NAME_TYPES = {1, 9}
SPECIAL_INTL_CLASSES = {'006', '015', '016', '018', '024', '025', '027', '035'}


@company_module_access_required('infringement', '侵权板块')
def trend_page(request):
    nice_classifications = list(
        NiceClassification.objects.all().order_by('code').values('code', 'name')
    )
    return render(request, 'trend_v2.html', {
        'active_nav': 'theme_products',
        'nice_classifications': nice_classifications,
        'special_intl_classes': sorted(SPECIAL_INTL_CLASSES),
        'medium_risk_status_codes': sorted(MEDIUM_RISK_STATUS_CODES),
    })


@require_POST
@csrf_exempt
def trend_search(request):
    query = request.POST.get('trendQueryInput', '').strip()
    mode = int(request.POST.get('searchMode', 1))
    if not query:
        return JsonResponse({'error': '请输入搜索关键词'}, status=400)

    data = analyze_theme_trend(query, mode=mode)

    # 记录查询日志
    try:
        mode_text = '切词' if mode == 1 else '组词'
        risk_text = data.get('theme_risk_text', '未知')
        hit_uspto = len(data.get('uspto_keywords', []))
        hit_tro = len(data.get('tro_keywords', []))
        record = f"查询词: {query} | 模式: {mode_text} | 风险: {risk_text} | 美标命中: {hit_uspto} | 侵权词库命中: {hit_tro}"
        # 截断到250字符
        if len(record) > 250:
            record = record[:247] + "..."

        UserOperationLog.objects.create(
            user=request.user,
            operation_type=UserOperationLog.OperationType.TRO_SEARCH,
            operation_record=record,
        )
    except Exception as log_error:
        print(f"❌ 侵权词查询日志记录失败: {log_error}")

    return JsonResponse(data, json_dumps_params={'ensure_ascii': False})


def batch_analyze_theme_trend(themes):
    """
    批量分析主题词的侵权风险趋势。
    Args:
        themes (list): 主题词列表
    Returns:
        dict: {theme: analysis_result}
    """
    results = {}
    unique_tokens = set()
    theme_tokens_map = {}

    # 1. 预处理所有主题，收集 tokens
    for theme in themes:
        if not theme:
            continue
        # 尝试从缓存获取 (注意：逻辑变更，升级缓存key)
        cache_key = f'risk_analysis_v3:{hash(theme)}'
        cached_result = cache.get(cache_key)
        if cached_result:
            results[theme] = cached_result
            continue

        # 使用 get_ngram_phrases 进行分词，弃用 words_split
        tokens = get_ngram_phrases(theme.strip())
        valid_tokens = [t for t in tokens if not should_skip_word(t)]
        # valid_tokens = [word for word in valid_tokens if word.lower() not in ENGLISH_STOP_WORDS]

        if not valid_tokens:
            # 空结果直接缓存
            empty_result = {
                'query': theme, 'tokens': tokens,
                'uspto_keywords': [], 'uspto_details': {},
                'tro_keywords': [], 'tro_details': {},
                'word_risk_map': {},
                'high_risk_words': [], 'medium_risk_words': [], 'low_risk_words': [],
                'theme_risk_level': 'low', 'theme_risk_text': '低风险',
            }
            cache.set(cache_key, empty_result, 3600)  # 缓存1小时
            results[theme] = empty_result
            continue

        theme_tokens_map[theme] = valid_tokens
        for token in valid_tokens:
            unique_tokens.add(token)

    if not unique_tokens:
        return results

    # 2. 批量查询数据库
    # TRO查询（包含所有类型，用于识别低风险白名单）
    q_tro = Q()
    for token in unique_tokens:
        q_tro |= Q(theme_name__iexact=token)

    tro_records_all = TroTable.objects.filter(q_tro).values('theme_name', 'name_type')

    # 分离低风险白名单词和其他TRO词
    low_risk_whitelist = set()  # name_type in {1,9} 的词（白名单，不查美标网）
    tro_risk_map_global = {}  # 其他需要风险判断的词

    for r in tro_records_all:
        word_lower = r['theme_name'].lower()
        name_type = r['name_type']
        if name_type in LOW_RISK_NAME_TYPES:
            low_risk_whitelist.add(word_lower)  # 白名单词
        else:
            tro_risk_map_global[word_lower] = name_type

    token_uppers = list({t.upper() for t in unique_tokens if t.lower() not in low_risk_whitelist})

    trademark_records = TrademarkInfo.objects.filter(
        word_mark__in=token_uppers
    ).values('word_mark', 'serial_number', 'intl_class', 'status_code', 'mark_drawing_type__description_cn')

    uspto_details_global = defaultdict(list)
    word_status_codes_global = defaultdict(set)
    word_intl_classes_global = defaultdict(set)
    uspto_word_lower_map_global = {}

    for record in trademark_records:
        word = record['word_mark']
        word_lower = word.lower()

        uspto_details_global[word].append({
            'serial_number': record['serial_number'],
            'intl_class': record['intl_class'] or 'N/A',
            'status_code': record['status_code'],
            'mark_drawing_type_cn': record['mark_drawing_type__description_cn'] or 'N/A'
        })

        if record['status_code']:
            try:
                word_status_codes_global[word].add(int(record['status_code']))
            except (ValueError, TypeError):
                pass

        if record['intl_class']:
            word_intl_classes_global[word].add(record['intl_class'])

        uspto_word_lower_map_global[word_lower] = word

    # 3. 为每个未缓存的主题生成结果
    for theme, valid_tokens in theme_tokens_map.items():
        uspto_matches = []
        uspto_details = {}
        tro_matches = []
        tro_details = {}

        high_risk_words = []
        medium_risk_words = []
        low_risk_words = []
        word_risk_map = {}

        for token in valid_tokens:
            token_lower = token.lower()
            token_upper = token.upper()

            # ===== 优先检查白名单（name_type=1,9）=====
            if token_lower in low_risk_whitelist:
                # 白名单词：直接标记为低风险，不查美标网
                word_risk_map[token] = ['low', '', [], False]
                low_risk_words.append(token)
                continue

            # 收集匹配信息用于前端显示（仅非白名单词）
            if token_lower in uspto_word_lower_map_global:
                original_word = uspto_word_lower_map_global[token_lower]
                if original_word not in uspto_details:
                    uspto_matches.append(original_word)
                    uspto_details[original_word] = uspto_details_global[original_word]

            if token_lower in tro_risk_map_global:
                # 查找原始大小写形式（从valid_tokens或数据库中恢复）
                # 这里简化处理，直接用token
                tro_matches.append(token)
                tro_details[token] = tro_risk_map_global[token_lower]

            # 风险判断逻辑
            # 高风险 (TRO)
            if token_lower in tro_risk_map_global:
                name_type = tro_risk_map_global[token_lower]
                original_word = uspto_word_lower_map_global.get(token_lower, token_upper)
                status_codes = word_status_codes_global.get(original_word, set())

                if name_type in HIGH_RISK_NAME_TYPES:
                    intl_classes = list(word_intl_classes_global.get(original_word, set()))
                    has_special_class = any(cls in SPECIAL_INTL_CLASSES for cls in intl_classes)
                    word_risk_map[original_word] = ['high', list(status_codes), intl_classes, has_special_class]
                    high_risk_words.append(original_word)
                    continue

            # 中风险 (美标) - 仅对非白名单词进行判断
            if token_lower in uspto_word_lower_map_global and token_lower not in low_risk_whitelist:
                original_word = uspto_word_lower_map_global[token_lower]
                status_codes = word_status_codes_global.get(original_word, set())
                intl_classes = list(word_intl_classes_global.get(original_word, set()))
                has_special_class = any(cls in SPECIAL_INTL_CLASSES for cls in intl_classes)

                if status_codes.intersection(MEDIUM_RISK_STATUS_CODES):
                    word_risk_map[original_word] = ['medium', list(status_codes), intl_classes, has_special_class]
                    medium_risk_words.append(original_word)
                else:
                    word_risk_map[original_word] = ['low', list(status_codes), intl_classes, has_special_class]
                    low_risk_words.append(original_word)
            else:
                # 低风险
                word_risk_map[token] = ['low', '', [], False]
                low_risk_words.append(token)

        # 4.5 兜底过滤：确保白名单词不出现在美标网结果中
        uspto_matches = [w for w in uspto_matches if w.lower() not in low_risk_whitelist]
        keys_to_remove = [k for k in uspto_details if k.lower() in low_risk_whitelist]
        for k in keys_to_remove:
            del uspto_details[k]

        # 整体风险等级
        if high_risk_words:
            theme_risk_level, theme_risk_text = 'high', '高风险'
        elif medium_risk_words:
            theme_risk_level, theme_risk_text = 'medium', '中风险'
        else:
            theme_risk_level, theme_risk_text = 'low', '低风险'

        result = {
            'query': theme, 'tokens': words_split(theme),  # 返回原始tokens
            'uspto_keywords': uspto_matches, 'uspto_details': uspto_details,
            'tro_keywords': tro_matches, 'tro_details': tro_details,
            'word_risk_map': word_risk_map,
            'high_risk_words': high_risk_words,
            'medium_risk_words': medium_risk_words,
            'low_risk_words': low_risk_words,
            'theme_risk_level': theme_risk_level,
            'theme_risk_text': theme_risk_text,
        }

        # 存入缓存
        cache_key = f'risk_analysis_v3:{hash(theme)}'
        cache.set(cache_key, result, 3600)
        results[theme] = result

    return results


# ================2026.2.2更新 算法列出所有情况的分词方法============================
def get_ngram_phrases(text, min_words=1, max_words=None):
    """
    将文本拆分为所有连续N-gram词组列表

    :param text: 输入句子，如 "Heated Shane Hollander 24 Montreal Metros"
    :param min_words: 最小词数（默认1）
    :param max_words: 最大词数（默认None，即整句长度）
    :return: 词组列表，按词数从小到大，同词数按出现顺序
    """
    import re

    # 清理文本：转大写，保留字母数字，多空格变单空格
    text = text.upper().strip()
    text = re.sub(r'[^A-Z0-9\s]', ' ', text)
    words = [w for w in text.split() if w]

    if not words:
        return []

    phrases = []
    max_n = max_words or len(words)

    # 从 min_words 遍历到 max_words
    for n in range(min_words, min(max_n, len(words)) + 1):
        # 滑动窗口提取n个连续词
        for i in range(len(words) - n + 1):
            phrase = ' '.join(words[i:i + n])
            phrases.append(phrase)

    return phrases


# ==================================================End=========================


def analyze_theme_trend(theme, mode=1):
    """
    分析主题词的侵权风险趋势。

    Args:
        theme (str): 需要分析的主题词或短语。
        mode (int): 分词模式。
            1 - words_split + 整体查询（将完整theme作为一个token，默认）
            2 - 全组合查询（get_ngram_phrases生成所有连续N-gram词组）
            # 3 - 语义查询（已废弃，使用spacy语义分词，原功能已注释）

    Returns:
        dict: 包含分析结果的字典，主要字段包括：
            - theme_risk_level (str): 风险等级 ('high', 'medium', 'low')
            - theme_risk_text (str): 风险描述 ('高风险', '中风险', '低风险')
            - word_risk_map (dict): 每个分词的详细风险数据
            - high_risk_words (list): 高风险词列表
            - medium_risk_words (list): 中风险词列表
            - low_risk_words (list): 低风险词列表
            - uspto_keywords (list): 命中的美标关键词
            - tro_keywords (list): 命中的TRO关键词
    """
    query = theme.strip()
    # ===========26.1.31 update 引入过滤停用词======================

    # 1. 分词处理（根据 mode 选择分词方法）
    # if mode == 3:
    #     # ==========================================
    #     # 新增：Mode 3 - 使用 en_core_web_trf 进行语义分词
    #     # ==========================================
    #     import spacy
    #     # 建议在项目启动时加载模型，或使用单例模式，避免每次请求重复加载（耗时数秒）
    #     # 这里假设你已经安装并加载了模型 nlp_trf = spacy.load("en_core_web_trf")
    #     try:
    #         # 仅在需要时导入，防止影响其他模式速度
    #         from theme.apps import ThemeConfig
    #         # 1. 直接引用已经在 apps.py 中加载好的类变量
    #         nlp = ThemeConfig.nlp_trf
    #
    #         if nlp:
    #             # 2. 执行 Transformer 语义识别
    #             doc = nlp(query)
    #
    #             # 3. 提取实体 (ENT) 和 名词短语 (CHUNK)
    #             # 例如 "Pink Floyd T-shirt" 会被识别为 "Pink Floyd" 和 "T-shirt"
    #             semantic_tokens = [ent.text for ent in doc.ents]
    #             for chunk in doc.noun_chunks:
    #                 if chunk.text not in semantic_tokens:
    #                     semantic_tokens.append(chunk.text)
    #
    #             # 如果 TRF 没有识别出任何结果（比如输入的词太偏），则降级使用普通分词
    #             tokens = semantic_tokens if semantic_tokens else words_split(query)
    #         else:
    #             # 兜底：如果模型加载失败，使用普通分词
    #             tokens = words_split(query)
    #     except Exception as e:
    #         # 容错处理：模型未加载或报错时降级
    #         tokens = words_split(query)
    if mode == 2:
        # 使用 get_ngram_phrases 方法
        tokens = get_ngram_phrases(query)
    else:  # 默认模式：words_split + 整体查询
        # words_split + 整体查询
        tokens = words_split(query)
        # 将完整query作为一个整体token加入（大写形式用于查询）
        full_theme_token = query.upper()
        if full_theme_token not in tokens:
            tokens.append(full_theme_token)

    valid_tokens = [t for t in tokens if not should_skip_word(t)]
    # valid_tokens = [word for word in valid_tokens if word.lower() not in ENGLISH_STOP_WORDS]

    if not valid_tokens:
        return {
            'query': query, 'tokens': tokens,
            'uspto_keywords': [], 'uspto_details': {},
            'tro_keywords': [], 'tro_details': {},
            'word_risk_map': {},
            'high_risk_words': [], 'medium_risk_words': [], 'low_risk_words': [],
            'theme_risk_level': 'low', 'theme_risk_text': '低风险',
        }

    # ==========================================
    # TroTable 查询（包含所有类型，用于识别白名单）
    # ==========================================
    q_tro = Q()
    tro_matches = []
    tro_details = {}
    for token in valid_tokens:
        q_tro |= Q(theme_name__iexact=token)

    tro_records_all = TroTable.objects.filter(q_tro).values('theme_name', 'name_type')

    # 分离低风险白名单词和其他TRO词
    low_risk_whitelist = set()  # name_type in {1,9} 的词（白名单，不查美标网）
    tro_risk_map = {}  # 其他需要风险判断的词

    for record in tro_records_all:
        word_lower = record['theme_name'].lower()
        name_type = record['name_type']
        if name_type in LOW_RISK_NAME_TYPES:
            low_risk_whitelist.add(word_lower)  # 白名单词
        else:
            tro_risk_map[word_lower] = name_type
            tro_matches.append(record['theme_name'])
            tro_details[record['theme_name']] = name_type

    # ==========================================
    # 核心优化：美标网全大写，直接转大写用 __in 走索引！
    # ==========================================
    token_uppers = [t.upper() for t in valid_tokens if t.lower() not in low_risk_whitelist]

    trademark_records = TrademarkInfo.objects.filter(
        word_mark__in=token_uppers
    ).values('word_mark', 'serial_number', 'intl_class', 'status_code', 'mark_drawing_type__description_cn')

    uspto_matches = []
    uspto_details = {}
    word_status_codes = defaultdict(set)
    word_intl_classes = defaultdict(set)
    uspto_word_lower_map = {}

    for record in trademark_records:
        word = record['word_mark']
        word_lower = word.lower()

        if word not in uspto_details:
            uspto_matches.append(word)
            uspto_details[word] = []
        uspto_details[word].append({
            'serial_number': record['serial_number'],
            'intl_class': record['intl_class'] or 'N/A',
            'status_code': record['status_code'],
            'mark_drawing_type_cn': record['mark_drawing_type__description_cn'] or 'N/A'
        })
        if record['status_code']:
            try:
                word_status_codes[word].add(int(record['status_code']))
            except (ValueError, TypeError):
                pass

        if record['intl_class']:
            word_intl_classes[word].add(record['intl_class'])

        uspto_word_lower_map[word_lower] = word

    # 4. 风险判断（纯内存操作）
    high_risk_words, medium_risk_words, low_risk_words = [], [], []
    word_risk_map = {}

    for token in valid_tokens:
        token_lower = token.lower()
        token_upper = token.upper()

        # ===== 优先检查白名单（name_type=1,9）=====
        if token_lower in low_risk_whitelist:
            # 白名单词：直接标记为低风险，不查美标网
            word_risk_map[token] = ['low', '', [], False]
            low_risk_words.append(token)
            continue

        # 高风险判断（TroTable）
        if token_lower in tro_risk_map:
            name_type = tro_risk_map[token_lower]
            # 获取美标网原始大写形式，如果没有就用原词
            original_word = uspto_word_lower_map.get(token_lower, token_upper)
            # 获取状态码
            status_codes = word_status_codes.get(original_word, set())

            if name_type in HIGH_RISK_NAME_TYPES:
                intl_classes = list(word_intl_classes.get(original_word, set()))
                has_special_class = any(cls in SPECIAL_INTL_CLASSES for cls in intl_classes)
                word_risk_map[original_word] = ['high', list(status_codes), intl_classes, has_special_class]
                high_risk_words.append(original_word)
                continue

        # 中风险判断（美标网状态码）- 仅对非白名单词进行判断
        if token_lower in uspto_word_lower_map and token_lower not in low_risk_whitelist:
            original_word = uspto_word_lower_map[token_lower]
            status_codes = word_status_codes.get(original_word, set())
            intl_classes = list(word_intl_classes.get(original_word, set()))
            has_special_class = any(cls in SPECIAL_INTL_CLASSES for cls in intl_classes)

            if status_codes.intersection(MEDIUM_RISK_STATUS_CODES):
                word_risk_map[original_word] = ['medium', list(status_codes), intl_classes, has_special_class]
                medium_risk_words.append(original_word)
            else:
                word_risk_map[original_word] = ['low', list(status_codes), intl_classes, has_special_class]
                low_risk_words.append(original_word)
        else:
            # 不在美标网中，低风险
            word_risk_map[token] = ['low', '', [], False]
            low_risk_words.append(token)

    # 4.5 兜底过滤：确保白名单词不出现在美标网结果中
    uspto_matches = [w for w in uspto_matches if w.lower() not in low_risk_whitelist]
    keys_to_remove = [k for k in uspto_details if k.lower() in low_risk_whitelist]
    for k in keys_to_remove:
        del uspto_details[k]

    # 5. 整体风险等级
    if high_risk_words:
        theme_risk_level, theme_risk_text = 'high', '高风险'
    elif medium_risk_words:
        theme_risk_level, theme_risk_text = 'medium', '中风险'
    else:
        theme_risk_level, theme_risk_text = 'low', '低风险'

    return {
        'query': query, 'tokens': tokens,
        'uspto_keywords': uspto_matches, 'uspto_details': uspto_details,
        'tro_keywords': tro_matches, 'tro_details': tro_details,
        'word_risk_map': word_risk_map,
        'high_risk_words': high_risk_words,
        'medium_risk_words': medium_risk_words,
        'low_risk_words': low_risk_words,
        'theme_risk_level': theme_risk_level,
        'theme_risk_text': theme_risk_text,
    }


def words_split(theme):
    tokenizer = TweetTokenizer()
    return tokenizer.tokenize(theme or '')


# ====更新过滤函数===================#
# AMAZON_NOISE_WORDS = {
#     'tshirt', 't-shirt', 'shirt', 'clothing', 'apparel', 'gift', 'size',
#     'small', 'large', 'unisex', 'men', 'women', 'kids', 'adult', 'set',
#     'pack', 'pcs', 'color', 'black', 'white', 'soft', 'vintage', 'retro'
# }


def should_skip_word(word):
    """
    判断是否应该跳过该词的检测。
    增加了电商噪声过滤和停用词过滤。
    """
    if not word:
        return True

    word = word.strip().lower()  # 统一小写进行判断

    # 1. 基础物理过滤
    if len(word) <= 1:
        # 特例：如果是 5 (Season 5) 这种有意义的数字，可以考虑保留。
        # 但通常单个字母/数字不构成独立侵权风险。
        return True

    if all(c in string.punctuation for c in word):
        return True

    # 2. 停用词过滤 (核心优化：过滤 is, the, with, for 等)
    # if word in ENGLISH_STOP_WORDS:
    #     return True

    # 3. 电商属性噪声过滤 (核心优化：过滤 shirt, size 等)
    # if word in AMAZON_NOISE_WORDS:
    #     return True

    # 4. 纯数字过滤 (可选)
    # 亚马逊标题中常有价格或年份，如果你的侵权库不包含年份，可以过滤
    if word.isdigit():
        return True

    # 5. 校验是否有字母或数字（防止纯符号组合）
    if not any(c.isalnum() for c in word):
        return True

    return False


def words_split_api(request):
    theme = (request.POST.get('theme') or request.GET.get('theme') or '').strip()
    if not theme:
        return JsonResponse({'error': '请输入 theme'}, status=400)
    tokens = words_split(theme)
    return JsonResponse({'theme': theme, 'tokens': tokens})
