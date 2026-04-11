from django.db import models


class Product(models.Model):
    """产品表"""
    id = models.IntegerField(primary_key=True)  # 业务ID做主键
    name = models.CharField('产品名称', max_length=255)

    class Meta:
        db_table = 'divi_product'
        verbose_name = '产品'
        verbose_name_plural = '产品'

    def __str__(self):
        return self.name


class ProductColor(models.Model):
    """产品颜色表"""
    id = models.AutoField(primary_key=True)
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='colors',
        verbose_name='产品'
    )
    color_classify_id = models.IntegerField('颜色分类ID')
    color_name = models.CharField('颜色名称', max_length=100)
    en_name = models.CharField('颜色英文名', max_length=100)

    class Meta:
        db_table = 'divi_product_color'
        verbose_name = '产品颜色'
        verbose_name_plural = '产品颜色'
        # 一个产品的同一个颜色不能重复
        unique_together = ['product', 'color_classify_id']

    def __str__(self):
        return f"{self.product.name} - {self.color_name}"


class ProductSize(models.Model):
    """产品尺寸表"""
    id = models.AutoField(primary_key=True)
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='sizes',
        verbose_name='产品'
    )
    product_size_id = models.IntegerField('尺寸ID')
    product_size_name = models.CharField('尺寸名称', max_length=100)

    class Meta:
        db_table = 'divi_product_size'
        verbose_name = '产品尺寸'
        verbose_name_plural = '产品尺寸'
        # 一个产品的同一个尺寸不能重复
        unique_together = ['product', 'product_size_id']

    def __str__(self):
        return f"{self.product.name} - {self.product_size_name}"





class DiviExportTemplate(models.Model):
    """
    DIVI 汇出模板表
    存储从 DIVI 系统同步的亚马逊模板信息
    """
    template_id = models.IntegerField(
        '模板ID',
        primary_key=True,
        db_comment='DIVI 系统的模板ID (amazonTemplateId)'
    )
    template_name = models.CharField(
        '模板名称',
        max_length=255,
        blank=True,
        null=True,
        db_comment='模板名称，如：美国-所有帽子-10.99-吴晓云-29曹家勇_2169'
    )
    product_type = models.CharField(
        '产品类型',
        max_length=100,
        blank=True,
        null=True,
        db_comment='产品类型，如：hat, shirt, decorativesignage 等'
    )

    # 多对多关系：模板关联的产品（在 divi 应用中）
    products = models.ManyToManyField(
        'Product',
        blank=True,
        related_name='export_templates',
        verbose_name='关联产品',
    )

    # 多对多关系：模板关联的店铺（通过 divi_shop_id 关联 AmazonShop）
    shops = models.ManyToManyField(
        'general.AmazonShop',
        blank=True,
        related_name='divi_export_templates',
        verbose_name='关联店铺',
    )

    # 公司隔离（用于数据权限控制）
    company = models.ForeignKey(
        'general.Company',
        on_delete=models.CASCADE,
        related_name='divi_export_templates',
        verbose_name='所属公司',
        null=True,
        blank=True,
        db_comment='数据隔离边界'
    )

    # 记录同步时间
    synced_at = models.DateTimeField(
        '同步时间',
        auto_now=True,
        db_comment='最近一次从 DIVI 同步的时间'
    )
    created_at = models.DateTimeField(
        '创建时间',
        auto_now_add=True,
        db_comment='记录创建时间'
    )

    class Meta:
        db_table = 'divi_export_templates'
        verbose_name = 'DIVI 汇出模板'
        verbose_name_plural = verbose_name
        ordering = ['-synced_at']
        indexes = [
            models.Index(fields=['company', 'synced_at'], name='idx_divi_tpl_company_synced'),
            models.Index(fields=['product_type'], name='idx_divi_tpl_product_type'),
        ]

    def __str__(self):
        return f"{self.template_id} - {self.template_name or '未命名模板'}"


class DiviImageClassify(models.Model):
    """
    DIVI 图库分类表
    存储从 DIVI 系统同步的图库目录树结构
    """
    id = models.IntegerField(
        '分类ID',
        primary_key=True,
        db_comment='DIVI 系统的分类ID'
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        verbose_name='父节点',
        db_comment='父分类ID，根节点为null'
    )
    label = models.CharField(
        '显示名称',
        max_length=255,
        db_comment='分类显示名称，如"10月"、"10.7天空"'
    )
    technology_name = models.CharField(
        '技术名称',
        max_length=100,
        blank=True,
        null=True,
        db_comment='技术分类名称，如"印花"'
    )
    level = models.IntegerField(
        '层级',
        default=0,
        db_comment='层级深度，0=根节点，1=一级，以此类推'
    )
    path = models.CharField(
        '完整路径',
        max_length=500,
        blank=True,
        null=True,
        db_comment='完整路径，如"/100000/117298/117299"，便于查询子树'
    )
    sort_order = models.IntegerField(
        '排序',
        default=0,
        db_comment='同层级内的排序'
    )
    
    # 记录同步时间
    # 账号信息（从 cookie 中提取）
    username = models.CharField(
        'DIVI 账号',
        max_length=100,
        blank=True,
        null=True,
        db_comment='同步数据的 DIVI 账号，如 YMX-26'
    )
    
    synced_at = models.DateTimeField(
        '同步时间',
        auto_now=True,
        db_comment='最近一次从 DIVI 同步的时间'
    )
    created_at = models.DateTimeField(
        '创建时间',
        auto_now_add=True,
        db_comment='记录创建时间'
    )

    class Meta:
        db_table = 'divi_image_classify'
        verbose_name = 'DIVI 图库分类'
        verbose_name_plural = 'DIVI 图库分类'
        ordering = ['username', 'level', 'sort_order', 'id']
        indexes = [
            models.Index(fields=['parent', 'sort_order'], name='idx_divi_img_parent_sort'),
            models.Index(fields=['level'], name='idx_divi_img_level'),
            models.Index(fields=['path'], name='idx_divi_img_path'),
            models.Index(fields=['username'], name='idx_divi_img_username'),
        ]

    def __str__(self):
        return f"{'  ' * self.level}{self.label}"
    
    def get_full_path_name(self):
        """获取完整路径名称，如：印花/10月/10.7/10.7天空"""
        names = []
        node = self
        while node:
            names.append(node.label)
            node = node.parent
        return '/'.join(reversed(names))
