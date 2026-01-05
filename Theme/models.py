from django.db import models


class AmazonProduct(models.Model):
    """固定数据 - 产品基本信息"""
    asin = models.CharField(max_length=10, primary_key=True, verbose_name='ASIN')  # ← 主键
    title = models.CharField(max_length=500, verbose_name='产品标题')
    title_translation = models.CharField(max_length=500, blank=True, verbose_name='标题翻译')
    subject = models.CharField(max_length=200, verbose_name='产品主题')
    subject_translation = models.CharField(max_length=200, blank=True, verbose_name='主题翻译')
    image_url = models.URLField(max_length=500, verbose_name='图片链接')
    launch_date = models.DateField(null=True, blank=True, verbose_name='上架时间')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='首次抓取时间')
    PRODUCT_TYPE_CHOICES = [
        ('new_peculiar', '新奇特'),
        ('new_arrival', '新品榜'),
    ]
    product_type = models.CharField(
        max_length=20,
        choices=PRODUCT_TYPE_CHOICES,
        verbose_name='产品类型'
    )
    class Meta:
        db_table = 'amazon_product'
        verbose_name = '亚马逊产品'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.asin} - {self.title[:50]}"


class ProductRankHistory(models.Model):
    """每日变化数据 - 排名历史"""
    product = models.ForeignKey(
        AmazonProduct,
        on_delete=models.CASCADE,
        related_name='rank_history',
        verbose_name='关联产品'
    )  # FK 会自动关联到 ASIN 主键
    crawl_date = models.DateField(verbose_name='爬取日期')
    rank = models.IntegerField(null=True, blank=True, verbose_name='当前排名')
    rank_category = models.CharField(max_length=100, blank=True, verbose_name='排名大类')
    crawled_at = models.DateTimeField(auto_now_add=True, verbose_name='抓取时间')

    class Meta:
        db_table = 'product_rank_history'
        indexes = [
            models.Index(fields=['product', 'crawl_date']),
            models.Index(fields=['crawl_date']),
        ]
        unique_together = ['product', 'crawl_date']
        verbose_name = '排名历史'
        verbose_name_plural = verbose_name

    def __str__(self):
        rank_display = self.rank if self.rank is not None else '暂无排名'
        return f"{self.product.asin} - {self.crawl_date} - 排名:{rank_display}"