from django.shortcuts import render
from django.utils import timezone

def dashboard(request):
    balance_total = 120
    medium_risk = 15
    low_risk = 5
    
    context = {
        'now': timezone.now(), # 添加 now 变量
        'balance_warning': {
            'total': balance_total,
            'medium_risk': medium_risk,
            'low_risk': low_risk,
            'medium_risk_percent': (medium_risk / balance_total * 100) if balance_total > 0 else 0,
            'low_risk_percent': (low_risk / balance_total * 100) if balance_total > 0 else 0,
        },
        'consumer_act_risk': {
            'total': 3,
        },
        'legal_person_cooperation_risk': {
            'total': 2,
        },
        'company_subject_risk': {
            'total': 1,
        },
        'shop_health': {
            'total': 150,
            'healthy': 130,
            'risky': 10,
            'disabled': 10,
        },
        'order_subject_risk': {
            'total': 4,
        },
        'policy_compliance': {
            'total': 25,
            'breakdown': {
                'suspected_ip_infringement': 2,
                'ip_complaints': 1,
                'authenticity_complaints': 0,
                'condition_complaints': 3,
                'safety_issues': 1,
                'listing_policy_violations': 5,
                'restricted_product_policy': 2,
                'review_policy_violations': 1,
                'other_policy_violations': 5,
                'regulatory_compliance': 5,
            }
        }
    }
    return render(request, 'shop_guard/dashboard.html', context)
