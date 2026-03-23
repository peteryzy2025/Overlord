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
