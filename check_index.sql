-- 检查 search_terms 表的索引是否创建成功
-- 方法1：查看表的所有索引
SELECT 
    indexname AS 索引名称,
    indexdef AS 索引定义
FROM pg_indexes 
WHERE tablename = 'search_terms'
ORDER BY indexname;

-- 方法2：查看特定索引是否存在（更精确）
SELECT 
    tablename AS 表名,
    indexname AS 索引名,
    CASE 
        WHEN indexdef LIKE '%USING btree%' THEN 'B-tree索引'
        WHEN indexdef LIKE '%USING gin%' THEN 'GIN索引'
        ELSE '其他类型'
    END AS 索引类型
FROM pg_indexes 
WHERE tablename = 'search_terms' 
  AND indexname LIKE '%category%';

-- 方法3：查看索引大小（确认索引已生效）
SELECT
    relname AS 索引名称,
    pg_size_pretty(pg_relation_size(oid)) AS 索引大小
FROM pg_class
WHERE relname LIKE 'category_denoising_idx%'
   OR relname LIKE 'denoising_category_idx%'
   OR relname LIKE 'search_terms%idx%';

-- 方法4：测试查询是否走索引（关键！）
EXPLAIN ANALYZE
SELECT id FROM search_terms 
WHERE category = 'shirt' AND denoising = false;
-- 如果看到 "Index Scan" 或 "Bitmap Index Scan" 就说明索引起效了
-- 如果看到 "Seq Scan" 说明是全表扫描，索引没用到
