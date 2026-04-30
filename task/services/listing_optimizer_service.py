# -*- coding: utf-8 -*-
import json
import os
import re
import shutil
import threading
import uuid
import urllib.error
import urllib.request
import warnings
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone
from openpyxl import load_workbook

from task.models import ListingOptimizationJob, ListingOptimizationRow


TITLE_KEY = "Product Name（标题）"
DESCRIPTION_KEY = "Product Description（描述）"
BULLET_1_KEY = "Key Product Features 1（五点1）"
BULLET_2_KEY = "Key Product Features 2（五点2）"
BULLET_3_KEY = "Key Product Features 3（五点3）"
BULLET_4_KEY = "Key Product Features 4（五点4）"
BULLET_5_KEY = "Key Product Features 5（五点5）"
SEARCH_TERMS_KEY = "Search Terms（后台关键词）"
MAIN_IMAGE_KEY = "Main Image URL（主图）"

TRANSLATABLE_KEYS = [
    TITLE_KEY,
    DESCRIPTION_KEY,
    BULLET_1_KEY,
    BULLET_2_KEY,
    BULLET_3_KEY,
    BULLET_4_KEY,
    BULLET_5_KEY,
    SEARCH_TERMS_KEY,
]
REQUIRED_LISTING_KEYS = [*TRANSLATABLE_KEYS, MAIN_IMAGE_KEY]

OUTPUT_KEYS: List[str] = []
for _field_key in TRANSLATABLE_KEYS:
    OUTPUT_KEYS.extend([_field_key, f"{_field_key}中文", f"{_field_key}原文中文"])
OUTPUT_KEYS.append(MAIN_IMAGE_KEY)
del _field_key

EXCEL_COLUMN_MAP = {
    "item_name": TITLE_KEY,
    "product_description": DESCRIPTION_KEY,
    "bullet_point1": BULLET_1_KEY,
    "bullet_point2": BULLET_2_KEY,
    "bullet_point3": BULLET_3_KEY,
    "bullet_point4": BULLET_4_KEY,
    "bullet_point5": BULLET_5_KEY,
    "generic_keywords": SEARCH_TERMS_KEY,
    "main_image_url": MAIN_IMAGE_KEY,
}

HEADER_ROW = 3
DATA_START_ROW = 4
MAX_UPLOAD_SIZE = 10 * 1024 * 1024
DEFAULT_PROMPT_PROFILE = "amazon_grammar_tyrant"
DEFAULT_AI_MODEL = "qwen-flash"

PROMPT_PROFILE_OPTIONS = [
    {
        "value": DEFAULT_PROMPT_PROFILE,
        "label": "亚马逊语法暴君",
        "enabled": True,
    },
    {
        "value": "conversion_demon",
        "label": "转化率魔神",
        "enabled": False,
    },
    {
        "value": "traffic_topology_emperor",
        "label": "流量拓扑皇帝",
        "enabled": False,
    },
    {
        "value": "a10_judge",
        "label": "A10裁决者",
        "enabled": False,
    },
]

AI_MODEL_OPTIONS = [
    {
        "value": "qwen-flash",
        "label": "qwen-flash",
        "enabled": True,
        "provider": "dashscope",
        "api_key_setting": "DASHSCOPE_API_KEY",
        "endpoint_setting": "DASHSCOPE_ENDPOINT",
        "default_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    },
    {
        "value": "qwen3.5-flash",
        "label": "qwen3.5-flash",
        "enabled": True,
        "provider": "dashscope",
        "api_key_setting": "DASHSCOPE_API_KEY",
        "endpoint_setting": "DASHSCOPE_ENDPOINT",
        "default_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    },
    {
        "value": "qwen3.6-flash",
        "label": "qwen3.6-flash",
        "enabled": True,
        "provider": "dashscope",
        "api_key_setting": "DASHSCOPE_API_KEY",
        "endpoint_setting": "DASHSCOPE_ENDPOINT",
        "default_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    },
    {
        "value": "deepseek-v4-flash",
        "label": "DeepSeek-V4-Flash",
        "enabled": True,
        "provider": "deepseek",
        "api_key_setting": "DEEPSEEK_API_KEY",
        "endpoint_setting": "DEEPSEEK_ENDPOINT",
        "default_endpoint": "https://api.deepseek.com/chat/completions",
        "aliases": ["DeepSeek-V4-Flash"],
    },
    {
        "value": "deepseek-v4-pro",
        "label": "Deepseek-v4-pro",
        "enabled": True,
        "provider": "deepseek",
        "api_key_setting": "DEEPSEEK_API_KEY",
        "endpoint_setting": "DEEPSEEK_ENDPOINT",
        "default_endpoint": "https://api.deepseek.com/chat/completions",
    },
]

_active_jobs = set()
_worker_lock = threading.Lock()


class ListingValidationError(ValueError):
    pass


class DashScopeError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def get_listing_optimizer_config() -> Dict[str, Any]:
    return {
        "prompt_profiles": PROMPT_PROFILE_OPTIONS,
        "ai_models": [
            {
                "value": item["value"],
                "label": item["label"],
                "enabled": item["enabled"],
            }
            for item in AI_MODEL_OPTIONS
        ],
        "defaults": {
            "prompt_profile": DEFAULT_PROMPT_PROFILE,
            "ai_model": DEFAULT_AI_MODEL,
        },
    }


def validate_prompt_profile(value: Optional[str]) -> str:
    profile = (value or DEFAULT_PROMPT_PROFILE).strip()
    options = {item["value"]: item for item in PROMPT_PROFILE_OPTIONS}
    selected = options.get(profile)
    if not selected:
        raise ListingValidationError("请选择有效的提示词。")
    if not selected.get("enabled"):
        raise ListingValidationError("该提示词暂未开放选择。")
    return profile


def validate_ai_model(value: Optional[str]) -> str:
    model = (value or DEFAULT_AI_MODEL).strip()
    selected = get_ai_model_option(model)
    if not selected:
        raise ListingValidationError("请选择有效的 AI 模型。")
    if not selected.get("enabled"):
        raise ListingValidationError("该 AI 模型暂未开放选择。")
    return selected["value"]


def get_ai_model_option(value: Optional[str]) -> Optional[Dict[str, Any]]:
    model = (value or "").strip()
    if not model:
        model = DEFAULT_AI_MODEL
    model_lower = model.lower()
    for item in AI_MODEL_OPTIONS:
        aliases = [item["value"], item["label"], *item.get("aliases", [])]
        if any(model_lower == str(alias).lower() for alias in aliases):
            return item
    return None


def get_prompt_profile_label(value: str) -> str:
    for item in PROMPT_PROFILE_OPTIONS:
        if item["value"] == value:
            return item["label"]
    return value or DEFAULT_PROMPT_PROFILE


def get_ai_model_label(value: str) -> str:
    option = get_ai_model_option(value)
    return option["label"] if option else value


def get_listing_user_display_name(user) -> str:
    if not user:
        return ""
    return (
        getattr(user, "first_name", "")
        or getattr(user, "username", "")
        or str(getattr(user, "id", ""))
    )


class QwenAmazonListingOptimizer:
    DEFAULT_PROMPT = """
你是拥有20年美国 Amazon POD 产品运营经验的资深卖家，也是一名深耕美国市场的 Amazon SEO 专家。你擅长识别标题背后的文化主题，并为美亚买家编写自然、合规、可转化的 listing。
你熟悉美国搜索习惯，并以 A10 相关性、COSMO/Rufus 语义理解、GEO 生成式检索友好表达为目标：用清晰的“主题词 + 产品词 + 图案/工艺 + 场景 + 人群”线性结构组织文案。

任务：
基于输入的标题、产品属性、图片 URL 和现有文案，先在内部识别“主题”和产品类型，再围绕主题重写 Amazon listing。主题指产品图案、文字、梗、节日、纪念事件、身份标签、情绪表达或文化场景；产品本身只是承载主题的载体。输出必须包含英文标题、五点描述、产品描述、后台搜索关键词、优化后英文内容的中文意思、输入原文的中文翻译，以及主图 URL。

硬性规则：
1. 只输出一个 JSON 对象，不要 Markdown，不要解释，不要多余字段。
2. JSON 的 key 必须严格等于用户提供的输出字段清单；顺序也尽量保持一致。
3. 除主图 URL 外，每个英文 listing 字段后面都必须增加两个中文字段：一个“中文”字段和一个“原文中文”字段，例如 "Key Product Features 1（五点1）中文"、"Key Product Features 1（五点1）原文中文"。
4. “中文”字段必须是优化后英文内容的自然中文翻译或中文意思；“原文中文”字段必须是输入原文字段的自然中文翻译。不要写优化说明，不要逐条解释你为什么这样写。
5. listing 优化必须“主题优先，产品承接”。不要把产品属性当成主题，不要用泛泛的产品词替代主题；产品材质、版型、尺寸、舒适度只作为辅助卖点，不能覆盖或稀释主题。
6. 标题使用地道美式英语，目标长度约 120 个字符，但绝不能超过 125 个字符。标题前半段必须突出主题或合规主题改写，并自然连接产品类型、图案/工艺、使用场景或人群。推荐结构：“合规主题词 + 产品类型 + graphic/printed/design/style + 人群/场景”。禁止生成主题缺失的泛产品标题，例如只写 “Vintage Washed Cotton Dad Hat for Men & Women” 这类文案。
7. 五点描述共 5 条，每条只写一段英文，并必须围绕主题埋词和扩展：主题含义/情绪共鸣、图案视觉/印花质感、文化或使用场景、礼品人群、产品承载属性。每条都应让买家理解这个图案主题为什么值得购买，而不是只描述产品本身。
8. 产品描述写成单段流畅英文自然段，以主题故事、文化语境、情绪价值、场景和礼品价值为主，再自然带出产品类型和可确认的产品属性。不要写成泛泛的产品材质介绍，不要虚构认证、销量或无法确认的卖点。
9. 后台搜索关键词不超过 250 个字符；全部小写；用空格分隔；优先补充标题未覆盖的主题同义词、文化场景词、人群词和礼品词；不重复；不要标点、品牌名、ASIN、竞品词或侵权词。
10. “Search Terms（后台关键词）中文”和“Search Terms（后台关键词）原文中文”按正常中文意思翻译即可，可以是自然短语，不需要遵守后台关键词的空格格式。
11. 侵权与合规过滤：不要使用商标、品牌、球队、电影、明星、角色、歌词、组织名称等受保护内容；不要写 official、licensed、authentic、best、#1、guaranteed、medical claims 等高风险表达。
12. 如果输入主题存在侵权或高风险表达，应改写为中性、合规、可搜索的主题表达，但不能直接删除主题或把它弱化成通用产品词。例如 "AMERICA 250" 可改写为 "250th Anniversary"；其他高风险主题也按同样原则改写为通用文化/纪念/节日表达。
13. 不要虚构认证、销量、库存、物流、环保认证或“latest 2026 release”等无法从输入确认的事实。
14. 绝对禁止出现 "3D" 或任何 3D 变体；不要写颜色描述词；不要写具体面料成分或比例，例如 "100% Cotton"。
15. 产品类型必须跟随输入和图片 URL 所能确认的信息。只有当产品确实是印花鸭舌帽/棒球帽/帽子时，才可以自然使用 "printed baseball cap"、"graphic printed cap"、"dad hat" 等表达；不要把所有产品都强制写成 Printing Baseball Cap。
16. 如果输入标题中出现 shirt 等词，但产品图片或字段显示实际产品是帽子/其他 POD 产品，应把 shirt 只当作图案主题或原始噪音处理，不要把产品类型误写成 shirt。
17. 主图 URL 必须原样返回，并且不要为主图 URL 添加中文字段或原文中文字段。
18. 输入字典中如果有额外字段，可以作为上下文参考，但不要把额外字段返回。
"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        prompt_profile: Optional[str] = None,
        endpoint: Optional[str] = None,
        timeout: int = 90,
    ) -> None:
        env_model = getattr(settings, "DASHSCOPE_MODEL", "") or os.getenv("DASHSCOPE_MODEL", "")
        try:
            self.model = validate_ai_model(model or env_model or DEFAULT_AI_MODEL)
        except ListingValidationError:
            if model:
                raise
            self.model = DEFAULT_AI_MODEL
        self.model_option = get_ai_model_option(self.model) or get_ai_model_option(DEFAULT_AI_MODEL)
        self.provider = self.model_option.get("provider", "dashscope")
        api_key_setting = self.model_option.get("api_key_setting", "DASHSCOPE_API_KEY")
        endpoint_setting = self.model_option.get("endpoint_setting", "DASHSCOPE_ENDPOINT")
        default_endpoint = self.model_option.get(
            "default_endpoint",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        )
        self.api_key = api_key or getattr(settings, api_key_setting, "") or os.getenv(api_key_setting, "")
        self.prompt_profile = validate_prompt_profile(prompt_profile)
        self.system_prompt = self.DEFAULT_PROMPT
        self.endpoint = (
            endpoint
            or getattr(settings, endpoint_setting, "")
            or os.getenv(endpoint_setting, "")
            or default_endpoint
        )
        self.timeout = timeout
        if not self.api_key:
            raise DashScopeError(f"缺少 {self.provider} API key，请在 .env 中配置 {api_key_setting}。")

    def optimize(self, listing: Dict[str, Any]) -> Dict[str, str]:
        source_listing = validate_listing_dict(listing)
        last_error: Optional[DashScopeError] = None
        for candidate_model in self._candidate_models():
            for include_response_format in (True, False):
                thinking_flags = (True, False) if self.provider == "dashscope" else (False,)
                for include_thinking_flag in thinking_flags:
                    payload = self._build_payload(
                        source_listing,
                        candidate_model,
                        include_response_format,
                        include_thinking_flag,
                    )
                    try:
                        content, raw_response = self._chat_completion(payload)
                        parsed = self._extract_json_object(content, raw_response)
                        try:
                            return normalize_optimizer_result(parsed, source_listing)
                        except DashScopeError as exc:
                            raise DashScopeError(
                                append_ai_raw_response(str(exc), raw_response),
                                exc.status,
                                exc.body,
                            ) from exc
                    except DashScopeError as exc:
                        last_error = exc
                        if self._should_retry(exc) or (include_response_format and self._should_retry_without_json_mode(exc)):
                            continue
                        raise

        if last_error:
            raise last_error
        raise DashScopeError("千问接口调用失败，但未返回具体错误。")

    def _candidate_models(self) -> Iterable[str]:
        yield self.model

    def _build_payload(
        self,
        listing: Dict[str, str],
        model: str,
        include_response_format: bool,
        include_thinking_flag: bool,
    ) -> Dict[str, Any]:
        user_prompt = (
            "请先在内部分析主题、产品属性、美国买家搜索词和潜在侵权风险，"
            "然后只返回最终 JSON 对象。\n\n"
            f"必须返回的字段清单：\n{json.dumps(OUTPUT_KEYS, ensure_ascii=False, indent=2)}\n\n"
            f"输入 listing：\n{json.dumps(listing, ensure_ascii=False, indent=2)}"
        )
        payload: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.35,
            "max_tokens": 2200,
        }
        if include_response_format:
            payload["response_format"] = {"type": "json_object"}
        if include_thinking_flag and self.provider == "dashscope":
            payload["enable_thinking"] = False
        return payload

    def _chat_completion(self, payload: Dict[str, Any]) -> Tuple[str, str]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise DashScopeError(f"AI API HTTP {exc.code}: {body}", exc.code, body) from exc
        except urllib.error.URLError as exc:
            raise DashScopeError(f"AI API request failed: {exc.reason}") from exc

        try:
            result = json.loads(raw)
            message = result["choices"][0].get("message", {})
            content = message.get("content", "")
            if content is None:
                content = ""
            return str(content), raw
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise DashScopeError(f"无法解析 AI 接口返回内容:\n{clip_debug_text(raw)}") from exc

    @staticmethod
    def _extract_json_object(content: str, raw_response: str = "") -> Dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                detail = clip_debug_text(content) if content.strip() else "message.content 为空"
                raise DashScopeError(append_ai_raw_response(f"模型没有返回 JSON 对象:\n{detail}", raw_response))
            parsed = json.loads(match.group(0))

        if not isinstance(parsed, dict):
            raise DashScopeError(append_ai_raw_response("模型返回的 JSON 不是对象。", raw_response))
        return parsed

    @staticmethod
    def _should_retry(error: DashScopeError) -> bool:
        if error.status != 400:
            return False
        retry_markers = (
            "enable_thinking",
            "model",
            "parameter",
            "invalid",
            "not support",
            "not exist",
            "unsupported",
            "response_format",
        )
        text = f"{error} {error.body}".lower()
        return any(marker in text for marker in retry_markers)

    @staticmethod
    def _should_retry_without_json_mode(error: DashScopeError) -> bool:
        text = str(error)
        retry_markers = (
            "模型没有返回 JSON 对象",
            "message.content 为空",
            "response_format",
            "json_object",
        )
        return any(marker in text for marker in retry_markers)


def validate_listing_dict(listing: Dict[str, Any]) -> Dict[str, str]:
    if not isinstance(listing, dict):
        raise ListingValidationError("listing 必须是 dict。")

    missing_keys = [key for key in REQUIRED_LISTING_KEYS if key not in listing]
    if missing_keys:
        raise ListingValidationError(f"listing 缺少必填字段: {', '.join(missing_keys)}")

    normalized = deepcopy(listing)
    for key in REQUIRED_LISTING_KEYS:
        value = normalized.get(key)
        if value is None:
            normalized[key] = ""
        elif not isinstance(value, str):
            normalized[key] = str(value)
    return normalized


def normalize_optimizer_result(result: Dict[str, Any], original: Dict[str, str]) -> Dict[str, str]:
    missing_keys = [key for key in OUTPUT_KEYS if key not in result]
    if missing_keys:
        raise DashScopeError(f"模型返回结果缺少字段: {', '.join(missing_keys)}")

    normalized: Dict[str, str] = {}
    for key in OUTPUT_KEYS:
        if key == MAIN_IMAGE_KEY:
            normalized[key] = clean_text(original[MAIN_IMAGE_KEY])
        else:
            normalized[key] = clean_listing_output_text(result[key])

    normalized[TITLE_KEY] = clip_at_word(normalized[TITLE_KEY], 125)
    normalized[SEARCH_TERMS_KEY] = clip_at_word(clean_search_terms(normalized[SEARCH_TERMS_KEY]), 250)
    return normalized


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def clip_debug_text(value: Any, limit: int = 4000) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...（已截断，仅显示前 {limit} 字符）"


def append_ai_raw_response(message: str, raw_response: str = "") -> str:
    if not raw_response:
        return message
    if "AI 原始返回:" in message:
        return message
    return f"{message}\n\nAI 原始返回:\n{clip_debug_text(raw_response)}"


def clean_listing_output_text(value: Any) -> str:
    text = clean_text(value)
    text = re.sub(r"\b3\s*[- ]?d\b", "graphic", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\b100\s*%\s*(?:premium\s*)?(?:washed\s*)?cotton\b",
        "washed fabric",
        text,
        flags=re.IGNORECASE,
    )
    return clean_text(text)


def clean_search_terms(value: str) -> str:
    tokens = re.findall(r"[a-z0-9][a-z0-9'-]*", value.lower())
    unique_tokens = []
    seen = set()
    for token in tokens:
        token = token.strip("'-")
        if token and token not in seen:
            seen.add(token)
            unique_tokens.append(token)
    return " ".join(unique_tokens)


def clip_at_word(value: str, limit: int) -> str:
    value = clean_text(value)
    if len(value) <= limit:
        return value
    clipped = value[:limit].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped.rstrip(" ,.;:-")


def save_uploaded_listing_file(uploaded_file) -> Tuple[str, str]:
    if not uploaded_file.name.lower().endswith((".xlsx", ".xlsm")):
        raise ListingValidationError("仅支持 Excel 文件（.xlsx、.xlsm）。")
    if uploaded_file.size > MAX_UPLOAD_SIZE:
        raise ListingValidationError("文件大小不能超过 10MB。")

    temp_dir = os.path.join(settings.MEDIA_ROOT, "temp_uploads", "listing_optimizer", str(uuid.uuid4()))
    os.makedirs(temp_dir, exist_ok=True)
    file_path = os.path.join(temp_dir, uploaded_file.name)
    with open(file_path, "wb+") as destination:
        for chunk in uploaded_file.chunks():
            destination.write(chunk)

    relative_path = os.path.relpath(file_path, settings.MEDIA_ROOT)
    return relative_path.replace("\\", "/"), file_path


def create_job_from_excel(
    uploaded_file,
    user,
    prompt_profile: Optional[str] = None,
    ai_model: Optional[str] = None,
) -> ListingOptimizationJob:
    prompt_profile = validate_prompt_profile(prompt_profile)
    ai_model = validate_ai_model(ai_model)
    relative_path, full_path = save_uploaded_listing_file(uploaded_file)
    rows = read_listing_rows(full_path)

    with transaction.atomic():
        job = ListingOptimizationJob.objects.create(
            created_by=user,
            original_filename=uploaded_file.name,
            original_file_path=relative_path,
            prompt_profile=prompt_profile,
            ai_model=ai_model,
            status=ListingOptimizationJob.STATUS_PENDING,
            total_rows=len(rows),
        )
        ListingOptimizationRow.objects.bulk_create(
            [
                ListingOptimizationRow(
                    job=job,
                    row_number=row_number,
                    source_data=source_data,
                    optimized_data={},
                    status=ListingOptimizationRow.STATUS_PENDING,
                )
                for row_number, source_data in rows
            ]
        )
    return job


def read_listing_rows(full_path: str) -> List[Tuple[int, Dict[str, str]]]:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Workbook contains no default style, apply openpyxl's default",
            category=UserWarning,
            module="openpyxl.styles.stylesheet",
        )
        workbook = load_workbook(full_path, read_only=True, data_only=True)
    worksheet = workbook.active
    header_map = _get_header_map(worksheet)
    missing_columns = [column for column in EXCEL_COLUMN_MAP if column not in header_map]
    if missing_columns:
        raise ListingValidationError(f"Excel 缺少必需列: {', '.join(missing_columns)}")

    rows = []
    for excel_row in range(DATA_START_ROW, worksheet.max_row + 1):
        title_value = worksheet.cell(excel_row, header_map["item_name"]).value
        if clean_text(title_value) == "":
            continue

        source_data = {}
        for excel_column, listing_key in EXCEL_COLUMN_MAP.items():
            value = worksheet.cell(excel_row, header_map[excel_column]).value
            source_data[listing_key] = clean_text(value)
        rows.append((excel_row, source_data))

    workbook.close()
    if not rows:
        raise ListingValidationError("Excel 中没有可优化的 listing 行。")
    return rows


def _get_header_map(worksheet) -> Dict[str, int]:
    header_map = {}
    for cell in worksheet[HEADER_ROW]:
        value = clean_text(cell.value)
        if value:
            header_map[value] = cell.column
    return header_map


def start_listing_optimization_job(job_id: int) -> bool:
    with _worker_lock:
        if job_id in _active_jobs:
            return False
        _active_jobs.add(job_id)

    worker = threading.Thread(
        target=_run_listing_optimization_job,
        args=(job_id,),
        daemon=True,
        name=f"listing-optimizer-{job_id}",
    )
    worker.start()
    return True


def ensure_listing_job_running(job: ListingOptimizationJob) -> None:
    if job.status in {ListingOptimizationJob.STATUS_PENDING, ListingOptimizationJob.STATUS_PROCESSING}:
        start_listing_optimization_job(job.id)


def pause_listing_optimization_job(job: ListingOptimizationJob) -> ListingOptimizationJob:
    if job.status in {ListingOptimizationJob.STATUS_PENDING, ListingOptimizationJob.STATUS_PROCESSING}:
        job.status = ListingOptimizationJob.STATUS_PAUSED
        job.save(update_fields=["status", "updated_at"])
    return job


def retry_failed_listing_rows(
    job: ListingOptimizationJob,
    row_ids: Optional[Iterable[int]] = None,
) -> Tuple[ListingOptimizationJob, int, bool]:
    if job.status in {ListingOptimizationJob.STATUS_PENDING, ListingOptimizationJob.STATUS_PROCESSING}:
        raise ListingValidationError("任务正在优化中，请先等待完成或暂停后再重试失败行。")

    failed_rows = ListingOptimizationRow.objects.filter(
        job=job,
        status=ListingOptimizationRow.STATUS_FAILED,
    )
    if row_ids is not None:
        failed_rows = failed_rows.filter(id__in=list(row_ids))

    retry_count = failed_rows.update(
        status=ListingOptimizationRow.STATUS_PENDING,
        error_message="",
        updated_at=timezone.now(),
    )
    if retry_count == 0:
        return job, 0, False

    _refresh_job_progress(job.id)
    update_values = {
        "error_message": "",
        "completed_at": None,
        "output_file_path": "",
        "updated_at": timezone.now(),
    }
    should_start = job.status != ListingOptimizationJob.STATUS_PAUSED
    if should_start:
        update_values["status"] = ListingOptimizationJob.STATUS_PENDING
    ListingOptimizationJob.objects.filter(id=job.id).update(**update_values)
    job.refresh_from_db()
    return job, retry_count, should_start


def _run_listing_optimization_job(job_id: int) -> None:
    close_old_connections()
    try:
        job = ListingOptimizationJob.objects.get(id=job_id)
        ListingOptimizationRow.objects.filter(
            job=job,
            status=ListingOptimizationRow.STATUS_PROCESSING,
        ).update(status=ListingOptimizationRow.STATUS_PENDING, error_message="")

        if job.status == ListingOptimizationJob.STATUS_PAUSED:
            return

        if job.status != ListingOptimizationJob.STATUS_PROCESSING:
            job.status = ListingOptimizationJob.STATUS_PROCESSING
            if not job.started_at:
                job.started_at = timezone.now()
            job.save(update_fields=["status", "started_at", "updated_at"])

        optimizer = QwenAmazonListingOptimizer(
            model=job.ai_model,
            prompt_profile=job.prompt_profile,
        )
        pending_rows = ListingOptimizationRow.objects.filter(
            job_id=job_id,
            status=ListingOptimizationRow.STATUS_PENDING,
        ).order_by("row_number")

        for row in pending_rows:
            current_status = ListingOptimizationJob.objects.filter(id=job_id).values_list("status", flat=True).first()
            if current_status == ListingOptimizationJob.STATUS_PAUSED:
                return

            row.status = ListingOptimizationRow.STATUS_PROCESSING
            row.error_message = ""
            row.save(update_fields=["status", "error_message", "updated_at"])
            try:
                optimized = optimizer.optimize(row.source_data)
                row.optimized_data = optimized
                row.status = ListingOptimizationRow.STATUS_COMPLETED
                row.error_message = ""
                row.save(update_fields=["optimized_data", "status", "error_message", "updated_at"])
            except Exception as exc:
                row.status = ListingOptimizationRow.STATUS_FAILED
                row.error_message = str(exc)[:6000]
                row.save(update_fields=["status", "error_message", "updated_at"])
            _refresh_job_progress(job_id)

            current_status = ListingOptimizationJob.objects.filter(id=job_id).values_list("status", flat=True).first()
            if current_status == ListingOptimizationJob.STATUS_PAUSED:
                return

        _finish_job(job_id)
    except Exception as exc:
        ListingOptimizationJob.objects.filter(id=job_id).update(
            status=ListingOptimizationJob.STATUS_FAILED,
            error_message=str(exc)[:6000],
            completed_at=timezone.now(),
        )
    finally:
        with _worker_lock:
            _active_jobs.discard(job_id)
        close_old_connections()


def _refresh_job_progress(job_id: int) -> None:
    optimized_count = ListingOptimizationRow.objects.filter(
        job_id=job_id,
        status=ListingOptimizationRow.STATUS_COMPLETED,
    ).count()
    failed_count = ListingOptimizationRow.objects.filter(
        job_id=job_id,
        status=ListingOptimizationRow.STATUS_FAILED,
    ).count()
    ListingOptimizationJob.objects.filter(id=job_id).update(
        optimized_rows=optimized_count,
        failed_rows=failed_count,
        updated_at=timezone.now(),
    )


def _finish_job(job_id: int) -> None:
    _refresh_job_progress(job_id)
    job = ListingOptimizationJob.objects.get(id=job_id)
    has_failed = job.failed_rows > 0
    ListingOptimizationJob.objects.filter(id=job_id).update(
        status=ListingOptimizationJob.STATUS_FAILED if has_failed else ListingOptimizationJob.STATUS_COMPLETED,
        completed_at=timezone.now(),
        updated_at=timezone.now(),
    )


def update_row_optimized_data(row: ListingOptimizationRow, optimized_data: Dict[str, Any]) -> ListingOptimizationRow:
    cleaned = {}
    base_data = row.optimized_data or row.source_data or {}
    for key in OUTPUT_KEYS:
        if key == MAIN_IMAGE_KEY:
            cleaned[key] = row.source_data.get(MAIN_IMAGE_KEY, "")
        else:
            cleaned[key] = clean_listing_output_text(optimized_data.get(key, base_data.get(key, "")))

    for listing_key in TRANSLATABLE_KEYS:
        original_translation_key = f"{listing_key}原文中文"
        if not cleaned.get(original_translation_key):
            cleaned[original_translation_key] = clean_text(base_data.get(original_translation_key, ""))

    cleaned[TITLE_KEY] = clip_at_word(cleaned[TITLE_KEY], 125)
    cleaned[SEARCH_TERMS_KEY] = clip_at_word(clean_search_terms(cleaned[SEARCH_TERMS_KEY]), 250)
    row.optimized_data = cleaned
    row.save(update_fields=["optimized_data", "updated_at"])
    return row


def generate_optimized_excel(job: ListingOptimizationJob) -> str:
    original_full_path = os.path.join(settings.MEDIA_ROOT, job.original_file_path)
    if not os.path.exists(original_full_path):
        raise FileNotFoundError("原始上传文件不存在，无法生成下载文件。")

    output_dir = os.path.join(settings.MEDIA_ROOT, "temp_uploads", "listing_optimizer_outputs", str(job.id))
    os.makedirs(output_dir, exist_ok=True)
    filename_root, filename_ext = os.path.splitext(job.original_filename)
    output_name = f"{filename_root}_listing优化_{datetime.now().strftime('%Y%m%d%H%M%S')}{filename_ext or '.xlsx'}"
    output_full_path = os.path.join(output_dir, output_name)
    shutil.copy2(original_full_path, output_full_path)

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Workbook contains no default style, apply openpyxl's default",
            category=UserWarning,
            module="openpyxl.styles.stylesheet",
        )
        workbook = load_workbook(output_full_path)
    worksheet = workbook.active
    header_map = _get_header_map(worksheet)
    missing_columns = [column for column in EXCEL_COLUMN_MAP if column not in header_map]
    if missing_columns:
        workbook.close()
        raise ListingValidationError(f"Excel 缺少必需列: {', '.join(missing_columns)}")

    rows = job.rows.all().order_by("row_number")
    reverse_map = {listing_key: excel_column for excel_column, listing_key in EXCEL_COLUMN_MAP.items()}
    for row in rows:
        data = row.optimized_data or row.source_data
        for listing_key in REQUIRED_LISTING_KEYS:
            excel_column_name = reverse_map[listing_key]
            worksheet.cell(row.row_number, header_map[excel_column_name]).value = data.get(listing_key, "")

    workbook.save(output_full_path)
    workbook.close()

    relative_output_path = os.path.relpath(output_full_path, settings.MEDIA_ROOT).replace("\\", "/")
    job.output_file_path = relative_output_path
    job.save(update_fields=["output_file_path", "updated_at"])
    return relative_output_path


def serialize_job(
    job: ListingOptimizationJob,
    include_rows: bool = False,
    include_owner: bool = False,
) -> Dict[str, Any]:
    data = {
        "id": job.id,
        "original_filename": job.original_filename,
        "created_by_id": job.created_by_id,
        "created_by_name": get_listing_user_display_name(getattr(job, "created_by", None)) if include_owner else "",
        "prompt_profile": job.prompt_profile,
        "prompt_profile_label": get_prompt_profile_label(job.prompt_profile),
        "ai_model": job.ai_model,
        "ai_model_label": get_ai_model_label(job.ai_model),
        "status": job.status,
        "status_display": job.get_status_display(),
        "total_rows": job.total_rows,
        "optimized_rows": job.optimized_rows,
        "failed_rows": job.failed_rows,
        "error_message": job.error_message,
        "output_file_path": job.output_file_path,
        "created_at": job.created_at.strftime("%Y-%m-%d %H:%M:%S") if job.created_at else "",
        "updated_at": job.updated_at.strftime("%Y-%m-%d %H:%M:%S") if job.updated_at else "",
        "download_url": "",
    }
    if job.output_file_path:
        data["download_url"] = f"/api/tasks/listing-optimizer/jobs/{job.id}/download/"
    if include_rows:
        data["rows"] = [serialize_row(row) for row in job.rows.all().order_by("row_number")]
    return data


def serialize_row(row: ListingOptimizationRow) -> Dict[str, Any]:
    display_number = max((row.row_number or DATA_START_ROW) - DATA_START_ROW + 1, 1)
    return {
        "id": row.id,
        "row_number": row.row_number,
        "display_number": display_number,
        "status": row.status,
        "status_display": row.get_status_display(),
        "source_data": row.source_data or {},
        "optimized_data": row.optimized_data or {},
        "error_message": row.error_message,
        "updated_at": row.updated_at.strftime("%Y-%m-%d %H:%M:%S") if row.updated_at else "",
    }
