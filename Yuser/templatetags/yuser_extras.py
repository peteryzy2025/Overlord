from django import template
import json
register = template.Library()

@register.filter
def get_item(dictionary, key):
    """从字典获取值，用于模板中访问字典"""
    return dictionary.get(key) if dictionary else None

@register.filter
def parse_json(value):
    """解析JSON字符串"""
    if not value:
        return None
    try:
        return json.loads(value)
    except:
        return None
@register.simple_tag
def get_special_rules(assess_type):
    """获取特殊规则"""
    rules_map = {
        'amazon_operation': [
            {'title': '核心红线', 'content': '链接操作失误造成转化链接删除/未经申请同意低价销售/迟到半小时以上、摸鱼玩手机等，对应项分数全无'},
            {'title': '连续低分', 'content': '连续3个月得分D/E级，自动离职'}
        ],
        'temu_operation': [
            {'title': '店铺激活', 'content': '精铺店铺激活率必须达到100%'},
            {'title': '广告ROI', 'content': '广告投入产出异常造成预算浪费将扣分'},
            {'title': '店铺违规', 'content': '个人原因导致店铺违规，分数全无'}
        ],
        'amazon_assistant': [
            {'title': '转正标准', 'content': '评分≥70分且业绩指标完成，可转为运营岗位'},
            {'title': '淘汰规则', 'content': '评分＜70分且业绩无达标，连续两个月则自动离职'}
        ]
    }
    return rules_map.get(assess_type, [])

@register.filter
def sum_max_score(configs, category):
    """计算某类别的满分总和"""
    return sum(config.max_score for config in configs if config.category == category)

@register.filter
def multiply(value, arg):
    """乘法运算"""
    return value * arg