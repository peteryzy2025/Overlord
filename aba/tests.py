"""
ABA 分区表生成脚本

功能：为 search_term_metrics 表生成按周分区的 SQL 文件

注意：
- 生成 260 个周分区（2022-01-02 到 2026-12-27）
- 查询时限定 report_week 条件，PostgreSQL 会自动只查对应分区
- 建议用命令行执行生成的 SQL，不要用 Navicat（可能会卡）

执行方式：
    python aba/tests.py
    
然后在 psql 中执行：
    psql -h 192.168.110.54 -U track -d aba_db -f create_partitions.sql
"""

import datetime


def generate_partition_sql():
    """生成分区表的 SQL 文件"""
    
    # 配置
    start_date = datetime.date(2022, 1, 2)   # 2022年第一个周日
    end_date = datetime.date(2026, 12, 27)   # 2026年最后一个周日
    output_file = "create_partitions.sql"

    sql_lines = []

    # 主表创建语句
    sql_lines.append("""
-- ============================================
-- ABA 搜索词指标表 - 按周分区
-- 生成时间：{timestamp}
-- 分区范围：{start} 至 {end}（共 {weeks} 周）
-- ============================================

-- 创建主表（分区表）
CREATE TABLE IF NOT EXISTS search_term_metrics (
    id BIGSERIAL,
    report_week DATE NOT NULL,
    search_term_id INTEGER NOT NULL REFERENCES search_terms(id),
    search_frequency_rank INTEGER NOT NULL,

    asin_1_code VARCHAR(20) NOT NULL,
    asin_1_title TEXT NOT NULL,
    asin_1_click_share NUMERIC(6,4) NOT NULL,
    asin_1_conversion_share NUMERIC(6,4) NOT NULL,

    asin_2_code VARCHAR(20),
    asin_2_title TEXT,
    asin_2_click_share NUMERIC(6,4),
    asin_2_conversion_share NUMERIC(6,4),

    asin_3_code VARCHAR(20),
    asin_3_title TEXT,
    asin_3_click_share NUMERIC(6,4),
    asin_3_conversion_share NUMERIC(6,4),

    last_week_rank INTEGER,
    rank_change INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),

    PRIMARY KEY (id, report_week)
) PARTITION BY RANGE (report_week);

-- 在父表创建索引（自动应用到所有分区）
CREATE INDEX IF NOT EXISTS idx_metrics_week_rank ON search_term_metrics (report_week, search_frequency_rank);
CREATE INDEX IF NOT EXISTS idx_metrics_term_week ON search_term_metrics (search_term_id, report_week);
CREATE INDEX IF NOT EXISTS idx_metrics_asin1 ON search_term_metrics (asin_1_code, report_week);

-- 联合唯一约束：防止同一周同一搜索词重复导入
CREATE UNIQUE INDEX IF NOT EXISTS unique_week_term ON search_term_metrics (report_week, search_term_id);

-- ============================================
-- 周分区列表
-- ============================================
""".format(
        timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        start=start_date,
        end=end_date,
        weeks=((end_date - start_date).days // 7) + 1
    ))

    # 生成每周分区
    current = start_date
    week_count = 0
    year_weeks = {}  # 按年统计

    while current <= end_date:
        next_week = current + datetime.timedelta(days=7)
        partition_name = f"search_term_metrics_{current.strftime('%Y%m%d')}"
        year = current.year

        # 统计每年的分区数
        if year not in year_weeks:
            year_weeks[year] = 0
        year_weeks[year] += 1

        # 每年开头加注释
        if year_weeks[year] == 1:
            sql_lines.append(f"\n-- {year} 年\n")

        sql_lines.append(f"CREATE TABLE IF NOT EXISTS {partition_name} PARTITION OF search_term_metrics FOR VALUES FROM ('{current}') TO ('{next_week}');")

        week_count += 1
        current = next_week

    # 文件尾注释
    sql_lines.append(f"""

-- ============================================
-- 完成
-- 共生成 {week_count} 个分区
-- {chr(10).join([f"--   {year} 年：{count} 个分区" for year, count in sorted(year_weeks.items())])}
-- ============================================
""")

    # 写入文件
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(sql_lines))

    print(f"✅ 已生成 {week_count} 个分区")
    print(f"   {start_date} 至 {end_date}")
    print()
    print("按年统计：")
    for year, count in sorted(year_weeks.items()):
        print(f"   {year} 年：{count} 个分区")
    print()
    print(f"📄 SQL 文件：{output_file}")
    print(f"📊 总行数：约 {len(sql_lines)} 行")
    print()
    print("⚠️  执行建议：")
    print("   psql -h 192.168.110.54 -U track -d aba_db -f create_partitions.sql")
    print()
    print("📝 注意：")
    print("   - 确保 search_terms 表已创建（外键依赖）")
    print("   - 执行时间约 30-60 秒（260 个分区）")
    print("   - 不建议用 Navicat 执行，可能会卡死")


if __name__ == "__main__":
    # 验证 start_date 是周日
    start_date = datetime.date(2022, 1, 2)
    if start_date.strftime("%A") != "Sunday":
        print(f"⚠️  警告：{start_date} 不是周日，而是 {start_date.strftime('%A')}")
        print("   请检查分区起始日期是否正确")
    else:
        generate_partition_sql()
