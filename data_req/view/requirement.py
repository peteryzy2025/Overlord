import json
from datetime import datetime, timedelta
from calendar import monthrange
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.views import View
from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.utils import timezone
from general.models import User
from data_req.models import DataRequirement, RequirementTimeline


class RequirementListView(LoginRequiredMixin, ListView):
    """需求列表页面"""
    model = DataRequirement
    template_name = 'data_req/requirement_list.html'
    context_object_name = 'requirements'
    paginate_by = 20

    def get_paginate_by(self, queryset):
        """支持动态每页条数"""
        page_size = self.request.GET.get('page_size')
        if page_size:
            try:
                return int(page_size)
            except ValueError:
                pass
        return self.paginate_by

    def get_queryset(self):
        queryset = DataRequirement.objects.all().select_related('requester', 'developer')
        status = self.request.GET.get('status')
        priority = self.request.GET.get('priority')
        req_type = self.request.GET.get('type')
        developer_id = self.request.GET.get('developer')
        requester_id = self.request.GET.get('requester')
        keyword = self.request.GET.get('keyword', '').strip()
        time_filter = self.request.GET.get('time_filter', '')
        custom_start = self.request.GET.get('custom_start', '')
        custom_end = self.request.GET.get('custom_end', '')

        if status:
            queryset = queryset.filter(status=status)
        if priority:
            queryset = queryset.filter(priority=priority)
        if req_type:
            queryset = queryset.filter(requirement_type=req_type)
        if developer_id:
            queryset = queryset.filter(developer_id=developer_id)
        if requester_id:
            queryset = queryset.filter(requester_id=requester_id)
        if keyword:
            queryset = queryset.filter(Q(name__icontains=keyword))

        if time_filter:
            today = timezone.now().date()
            if time_filter == 'this_month':
                start_date = today.replace(day=1)
                last_day = monthrange(today.year, today.month)[1]
                end_date = today.replace(day=last_day)
                queryset = queryset.filter(finish_date__date__gte=start_date, finish_date__date__lte=end_date)
            elif time_filter == 'last_month':
                first_day_this_month = today.replace(day=1)
                last_day_last_month = first_day_this_month - timedelta(days=1)
                start_date = last_day_last_month.replace(day=1)
                end_date = last_day_last_month
                queryset = queryset.filter(finish_date__date__gte=start_date, finish_date__date__lte=end_date)
            elif time_filter == 'custom' and custom_start and custom_end:
                queryset = queryset.filter(finish_date__date__gte=custom_start, finish_date__date__lte=custom_end)

        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['stats'] = {
            'total': DataRequirement.objects.count(),
            'completed': DataRequirement.objects.filter(status='completed').count(),
            'developing': DataRequirement.objects.filter(status='developing').count(),
            'pending': DataRequirement.objects.filter(status='pending').count(),
        }

        requirements = context['requirements']
        for req in requirements:
            # 开发开始日期显示
            start_date = req.start_date
            req.start_date_display = start_date.strftime('%Y-%m-%d') if start_date else '-'

            # 预计完成天数（预计完成日期 - 开发开始日期）
            if req.start_date and req.expected_finish:
                delta = req.expected_finish.date() - req.start_date.date()
                req.expected_days = delta.days + 1 if delta.days >= 0 else 0
            else:
                req.expected_days = None

            # 实际完成天数（完成日期 - 开发开始日期）
            if req.start_date and req.finish_date:
                delta = req.finish_date.date() - req.start_date.date()
                req.actual_days = delta.days + 1 if delta.days >= 0 else 0
            else:
                req.actual_days = None
        context['developers'] = User.objects.filter(status=1, permission_configs__code=554).distinct().order_by('first_name')
        context['requesters'] = User.objects.filter(status=1).order_by('first_name')
        context['systems'] = DataRequirement.objects.filter(requirement_type='system').order_by('-created_at')
        context['simple_tasks'] = DataRequirement.objects.filter(requirement_type='simple').order_by('-created_at')

        user = self.request.user
        context['is_developer'] = user.permission_configs.filter(code=554).exists()
        context['is_dev_admin'] = user.permission_configs.filter(code=5555).exists()

        context['current_filters'] = {
            'status': self.request.GET.get('status', ''),
            'priority': self.request.GET.get('priority', ''),
            'type': self.request.GET.get('type', ''),
            'developer': self.request.GET.get('developer', ''),
            'requester': self.request.GET.get('requester', ''),
            'keyword': self.request.GET.get('keyword', ''),
            'time_filter': self.request.GET.get('time_filter', ''),
            'custom_start': self.request.GET.get('custom_start', ''),
            'custom_end': self.request.GET.get('custom_end', ''),
        }

        developer_id = self.request.GET.get('developer')
        time_filter = self.request.GET.get('time_filter', '')
        custom_start = self.request.GET.get('custom_start', '')
        custom_end = self.request.GET.get('custom_end', '')

        context['show_score_stats'] = False
        context['score_stats'] = {'developer_name': '', 'total_score': 0, 'task_count': 0, 'period': ''}

        if developer_id and time_filter:
            try:
                developer = User.objects.get(id=developer_id)
                stats_queryset = DataRequirement.objects.filter(developer_id=developer_id, status='completed',
                                                                requirement_type='simple')
                today = timezone.now().date()
                period_text = ''

                if time_filter == 'this_month':
                    start_date = today.replace(day=1)
                    last_day = monthrange(today.year, today.month)[1]
                    end_date = today.replace(day=last_day)
                    stats_queryset = stats_queryset.filter(finish_date__date__gte=start_date,
                                                           finish_date__date__lte=end_date)
                    period_text = f"{today.year}年{today.month}月"
                elif time_filter == 'last_month':
                    first_day_this_month = today.replace(day=1)
                    last_day_last_month = first_day_this_month - timedelta(days=1)
                    start_date = last_day_last_month.replace(day=1)
                    end_date = last_day_last_month
                    stats_queryset = stats_queryset.filter(finish_date__date__gte=start_date,
                                                           finish_date__date__lte=end_date)
                    period_text = f"{last_day_last_month.year}年{last_day_last_month.month}月"
                elif time_filter == 'custom' and custom_start and custom_end:
                    stats_queryset = stats_queryset.filter(finish_date__date__gte=custom_start,
                                                           finish_date__date__lte=custom_end)
                    period_text = f"{custom_start} 至 {custom_end}"

                total_score = stats_queryset.aggregate(total=Sum('score'))['total'] or 0
                task_count = stats_queryset.count()

                context['show_score_stats'] = True
                context['score_stats'] = {
                    'developer_name': developer.first_name or developer.username,
                    'total_score': round(total_score, 1),
                    'task_count': task_count,
                    'period': period_text
                }
            except User.DoesNotExist:
                pass

        return context


class RequirementDetailView(LoginRequiredMixin, DetailView):
    model = DataRequirement
    template_name = 'data_req/requirement_detail.html'
    context_object_name = 'requirement'
    pk_url_kwarg = 'pk'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        req = self.object
        context['children'] = req.children.select_related('developer').all()
        context['extended_tasks'] = req.extended_tasks.select_related('developer').all()
        context['timelines'] = req.timelines.select_related('operator').order_by('-timestamp')[:20]
        if req.requirement_type == 'system':
            context['total_score'] = req.get_actual_score()
        user = self.request.user
        context['is_developer'] = user.permission_configs.filter(code=554).exists()
        context['is_dev_admin'] = user.permission_configs.filter(code=5555).exists()
        return context


class RequirementCreateAPI(LoginRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            developer_id = data.get('developer') or None
            now = timezone.now()

            if developer_id:
                status = 'claimed'
                claim_date = now
            else:
                status = 'pending'
                claim_date = None

            req = DataRequirement.objects.create(
                name=data.get('name'),
                requirement_type=data.get('requirement_type', 'simple'),
                priority=data.get('priority', 'P2'),
                score=float(data.get('score')) if data.get('score') else None,
                parent_id=data.get('parent') or None,
                extends_from_id=data.get('extends_from') or None,
                requester_id=data.get('requester') or None,
                developer_id=developer_id,
                publish_date=data.get('publish_date'),
                expected_finish=data.get('expected_finish') or None,
                remark=data.get('remark', ''),
                status=status,
                claim_date=claim_date
            )

            if developer_id:
                RequirementTimeline.objects.create(requirement=req, action='claim', operator=request.user,
                                                   reason='创建需求时自动领取')
            else:
                RequirementTimeline.objects.create(requirement=req, action='', operator=request.user, reason='需求创建')

            return JsonResponse({'success': True, 'message': '需求创建成功', 'data': {'id': req.id, 'name': req.name}})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class RequirementUpdateAPI(LoginRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            req_id = data.get('id')
            req = DataRequirement.objects.get(id=req_id)
            new_developer_id = data.get('developer') or None
            old_developer_id = req.developer_id if req.developer else None
            now = timezone.now()
            unclaim_reason = data.get('unclaim_reason', '')

            if not old_developer_id and new_developer_id:
                req.status = 'claimed'
                req.claim_date = now
                auto_claimed = True
                auto_unclaimed = False
            elif old_developer_id and not new_developer_id:
                if not unclaim_reason:
                    return JsonResponse(
                        {'success': False, 'message': 'need_reason', 'detail': '取消开发者时需要填写原因'})
                req.status = 'pending'
                req.claim_date = None
                req.start_date = None
                req.finish_date = None
                auto_claimed = False
                auto_unclaimed = True
            else:
                auto_claimed = False
                auto_unclaimed = False

            req.name = data.get('name', req.name)
            req.priority = data.get('priority', req.priority)
            req.score = float(data.get('score')) if data.get('score') else None
            req.parent_id = data.get('parent') or None
            req.extends_from_id = data.get('extends_from') or None
            req.requester_id = data.get('requester') or None
            req.developer_id = new_developer_id
            req.publish_date = data.get('publish_date', req.publish_date)
            req.expected_finish = data.get('expected_finish') or None
            req.finish_date = data.get('finish_date') or None
            req.remark = data.get('remark', '')
            if req.status == 'paused' and data.get('pause_reason'):
                req.pause_reason = data.get('pause_reason')
            req.save()

            if auto_claimed:
                RequirementTimeline.objects.create(requirement=req, action='claim', operator=request.user,
                                                   reason='编辑时自动领取')
            elif auto_unclaimed:
                RequirementTimeline.objects.create(requirement=req, action='unclaim', operator=request.user,
                                                   reason=f'取消开发者（退领）：{unclaim_reason}')

            return JsonResponse({'success': True, 'message': '需求更新成功',
                                 'data': {'id': req.id, 'name': req.name, 'new_status': req.status,
                                          'auto_claimed': auto_claimed, 'auto_unclaimed': auto_unclaimed}})
        except DataRequirement.DoesNotExist:
            return JsonResponse({'success': False, 'message': '需求不存在'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class RequirementDeleteAPI(LoginRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            req_id = data.get('id')
            req = DataRequirement.objects.get(id=req_id)
            req.delete()
            return JsonResponse({'success': True, 'message': '需求已删除'})
        except DataRequirement.DoesNotExist:
            return JsonResponse({'success': False, 'message': '需求不存在'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class RequirementDetailAPI(LoginRequiredMixin, View):
    def get(self, request):
        try:
            req_id = request.GET.get('id')
            req = DataRequirement.objects.select_related('requester', 'developer').get(id=req_id)
            return JsonResponse({
                'success': True,
                'data': {
                    'id': req.id, 'name': req.name, 'requirement_type': req.requirement_type, 'priority': req.priority,
                    'score': req.score, 'parent': req.parent_id, 'extends_from': req.extends_from_id,
                    'requester': req.requester_id, 'developer': req.developer_id,
                    'publish_date': req.publish_date.strftime('%Y-%m-%d') if req.publish_date else '',
                    'expected_finish': req.expected_finish.strftime('%Y-%m-%d') if req.expected_finish else '',
                    'finish_date': req.finish_date.strftime('%Y-%m-%d') if req.finish_date else '',
                    'remark': req.remark, 'pause_reason': req.pause_reason, 'status': req.status
                }
            })
        except DataRequirement.DoesNotExist:
            return JsonResponse({'success': False, 'message': '需求不存在'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class RequirementStatsAPI(LoginRequiredMixin, View):
    def get(self, request):
        try:
            stats = {
                'total': DataRequirement.objects.count(),
                'completed': DataRequirement.objects.filter(status='completed').count(),
                'developing': DataRequirement.objects.filter(status='developing').count(),
                'pending': DataRequirement.objects.filter(status='pending').count(),
                'claimed': DataRequirement.objects.filter(status='claimed').count(),
                'paused': DataRequirement.objects.filter(status='paused').count(),
                'cancelled': DataRequirement.objects.filter(status='cancelled').count(),
            }
            return JsonResponse({'success': True, 'data': stats})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class RequirementStatusAPI(LoginRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            req_id = data.get('requirement_id')
            action = data.get('action')
            reason = data.get('reason', '')
            req = DataRequirement.objects.get(id=req_id)
            user = request.user
            now = datetime.now()
            is_developer = user.permission_configs.filter(code=554).exists()
            is_dev_admin = user.permission_configs.filter(code=5555).exists()

            if action == 'claim':
                if not is_developer:
                    return JsonResponse({'success': False, 'message': '只有开发人员(code=554)可以领取任务'})
                req.status = 'claimed'
                req.developer = user
                req.claim_date = now
                timeline_action = 'claim'
                timeline_reason = '领取任务'
            elif action == 'unclaim':
                if req.developer != user and not is_dev_admin:
                    return JsonResponse({'success': False, 'message': '只能退领自己的任务'})
                if not reason:
                    return JsonResponse({'success': False, 'message': '退领原因必填'})
                req.status = 'pending'
                req.developer = None
                timeline_action = 'unclaim'
                timeline_reason = f'退领任务：{reason}'
            elif action == 'start':
                if req.developer != user:
                    return JsonResponse({'success': False, 'message': '只能开始自己领取的任务'})
                req.status = 'developing'
                req.start_date = now
                timeline_action = 'start'
                timeline_reason = '开始开发'
            elif action == 'pause':
                if req.developer != user:
                    return JsonResponse({'success': False, 'message': '只能暂停自己的任务'})
                if not reason:
                    return JsonResponse({'success': False, 'message': '暂停原因必填'})
                req.status = 'paused'
                req.pause_reason = reason
                timeline_action = 'pause'
                timeline_reason = f'暂停开发：{reason}'
            elif action == 'resume':
                if req.developer != user:
                    return JsonResponse({'success': False, 'message': '只能恢复自己的任务'})
                req.status = 'developing'
                req.pause_reason = ''
                timeline_action = 'resume'
                timeline_reason = '恢复开发'
            elif action == 'complete':
                if req.developer != user:
                    return JsonResponse({'success': False, 'message': '只能完成自己的任务'})
                req.status = 'completed'
                req.finish_date = now
                timeline_action = 'complete'
                timeline_reason = '任务完成'
            elif action == 'cancel':
                if req.developer != user and not is_dev_admin:
                    return JsonResponse({'success': False, 'message': '只能取消自己的任务'})
                if not reason:
                    return JsonResponse({'success': False, 'message': '取消原因必填'})
                req.status = 'cancelled'
                timeline_action = 'cancel'
                timeline_reason = f'取消任务：{reason}'
            elif action == 'restart':
                if not is_dev_admin:
                    return JsonResponse({'success': False, 'message': '只有开发管理员可以重启任务'})
                req.status = 'developing'
                req.finish_date = None
                timeline_action = 'restart'
                timeline_reason = '重新开发'

            req.save()
            RequirementTimeline.objects.create(requirement=req, action=timeline_action, operator=user,
                                               reason=timeline_reason)
            return JsonResponse({'success': True, 'message': f'状态已更新为：{req.get_status_display()}',
                                 'data': {'new_status': req.status, 'new_status_display': req.get_status_display()}})
        except DataRequirement.DoesNotExist:
            return JsonResponse({'success': False, 'message': '需求不存在'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})


class RequirementListAPI(LoginRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            page = int(data.get('page', 1))
            page_size = int(data.get('page_size', 20))
            queryset = DataRequirement.objects.all().select_related('requester', 'developer')
            filters = data.get('filters', {})

            if filters.get('status'):
                queryset = queryset.filter(status=filters['status'])
            if filters.get('priority'):
                queryset = queryset.filter(priority=filters['priority'])
            if filters.get('type'):
                queryset = queryset.filter(requirement_type=filters['type'])
            if filters.get('developer'):
                queryset = queryset.filter(developer_id=filters['developer'])
            if filters.get('keyword'):
                queryset = queryset.filter(Q(name__icontains=filters['keyword']))

            time_filter = filters.get('time_filter')
            if time_filter:
                today = timezone.now().date()
                if time_filter == 'this_month':
                    start_date = today.replace(day=1)
                    last_day = monthrange(today.year, today.month)[1]
                    end_date = today.replace(day=last_day)
                    queryset = queryset.filter(finish_date__date__gte=start_date, finish_date__date__lte=end_date)
                elif time_filter == 'last_month':
                    first_day_this_month = today.replace(day=1)
                    last_day_last_month = first_day_this_month - timedelta(days=1)
                    start_date = last_day_last_month.replace(day=1)
                    end_date = last_day_last_month
                    queryset = queryset.filter(finish_date__date__gte=start_date, finish_date__date__lte=end_date)
                elif time_filter == 'custom':
                    custom_start = filters.get('custom_start')
                    custom_end = filters.get('custom_end')
                    if custom_start and custom_end:
                        queryset = queryset.filter(finish_date__date__gte=custom_start,
                                                   finish_date__date__lte=custom_end)

            paginator = Paginator(queryset.order_by('-created_at'), page_size)
            page_obj = paginator.get_page(page)
            requirements = []
            for req in page_obj:
                requirements.append({
                    'id': req.id, 'name': req.name, 'type': req.requirement_type,
                    'type_display': req.get_requirement_type_display(), 'status': req.status,
                    'status_display': req.get_status_display(), 'priority': req.priority, 'score': req.score,
                    'requester': req.requester.first_name if req.requester else '-',
                    'developer': req.developer.first_name if req.developer else '-',
                    'publish_date': req.publish_date.strftime('%Y-%m-%d') if req.publish_date else '-',
                    'claim_date': req.claim_date.strftime('%Y-%m-%d') if req.claim_date else '-',
                    'start_date': req.start_date.strftime('%Y-%m-%d') if req.start_date else '-',
                    'expected_finish': req.expected_finish.strftime('%Y-%m-%d') if req.expected_finish else '-',
                    'finish_date': req.finish_date.strftime('%Y-%m-%d') if req.finish_date else '-',
                })

            return JsonResponse({'success': True, 'data': {'requirements': requirements, 'total': paginator.count,
                                                           'total_pages': paginator.num_pages, 'page': page}})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})