"""
Django Management Command: run_novelty_clustering
================================================
从散装 ASIN 标题提取指纹并进行拓扑聚类的全链路命令 (新奇特数据)。

用法:
    # 增量模式 (只处理未关联指纹的 ASIN)
    python manage.py run_novelty_clustering

    # 全量重建模式
    python manage.py run_novelty_clustering --reset

    # 自定义参数
    python manage.py run_novelty_clustering --pmi-threshold=4.0 --jaccard-threshold=0.55
"""

from django.core.management.base import BaseCommand

from theme.novelty_subject_cluster import AmazonNoveltyClusteringPipeline


class Command(BaseCommand):
    help = "从散装 ASIN 标题提取指纹并进行拓扑聚类 (新奇特数据)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            default=False,
            help="全量重建模式: 清空所有指纹与聚类, 从头开始",
        )
        parser.add_argument(
            "--pmi-threshold",
            type=float,
            default=3.0,
            help="N-Gram PMI 阈值 (默认: 3.0)",
        )
        parser.add_argument(
            "--min-freq",
            type=int,
            default=5,
            help="N-Gram 最低频次 (默认: 5)",
        )
        parser.add_argument(
            "--jaccard-threshold",
            type=float,
            default=0.55,
            help="Jaccard 相似度阈值 (默认: 0.55)",
        )
        parser.add_argument(
            "--core-tag-count",
            type=int,
            default=5,
            help="每个指纹提取的 Core Tag 数量 (默认: 5)",
        )
        parser.add_argument(
            "--min-intersection",
            type=int,
            default=3,
            help="交集最低词数门槛 (默认: 3)",
        )
        parser.add_argument(
            "--idf-threshold",
            type=float,
            default=1.0,
            help="交集词最低 IDF 门槛 (默认: 1.0)",
        )

    def handle(self, *args, **options):
        pipeline = AmazonNoveltyClusteringPipeline(
            pmi_threshold=options["pmi_threshold"],
            min_freq=options["min_freq"],
            jaccard_threshold=options["jaccard_threshold"],
            core_tag_count=options["core_tag_count"],
            min_intersection=options["min_intersection"],
            idf_threshold=options["idf_threshold"],
        )
        pipeline.run(reset=options["reset"])

        mode = "全量重建" if options["reset"] else "增量"
        self.stdout.write(
            self.style.SUCCESS(f"新奇特主题聚类 Pipeline 执行完成 ({mode} 模式)")
        )
