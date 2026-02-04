-- 创建 amazon_listing_tro_words 中间表（ManyToMany关系）
CREATE TABLE IF NOT EXISTS amazon_listing_tro_words (
    id BIGSERIAL PRIMARY KEY,
    amazonlisting_id BIGINT NOT NULL REFERENCES amazon_listing(id) ON DELETE CASCADE,
    trotable_id INTEGER NOT NULL REFERENCES theme_tro_table(id) ON DELETE CASCADE,
    CONSTRAINT uniq_listing_tro UNIQUE (amazonlisting_id, trotable_id)
);

-- 创建索引
CREATE INDEX idx_tro_words_listing_id ON amazon_listing_tro_words(amazonlisting_id);
CREATE INDEX idx_tro_words_tro_id ON amazon_listing_tro_words(trotable_id);

COMMENT ON TABLE amazon_listing_tro_words IS 'AmazonListing 与 TroTable 的多对多关系中间表';
