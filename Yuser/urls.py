# Yuser/urls.py
from django.urls import path
from Yuser import view_assessment_management

app_name = 'Yuser'

urlpatterns = [
    # 新增动态版本
    # 绩效考核管理
    path('assessment/', view_assessment_management.AssessmentListView.as_view(), name='assessment_list'),
    path('assessment/create-batch/', view_assessment_management.CreateBatchAssessmentView.as_view(),
         name='assessment_create_batch'),
    path('assessment/<int:pk>/', view_assessment_management.AssessmentEditView.as_view(), name='assessment_detail'),
    path('assessment/<int:pk>/submit/', view_assessment_management.AssessmentSubmitView.as_view(),
         name='assessment_submit'),
    path('assessment/<int:pk>/member-confirm/', view_assessment_management.MemberConfirmView.as_view(),
         name='member_confirm'),
    path('assessment/<int:pk>/member-reject/', view_assessment_management.MemberRejectView.as_view(),
         name='member_reject'),
    path('assessment/<int:pk>/leader-confirm/', view_assessment_management.LeaderFinalConfirmView.as_view(),
         name='leader_confirm'),
    path('assessment/<int:pk>/submit/', view_assessment_management.AssessmentSubmitView.as_view(),
         name='assessment_submit'),
    path('assessment/<int:pk>/submit-to-member/', view_assessment_management.SubmitToMemberView.as_view(),
         name='assessment_submit_to_member'),
    path('assessment/<int:pk>/refresh-orders/', view_assessment_management.RefreshOrderDataView.as_view(),
         name='assessment_refresh_orders'),
    path('assessment/<int:pk>/delete/', view_assessment_management.AssessmentDeleteView.as_view(),
         name='assessment_delete'),
path('assessment/batch-refresh-orders/', view_assessment_management.BatchRefreshOrdersView.as_view(),
     name='assessment_batch_refresh_orders'),


]
