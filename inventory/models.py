from django.db import models


class Factory(models.Model):
    """工厂基础信息"""
    name = models.CharField('工厂名称', max_length=200, unique=True, db_index=True)
    remark = models.TextField('备注', blank=True)

    class Meta:
        db_table = 'inventory_factory'
        verbose_name = '工厂信息'
        verbose_name_plural = '工厂信息'
        ordering = ['name']

    def __str__(self):
        return self.name


class InventoryMaster(models.Model):
    """库存主数据 - 产品基础信息"""
    mosku = models.CharField('MOSKU编码', max_length=100, db_index=True)
    factory = models.ForeignKey(
        Factory,
        on_delete=models.PROTECT,  # 防止误删有库存数据的工厂
        verbose_name='工厂',
        null=True,
        related_name='inventory_items'
    )
    supplier_name = models.CharField('供应商名称', max_length=200, null=True, blank=True)
    product_name = models.CharField('产品名称', max_length=300, db_index=True)
    color = models.CharField('颜色', max_length=100, blank=True, db_index=True)
    size = models.CharField('尺码', max_length=100, blank=True, db_index=True)
    location = models.CharField('库位', max_length=100, db_index=True)
    stock_qty = models.IntegerField('库存数量', default=0)

    class Meta:
        db_table = 'inventory_master'
        verbose_name = '库存主数据'
        verbose_name_plural = '库存主数据'
        ordering = ['mosku']
        # 组合唯一约束
        constraints = [
            models.UniqueConstraint(
                fields=['mosku', 'factory'],
                name='unique_mosku_factory'
            )
        ]
        indexes = [
            models.Index(fields=['factory', 'mosku']),
            models.Index(fields=['product_name', 'color', 'size']),
        ]

    def __str__(self):
        return f'{self.mosku} - {self.product_name}'


class InventoryDaily(models.Model):
    """每日库存快照"""
    inventory = models.ForeignKey(
        InventoryMaster,
        on_delete=models.CASCADE,
        verbose_name='库存主数据',
        related_name='daily_records'
    )
    date = models.DateField('日期', db_index=True)
    available_qty = models.IntegerField('可用数量', default=0)

    class Meta:
        db_table = 'inventory_daily'
        verbose_name = '每日库存快照'
        verbose_name_plural = '每日库存快照'
        unique_together = ['inventory', 'date']
        indexes = [
            models.Index(fields=['date', 'inventory']),
            models.Index(fields=['inventory', '-date']),  # 倒序查询优化
        ]

    def __str__(self):
        return f'{self.inventory.mosku} - {self.date}'