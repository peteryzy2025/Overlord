from django.db import models


class InventoryMaster(models.Model):
    """库存主数据 - 产品基础信息"""
    mosku = models.CharField(
        'MOSKU编码',
        max_length=100,
        primary_key=True,
        help_text='唯一SKU编码'
    )
    factory_name = models.CharField('工厂名称', max_length=200, db_index=True)
    supplier_name = models.CharField('供应商名称', max_length=200,null=True)
    product_name = models.CharField('产品名称', max_length=300, db_index=True)
    color = models.CharField('颜色', max_length=100, blank=True, db_index=True)
    size = models.CharField('尺码', max_length=100, blank=True, db_index=True)
    location = models.CharField('库位', max_length=100, db_index=True)

    is_active = models.BooleanField('是否启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'inventory_master'
        verbose_name = '库存主数据'
        verbose_name_plural = '库存主数据'
        indexes = [
            models.Index(fields=['factory_name', 'supplier_name']),
            models.Index(fields=['product_name', 'color', 'size']),
        ]

    def __str__(self):
        return f'{self.mosku} - {self.product_name}'


class InventoryDaily(models.Model):
    """每日库存快照"""
    inventory = models.ForeignKey(
        InventoryMaster,
        on_delete=models.CASCADE,
        verbose_name='MOSKU',
        related_name='daily_records'
    )
    date = models.DateField('日期', db_index=True)
    available_qty = models.IntegerField('可用数量', default=0)
    stock_qty = models.IntegerField('库存数量', default=0)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'inventory_daily'
        verbose_name = '每日库存快照'
        verbose_name_plural = '每日库存快照'
        unique_together = ['inventory', 'date']
        indexes = [
            models.Index(fields=['date', 'inventory']),
        ]

    def __str__(self):
        return f'{self.inventory.mosku} - {self.date}'