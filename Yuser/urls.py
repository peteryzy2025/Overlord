# Yuser/urls.py
from django.urls import path
from Yuser import view_yuser


urlpatterns = [
    # 主页面
    path('assessment/', view_yuser.assessment_management_view, name='assessment_management'),#temu运营
    # 亚马逊运营考核
    path('amazon/operation-assessment/', view_yuser.amazon_operation_assessment_view,
         name='amazon_operation_assessment'),

    # 亚马逊运营助理考核
    path('amazon/assistant-assessment/', view_yuser.amazon_assistant_assessment_view,
         name='amazon_assistant_assessment'),
]
