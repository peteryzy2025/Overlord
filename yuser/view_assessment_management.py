import json
import math
from datetime import datetime, timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.utils import timezone
from django.db import transaction
from django.contrib import messages
from django.db.models import Sum, Q
from django.utils.dateparse import parse_date
from decimal import Decimal

from general.models import UserOperationLog, PersonalPerformanceTarget
from yuser.models import (
    PerformanceAssessment,
    PerformanceScoreDetail,
    AssessmentItemConfig,
    User,
    AssessmentHistory
)
from general.models import AmazonShop, TemuShop
from amazon.models import LingXingAmazonShop, AmazonOrders, AmazonOrderItem
from temu.models import LingXingTemuShop, TemuOrder, TemuOrderItem


class AssessmentManagementView(LoginRequiredMixin, View):
    """基础权限视图"""

    def is_admin(self, user):
        if getattr(user, 'is_superuser', False):
            return True

        user_permissions = getattr(user, 'permission', '') or ''
        permission_list = [p.strip() for p in user_permissions.split(',') if p.strip()]
        return '555' in permission_list

    def is_group_leader(self, user):
        return user.role == '运营组长'

    def get_group_members(self, leader):
        """获取组长的所有组员"""
        if not leader.operational_account or not leader.operational_account.ops_group:
            return User.objects.none()

        return User.objects.filter(
            operational_account__ops_group=leader.operational_account.ops_group
        ).exclude(id=leader.id)

    # ===== 权限检查方法 =====
    def can_edit(self, assessment):
        """是否可编辑（仅组长在草稿状态可编辑和保存）"""
        user = self.request.user
        if assessment.is_locked:
            return False
        return user == assessment.leader and assessment.status == 'draft'

    def can_submit(self, assessment):
        """是否可提交给组员"""
        user = self.request.user
        return (user == assessment.leader and
                assessment.status == 'draft' and
                not assessment.is_locked)

    def can_confirm(self, assessment):
        """是否可确认"""
        user = self.request.user
        if user == assessment.employee and assessment.status == 'pending_member':
            return True
        if user == assessment.leader and assessment.status == 'pending_leader':
            return True
        return False

    def can_reject(self, assessment):
        """是否可驳回"""
        user = self.request.user
        return (user == assessment.employee and
                assessment.status == 'pending_member')

    def get_grade_rules(self, assess_type):
        """获取评分等级规则"""
        if assess_type == 'temu_operation':
            return [
                {'level': 'S级评分≥150', 'reward': '提成+300元奖励'},
                {'level': 'A级评分90-100', 'reward': '提成按得分百分比发放'},
                {'level': 'B级评分80-89', 'reward': '提成按80%发放'},
                {'level': 'C级评分70-79', 'reward': '提成按70%发放'},
                {'level': 'D级评分60-69', 'reward': '提成按50%发放'},
                {'level': 'E级评分<60', 'reward': '提成不予发放'},
                {'level': '连续3个月得分D/E', 'reward': '自动离职', 'is_warning': True},
            ]
        elif assess_type == 'amazon_operation':
            return [
                {'level': 'S级评分 ≥ 150', 'reward': '提成+300元奖励'},
                {'level': 'A级评分 90-100', 'reward': '提成按得分百分比发放'},
                {'level': 'B级评分 80-89', 'reward': '提成按80%发放'},
                {'level': 'C级评分 70-79', 'reward': '提成按70%发放'},
                {'level': 'D级评分 60-69', 'reward': '提成按50%发放'},
                {'level': 'E级评分 < 60', 'reward': '提成不予发放'},
                {'level': '连续3个月得分D/E', 'reward': '自动离职', 'is_warning': True},
            ]
        else:
            return [
                {'level': '评分 ≥ 70分', 'reward': '且业绩指标完成，可转为运营岗位'},
                {'level': '评分 ＜ 70分', 'reward': '业绩无达标，连续两个月则自动离职'},
                {'level': '评分 ＜ 60分', 'reward': '自动离职', 'is_warning': True},
            ]

    # ===== 计算逻辑方法 =====
    def calculate_performance_score(self, assessment):
        """计算业绩达成得分"""
        if assessment.assess_type in ['temu_operation', 'amazon_operation']:
            max_score = 90
        else:  # amazon_assistant
            max_score = 80

        rate = assessment.achievement_rate
        if rate >= 100:
            return max_score
        elif rate >= 80:
            return max_score - ((100 - rate) * 2)
        return 0

    # ========== 新增：等级计算 ==========
    def calculate_grade_level(self, score, assess_type):
        """根据得分和考核类型计算等级"""
        if assess_type in ['temu_operation', 'amazon_operation']:
            if score >= 150:
                return 'S级'
            elif score >= 90:
                return 'A级'
            elif score >= 80:
                return 'B级'
            elif score >= 70:
                return 'C级'
            elif score >= 60:
                return 'D级'
            else:
                return 'E级'
        else:  # amazon_assistant
            return '达标' if score >= 70 else '不达标'

    # ========== 新增：消息构建 ==========
    def _build_notification_message(self, assessment, operator, operation_type, final_score=None, extra_context=None):
        """
        构建考核通知消息内容
        """
        # 获取评分明细
        score_details = {
            d.item_key: float(d.score_value)
            for d in assessment.score_details.all()
        }

        # 关键修复：事故分只显示实际扣分（>0才显示）
        accident_score = score_details.get('accident_score', 0)

        # 计算业绩得分
        performance_score = self.calculate_performance_score(assessment)

        # 计算行为考核小计(排除特殊项)
        behavior_raw = sum(
            score for key, score in score_details.items()
            if key not in ['performance_score', 'accident_score', 'extra_bonus', 'shop_activation']
        )

        # 构建消息
        lines = [
            f"【绩效考核通知】",
            f"📋 **考核信息**：{assessment.get_assess_type_display()} | {assessment.month[:4]}年{assessment.month[5:]}月",
            f"👥 **操作人员**：{operator.first_name}",
            f"📝 **操作类型**：{operation_type}",
            "",
            f"📊 **评分汇总**：",
            f"• 业绩得分：{performance_score:.2f} / {performance_score:.2f}",
            f"• 行为考核：{behavior_raw:.2f} / {behavior_raw:.2f}",
        ]

        # 🔥 关键修复：只有实际扣分（>0）才显示
        if accident_score > 0:
            lines.append(f"• 事故扣分：-{accident_score:.2f}")

        # 🔥 关键修复：只有实际加分（>0）才显示
        extra_bonus = score_details.get('extra_bonus', 0)
        if extra_bonus > 0:
            lines.append(f"• 超额完成：+{extra_bonus:.2f}")

        shop_activation = score_details.get('shop_activation', 0)
        if shop_activation > 0:
            lines.append(f"• 店铺激活：+{shop_activation:.2f}")

        # 最终得分
        if final_score is not None:
            grade_level = self.calculate_grade_level(final_score, assessment.assess_type)
            lines.append(f"")
            lines.append(f"🏆 **最终得分**：**{final_score:.2f}** ({grade_level})")

        # 额外上下文(驳回原因等)
        if extra_context and extra_context.get('reject_reason'):
            lines.append(f"")
            lines.append(f"❌ **驳回原因**：{extra_context['reject_reason']}")

        lines.extend([
            "",
            f"✅ **当前状态**：{assessment.get_status_display()}",
            f"⏰ **操作时间**：{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}"
        ])

        return "\n".join(lines)

    def calculate_actual_orders_and_update(self, assessment):
        """
        计算并更新实际订单量（有效销量，排除退货）
        同时更新 achievement_rate 和 shop_activation
        支持亚马逊 + Temu 双平台自动识别
        """
        user = assessment.employee

        # 1. 获取该员工负责的所有店铺（分平台）
        amazon_shops = AmazonShop.objects.filter(ops=user).values_list('id', flat=True)
        temu_shops = TemuShop.objects.filter(ops_id=user.id).values_list('id', flat=True)

        if not amazon_shops and not temu_shops:
            return

        # 2. 解析考核月份范围
        year, month = map(int, assessment.month.split('-'))
        start_date = datetime(year, month, 1).date()
        if month == 12:
            end_date = datetime(year + 1, 1, 1).date() - timedelta(days=1)
        else:
            end_date = datetime(year, month + 1, 1).date() - timedelta(days=1)

        # 3. 初始化有效销量
        valid_sales_quantity = 0
        # 新增：初始化Temu店铺激活数量
        shop_activation_score = 0

        # 4. 统计亚马逊平台（保持不变）
        if amazon_shops:
            lingxing_shops = LingXingAmazonShop.objects.filter(
                amazon_shop_id__in=list(amazon_shops)
            )
            if lingxing_shops:
                lingxing_shop_ids = list(lingxing_shops.values_list('sid', flat=True))

                all_orders = AmazonOrders.objects.filter(
                    lingxing_shop_id__in=lingxing_shop_ids,
                    purchase_date_local__date__gte=start_date,
                    purchase_date_local__date__lte=end_date
                )

                cancelled_orders = all_orders.filter(order_status='Canceled')
                all_items = AmazonOrderItem.objects.filter(order__in=all_orders)
                return_items = AmazonOrderItem.objects.filter(order__in=cancelled_orders)

                total_quantity = all_items.aggregate(total=Sum('quantity_ordered'))['total'] or 0
                return_quantity = return_items.aggregate(total=Sum('quantity_ordered'))['total'] or 0

                valid_sales_quantity += (total_quantity - return_quantity)

        # 5. 统计Temu平台（核心修改）
        if temu_shops:
            lingxing_temu_shops = LingXingTemuShop.objects.filter(
                temu_shop_id__in=list(temu_shops)
            )
            if lingxing_temu_shops:
                # 获取所有店铺ID
                temu_shop_records = list(lingxing_temu_shops.values('store_id', 'temu_shop_id'))

                # 遍历每个店铺，单独统计订单量
                for shop_record in temu_shop_records:
                    store_id = shop_record['store_id']
                    temu_shop_id = shop_record['temu_shop_id']

                    # 统计该店铺当月的所有订单
                    shop_orders = TemuOrder.objects.filter(
                        lingxing_shop__store_id=store_id,
                        global_purchase_time__date__gte=start_date,
                        global_purchase_time__date__lte=end_date
                    ).values('global_order_no', 'platform_info')

                    shop_orders_list = list(shop_orders)

                    # 排除取消订单
                    cancelled_order_nos = [
                        o['global_order_no'] for o in shop_orders_list
                        if o.get('platform_info') and len(o.get('platform_info', [])) > 0
                           and o['platform_info'][0].get('status') == 'CANCELED'
                    ]

                    # 统计该店铺的有效订单量
                    shop_all_items = TemuOrderItem.objects.filter(
                        order__global_order_no__in=[o['global_order_no'] for o in shop_orders_list]
                    )
                    shop_return_items = TemuOrderItem.objects.filter(
                        order__global_order_no__in=cancelled_order_nos
                    )

                    shop_total = shop_all_items.aggregate(total=Sum('quantity'))['total'] or 0
                    shop_return = shop_return_items.aggregate(total=Sum('quantity'))['total'] or 0
                    shop_valid_quantity = shop_total - shop_return

                    # 累加到总订单量
                    valid_sales_quantity += shop_valid_quantity

                    # 判断该店铺是否达标（订单量≥200）
                    if shop_valid_quantity >= 200:
                        shop_activation_score += 1

                    # print(
                    #     f"🏪 店铺统计: ShopID={temu_shop_id} | 销量={shop_valid_quantity} | 达标={shop_valid_quantity >= 200}")

        # 6. 更新考核数据
        assessment.actual_orders = valid_sales_quantity

        # 7. 计算达成率
        if assessment.target_orders > 0:
            achievement_rate = (valid_sales_quantity / assessment.target_orders) * 100
        else:
            achievement_rate = 0
        assessment.achievement_rate = round(achievement_rate, 2)

        # 8. 保存到数据库
        assessment.save()

        # 9. 关键：保存Temu店铺激活加分（仅Temu考核）
        if assessment.assess_type == 'temu_operation':
            PerformanceScoreDetail.objects.update_or_create(
                assessment=assessment,
                item_key='shop_activation',
                defaults={'score_value': shop_activation_score}
            )

        print(
            f"✅ 更新考核数据: {user.first_name} | {assessment.month} | 销量: {valid_sales_quantity}件 | 达成率: {assessment.achievement_rate}% | 店铺激活加分: {shop_activation_score}")

    def calculate_final_score(self, assessment):
        """计算最终总分（业绩达成得分 × 权重 + 行为考核得分 × 权重 + 加分项）"""

        # 1. 设置权重
        if assessment.assess_type == 'temu_operation':
            kpi_weight = Decimal('0.7')
            behavior_weight = Decimal('0.3')
        elif assessment.assess_type == 'amazon_operation':
            kpi_weight = Decimal('0.6')
            behavior_weight = Decimal('0.4')
        else:  # amazon_assistant
            kpi_weight = Decimal('0.3')
            behavior_weight = Decimal('0.7')

        # 2. 计算业绩得分
        performance_score = Decimal(str(self.calculate_performance_score(assessment)))

        # 3. 获取评分项
        details = assessment.score_details.all()
        details_dict = {d.item_key: Decimal(str(d.score_value)) for d in details}

        # 4. 计算超额完成业绩（仅超额部分，不合并shop_activation）
        achievement_rate = assessment.achievement_rate
        extra_bonus = Decimal('0')
        if achievement_rate > 100:
            extra_bonus = Decimal(str(int(achievement_rate - 100)))

        # 关键修复：不更新details_dict，保持extra_bonus独立

        # 5. 计算KPI总分（业绩得分 + 事故分）* 权重
        accident_score = details_dict.get('accident_score', Decimal('0'))
        kpi_raw = performance_score + accident_score
        kpi_total = kpi_raw * kpi_weight

        # 6. 计算行为考核总分 * 权重
        exclude_keys = {'performance_score', 'accident_score', 'extra_bonus', 'shop_activation'}
        behavior_raw = sum(
            score for key, score in details_dict.items()
            if key not in exclude_keys
        )
        behavior_total = behavior_raw * behavior_weight

        # 7. 获取店铺激活加分（仅Temu，不合并到extra_bonus）
        shop_activation = Decimal('0')
        if assessment.assess_type == 'temu_operation':
            shop_activation = details_dict.get('shop_activation', Decimal('0'))

        # 8. 计算最终得分（关键修复：分别加上两个加分项）

        final_score = kpi_total + behavior_total + extra_bonus + shop_activation
        print(f"计算最终得分: KPI={kpi_total} | 行为={behavior_total} | 超额完成={extra_bonus} | 店铺激活={shop_activation} => 最终得分={final_score}")
        # 9. 返回时明确extra_bonus仅超额部分
        return round(final_score, 2), extra_bonus


class AssessmentListView(AssessmentManagementView, ListView):
    """考核列表视图"""
    model = PerformanceAssessment
    template_name = 'assessment_management_list.html'
    context_object_name = 'assessments'
    paginate_by = 20

    def get_queryset(self):
        """根据权限过滤可查看的考核"""
        user = self.request.user

        queryset = PerformanceAssessment.objects.select_related(
            'employee', 'leader', 'performance_target'
        ).prefetch_related('score_details')

        # 筛选参数
        month = self.request.GET.get('month')
        employee_id = self.request.GET.get('employee')
        assess_type = self.request.GET.get('assess_type')
        status = self.request.GET.get('status')

        if month:
            queryset = queryset.filter(month=month)
        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)
        if assess_type:
            queryset = queryset.filter(assess_type=assess_type)
        if status:
            queryset = queryset.filter(status=status)

        # 权限过滤
        if self.is_admin(user):
            pass
        elif self.is_group_leader(user):
            if user.operational_account and user.operational_account.ops_group:
                queryset = queryset.filter(
                    employee__operational_account__ops_group=user.operational_account.ops_group
                )
            else:
                queryset = queryset.none()
        else:
            queryset = queryset.filter(employee=user)

        return queryset.order_by('-month', '-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_admin'] = self.is_admin(self.request.user)

        # 下面的代码你模板里需要用到，所以也加上
        context['employees'] = User.objects.filter(
            assessments__isnull=False
        ).distinct().order_by('first_name')
        context['type_choices'] = PerformanceAssessment.ASSESSMENT_TYPES
        context['status_choices'] = PerformanceAssessment.STATUS_CHOICES
        context['active_page'] = 'assessment_list'

        try:
            current_user = self.request.user
            perms_raw = getattr(current_user, 'permission', '') or ''
            perms_list = [p.strip() for p in str(perms_raw).split(',') if p.strip()]
            assessments_page = context.get('assessments') or context.get('object_list') or []
            status_counts = {}
            for a in assessments_page:
                status_counts[a.status] = status_counts.get(a.status, 0) + 1
            print(
                f"[assessment_list] user_id={getattr(current_user, 'id', None)} "
                f"username={getattr(current_user, 'username', '')} "
                f"is_superuser={getattr(current_user, 'is_superuser', False)} "
                f"permission_raw={perms_raw!r} "
                f"permission_list={perms_list} "
                f"is_admin={context['is_admin']} "
                f"page_status_counts={status_counts}"
            )
        except Exception as e:
            print(f"[assessment_list] debug_print_failed: {e}")

        return context


class CreateBatchAssessmentView(AssessmentManagementView):
    """批量创建考核"""

    @transaction.atomic
    def post(self, request):
        if not self.is_admin(request.user):
            return JsonResponse({'success': False, 'message': '只有管理员可以创建考核'}, status=403)

        month = request.POST.get('month')
        if not month:
            return JsonResponse({'success': False, 'message': '请选择考核月份'}, status=400)

        users_to_assess = []

        # Temu运营
        temu_users = User.objects.filter(
            platform='Temu',
            role='运营',
            operational_account__isnull=False
        ).select_related('operational_account')
        users_to_assess.extend([
            (user, 'temu_operation', user.operational_account.ops_group)
            for user in temu_users if user.operational_account.ops_group
        ])

        # 亚马逊运营
        amazon_users = User.objects.filter(
            platform='亚马逊',
            role='运营',
            operational_account__isnull=False
        ).select_related('operational_account')
        users_to_assess.extend([
            (user, 'amazon_operation', user.operational_account.ops_group)
            for user in amazon_users if user.operational_account.ops_group
        ])

        # 亚马逊运营助理
        assistant_users = User.objects.filter(
            platform='亚马逊',
            role='运营助理',
            operational_account__isnull=False
        ).select_related('operational_account')
        users_to_assess.extend([
            (user, 'amazon_assistant', user.operational_account.ops_group)
            for user in assistant_users if user.operational_account.ops_group
        ])

        if not users_to_assess:
            return JsonResponse({'success': False, 'message': '没有找到需要考核的人员'}, status=400)

        created_count = 0
        skipped_count = 0

        for user, assess_type, ops_group in users_to_assess:
            if PerformanceAssessment.objects.filter(
                    employee=user,
                    month=month,
                    assess_type=assess_type
            ).exists():
                skipped_count += 1
                continue

            leader = User.objects.filter(
                role='运营组长',
                operational_account__ops_group=ops_group
            ).first()

            if not leader:
                skipped_count += 1
                continue

            try:
                target = PersonalPerformanceTarget.objects.get(
                    user=user,
                    month=month + '-01'
                )
            except PersonalPerformanceTarget.DoesNotExist:
                skipped_count += 1
                continue

            assessment = PerformanceAssessment.objects.create(
                assess_type=assess_type,
                month=month,
                employee=user,
                leader=leader,
                performance_target=target,
                target_orders=target.target_performance,
                actual_orders=0,
                achievement_rate=0,
                performance_score=0
            )

            configs = AssessmentItemConfig.objects.filter(assess_type=assess_type)
            score_details = [
                PerformanceScoreDetail(
                    assessment=assessment,
                    item_key=config.item_key,
                    score_value=0
                )
                for config in configs
            ]
            PerformanceScoreDetail.objects.bulk_create(score_details)
            # 自动计算订单数据
            if assess_type in ['amazon_operation', 'amazon_assistant']:
                try:
                    self.calculate_actual_orders_and_update(assessment)
                except Exception as e:
                    print(f"自动计算订单数据失败: {assessment.id} - {e}")
            created_count += 1

        UserOperationLog.objects.create(
            user=request.user,
            operation_type=UserOperationLog.ASSESSMENT_CREATE,
            operation_record=f'批量创建{month}月份考核，成功{created_count}条，跳过{skipped_count}条'
        )

        messages.success(request, f'批量创建完成！成功 {created_count} 条，跳过 {skipped_count} 条')
        return JsonResponse({
            'success': True,
            'created_count': created_count,
            'skipped_count': skipped_count
        })


class AssessmentEditView(AssessmentManagementView, DetailView):
    """考核编辑/详情视图"""
    model = PerformanceAssessment
    template_name = 'assessment_form.html'
    context_object_name = 'assessment'

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if not (self.is_admin(self.request.user) or
                self.request.user == obj.leader or
                self.request.user == obj.employee):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied("您无权查看此考核")
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        assessment = self.object

        configs = AssessmentItemConfig.objects.filter(
            assess_type=assessment.assess_type
        ).order_by('sort_order')

        scores = {
            detail.item_key: detail.score_value
            for detail in assessment.score_details.all()
        }

        performance_score = self.calculate_performance_score(assessment)
        final_score, extra_bonus = self.calculate_final_score(assessment)

        if assessment.assess_type == 'temu_operation':
            kpi_weight = 70
            behavior_weight = 30
        elif assessment.assess_type == 'amazon_operation':
            kpi_weight = 60
            behavior_weight = 40
        else:
            kpi_weight = 30
            behavior_weight = 70

        from yuser.templatetags.yuser_extras import get_special_rules
        special_rules = get_special_rules(assessment.assess_type)

        context.update({
            'configs': configs,
            'scores': scores,
            'performance_score': performance_score,
            'final_score': final_score,
            'kpi_weight': kpi_weight,
            'behavior_weight': behavior_weight,
            'special_rules': special_rules,
            'grade_rules': self.get_grade_rules(assessment.assess_type),
            'can_edit': self.can_edit(assessment),
            'can_submit': self.can_submit(assessment),
            'can_confirm': self.can_confirm(assessment),
            'can_reject': self.can_reject(assessment),
            'is_admin': self.is_admin(self.request.user),
        })

        return context


# ========== 状态流转视图 ==========

class SubmitToMemberView(AssessmentManagementView):
    """组长提交考核给组员确认"""

    @transaction.atomic
    def post(self, request, pk):
        assessment = get_object_or_404(PerformanceAssessment, pk=pk)

        # 权限校验
        if request.user != assessment.leader:
            return JsonResponse({'success': False, 'message': '无权操作'}, status=403)

        # 状态校验
        if assessment.status != 'draft':
            return JsonResponse({'success': False, 'message': '考核状态不正确'}, status=400)

        # 保存评分项
        for key, value in request.POST.items():
            if key.startswith('item_') or key in ['extra_bonus', 'shop_activation']:
                clean_key = key.replace('item_', '', 1) if key.startswith('item_') else key
                PerformanceScoreDetail.objects.update_or_create(
                    assessment=assessment,
                    item_key=clean_key,
                    defaults={'score_value': float(value)}
                )

        # 确保事故分也被保存
        accident_input = request.POST.get('item_accident_score', '0')
        PerformanceScoreDetail.objects.update_or_create(
            assessment=assessment,
            item_key='accident_score',
            defaults={'score_value': float(accident_input)}
        )

        # 关键新增：自动计算并保存extra_bonus
        # 重新计算达成率对应的加分
        achievement_rate = assessment.achievement_rate
        extra_bonus = Decimal('0')
        if achievement_rate > 100:
            extra_bonus = Decimal(str(int(achievement_rate - 100)))

        # 保存到数据库
        PerformanceScoreDetail.objects.update_or_create(
            assessment=assessment,
            item_key='extra_bonus',
            defaults={'score_value': extra_bonus}
        )

        # 更新考核总分
        assessment.performance_score = self.calculate_performance_score(assessment)
        final_score, _ = self.calculate_final_score(assessment)  # 重新计算最终得分
        assessment.final_score = final_score
        assessment.status = 'pending_member'
        assessment.save()
        # 【★ 新增】同步发送企业微信通知
        try:
            # 构建消息
            message = self._build_notification_message(
                assessment=assessment,
                operator=request.user,
                operation_type='组长提交考核',
                final_score=final_score
            )

            # 发送给组员
            if assessment.employee.wx_url:
                from api.WX.wx import send_wechat_work_message
                send_wechat_work_message(
                    webhook_url=assessment.employee.wx_url,
                    markdown_content=message
                )
        except Exception as e:
            # 静默失败，只记录日志
            print(f"通知发送失败(静默): {str(e)}")
        UserOperationLog.objects.create(
            user=request.user,
            operation_type=UserOperationLog.ASSESSMENT_SUBMIT,
            operation_record=f'提交考核(ID:{assessment.id})给组员{assessment.employee.first_name}确认'
        )

        messages.success(request, f'已提交给 {assessment.employee.first_name} 确认')
        return JsonResponse({'success': True})


class MemberConfirmView(AssessmentManagementView):
    """组员确认考核"""

    def post(self, request, pk):
        assessment = get_object_or_404(PerformanceAssessment, pk=pk)

        if request.user != assessment.employee:
            return JsonResponse({'success': False, 'message': '无权操作'}, status=403)

        if assessment.status != 'pending_member':
            return JsonResponse({'success': False, 'message': '考核状态不正确'}, status=400)

        assessment.status = 'pending_leader'
        assessment.member_confirmed_at = timezone.now()
        assessment.save()
        # 【★ 新增】同步发送企业微信通知
        try:
            message = self._build_notification_message(
                assessment=assessment,
                operator=request.user,
                operation_type='组员确认考核'
            )

            if assessment.leader and assessment.leader.wx_url:
                from api.WX.wx import send_wechat_work_message
                send_wechat_work_message(
                    webhook_url=assessment.leader.wx_url,
                    markdown_content=message
                )
        except Exception as e:
            print(f"通知发送失败(静默): {str(e)}")
        UserOperationLog.objects.create(
            user=request.user,
            operation_type=UserOperationLog.ASSESSMENT_MEMBER_CONFIRM,
            operation_record=f'确认组长{assessment.leader.first_name}的考核'
        )

        messages.success(request, '确认成功，等待组长最终确认')
        return JsonResponse({'success': True})


class MemberRejectView(AssessmentManagementView):
    """组员驳回考核"""

    @transaction.atomic
    def post(self, request, pk):
        assessment = get_object_or_404(PerformanceAssessment, pk=pk)

        if request.user != assessment.employee:
            return JsonResponse({'success': False, 'message': '无权操作'}, status=403)

        if assessment.status != 'pending_member':
            return JsonResponse({'success': False, 'message': '考核状态不正确'}, status=400)

        comment = request.POST.get('comment', '').strip()
        if not comment:
            return JsonResponse({'success': False, 'message': '请填写驳回原因'}, status=400)

        assessment.status = 'draft'
        assessment.save()
        # 【★ 新增】同步发送企业微信通知
        try:
            message = self._build_notification_message(
                assessment=assessment,
                operator=request.user,
                operation_type='组员驳回考核',
                extra_context={'reject_reason': comment}
            )

            if assessment.leader and assessment.leader.wx_url:
                from api.WX.wx import send_wechat_work_message
                send_wechat_work_message(
                    webhook_url=assessment.leader.wx_url,
                    markdown_content=message
                )
        except Exception as e:
            print(f"通知发送失败(静默): {str(e)}")
        UserOperationLog.objects.create(
            user=request.user,
            operation_type=UserOperationLog.ASSESSMENT_MEMBER_REJECT,
            operation_record=f'驳回组长{assessment.leader.first_name}的考核，原因：{comment}'
        )

        messages.warning(request, f'已驳回考核，组长可重新编辑')
        return JsonResponse({'success': True})


class LeaderFinalConfirmView(AssessmentManagementView):
    """组长最终确认并锁定考核"""

    @transaction.atomic
    def post(self, request, pk):
        assessment = get_object_or_404(PerformanceAssessment, pk=pk)

        if request.user != assessment.leader:
            return JsonResponse({'success': False, 'message': '无权操作'}, status=403)

        if assessment.status != 'pending_leader':
            return JsonResponse({'success': False, 'message': '考核状态不正确'}, status=400)

        try:
            # 计算最终得分并保存extra_bonus
            final_score, extra_bonus = self.calculate_final_score(assessment)

            # 保存extra_bonus到数据库
            PerformanceScoreDetail.objects.update_or_create(
                assessment=assessment,
                item_key='extra_bonus',
                defaults={'score_value': extra_bonus}
            )

            snapshot_data = self.generate_snapshot(assessment, final_score)

            AssessmentHistory.objects.create(
                assessment=assessment,
                snapshot_data=snapshot_data
            )

            assessment.status = 'confirmed'
            assessment.is_locked = True
            assessment.final_score = final_score
            assessment.leader_confirmed_at = timezone.now()
            assessment.save()
            # 【★ 新增】同步发送企业微信通知
            try:
                message = self._build_notification_message(
                    assessment=assessment,
                    operator=request.user,
                    operation_type='组长最终确认并锁定',
                    final_score=final_score
                )

                if assessment.employee.wx_url:
                    from api.WX.wx import send_wechat_work_message
                    send_wechat_work_message(
                        webhook_url=assessment.employee.wx_url,
                        markdown_content=message
                    )
            except Exception as e:
                print(f"通知发送失败(静默): {str(e)}")
            UserOperationLog.objects.create(
                user=request.user,
                operation_type=UserOperationLog.ASSESSMENT_LEADER_CONFIRM,
                operation_record=f'最终确认并锁定{assessment.employee.first_name}的考核，得分：{final_score}'
            )

            return JsonResponse({
                'success': True,
                'final_score': final_score,
                'message': f'考核已锁定，最终得分：{final_score}'
            })

        except Exception as e:
            import traceback
            print(f"最终确认失败: {str(e)}")
            traceback.print_exc()
            return JsonResponse({
                'success': False,
                'message': f'操作失败: {str(e)}'
            }, status=500)

    def generate_snapshot(self, assessment, final_score):
        """生成完整快照数据"""
        score_details = []
        for detail in assessment.score_details.all():
            config = AssessmentItemConfig.objects.get(
                assess_type=assessment.assess_type,
                item_key=detail.item_key
            )
            score_details.append({
                'item_key': detail.item_key,
                'item_name': config.item_name,
                'category': config.category,
                'score_value': float(detail.score_value),
                'max_score': float(config.max_score),
            })

        return {
            'assessment': {
                'id': assessment.id,
                'assess_type': assessment.assess_type,
                'assess_type_display': assessment.get_assess_type_display(),
                'month': assessment.month,
                'employee': {
                    'id': assessment.employee.id,
                    'name': assessment.employee.first_name,
                    'username': assessment.employee.username,
                },
                'leader': {
                    'id': assessment.leader.id,
                    'name': assessment.leader.first_name,
                    'username': assessment.leader.username,
                },
                'target_orders': assessment.target_orders,
                'actual_orders': assessment.actual_orders,
                'achievement_rate': float(assessment.achievement_rate),
                'performance_score': float(assessment.performance_score),
                'final_score': float(final_score),
                'created_at': assessment.created_at.isoformat(),
                'confirmed_at': timezone.now().isoformat(),
            },
            'score_details': score_details,
        }


class AssessmentSubmitView(AssessmentManagementView):
    """提交考核（最后统一入库）"""

    @transaction.atomic
    def post(self, request, pk):
        assessment = get_object_or_404(PerformanceAssessment, pk=pk)

        # ===== 调试打印1：查看POST提交的数据 =====
        print(f"\n{'=' * 60}")
        print(f"🔍 调试：考核ID {pk} 提交的数据")
        print(f"{'=' * 60}")
        for key, value in request.POST.items():
            if key.startswith('item_') or key in ['extra_bonus', 'shop_activation']:
                print(f"POST字段: {key} = {value}")

        if not self.can_edit(assessment):
            return JsonResponse({'success': False, 'message': '无权操作或考核已提交'}, status=403)

        # ===== 调试打印2：保存前的数据库值 =====
        old_details = {d.item_key: float(d.score_value) for d in assessment.score_details.all()}
        print(f"\n保存前数据库中的score_details:")
        for k, v in old_details.items():
            print(f"  {k}: {v}")

        # 保存所有表单提交的评分项
        for key, value in request.POST.items():
            if key.startswith('item_') or key in ['extra_bonus', 'shop_activation']:
                clean_key = key.replace('item_', '', 1) if key.startswith('item_') else key
                PerformanceScoreDetail.objects.update_or_create(
                    assessment=assessment,
                    item_key=clean_key,
                    defaults={'score_value': float(value)}
                )
                print(f"✅ 已保存: {clean_key} = {value}")

        # ===== 调试打印3：计算过程中的值 =====
        print(f"\n计算过程:")
        print(f"  assess_type: {assessment.assess_type}")
        print(f"  achievement_rate: {assessment.achievement_rate}")

        assessment.performance_score = self.calculate_performance_score(assessment)
        print(f"  performance_score: {assessment.performance_score}")

        # 重新获取所有评分项（确保是最新值）
        details = assessment.score_details.all()
        details_dict = {d.item_key: float(d.score_value) for d in details}
        print(f"\n保存后重新读取的score_details:")
        for k, v in details_dict.items():
            print(f"  {k}: {v}")

        final_score, extra_bonus = self.calculate_final_score(assessment)

        # ===== 调试打印4：最终结果 =====
        print(f"\n计算结果:")
        print(f"  shop_activation: {details_dict.get('shop_activation', 0)}")
        print(
            f"  extra_bonus (超额部分): {int(assessment.achievement_rate - 100) if assessment.achievement_rate > 100 else 0}")
        print(f"  extra_bonus (合并后): {extra_bonus}")
        print(f"  final_score: {final_score}")
        print(f"{'=' * 60}\n")

        # 强制保存计算后的完整extra_bonus到数据库
        PerformanceScoreDetail.objects.update_or_create(
            assessment=assessment,
            item_key='extra_bonus',
            defaults={'score_value': extra_bonus}
        )

        assessment.final_score = final_score
        assessment.save()

        return JsonResponse({'success': True})


class RefreshOrderDataView(AssessmentManagementView):
    """手动刷新订单数据"""

    def post(self, request, pk):
        assessment = get_object_or_404(PerformanceAssessment, pk=pk)

        is_admin = self.is_admin(request.user)
        can_refresh = is_admin or self.can_edit(assessment) or self.can_submit(assessment)

        if not can_refresh:
            return JsonResponse({'success': False, 'message': '无权操作'}, status=403)

        if assessment.assess_type not in ['amazon_operation', 'amazon_assistant', 'temu_operation']:
            return JsonResponse({'success': False, 'message': '不支持的考核类型'}, status=400)

        try:
            # 1. 刷新订单数据（更新actual_orders、achievement_rate和shop_activation）
            self.calculate_actual_orders_and_update(assessment)

            # 2. 重新计算业绩得分和最终得分（包含extra_bonus）
            performance_score = self.calculate_performance_score(assessment)
            final_score, extra_bonus = self.calculate_final_score(assessment)

            # 3. 关键：立即保存extra_bonus到数据库（Temu和亚马逊都有）
            PerformanceScoreDetail.objects.update_or_create(
                assessment=assessment,
                item_key='extra_bonus',
                defaults={'score_value': extra_bonus}
            )

            # 4. 获取shop_activation的值（仅Temu有）
            shop_activation = 0
            if assessment.assess_type == 'temu_operation':
                shop_activation_detail = assessment.score_details.filter(
                    item_key='shop_activation'
                ).first()
                if shop_activation_detail:
                    shop_activation = float(shop_activation_detail.score_value)

            # 5. 返回更新后的数据给前端
            return JsonResponse({
                'success': True,
                'message': f'订单数据已刷新，有效销量：{assessment.actual_orders}件，最终得分：{final_score}',
                'data': {
                    'actual_orders': assessment.actual_orders,
                    'achievement_rate': float(assessment.achievement_rate),
                    'performance_score': float(performance_score),
                    'final_score': float(final_score),
                    'extra_bonus': float(extra_bonus),
                    'shop_activation': shop_activation  # 新增返回字段（仅Temu）
                }
            })
        except Exception as e:
            print(f"刷新失败: {e}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'message': f'刷新失败: {str(e)}'}, status=500)


class BatchRefreshOrdersView(AssessmentManagementView):
    """批量刷新订单数据（管理员专用）"""

    @transaction.atomic
    def post(self, request):
        if not self.is_admin(request.user):
            return JsonResponse({'success': False, 'message': '只有管理员可以批量刷新'}, status=403)

        month = request.POST.get('month')
        employee_id = request.POST.get('employee')
        assess_type = request.POST.get('assess_type')
        status = request.POST.get('status')

        queryset = PerformanceAssessment.objects.select_related('employee')

        if month:
            queryset = queryset.filter(month=month)
        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)
        if assess_type:
            queryset = queryset.filter(assess_type=assess_type)
        if status:
            queryset = queryset.filter(status=status)

        queryset = queryset.filter(
            assess_type__in=['amazon_operation', 'amazon_assistant', 'temu_operation']
        )
        total_count = queryset.count()
        if total_count == 0:
            return JsonResponse({
                'success': False,
                'message': '没有找到符合条件的考核记录'
            }, status=400)

        success_count = 0
        failed_count = 0
        errors = []

        for assessment in queryset:
            try:
                # 1. 刷新订单数据（会更新actual_orders、achievement_rate，Temu还会保存shop_activation）
                self.calculate_actual_orders_and_update(assessment)

                # 2. 关键新增：计算extra_bonus并保存
                # 重新计算业绩得分和最终得分
                final_score, extra_bonus = self.calculate_final_score(assessment)

                # 保存extra_bonus到数据库
                PerformanceScoreDetail.objects.update_or_create(
                    assessment=assessment,
                    item_key='extra_bonus',
                    defaults={'score_value': extra_bonus}
                )

                success_count += 1
            except Exception as e:
                failed_count += 1
                errors.append(f'{assessment.employee.first_name}({assessment.id}): {str(e)}')
                print(f"刷新失败: {assessment.id} - {e}")
                import traceback
                traceback.print_exc()

        UserOperationLog.objects.create(
            user=request.user,
            operation_type=UserOperationLog.ASSESSMENT_BATCH_REFRESH,
            operation_record=f'批量刷新{total_count}条考核订单数据，成功{success_count}条，失败{failed_count}条'
        )

        return JsonResponse({
            'success': True,
            'message': f'批量刷新完成！成功 {success_count} 条，失败 {failed_count} 条',
            'data': {
                'total': total_count,
                'success': success_count,
                'failed': failed_count,
                'errors': errors if failed_count > 0 else None
            }
        })


class AssessmentDeleteView(AssessmentManagementView):
    @transaction.atomic
    def post(self, request, pk):
        if not self.is_admin(request.user):
            return JsonResponse({'success': False, 'message': '只有管理员可以删除考核'}, status=403)

        assessment = get_object_or_404(PerformanceAssessment, pk=pk)

        if assessment.status != 'draft':
            return JsonResponse({'success': False, 'message': '仅支持删除组长评分中的考核'}, status=400)

        assessment.delete()
        return JsonResponse({'success': True})
