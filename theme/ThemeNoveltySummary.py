import logging
from datetime import datetime

import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("theme_novelty_summary.log", mode="w", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("theme_novelty_summary")

DB_HOST = "192.168.110.54"
DB_PORT = "5432"
DB_NAME = "overlord_db"
DB_USER = "user1"
DB_PASS = "user555Y1"

SIMILARITY_THRESHOLD = 0.2


class DatabaseManager:
    def __init__(self):
        self.conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
        )
        self.cursor = self.conn.cursor()

    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def sync_novelty_summary_subjects(self):
        try:
            self.cursor.execute("""
                SELECT subject_translation, COUNT(*) as cnt
                FROM theme_amazon_novelty
                WHERE theme_novelty_summary_id IS NULL
                  AND subject_translation IS NOT NULL
                  AND subject_translation != ''
                GROUP BY subject_translation
            """)
            orphans = self.cursor.fetchall()

            if not orphans:
                logger.info("没有发现新的待分类主题")
                return 0

            updated_count = 0
            for row in orphans:
                text = row[0]

                self.cursor.execute("""
                    SELECT id FROM theme_novelty_summary
                    WHERE similarity(summary_subject_title, %s) > %s
                    ORDER BY similarity(summary_subject_title, %s) DESC
                    LIMIT 1
                """, (text, SIMILARITY_THRESHOLD, text))
                match = self.cursor.fetchone()

                if match:
                    target_id = match[0]
                    logger.debug(f"匹配成功: '{text}' -> ID {target_id}")
                else:
                    self.cursor.execute("""
                        INSERT INTO theme_novelty_summary (summary_subject_title, created_time)
                        VALUES (%s, %s) RETURNING id
                    """, (text, datetime.now()))
                    result = self.cursor.fetchone()
                    target_id = result[0]
                    logger.info(f"新建主题: '{text}' (ID {target_id})")

                self.cursor.execute("""
                    UPDATE theme_amazon_novelty
                    SET theme_novelty_summary_id = %s
                    WHERE subject_translation = %s AND theme_novelty_summary_id IS NULL
                """, (target_id, text))
                updated_count += self.cursor.rowcount

            self.commit()
            logger.info(f"主题归类完成，共处理 {len(orphans)} 个主题，更新 {updated_count} 条记录")
            return updated_count

        except Exception as e:
            self.rollback()
            logger.error(f"主题归类失败: {e}")
            raise


def main():
    db_manager = DatabaseManager()
    try:
        logger.info("开始新奇特主题归类...")
        db_manager.sync_novelty_summary_subjects()
    finally:
        db_manager.close()


if __name__ == "__main__":
    main()
