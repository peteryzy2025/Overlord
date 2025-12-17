# Yuser/models.py
from django.db import models


class AssessmentTemplate(models.Model):
    """考核模板主表"""
    name = models.CharField('模板名称', max_length=100)
    description = models.TextField('描述', blank=True)
    version = models.CharField('版本', max_length=20, default='1.0')
    is_active = models.BooleanField('启用', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '考核模板'
        verbose_name_plural = '考核模板管理'


class AssessmentCategory(models.Model):
    """一级分类：业绩指标、行为考核"""
    template = models.ForeignKey(AssessmentTemplate, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField('分类名称', max_length=50)
    weight = models.DecimalField('权重(%)', max_digits=5, decimal_places=2)  # 70.00表示70%
    order = models.IntegerField('排序', default=0)

    class Meta:
        verbose_name = '考核分类'
        verbose_name_plural = '考核分类管理'
        ordering = ['order']


class AssessmentGroup(models.Model):
    """二级分组：业务考核、工作态度、自主能力等"""
    category = models.ForeignKey(AssessmentCategory, on_delete=models.CASCADE, related_name='groups')
    name = models.CharField('分组名称', max_length=50)  # 如：业务考核
    order = models.IntegerField('排序', default=0)

    class Meta:
        verbose_name = '考核分组'
        ordering = ['order']


class AssessmentItem(models.Model):
    """具体考核项：最终打分条目"""
    # 一级分类（直接关联，用于业绩指标类型）
    category = models.ForeignKey(AssessmentCategory, on_delete=models.CASCADE, related_name='items')

    # 二级分组（可为空，用于行为考核类型）
    group = models.ForeignKey(AssessmentGroup, on_delete=models.CASCADE, related_name='items', null=True, blank=True)

    serial_number = models.CharField('序号', max_length=10, blank=True)
    name = models.CharField('项目名称', max_length=200)
    description = models.TextField('详细说明', blank=True)
    max_score = models.DecimalField('满分分值', max_digits=6, decimal_places=2)

    # 评分方式
    scoring_type = models.CharField('评分方式', max_length=20,
                                    choices=[
                                        ('manual', '手动评分'),
                                        ('auto', '自动计算'),
                                        ('deduct', '扣分制'),
                                        ('bonus', '加分项')
                                    ],
                                    default='manual'
                                    )
    formula = models.TextField('计算公式', blank=True, null=True)

    # 特殊规则标记
    is_zero_if_violated = models.BooleanField('违规则分数全无', default=False)
    is_bonus_item = models.BooleanField('加分项', default=False)

    order = models.IntegerField('排序', default=0)

    class Meta:
        verbose_name = '考核项目'
        ordering = ['order']

class ScoringRule(models.Model):
    """评分标准细则：存储详细的评分规则"""
    item = models.ForeignKey(AssessmentItem, on_delete=models.CASCADE, related_name='scoring_rules')
    condition = models.CharField('条件描述', max_length=300)  # 如：达成100%
    deduction_per_unit = models.DecimalField('每单位扣分', max_digits=5, decimal_places=2, null=True, blank=True)
    score_rule = models.CharField('计分规则描述', max_length=100)  # 如：满分 or 每低于1%扣2分
    order = models.IntegerField('排序', default=0)

    class Meta:
        verbose_name = '评分标准'


class AssessmentInstance(models.Model):
    """生成的考核实例（实际填写的表）"""
    template = models.ForeignKey(AssessmentTemplate, on_delete=models.PROTECT)
    employee_name = models.CharField('员工姓名', max_length=50)
    department = models.CharField('部门', max_length=50)
    position = models.CharField('职位', max_length=50)
    period = models.CharField('考核时段', max_length=50)

    # 审批相关
    employee_signature = models.CharField('被考核人签名', max_length=50, blank=True)
    employee_confirm_time = models.DateTimeField('确认时间', null=True, blank=True)
    manager_signature = models.CharField('上级签名', max_length=50, blank=True)
    manager_confirm_time = models.DateTimeField('上级确认时间', null=True, blank=True)

    # 总分与评级
    total_score = models.DecimalField('总分', max_digits=8, decimal_places=2, null=True)
    grade = models.CharField('评级', max_length=10, blank=True)  # S/A/B/C/D/E

    status = models.CharField('状态', max_length=20,
                              choices=[
                                  ('draft', '草稿'),
                                  ('submitted', '已提交'),
                                  ('confirmed', '已确认')
                              ],
                              default='draft'
                              )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)


class AssessmentScore(models.Model):
    """每个考核项的实际评分"""
    instance = models.ForeignKey(AssessmentInstance, on_delete=models.CASCADE, related_name='item_scores')
    item = models.ForeignKey(AssessmentItem, on_delete=models.CASCADE)
    actual_score = models.DecimalField('实际得分', max_digits=6, decimal_places=2)
    remarks = models.TextField('备注', blank=True)  # 填写说明或特殊情况