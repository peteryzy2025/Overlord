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
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    is_latest_deal = models.BooleanField(default=False, verbose_name='是否为最新成交')
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
    rank_category = models.CharField(max_length=100, null=True,blank=True, verbose_name='排名大类')
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


#  下面是新的模型


class AmazonTheme(models.Model):
    """亚马逊主题，存放稳定的基础信息"""
    asin = models.CharField(max_length=10, primary_key=True, verbose_name='ASIN')
    title = models.CharField(max_length=500, verbose_name='产品标题')
    title_translation = models.CharField(max_length=500, blank=True, verbose_name='标题译文')
    subject = models.CharField(max_length=200, verbose_name='产品主题')
    subject_translation = models.CharField(max_length=200, blank=True, verbose_name='主题译文')
    image_url = models.URLField(max_length=500, verbose_name='图片链接')
    launch_date = models.DateField(null=True, blank=True, verbose_name='上架日期')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='首次入库时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    is_latest_deal = models.BooleanField(default=False, verbose_name='是否为最新成交')
    class Meta:
        db_table = 'theme_amazon'
        verbose_name = '亚马逊主题表'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.asin} - {self.title[:50]}"


class ThemeRecord(models.Model):
    """AI主题记录表，存放AI输出/推断的主题与风险数据"""
    product = models.ForeignKey(
        AmazonTheme,
        on_delete=models.CASCADE,
        related_name='ai_records',
        verbose_name='关联产品'
    )
    infringement_level = models.CharField(
        max_length=10,
        verbose_name='侵权等级(词库)'
    )
    infringement_words = models.JSONField(
        null=True,
        blank=True,
        verbose_name='侵权词列表(词库)'
    )
    ai_infringement_level = models.CharField(
        max_length=10,
        verbose_name='侵权等级(AI)'
    )
    ai_infringement_words = models.JSONField(
        null=True,
        blank=True,
        verbose_name='侵权词列表(AI)'
    )
    duplicate_count = models.IntegerField(default=1, verbose_name='重复数')
    record_date = models.DateField(verbose_name='生成日期')
    record_time = models.DateTimeField(verbose_name='生成时间')

    class Meta:
        db_table = 'theme_record'
        indexes = [
            models.Index(fields=['record_date']),
            models.Index(fields=['score']),
            models.Index(fields=['infringement_level']),
            models.Index(fields=['ai_infringement_level']),
        ]
        verbose_name = 'AI主题记录'
        verbose_name_plural = verbose_name

    def __str__(self):
        # 改为使用 product.subject，这个字段存在
        return f"{self.product.asin} - {self.product.subject[:30]}"

class ThemeDailyData(models.Model):
    """主题每日数据"""
    product = models.ForeignKey(
        AmazonTheme,
        on_delete=models.CASCADE,
        related_name='rank_history',
        verbose_name='关联产品'
    )
    crawl_date = models.DateField(verbose_name='抓取日期')
    rank = models.IntegerField(null=True, blank=True, verbose_name='排名')
    rank_category = models.CharField(max_length=100, null=True, blank=True, verbose_name='排名分类')
    crawled_at = models.DateTimeField(auto_now_add=True, verbose_name='抓取时间')
    appear_count = models.IntegerField(default=1, verbose_name='重复数')
    score = models.IntegerField(default=0, verbose_name='分值')
    class Meta:
        db_table = 'theme_daily_data'
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


class ThemeDailySubjectStat(models.Model):
    """当日主题汇总表，用于榜单/趋势统计 这个暂时不写入"""
    record_date = models.DateField(verbose_name='统计日期')
    subject_snapshot = models.CharField(max_length=200, verbose_name='主题')
    appear_count = models.IntegerField(default=0, verbose_name='出现次数')

    class Meta:
        db_table = 'theme_daily_subject_stat'
        unique_together = [('record_date', 'subject_snapshot')]
        indexes = [
            models.Index(fields=['record_date']),
            models.Index(fields=['record_date', 'subject_snapshot']),
        ]
        verbose_name = '当日主题统计'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.record_date} - {self.subject_snapshot[:30]}"
