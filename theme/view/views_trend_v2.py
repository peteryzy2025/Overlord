from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from django.core.cache import cache
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import nltk
import json
import string
from collections import defaultdict
from nltk.tokenize import TweetTokenizer
from django.contrib.auth.decorators import login_required
from google import genai
from theme.models import *

# ==========================================
# API Keys 列表 - 在这里添加多个 Key 实现轮换
# ==========================================
GEMINI_API_KEYS = [
    # "AIzaSyByQAqg7_OajzkoYeXNF1FVmTpwnTsMKrc",
    # "IzaSyDCxKxA9_B6ZnH_n2IuIEy7ciFnDEdRgZI",
    "AIzaSyDJzsLBabU_ZoP98yyhZPRTqH6aGUVjr5U",
    # "AIzaSy...",  # 第二个 Key（限流时自动切换）
]

# 状态码集合（保持不变）
before_STATUS_CODES = {
    616, 630, 638, 640, 641, 642, 643, 644, 645, 646, 647, 648,
    649, 650, 651, 652, 653, 654, 655, 656, 657, 658, 659, 660,
    661, 663, 665, 666, 672, 680, 681, 746, 760, 969, 686
}

live_pending = {
    410, 413, 616, 620, 630, 631, 638, 640, 641, 642, 643, 644,
    645, 646, 647, 648, 649, 650, 651, 652, 653, 654, 655, 656,
    657, 658, 659, 660, 661, 663, 664, 665, 666, 667, 668, 672,
    680, 681, 682, 686, 688, 689, 690, 692, 693, 694, 718, 719,
    720, 721, 722, 724, 725, 730, 731, 732, 733, 734, 740, 744,
    745, 746, 748, 752, 753, 756, 757, 760, 762, 763, 764, 772,
    773, 774, 777, 779, 794, 801, 802, 803, 804, 806, 807, 808,
    809, 810, 811, 812, 813, 814, 815, 816, 817, 818, 819, 820,
    821, 822, 823, 824, 825, 969, 973
}

last_STATUS_CODES = live_pending - before_STATUS_CODES
HIGH_RISK_NAME_TYPES = {4, 5, 6, 7, 10}
LOW_RISK_NAME_TYPES = {1, 9}


def get_live_status_codes():
    """缓存获取 live_registered 状态码"""
    cache_key = 'live_registered_status_codes'
    live_registered = cache.get(cache_key)
    if live_registered is None:
        live_registered = set(
            StatusCodeMapping.objects.filter(
                status_type='Registered'
            ).values_list('status_code', flat=True)
        )
        cache.set(cache_key, live_registered, 3600)
    return live_registered


# ==========================================
# Gemini AI 分析函数（独立出来给 V2 用）
# ==========================================
def analyze_with_gemini_v2(theme: str, timeout: int = 30):
    """
    V2 AI 分析 - 修复 JSON 截断问题
    关键修复：max_output_tokens 增加到 8192（原来是 2048）
    """
    system_prompt = """You are an Amazon US compliance risk detection system. Your analysis must follow Amazon's "guilty until proven innocent" sweep standards, NOT general legality.

STRICT RULES:
1. NO FAIR USE defense - Amazon bots don't recognize it.
2. RECENT EVENTS: Treat BLM, Pride, political slogans, viral phrases as HIGH risk due to preemptive suppression.
3. TRADEMARKS: Check Nice Classes (especially Class 25 for apparel). Include "phantom" trademarks (recently filed).
4. UNCERTAINTY: When in doubt, classify as Medium or High. Never assume safety.
5. PLATFORM POLICY: Check for brand misuse, military/political sensitivity, prohibited content.
6. POD SPECIFIC: Check automated trigger keywords, official look-alike structures.

ANALYSIS FRAMEWORK:
- Trademark: Brand names, slogans, phonetic variations, pop culture quotes
- Copyright: Characters, movie quotes, celebrity likeness, meme origins  
- Policy: Prohibited symbols, military associations, political content
- POD Triggers: Gun sounds (PEW PEW), onomatopoeia that mimic brands

OUTPUT FORMAT - STRICT JSON ONLY:
{
    "theme": "原始主题",
    "overall_risk_level": "高|中|低",
    "overall_assessment": "200字内的整体评价，说明主要风险点和建议操作",
    "high_risk_items": [
        {"term": "风险词/短语", "reason": "具体原因", "category": "商标|版权|平台政策|POD敏感"}
    ],
    "medium_risk_items": [
        {"term": "风险词/短语", "reason": "具体原因", "category": "商标|版权|平台政策|POD敏感"}
    ],
    "low_risk_notes": ["需要注意但相对安全的点"],
    "recommendation": "建议操作：禁止上架|谨慎上架|可上架但需修改|安全"
}

CONSTRAINTS:
- 高风险词语和中风险词语必须区分开
- 整体评价用中文，简洁专业
- 如果无明显风险，high_risk_items 和 medium_risk_items 为空数组
- 绝对禁止输出 markdown 代码块标记（```）
- 只返回纯 JSON 字符串"""

    last_error = None
    raw_response = ""  # 用于调试

    for idx, api_key in enumerate(GEMINI_API_KEYS):
        try:
            client = genai.Client(api_key=api_key)

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"{system_prompt}\n\n待分析主题：{theme}",
                config={
                    'response_mime_type': 'application/json',
                    'temperature': 0.1,
                    'max_output_tokens': 8192,  # 🔴 关键修复：从 2048 改为 8192，防止截断
                }
            )

            raw_response = response.text.strip()

            # 防御性清理
            if not raw_response:
                last_error = "API 返回空内容"
                continue

            # 尝试解析 JSON
            try:
                result = json.loads(raw_response)
            except json.JSONDecodeError:
                # 清理 markdown 标记后重试
                text = raw_response
                if text.startswith("```json"):
                    text = text[7:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

                # 如果清理后还是解析失败，记录错误但返回降级结果（不全盘报错）
                try:
                    result = json.loads(text)
                except json.JSONDecodeError as e:
                    # 兜底：返回原始响应供前端显示，而不是空白
                    return {
                        "error": "JSON_PARSE_ERROR",
                        "error_detail": str(e),
                        "raw_response": raw_response[:500],  # 返回原始内容前500字供查看
                        "theme": theme,
                        "overall_risk_level": "中",
                        "overall_assessment": "AI 返回格式异常，请检查原始响应（可能是生成长度过长被截断）",
                        "high_risk_items": [],
                        "medium_risk_items": [],
                        "low_risk_notes": [f"原始响应片段: {raw_response[:200]}..."],
                        "recommendation": "建议重试或手动检查"
                    }

            # 字段补全
            result.setdefault('theme', theme)
            result.setdefault('overall_risk_level', '未知')
            result.setdefault('overall_assessment', '解析异常')
            result.setdefault('high_risk_items', [])
            result.setdefault('medium_risk_items', [])
            result.setdefault('low_risk_notes', [])
            result.setdefault('recommendation', '未知')
            return result

        except json.JSONDecodeError as e:
            last_error = f"JSON解析失败: {str(e)[:100]}"
            continue

        except Exception as e:
            error_str = str(e)
            last_error = error_str[:200]

            if any(keyword in error_str for keyword in ["RESOURCE_EXHAUSTED", "429", "QUOTA_EXHAUSTED"]):
                continue

            continue

    # 所有 Key 都失败
    return {
        "error": "API_ALL_KEYS_FAILED",
        "error_detail": last_error or "所有API Key均请求失败",
        "raw_response": raw_response[:300] if raw_response else "",
        "theme": theme,
        "overall_risk_level": "未知",
        "overall_assessment": f"AI 服务暂时不可用: {last_error or '未知错误'}",
        "high_risk_items": [],
        "medium_risk_items": [],
        "low_risk_notes": [],
        "recommendation": "请稍后重试或联系管理员"
    }

@login_required
def trend_page_v2(request):
    """V2 页面渲染"""
    return render(request, 'trend_v2.html', {'active_nav': 'theme_products'})


@require_POST
@csrf_exempt
def trend_search_v2(request):
    """
    V2 系统风险查询 - 只查数据库，不调用 AI
    快速返回，不阻塞前端
    """
    query = request.POST.get('trendQueryInput', '').strip()
    if not query:
        return JsonResponse({'error': '请输入搜索关键词'}, status=400)

    # 1. 分词处理
    tokens = words_split(query)
    valid_tokens = [t for t in tokens if not should_skip_word(t)]

    if not valid_tokens:
        return JsonResponse({
            'query': query,
            'tokens': tokens,
            'uspto_keywords': [],
            'uspto_details': {},
            'tro_keywords': [],
            'tro_details': {},
            'word_risk_map': {},
            'high_risk_words': [],
            'medium_risk_words': [],
            'low_risk_words': [],
            'theme_risk_level': 'low',
            'theme_risk_text': '低风险',
        })

    # 2. 美标网查询（核心优化：全大写走索引）
    token_uppers = [t.upper() for t in valid_tokens]

    trademark_records = TrademarkInfo.objects.filter(
        word_mark__in=token_uppers
    ).values('word_mark', 'serial_number', 'intl_class', 'status_code')

    # 构建内存数据结构
    uspto_matches = []
    uspto_details = {}
    word_status_codes = defaultdict(set)
    uspto_word_lower_map = {}

    for record in trademark_records:
        word = record['word_mark']
        word_lower = word.lower()

        if word not in uspto_details:
            uspto_matches.append(word)
            uspto_details[word] = []
        uspto_details[word].append({
            'serial_number': record['serial_number'],
            'intl_class': record['intl_class'] or 'N/A'
        })

        if record['status_code']:
            try:
                word_status_codes[word].add(int(record['status_code']))
            except (ValueError, TypeError):
                pass

        uspto_word_lower_map[word_lower] = word

    # 3. TroTable 查询
    q_tro = Q()
    for token in valid_tokens:
        q_tro |= Q(theme_name__iexact=token)

    tro_records = TroTable.objects.filter(q_tro).exclude(
        name_type__in=LOW_RISK_NAME_TYPES
    ).values('theme_name', 'name_type')

    tro_matches = []
    tro_details = {}
    tro_risk_map = {}

    for record in tro_records:
        word = record['theme_name']
        name_type = record['name_type']
        tro_matches.append(word)
        tro_details[word] = name_type
        tro_risk_map[word.lower()] = name_type

    # 4. 风险判断（纯内存操作）
    all_live = last_STATUS_CODES.union(get_live_status_codes())
    high_risk_words, medium_risk_words, low_risk_words = [], [], []
    word_risk_map = {}

    for token in valid_tokens:
        token_lower = token.lower()
        token_upper = token.upper()

        # 高风险判断（TroTable）
        if token_lower in tro_risk_map:
            name_type = tro_risk_map[token_lower]
            original_word = uspto_word_lower_map.get(token_lower, token_upper)

            if name_type in HIGH_RISK_NAME_TYPES:
                word_risk_map[original_word] = 'high'
                high_risk_words.append(original_word)
                continue

        # 中风险判断（美标网状态码）
        if token_lower in uspto_word_lower_map:
            original_word = uspto_word_lower_map[token_lower]
            status_codes = word_status_codes.get(original_word, set())

            if status_codes.intersection(all_live):
                word_risk_map[original_word] = 'medium'
                medium_risk_words.append(original_word)
            else:
                word_risk_map[original_word] = 'low'
                low_risk_words.append(original_word)
        else:
            word_risk_map[token] = 'low'
            low_risk_words.append(token)

    # 5. 整体风险等级
    if high_risk_words:
        theme_risk_level, theme_risk_text = 'high', '高风险'
    elif medium_risk_words:
        theme_risk_level, theme_risk_text = 'medium', '中风险'
    else:
        theme_risk_level, theme_risk_text = 'low', '低风险'

    return JsonResponse({
        'query': query,
        'tokens': tokens,
        'uspto_keywords': uspto_matches,
        'uspto_details': uspto_details,
        'tro_keywords': tro_matches,
        'tro_details': tro_details,
        'word_risk_map': word_risk_map,
        'high_risk_words': high_risk_words,
        'medium_risk_words': medium_risk_words,
        'low_risk_words': low_risk_words,
        'theme_risk_level': theme_risk_level,
        'theme_risk_text': theme_risk_text,
        # V2：不返回 ai_analysis，让前端单独请求
    }, json_dumps_params={'ensure_ascii': False})


@require_POST
@csrf_exempt
def ai_analyze_v2(request):
    """
    V2 AI 分析接口 - 独立接口，慢但不阻塞系统风险显示
    """
    query = request.POST.get('trendQueryInput', '').strip()
    if not query:
        return JsonResponse({'error': '请输入搜索关键词'}, status=400)

    result = analyze_with_gemini_v2(query)

    return JsonResponse(result, json_dumps_params={'ensure_ascii': False})


def words_split(theme):
    tokenizer = TweetTokenizer()
    return tokenizer.tokenize(theme or '')


def should_skip_word(word):
    """判断是否应该跳过该词的检测"""
    word = word.strip()
    if not word or len(word) == 1:
        return True
    if all(c in string.punctuation for c in word):
        return True
    if not any(c.isalnum() for c in word):
        return True
    return False


@login_required
def words_split_api(request):
    """保留给 V2 使用"""
    theme = (request.POST.get('theme') or request.GET.get('theme') or '').strip()
    if not theme:
        return JsonResponse({'error': '请输入 theme'}, status=400)
    tokens = words_split(theme)
    return JsonResponse({'theme': theme, 'tokens': tokens})