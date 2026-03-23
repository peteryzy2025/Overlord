-- PostgreSQL GIN 索引优化（用于正则搜索）
-- 执行前请确保已安装 pg_trgm 扩展

-- 1. 启用 pg_trgm 扩展（如果未启用）
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. 在 SearchTerm.term 上创建 GIN 索引（加速正则/模糊搜索）
-- 注意：这个索引会占用额外存储空间，但能极大加速 LIKE/正则查询
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_search_terms_term_gin 
ON search_terms USING GIN (term gin_trgm_ops);

-- 3. 如果品类查询频繁，考虑添加品类标记字段
-- 添加 category 字段到 search_terms（如果清洗时已知品类）
ALTER TABLE search_terms ADD COLUMN IF NOT EXISTS category VARCHAR(100);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_search_terms_category 
ON search_terms(category) WHERE category IS NOT NULL;

-- 4. 复合索引优化（去噪+搜索词）
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_search_terms_denoising_term 
ON search_terms(denoising, term text_pattern_ops);

-- 验证索引
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE tablename = 'search_terms';
