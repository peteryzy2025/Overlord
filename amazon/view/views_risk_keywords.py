"""
深渊 - 风险关键词管理
"""
import json
from django.http import JsonResponse
from django.views import View
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Q

from amazon.models import RiskKeyword


@login_required
def amazon_risk_keywords_page(request):
    """风险关键词管理页面"""
    return render(request, 'amazon_risk_keywords.html', {
        'active_page': 'amazon_risk_keywords'
    })


class RiskKeywordListAPI(LoginRequiredMixin, View):
    """风险关键词列表 API"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # 分页参数
            page = int(data.get('page', 1))
            page_size = int(data.get('page_size', 20))
            
            # 筛选参数
            keyword_filter = data.get('keyword', '').strip()
            category = data.get('category', '')
            match_type = data.get('match_type', '')
            is_active = data.get('is_active', '')
            apply_to = data.get('apply_to', '')
            
            # 排序参数
            sort_field = data.get('sort_field', '-priority')
            sort_order = data.get('sort_order', 'desc')
            
            # 基础查询
            queryset = RiskKeyword.objects.all()
            
            # 应用筛选
            if keyword_filter:
                queryset = queryset.filter(Q(keyword__icontains=keyword_filter))
            if category:
                queryset = queryset.filter(category=category)
            if match_type:
                queryset = queryset.filter(match_type=match_type)
            if is_active != '':
                queryset = queryset.filter(is_active=is_active == 'true' or is_active == True)
            if apply_to:
                queryset = queryset.filter(apply_to=apply_to)
            
            # 应用排序
            order_by = sort_field if sort_order == 'asc' else f'-{sort_field.lstrip("-")}'
            queryset = queryset.order_by(order_by)
            
            # 分页
            paginator = Paginator(queryset, page_size)
            page_obj = paginator.get_page(page)
            
            # 序列化数据
            keywords = []
            for item in page_obj:
                keywords.append({
                    'id': item.id,
                    'keyword': item.keyword,
                    'category': item.category,
                    'category_display': item.get_category_display(),
                    'match_type': item.match_type,
                    'match_type_display': item.get_match_type_display(),
                    'is_active': item.is_active,
                    'priority': item.priority,
                    'description': item.description or '',
                    'example_text': item.example_text or '',
                    'apply_to': item.apply_to,
                    'apply_to_display': item.get_apply_to_display(),
                    'created_at': item.created_at.strftime('%Y-%m-%d %H:%M') if item.created_at else '-',
                })
            
            return JsonResponse({
                'success': True,
                'data': {
                    'keywords': keywords,
                    'total': paginator.count,
                    'total_pages': paginator.num_pages,
                    'page': page,
                }
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class RiskKeywordCreateAPI(LoginRequiredMixin, View):
    """创建风险关键词 API"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            keyword = data.get('keyword', '').strip()
            if not keyword:
                return JsonResponse({'success': False, 'message': '关键词不能为空'})
            
            # 检查关键词是否已存在
            if RiskKeyword.objects.filter(keyword__iexact=keyword).exists():
                return JsonResponse({'success': False, 'message': '该关键词已存在'})
            
            # 创建关键词
            risk_keyword = RiskKeyword.objects.create(
                keyword=keyword,
                category=data.get('category', 'other'),
                match_type=data.get('match_type', 'whole'),
                is_active=data.get('is_active', True),
                priority=int(data.get('priority', 0)),
                description=data.get('description', ''),
                example_text=data.get('example_text', ''),
                apply_to=data.get('apply_to', 'all')
            )
            
            return JsonResponse({
                'success': True,
                'message': '风险关键词创建成功',
                'data': {
                    'id': risk_keyword.id,
                    'keyword': risk_keyword.keyword,
                }
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class RiskKeywordOptionsAPI(LoginRequiredMixin, View):
    """获取风险关键词选项 API（分类、匹配方式等）"""
    
    def get(self, request):
        try:
            return JsonResponse({
                'success': True,
                'data': {
                    'categories': [
                        {'value': 'account_ban', 'label': '账户停用/冻结'},
                        {'value': 'performance', 'label': '绩效/政策警告'},
                        {'value': 'funds', 'label': '资金/提现异常'},
                        {'value': 'listing', 'label': 'Listing下架/违规'},
                        {'value': 'verification', 'label': '审核/验证通知'},
                        {'value': 'tro', 'label': 'TRO/法律诉讼'},
                        {'value': 'inventory', 'label': '库存/物流异常'},
                        {'value': 'other', 'label': '其他'},
                    ],
                    'match_types': [
                        {'value': 'whole', 'label': '整词匹配'},
                        {'value': 'contains', 'label': '包含匹配'},
                        {'value': 'regex', 'label': '正则表达式'},
                        {'value': 'start', 'label': '开头匹配'},
                    ],
                    'apply_to_options': [
                        {'value': 'all', 'label': '全部'},
                        {'value': 'email', 'label': '仅邮件'},
                        {'value': 'performance', 'label': '仅绩效通知'},
                    ],
                }
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
