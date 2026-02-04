#!/usr/bin/env python
"""
修复 amazon_listing_tro_words 中间表缺失问题
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Overlord.settings')
django.setup()

from django.db import connection, transaction

def fix_tro_words_table():
    """创建 amazon_listing_tro_words 中间表"""
    
    sql = """
    -- 创建 amazon_listing_tro_words 中间表（ManyToMany关系）
    CREATE TABLE IF NOT EXISTS amazon_listing_tro_words (
        id BIGSERIAL PRIMARY KEY,
        amazonlisting_id BIGINT NOT NULL REFERENCES amazon_listing(id) ON DELETE CASCADE,
        trotable_id INTEGER NOT NULL REFERENCES theme_tro_table(id) ON DELETE CASCADE,
        CONSTRAINT uniq_listing_tro UNIQUE (amazonlisting_id, trotable_id)
    );

    -- 创建索引
    CREATE INDEX IF NOT EXISTS idx_tro_words_listing_id ON amazon_listing_tro_words(amazonlisting_id);
    CREATE INDEX IF NOT EXISTS idx_tro_words_tro_id ON amazon_listing_tro_words(trotable_id);

    COMMENT ON TABLE amazon_listing_tro_words IS 'AmazonListing 与 TroTable 的多对多关系中间表';
    """
    
    with connection.cursor() as cursor:
        # 检查表是否存在
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'amazon_listing_tro_words'
            );
        """)
        table_exists = cursor.fetchone()[0]
        
        if table_exists:
            print("✓ amazon_listing_tro_words 表已存在")
            return
        
        print("× amazon_listing_tro_words 表不存在，正在创建...")
        cursor.execute(sql)
        print("✓ 表创建成功！")

if __name__ == '__main__':
    fix_tro_words_table()
