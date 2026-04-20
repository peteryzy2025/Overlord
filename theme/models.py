from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver


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
    rank_category = models.CharField(max_length=100, null=True, blank=True, verbose_name='排名大类')
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

#=============尝试新的聚类算法（新奇特）=======================
class AmazonThemeClusterNovelty(models.Model):
    """
    第三层：主题聚类层 (The "Master" Themes)
    代表最终的业务概念
    """
    display_title = models.CharField(max_length=500, verbose_name="展示标题")
    core_tags = models.JSONField(default=list, help_text="算法提取的核心特征词",verbose_name='核心词')

    # 统计信息，方便在 Admin 后台查看规模
    fingerprint_count = models.IntegerField(default=0,verbose_name='聚类主题下Fingerprint数')
    asin_count = models.IntegerField(default=0,verbose_name='聚类主题下ASIN数')
    burst_score = models.FloatField(default=0.0, verbose_name="爆发指数",null=True,blank=True) #launch_date <= 7d ASIN数 / 该Cluster下的ASIN总数
    new_asin_7d = models.IntegerField(default=0, verbose_name="7天内新上架数",null=True,blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'theme_novelty_cluster'
        verbose_name = "新奇特主题聚类"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.display_title

class ThemeFingerprintNovelty(models.Model):
    """
    第二层：指纹层 (Normalized Fingerprints)
    处理字面完全一致的情况，消灭大小写、缩写差异。
    """
    # 归一化后的字符串唯一索引，如 "am i jesus project ..."
    fingerprint_key = models.CharField(max_length=500, unique=True, db_index=True,verbose_name='指纹')

    # 该指纹组下最具有代表性的原始文本（用于自动给 Cluster 命名）
    representative_title = models.CharField(max_length=500,verbose_name='代表性标题')

    # 关联到大主题，如果为 Null，逻辑上视为待分配或孤儿
    cluster = models.ForeignKey(
        AmazonThemeClusterNovelty,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='cluster_theme_novelty',
        verbose_name = '聚合标题'
    )

    asin_count = models.IntegerField(default=0)
    class Meta:
        db_table = 'theme_novelty_fingerprint'
        verbose_name = '新奇特主题聚合指纹'

    def __str__(self):
        return f"FingerPrint: {self.representative_title[:50]}"


class AmazonThemeNovelty(models.Model):
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

    # 关联到新奇特主题（新增字段）
    theme_novelty = models.ForeignKey(
        'ThemeNovelty',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='asins',
        verbose_name='所属新奇特主题'
    )
    theme_novelty_summary = models.ForeignKey(
        'ThemeNoveltySummary',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='summary_subject',
        verbose_name='所属新奇特聚合主题'
    )
    fingerprint = models.ForeignKey(
        'ThemeFingerprintNovelty',
        on_delete=models.SET_NULL,
        related_name='fingerprint_novelty',
        verbose_name='关联指纹',
        null=True,
        blank=True,
    )


    class Meta:
        db_table = 'theme_amazon_novelty'
        verbose_name = '亚马逊主题表'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.asin} - {self.title[:50]}"


class ThemeRecord(models.Model):
    """AI主题记录表，存放AI输出/推断的主题与风险数据"""
    product = models.ForeignKey(
        AmazonThemeNovelty,
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
    record_date = models.DateField(verbose_name='生成日期')
    record_time = models.DateTimeField(verbose_name='生成时间')

    class Meta:
        db_table = 'theme_record'
        indexes = [
            models.Index(fields=['record_date']),
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
        AmazonThemeNovelty,
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


class ThemeTrashBin(models.Model):
    asin = models.CharField(max_length=10, primary_key=True, verbose_name='ASIN')

    class Meta:
        db_table = "theme_trash_bin"

    def __str__(self):
        return self.asin


# ---------------------------

class StatusCodeMapping(models.Model):
    """商标状态码映射表"""
    status_code = models.CharField(max_length=50, verbose_name='商标状态码', primary_key=True)
    status_type = models.CharField(max_length=50, verbose_name='商标状态类型')

    class Meta:
        db_table = 'theme_status_code_mapping'
        verbose_name = '商标状态码映射'

        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.status_code} - {self.status_type}"


class MarkDrawingTypeMapping(models.Model):
    """商标绘制类型映射表"""
    code = models.CharField(max_length=50, verbose_name='商标绘制类型码', primary_key=True)
    description_en = models.CharField(max_length=255, verbose_name='商标绘制类型英文描述')
    description_cn = models.CharField(max_length=255, verbose_name='商标绘制类型中文描述')

    class Meta:
        db_table = 'theme_mark_drawing_type_mapping'
        verbose_name = '商标绘制类型映射'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.code} - {self.description_en} - {self.description_cn}"


class EntityTypeMapping(models.Model):
    """法律实体类型映射表"""
    code = models.CharField(max_length=50, verbose_name='法律实体类型码', primary_key=True)
    description = models.CharField(max_length=100, verbose_name='法律实体类型描述')

    class Meta:
        db_table = 'theme_entity_type_mapping'
        verbose_name = '法律实体类型映射'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.code} - {self.description}"


# =====================================侵权词表===================================#

class TroTable(models.Model):
    """侵权词表,用于判断高/低风险"""
    id = models.AutoField(primary_key=True, verbose_name='ID')
    theme_name = models.CharField(max_length=765, verbose_name='侵权词名', unique=True)
    replacement_word = models.CharField(
        max_length=765,
        verbose_name='建议替换词',
        null=True,
        blank=True,
        help_text='检测到侵权时建议使用的替代词汇'
    )
    name_type = models.IntegerField(verbose_name='侵权类型码', null=True, blank=True)
    international_classes = models.ManyToManyField(
        'NiceClassification',
        related_name='tro_words',
        verbose_name='所属国际类',
        blank=True,
        db_table='theme_tro_nice_classification'  # 自定义中间表名，避免自动生成太长
    )
    shop = models.ForeignKey(
        'general.AmazonShop',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tro_words',  # 反向查询：shop.tro_words.all()
        verbose_name='所属店铺'
    )

    class Category(models.IntegerChoices):
        TEXT = 1, '文字侵权'
        COPYRIGHT = 2, '版权侵权'

    category = models.IntegerField(
        verbose_name='侵权分类',
        choices=Category.choices,  # type: ignore
        null=True, blank=True
    )
    create_time = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    update_time = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    creator = models.ForeignKey(
        'general.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_tro_words',
        verbose_name='创建人'
    )

    class Meta:
        db_table = 'theme_tro_table'
        indexes = [
            models.Index(fields=['theme_name']),
            models.Index(fields=['name_type']),
            models.Index(fields=['theme_name', 'name_type']),
        ]
        verbose_name = '侵权词表'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.theme_name} - {self.name_type}"


class TrademarkInfo(models.Model):
    """美标网商标信息表，用于判断中风险"""
    serial_number = models.CharField(max_length=10, verbose_name='商标注册号', primary_key=True)
    word_mark = models.CharField(max_length=525, verbose_name='侵权词')
    registration_number = models.CharField(max_length=100, verbose_name='注册号', null=True, blank=True)
    filing_date = models.DateField(verbose_name='入库时间', auto_now_add=True, null=True, blank=True)
    registration_date = models.DateField(verbose_name='注册日期', null=True, blank=True)
    transaction_date = models.DateField(verbose_name='交易日期', null=True, blank=True)
    status_code = models.ForeignKey(
        StatusCodeMapping,
        to_field='status_code',
        db_column='status_code',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='trademarks',
        verbose_name='商标状态码'
    )  # 迁移时需要修改字段类型
    intl_class = models.CharField(max_length=500, verbose_name='国际类', null=True, blank=True)
    mark_drawing_type = models.ForeignKey(
        MarkDrawingTypeMapping,
        on_delete=models.PROTECT,
        to_field='code',
        db_column='mark_drawing_type',
        null=True,
        blank=True,
        related_name='trademarks',
        verbose_name='商标绘制类型'
    )
    owner_name = models.CharField(max_length=525, verbose_name='商标所有者', null=True, blank=True)
    legal_entity_type = models.ForeignKey(
        EntityTypeMapping,
        to_field='code',
        db_column='legal_entity_type',
        on_delete=models.PROTECT,
        related_name='trademark_entities',
        verbose_name='法律实体类型',
        null=True,
        blank=True
    )
    entity_statement = models.CharField(max_length=500, verbose_name='法律实体声明', null=True, blank=True)

    class Meta:
        db_table = 'theme_trademark_info'
        indexes = [
            models.Index(fields=['word_mark', 'status_code']),
            models.Index(fields=['word_mark', 'mark_drawing_type', 'status_code']),
        ]
        verbose_name = '美标网表'
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.word_mark} - {self.status_code} - {self.mark_drawing_type}"


class ThemeReport(models.Model):
    """主题举报记录表"""
    product = models.ForeignKey(
        AmazonThemeNovelty,
        on_delete=models.CASCADE,
        related_name='theme_reports',
        verbose_name='商品ASIN'
    )
    reporter = models.ForeignKey(
        'general.User',
        on_delete=models.SET_NULL,
        null=True,
        related_name='theme_reports',
        verbose_name='举报人'
    )
    is_active = models.BooleanField(default=True, verbose_name='是否有效')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='举报时间')

    class Meta:
        db_table = 'theme_reports'
        verbose_name = '主题举报记录'
        verbose_name_plural = verbose_name
        unique_together = ['product', 'reporter']  # 每个用户对每个产品只能举报一次
        indexes = [
            models.Index(fields=['product', 'is_active']),
            models.Index(fields=['reporter', 'is_active']),
        ]

    def __str__(self):
        return f"{self.product.asin} - {self.reporter.first_name if self.reporter else 'Unknown'}"


class NiceClassification(models.Model):
    """
    尼斯分类（商标国际分类）- 共45类
    01-34类为商品，35-45类为服务
    """
    code = models.CharField(
        max_length=2,
        primary_key=True,
        verbose_name='分类编号',
        help_text='01-45，带前导零'
    )
    name = models.CharField(
        max_length=100,
        verbose_name='分类名称'
    )
    category_type = models.CharField(
        max_length=10,
        choices=[('goods', '商品'), ('service', '服务')],
        verbose_name='类型',
        db_index=True
    )

    class Meta:
        db_table = 'theme_nice_classification'
        verbose_name = '尼斯分类'
        verbose_name_plural = verbose_name
        ordering = ['code']

    def __str__(self):
        return f"{self.code}类：{self.name}"

    def save(self, *args, **kwargs):
        # 自动判断商品/服务类型
        if int(self.code) <= 34:
            self.category_type = 'goods'
        else:
            self.category_type = 'service'
        super().save(*args, **kwargs)


class MarketCategory(models.Model):
    """市场分类树"""
    name = models.CharField(max_length=255, verbose_name="分类名称")
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        verbose_name="父分类"
    )
    level = models.PositiveSmallIntegerField(default=1, verbose_name="层级")
    path = models.CharField(max_length=500, blank=True, verbose_name="路径ID链", db_index=True)

    class Meta:
        db_table = 'theme_market_category'
        unique_together = [['name', 'parent']]
        indexes = [
            models.Index(fields=['path']),
        ]
        verbose_name = "市场分类"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{'›' * self.level} {self.name}"


class NicheMarket(models.Model):
    """细分市场数据"""
    market_name = models.CharField(max_length=255, verbose_name="细分市场名称")
    market_name_cn = models.CharField(max_length=255, blank=True, verbose_name="中文翻译")
    monthly_sales = models.BigIntegerField(null=True, blank=True, verbose_name="月总销量")
    monthly_revenue = models.DecimalField(
        max_digits=15, decimal_places=2,
        null=True, blank=True,
        verbose_name="月均销售额"
    )
    leaf_category = models.ForeignKey(
        MarketCategory,
        on_delete=models.CASCADE,
        related_name='niche_markets',
        verbose_name="所属叶子分类"
    )

    class Meta:
        db_table = 'theme_niche_market'
        unique_together = [['market_name', 'leaf_category']]
        verbose_name = "细分市场"
        verbose_name_plural = verbose_name

    def __str__(self):
        return f"{self.market_name_cn or self.market_name}"



#=============尝试新的聚类算法(新品榜)=======================
class AmazonThemeCluster(models.Model):
    """
    第三层：主题聚类层 (The "Master" Themes)
    代表最终的业务概念，如 "USA 250th Anniversary" 或 "Folk Art Bird"
    """
    display_title = models.CharField(max_length=500, verbose_name="展示标题")
    core_tags = models.JSONField(default=list, help_text="算法提取的核心特征词, 如 ['1776', '250th']",verbose_name='核心词')

    # 统计信息，方便在 Admin 后台查看规模
    fingerprint_count = models.IntegerField(default=0,verbose_name='聚类主题下Fingerprint数')
    asin_count = models.IntegerField(default=0,verbose_name='聚类主题下ASIN数')
    burst_score = models.FloatField(default=0.0, verbose_name="爆发指数",null=True,blank=True) #launch_date <= 7d ASIN数 / 该Cluster下的ASIN总数
    new_asin_7d = models.IntegerField(default=0, verbose_name="7天内新上架数",null=True,blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'theme_new_release_cluster'
        verbose_name = "新品榜主题聚类"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.display_title




class ThemeFingerprint(models.Model):
    """
    第二层：指纹层 (Normalized Fingerprints)
    处理字面完全一致的情况，消灭大小写、缩写差异。
    """
    # 归一化后的字符串唯一索引，如 "am i jesus project ..."
    fingerprint_key = models.CharField(max_length=500, unique=True, db_index=True,verbose_name='指纹')

    # 该指纹组下最具有代表性的原始文本（用于自动给 Cluster 命名）
    representative_title = models.CharField(max_length=500,verbose_name='代表性标题')

    # 关联到大主题，如果为 Null，逻辑上视为待分配或孤儿
    cluster = models.ForeignKey(
        AmazonThemeCluster,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='cluster_theme',
        verbose_name = '聚合标题'
    )

    asin_count = models.IntegerField(default=0)
    class Meta:
        db_table = 'theme_new_release_fingerprint'

    def __str__(self):
        return f"FingerPrint: {self.representative_title[:50]}"


class AmazonNewReleaseRank(models.Model):
    """亚马逊新品榜主题，存放稳定的基础信息"""

    class Fulfillment(models.TextChoices):
        AMZ = "AMZ"
        FBA = "FBA"
        FBM = "FBM"

    asin = models.CharField(max_length=10, primary_key=True, verbose_name='ASIN')
    title = models.CharField(max_length=500, verbose_name='产品标题')
    title_translation = models.CharField(max_length=500, blank=True, verbose_name='标题译文')
    subject = models.CharField(max_length=200, verbose_name='产品主题')
    subject_translation = models.CharField(max_length=200, blank=True, verbose_name='主题译文')
    category = models.CharField(max_length=100, db_index=True, verbose_name="产品分类")
    image_url = models.URLField(max_length=500, verbose_name='图片链接')
    launch_date = models.DateField(null=True, blank=True, verbose_name='上架日期')
    summary_subject = models.ForeignKey(
        'ThemeSummary',
        models.SET_NULL,
        null=True,
        blank=True,
        related_name='summary_subject',
        verbose_name='汇总主题'
    )

    fingerprint = models.ForeignKey(
        ThemeFingerprint,
        on_delete=models.SET_NULL,
        related_name='fingerprint',
        verbose_name='关联指纹',
        null=True,
        blank=True,
    )
    report = models.BooleanField(default=False, verbose_name='举报ASIN')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='首次入库时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    denoising = models.BooleanField(default=False, verbose_name='是否去噪', db_index=True)
    fulfillment = models.CharField(max_length=10,
                                   choices=Fulfillment.choices,  # type:ignore
                                   null=True,
                                   blank=True,
                                   verbose_name="配送方式")


    class Meta:
        db_table = 'theme_amazon_new_release_rank'
        verbose_name = '亚马逊新品榜主题表'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['fulfillment']),
        ]

    def __str__(self):
        return f"{self.asin} - {self.title[:50]}"


class ThemeSummary(models.Model):
    id = models.AutoField(primary_key=True, verbose_name='ID')
    summary_subject_title = models.CharField(max_length=525, verbose_name='汇总主题', unique=True)
    report = models.BooleanField(default=False, verbose_name='举报主题')  # 目前不用
    created_time = models.DateTimeField(null=True, blank=True, verbose_name='创建时间', db_index=True)

    class Meta:
        db_table = 'theme_summary'
        verbose_name = '主题汇总'
        indexes = [
            models.Index(fields=['summary_subject_title']),
        ]

    def __str__(self):
        return f'{self.summary_subject_title}'


class NewReleaseThemeReport(models.Model):
    reporter = models.ForeignKey(
        'general.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='new_release_theme_reports',
        verbose_name='举报人'
    )
    theme = models.ForeignKey(
        'ThemeSummary',
        on_delete=models.CASCADE,
        related_name='new_release_theme_reports',
        verbose_name='被举报主题',
        db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='举报时间')

    class Meta:
        db_table = 'theme_new_release_theme_report'
        verbose_name = '新品榜主题举报记录'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['reporter', 'theme'],
                name='uniq_new_release_theme_report'
            ),
        ]
        indexes = [
            models.Index(fields=['theme']),
            models.Index(fields=['reporter', 'created_at']),
        ]
        ordering = ['-created_at']

    def clean(self):
        if not self.theme_id:
            raise ValidationError('必须选择举报主题')
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values('reporter_id', 'theme_id').first()
            if previous and (
                    previous['reporter_id'] != self.reporter_id or
                    previous['theme_id'] != self.theme_id
            ):
                raise ValidationError('主题举报记录创建后不可修改，请删除后重新创建')

    def save(self, *args, **kwargs):
        is_create = self._state.adding
        self.clean()
        super().save(*args, **kwargs)

        if is_create:
            NewReleaseAsinReport.sync_for_theme_report(self)

    @classmethod
    def is_reported_by(cls, theme, reporter):
        if not theme or not reporter:
            return False
        return cls.objects.filter(reporter=reporter, theme=theme).exists()

    def __str__(self):
        reporter_name = self.reporter or '未知用户'
        return f"{reporter_name} 举报主题:{self.theme.summary_subject_title[:20]}"




class NewReleaseAsinReport(models.Model):
    reporter = models.ForeignKey(
        'general.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='new_release_asin_reports',
        verbose_name='举报人'
    )
    asin = models.ForeignKey(
        'AmazonNewReleaseRank',
        on_delete=models.CASCADE,
        related_name='new_release_asin_reports',
        verbose_name='被举报ASIN',
        db_index=True
    )
    source_theme_report = models.ForeignKey(
        'NewReleaseThemeReport',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='asin_reports',
        verbose_name='来源主题举报'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='举报时间')

    class Meta:
        db_table = 'theme_new_release_asin_report'
        verbose_name = '新品榜ASIN举报记录'
        verbose_name_plural = verbose_name
        constraints = [
            models.UniqueConstraint(
                fields=['reporter', 'asin'],
                condition=models.Q(source_theme_report__isnull=True),
                name='uniq_new_release_manual_asin_report'
            ),
            models.UniqueConstraint(
                fields=['source_theme_report', 'asin'],
                condition=models.Q(source_theme_report__isnull=False),
                name='uniq_new_release_theme_derived_asin_report'
            ),
        ]
        indexes = [
            models.Index(fields=['asin']),
            models.Index(fields=['source_theme_report']),
            models.Index(fields=['reporter', 'created_at']),
        ]
        ordering = ['-created_at']

    def clean(self):
        if not self.asin_id:
            raise ValidationError('必须选择举报ASIN')

        if self.source_theme_report_id:
            if self.reporter_id and self.reporter_id != self.source_theme_report.reporter_id:
                raise ValidationError('来源主题举报人与ASIN举报人不一致')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    @classmethod
    def sync_for_theme_report(cls, theme_report):
        if not theme_report.reporter_id or not theme_report.theme_id:
            return 0

        asin_ids = list(
            AmazonNewReleaseRank.objects.filter(summary_subject_id=theme_report.theme_id)
            .values_list('asin', flat=True)
        )
        if not asin_ids:
            return 0

        reports_to_create = [
            cls(
                reporter_id=theme_report.reporter_id,
                asin_id=asin_id,
                source_theme_report=theme_report,
            )
            for asin_id in asin_ids
        ]
        cls.objects.bulk_create(reports_to_create, ignore_conflicts=True)
        return len(reports_to_create)

    @classmethod
    def sync_for_asin(cls, asin, previous_theme_id=None):
        current_theme_id = asin.summary_subject_id

        if previous_theme_id and previous_theme_id != current_theme_id:
            cls.objects.filter(
                asin=asin,
                source_theme_report__theme_id=previous_theme_id,
            ).delete()

        if not current_theme_id:
            return 0

        theme_reports = list(
            NewReleaseThemeReport.objects.filter(theme_id=current_theme_id)
            .exclude(reporter__isnull=True)
            .values('id', 'reporter_id')
        )
        if not theme_reports:
            return 0

        reports_to_create = [
            cls(
                reporter_id=theme_report['reporter_id'],
                asin=asin,
                source_theme_report_id=theme_report['id'],
            )
            for theme_report in theme_reports
        ]
        cls.objects.bulk_create(reports_to_create, ignore_conflicts=True)
        return len(reports_to_create)

    @classmethod
    def rebuild_for_theme(cls, theme_id):
        if not theme_id:
            return 0

        cls.objects.filter(
            source_theme_report__theme_id=theme_id,
        ).delete()

        theme_reports = list(
            NewReleaseThemeReport.objects.filter(theme_id=theme_id)
            .exclude(reporter__isnull=True)
        )
        created_count = 0
        for theme_report in theme_reports:
            created_count += cls.sync_for_theme_report(theme_report)
        return created_count

    def __str__(self):
        reporter_name = self.reporter or '未知用户'
        return f"{reporter_name} 举报ASIN:{self.asin_id}"


@receiver(pre_save, sender=AmazonNewReleaseRank)
def cache_previous_summary_subject(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_summary_subject_id = None
        return

    instance._previous_summary_subject_id = (
        sender.objects.filter(pk=instance.pk)
        .values_list('summary_subject_id', flat=True)
        .first()
    )


@receiver(post_save, sender=AmazonNewReleaseRank)
def auto_report_asin_on_theme_change(sender, instance, created, **kwargs):
    previous_theme_id = getattr(instance, '_previous_summary_subject_id', None)
    if not created and previous_theme_id == instance.summary_subject_id:
        return

    NewReleaseAsinReport.sync_for_asin(instance, previous_theme_id=previous_theme_id)


class ThemeNewDailyData(models.Model):
    """主题每日数据"""
    product = models.ForeignKey(
        AmazonNewReleaseRank,
        on_delete=models.CASCADE,
        related_name='new_release_daily_data',
        verbose_name='关联产品'
    )
    crawl_date = models.DateField(verbose_name='抓取日期')

    rank_category = models.CharField(max_length=100, null=True, blank=True, verbose_name='排名分类1')
    rank = models.IntegerField(null=True, blank=True, verbose_name='排名1')

    rank_category2 = models.CharField(max_length=100, null=True, blank=True, verbose_name='排名分类2')
    rank2 = models.IntegerField(null=True, blank=True, verbose_name='排名2')

    rank_category3 = models.CharField(max_length=100, null=True, blank=True, verbose_name='排名分类3')
    rank3 = models.IntegerField(null=True, blank=True, verbose_name='排名3')

    crawled_at = models.DateTimeField(auto_now_add=True, verbose_name='抓取时间')
    appear_count = models.IntegerField(default=1, verbose_name='重复数')
    score = models.IntegerField(default=0, verbose_name='分值')

    class Meta:
        db_table = 'theme_new_daily_data'
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


# =============================================================================
# 主题模型 - 三层架构设计（新增）
# =============================================================================


class ThemeSubject(models.Model):
    """一级：核心主题表"""

    canonical_subject = models.CharField(
        max_length=200,
        primary_key=True,
        verbose_name='标准化主题'
    )

    core_entities = models.JSONField(
        default=list,
        verbose_name='核心实体'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'theme_subject'
        verbose_name = '核心主题'
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.canonical_subject[:50]


class ThemeNovelty(models.Model):
    """二级：新奇特主题表"""

    subject = models.OneToOneField(
        ThemeSubject,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='theme_novelty',
        verbose_name='核心主题'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'theme_novelty'
        verbose_name = '新奇特主题'
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.subject.canonical_subject[:50]


class ThemeNoveltyDailyData(models.Model):
    """三级：新奇特主题每日数据表"""

    novelty_theme = models.ForeignKey(
        ThemeNovelty,
        on_delete=models.CASCADE,
        related_name='daily_data',
        verbose_name='新奇特主题'
    )

    theme_date = models.DateField(verbose_name='主题日期')
    asin_count = models.IntegerField(default=0, verbose_name='当日ASIN数量')
    ranked_asin_count = models.IntegerField(default=0, verbose_name='有排名ASIN数')
    score = models.IntegerField(default=0, verbose_name='核心分值')
    rank_trend_7d = models.JSONField(
        default=list,
        blank=True,
        verbose_name='7天排名趋势'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'theme_novelty_daily_data'
        unique_together = ['novelty_theme', 'theme_date']
        indexes = [
            models.Index(fields=['novelty_theme', 'theme_date']),
            models.Index(fields=['theme_date', 'score']),
        ]
        verbose_name = '新奇特主题每日数据'
        verbose_name_plural = verbose_name
        ordering = ['-theme_date']

    def __str__(self):
        return f"{self.novelty_theme.subject.canonical_subject[:30]} - {self.theme_date}"


class ThemeNoveltySummary(models.Model):
    id = models.AutoField(primary_key=True, verbose_name='ID')
    summary_subject_title = models.CharField(max_length=525, verbose_name='汇总主题', unique=True)
    created_time = models.DateTimeField(null=True, blank=True, verbose_name='创建时间', db_index=True)

    class Meta:
        db_table = 'theme_novelty_summary'
        verbose_name = '新奇特主题汇总'
        indexes = [
            models.Index(fields=['summary_subject_title']),
        ]

    def __str__(self):
        return f'{self.summary_subject_title}'


class DailyRecommendedTheme(models.Model):
    """
    每日推荐主题
    """
    id = models.AutoField(primary_key=True)
    theme = models.CharField(
        max_length=255,
        verbose_name="推荐主题",
        help_text="当天的推荐主题名称"
    )
    date = models.DateField(verbose_name="日期")

    # 自动时间戳（建议保留，便于追踪）
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        db_table = 'theme_daily_recommended_theme'
        verbose_name = '每日推荐主题'
        verbose_name_plural = '每日推荐主题'
        ordering = ['-date', '-created_at']

        # 核心约束：同一天内主题不能重复
        constraints = [
            models.UniqueConstraint(
                fields=['date', 'theme'],
                name='unique_daily_theme'
            )
        ]

    def __str__(self):
        return f"{self.date}: {self.theme}"

    @classmethod
    def get_themes_by_date(cls, target_date):
        """获取某天的所有推荐主题"""
        return cls.objects.filter(date=target_date)

    @classmethod
    def add_theme(cls, date, theme_name):
        """安全添加主题（重复则返回已存在记录）"""
        return cls.objects.get_or_create(date=date, theme=theme_name)

