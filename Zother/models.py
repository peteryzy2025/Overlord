from django.db import models



class BargainingOrder(models.Model):
    order_id = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    class Meta:
        db_table = "Zother_bargainingorder"
        verbose_name = "议价订单表"
        verbose_name_plural = "议价订单表"