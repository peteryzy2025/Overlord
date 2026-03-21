# 示例：带缓存的版本
from django.core.cache import cache

# 缓存配置
TERM_ID_LIST_CACHE_PREFIX = 'aba:term_ids:'
TERM_ID_LIST_CACHE_TTL = 300  # 5分钟

def _get_filtered_term_ids_with_cache(category='', search_term='', noise_status='all', search_mode='0'):
    """
    带缓存的版本：缓存符合条件的搜索词 ID 列表
    翻页时不需要重新计算正则过滤
    """
    # 构建缓存 key
    cache_key = f"{TERM_ID_LIST_CACHE_PREFIX}{category}:{noise_status}:{search_term}:{search_mode}"
    
    # 尝试从缓存读取
    cached_ids = cache.get(cache_key)
    if cached_ids is not None:
        print(f"[Cache Hit] {cache_key}, {len(cached_ids)} ids")
        return cached_ids
    
    # 缓存未命中，执行查询
    ids = _get_filtered_term_ids(category, search_term, noise_status, search_mode)
    
    # 存入缓存（即使为空列表也缓存，防止缓存穿透）
    cache.set(cache_key, ids, TERM_ID_LIST_CACHE_TTL)
    print(f"[Cache Miss] {cache_key}, cached {len(ids)} ids")
    
    return ids


def clear_term_id_cache(category='', noise_status='all'):
    """
    去噪操作后清除相关缓存
    """
    # 可以按前缀删除，或设置更短的过期时间
    # 简单方案：去噪操作后清除所有 aba:term_ids:* 缓存
    pass
