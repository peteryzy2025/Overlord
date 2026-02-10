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


#  下面是新的模型


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
        db_table= "theme_trash_bin"
    def __str__(self):
        return self.asin

#---------------------------

class StatusCodeMapping(models.Model):
    """商标状态码映射表"""
    status_code = models.CharField(max_length=50,verbose_name='商标状态码', primary_key=True)
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
    theme_name = models.CharField(max_length=765, verbose_name='侵权词名')
    replacement_word = models.CharField(
        max_length=765,
        verbose_name='建议替换词',
        null=True,
        blank=True,
        help_text='检测到侵权时建议使用的替代词汇'
    )
    name_type = models.IntegerField(verbose_name='侵权类型码',null=True, blank=True)
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


# class AmazonListing(models.Model):
#     """
#     Listing 数据库
#     唯一约束：同一个领星店铺（站点）内，ASIN 不能重复
#     """

#     id = models.BigAutoField(
#         primary_key=True,
#         verbose_name='ID',
#         db_comment='自增主键'
#     )

#     asin = models.CharField(
#         max_length=10,
#         db_index=True,  # 仍为查询热点，加索引
#         verbose_name='ASIN',
#         db_comment='亚马逊商品编码'
#     )

#     title = models.CharField(
#         max_length=500,
#         blank=True,
#         null=True,
#         verbose_name='标题',
#         db_comment='Listing标题'
#     )

#     # 外键：一个 Listing 属于一个店铺（多对一）
#     lingxing_shop = models.ForeignKey(
#         'amazon.LingXingAmazonShop',
#         on_delete=models.CASCADE,  # 店铺删除则 Listing 删除
#         related_name='listings',
#         verbose_name='所属领星店铺',
#         db_comment='绑定的领星站点店铺'
#     )

#     # 多对多：侵权词库（一个 ASIN 可能命中多个词，一个词可能关联多个 ASIN）
#     tro_words = models.ManyToManyField(
#         'TroTable',
#         related_name='listings',
#         verbose_name='命中侵权词',
#         blank=True,
#     )

#     # 多对多：美标网
#     trademarks = models.ManyToManyField(
#         'TrademarkInfo',
#         related_name='listings',
#         verbose_name='命中商标',
#         blank=True,
#     )

#     is_active = models.BooleanField(
#         default=True,
#         verbose_name='是否在售',
#         db_comment='Listing是否处于在售状态'
#     )

#     created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
#     updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

#     class Meta:
#         db_table = 'amazon_listing'
#         db_table_comment = 'Listing主表（店铺+ASIN唯一）'
#         verbose_name = 'Amazon Listing'
#         verbose_name_plural = 'Amazon Listings'

#         # 核心约束：同一个店铺内 ASIN 唯一
#         constraints = [
#             models.UniqueConstraint(
#                 fields=['lingxing_shop', 'asin'],
#                 name='uniq_lingxing_shop_asin'
#             )
#         ]

#         # 常用查询索引
#         indexes = [
#             models.Index(fields=['asin'], name='idx_listing_asin'),
#             models.Index(fields=['is_active'], name='idx_listing_active'),
#             models.Index(fields=['created_at'], name='idx_listing_created'),
#         ]

#     def __str__(self):
#         shop_name = self.lingxing_shop.name if self.lingxing_shop else '未知店铺'
#         return f"{shop_name} - {self.asin}"

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