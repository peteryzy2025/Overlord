import logging

import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("fix_summary_created_time")

DB_HOST = "192.168.110.54"
DB_PORT = "5432"
DB_NAME = "overlord_db"
DB_USER = "user1"
DB_PASS = "user555Y1"


def main():
    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, database=DB_NAME, user=DB_USER, password=DB_PASS
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM theme_summary WHERE created_time IS NULL
                """
            )
            null_count = cur.fetchone()[0]
            logger.info(f"created_time 为 NULL 的主题数量: {null_count}")

            if null_count == 0:
                logger.info("无需修复")
                return

            cur.execute(
                """
                UPDATE theme_summary s
                SET created_time = sub.earliest_at
                FROM (
                    SELECT summary_subject_id, MIN(created_at) AS earliest_at
                    FROM theme_amazon_new_release_rank
                    WHERE summary_subject_id IS NOT NULL
                    GROUP BY summary_subject_id
                ) sub
                WHERE s.created_time IS NULL
                  AND s.id = sub.summary_subject_id
                """
            )
            updated = cur.rowcount
            conn.commit()
            logger.info(f"修复完成，共更新 {updated} 条记录")

            cur.execute(
                """
                SELECT COUNT(*) FROM theme_summary WHERE created_time IS NULL
                """
            )
            remaining = cur.fetchone()[0]
            if remaining > 0:
                logger.warning(
                    f"仍有 {remaining} 条记录 created_time 为 NULL（无关联ASIN）"
                )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
