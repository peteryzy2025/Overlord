import logging
from datetime import datetime

import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("backfill_theme_novelty_summary_created_time")

DB_HOST = "192.168.110.54"
DB_PORT = "5432"
DB_NAME = "overlord_db"
DB_USER = "user1"
DB_PASS = "user555Y1"


def backfill_created_time():
    conn = None
    cursor = None
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
        )
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) FROM theme_novelty_summary
            WHERE created_time IS NULL
        """)
        missing_count = cursor.fetchone()[0]

        if missing_count == 0:
            logger.info("没有需要回填 created_time 的记录")
            return

        now = datetime.now()
        cursor.execute("""
            UPDATE theme_novelty_summary
            SET created_time = %s
            WHERE created_time IS NULL
        """, (now,))
        updated_count = cursor.rowcount
        conn.commit()

        logger.info(f"共发现 {missing_count} 条缺失 created_time 的记录，已回填 {updated_count} 条，回填时间: {now}")

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"回填失败: {e}")
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    backfill_created_time()
