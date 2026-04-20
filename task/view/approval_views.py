import json
import logging
import threading
import requests as _requests

logger = logging.getLogger(__name__)

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import models, transaction
from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from amazon.listing_models import AmazonListingV2
from amazon.models import LingXingAmazonShop
from general.models import OperationalAccount, User
from task.approval_models import (
    ApprovalRecord,
    ApprovalStatus,
    ApprovalStep,
    ExecStatus,
    AmazonAdApproval,
    AmazonAdShopConfig,
    Approval,
    RecordResult,
    StepStatus,
    ApprovalType,
    NegativeKeywordLibrary,
    ApprovalFlowConfig,
)
from task.utils.task_utils import parse_permissions


def get_amazon_operational_account(user):
    return OperationalAccount.objects.filter(
        user_id=user.id,
        platform=OperationalAccount.Platform.AMAZON,
    ).first()


def has_admin_555(user):
    permissions = parse_permissions(getattr(user, 'permission', ''))
    return bool(
        '555' in permissions
        or getattr(user, 'is_superuser', False)
        or user.permission_configs.filter(code=555).exists()
    )


def has_approval_access(user):
    return bool(
        get_amazon_operational_account(user)
        or has_admin_555(user)
    )


def get_leader_operational_account(user):
    return OperationalAccount.objects.filter(
        user_id=user.id,
        role=OperationalAccount.Role.LEADER,
    ).first()


def has_leader_approval_access(user):
    return bool(get_leader_operational_account(user))


def get_approval_chain(user):
    leader = user.manager
    supervisor = leader.manager if leader else None
    return leader, supervisor


def get_visible_lingxing_shops(user):
    queryset = LingXingAmazonShop.objects.select_related('amazon_shop').order_by('name', 'sid')

    if has_admin_555(user):
        return queryset

    return queryset.filter(
        amazon_shop__ops_id=user.id,
        amazon_shop__company_id=user.company_id,
    )


def user_has_shop_access(user, sid):
    return get_visible_lingxing_shops(user).filter(sid=sid).exists()


def get_current_status_label(approval):
    """返回审批流程主状态标签（与RPA执行状态分离）"""
    # 审批通过后进入RPA执行阶段，统一显示"已通过"
    if approval.status in (
        ApprovalStatus.APPROVED,
        ApprovalStatus.WAITING,
        ApprovalStatus.EXECUTING,
        ApprovalStatus.SUCCESS,
        ApprovalStatus.FAILED,
    ):
        return '已通过'
    status_map = {
        ApprovalStatus.REJECTED: '已驳回',
        ApprovalStatus.DRAFT: '草稿',
    }
    if approval.status in status_map:
        return status_map[approval.status]
    if approval.current_step_sequence == 0:
        return '待组长审批'
    if approval.current_step_sequence == 1:
        return '待组长上级审批'
    if approval.current_step_sequence == 2:
        return '已通过'
    return f'第{approval.current_step_sequence}步审核中'


def get_exec_status_summary(approval):
    exec_status_map = {
        ApprovalStatus.WAITING: ('待执行', 'waiting'),
        ApprovalStatus.EXECUTING: ('执行中', 'executing'),
        ApprovalStatus.SUCCESS: ('执行成功', 'success'),
        ApprovalStatus.FAILED: ('执行失败', 'failed'),
    }
    if approval.status in exec_status_map:
        return exec_status_map[approval.status]
    return None, None


def create_approval_steps(approval, applicant):
    """
    根据 ApprovalFlowConfig 配置动态创建审批步骤。
    返回 (step_1, step_2, skipped)
    skipped=True 表示该员工配置了跳过审批，不需要创建任何步骤。
    """
    flow_config = ApprovalFlowConfig.objects.filter(
        company=applicant.company,
        applicant=applicant,
        approval_type=approval.approval_type,
    ).first()

    if flow_config and flow_config.skip_approval:
        return None, None, True

    leader, supervisor = get_approval_chain(applicant)

    if flow_config:
        # 有配置记录时，完全尊重配置；没填的字段不创建对应步骤
        step_1_approver = flow_config.proxy_approver or leader
        step_2_approver = flow_config.step2_approver  # 可能为 None，表示不创建 step2
    else:
        # 无配置时，默认流程：组长 → 组长上级
        step_1_approver = leader
        step_2_approver = supervisor

    step_1 = ApprovalStep.objects.create(
        company=approval.company,
        approval=approval,
        sequence=1,
        step_name='组长审核',
        approver=step_1_approver,
        status=StepStatus.PENDING,
    )

    step_2 = None
    if step_2_approver:
        step_2 = ApprovalStep.objects.create(
            company=approval.company,
            approval=approval,
            sequence=2,
            step_name='组长上级审核',
            approver=step_2_approver,
            status=StepStatus.PENDING,
        )

    return step_1, step_2, False


def clone_rejected_approval(original_approval):
    cloned_approval = Approval.build_draft(
        applicant=original_approval.applicant,
        approval_type=original_approval.approval_type,
        original_approval=original_approval,
    )
    cloned_approval.save()

    original_detail = getattr(original_approval, 'ad_detail', None)
    cloned_detail = AmazonAdApproval.objects.create(
        company=original_approval.company,
        approval=cloned_approval,
        remark=original_detail.remark if original_detail else '',
    )

    if original_detail:
        original_configs = original_detail.shop_configs.select_related('lingxing_shop', 'negative_keyword_lib').prefetch_related('asins')
        for config in original_configs:
            cloned_config = AmazonAdShopConfig.objects.create(
                company=original_approval.company,
                amazon_ad=cloned_detail,
                lingxing_shop=config.lingxing_shop,
                negative_keyword_lib=config.negative_keyword_lib,
                exec_status=ExecStatus.PENDING,
                exec_result={},
                webhook_task_id='',
                sequence=config.sequence,
            )
            cloned_config.asins.set(config.asins.all())

    create_approval_steps(cloned_approval, original_approval.applicant)
    return cloned_approval


@login_required(login_url='/login/')
def approval_create_page(request):
    if not has_approval_access(request.user):
        return redirect('/')

    return render(request, 'approval_create.html', {
        'active_nav': 'task',
        'active_page': 'ad_create_page',
    })


@login_required(login_url='/login/')
def approval_leader_page(request):
    if not has_leader_approval_access(request.user):
        return redirect('/')

    return render(request, 'approval_leader_list.html', {
        'active_nav': 'task',
        'active_page': 'approval_leader_page',
    })


@login_required(login_url='/login/')
@require_http_methods(["GET"])
def approval_meta_api(request):
    if not has_approval_access(request.user):
        return JsonResponse({'success': False, 'message': '仅 Amazon 运营或 555 权限用户可访问'}, status=403)

    leader, supervisor = get_approval_chain(request.user)
    approval = Approval.build_draft(request.user)
    approval_type_choices = [
        {'value': value, 'label': label}
        for value, label in ApprovalType.choices
    ]

    return JsonResponse({
        'success': True,
        'data': {
            'applicant': {
                'id': request.user.id,
                'name': request.user.first_name or request.user.username,
            },
            'approval_no': approval.approval_no,
            'approval_type': approval.approval_type,
            'approval_type_label': dict(ApprovalType.choices).get(approval.approval_type, approval.approval_type),
            'approval_type_choices': approval_type_choices,
            'total_steps': approval.total_steps,
            'current_step_sequence': approval.current_step_sequence,
            'leader_name': leader.first_name or leader.username if leader else '',
            'supervisor_name': supervisor.first_name or supervisor.username if supervisor else '',
            'chain_ready': bool(leader or supervisor),
            'negative_keyword_libs':list(
                NegativeKeywordLibrary.objects.filter(
                    company = request.user.company,
                    is_active = True,
                ).values('id','name','lib_type')
            )
        }
    })


@login_required(login_url='/login/')
@require_http_methods(["GET"])
def approval_stores_api(request):
    if not has_approval_access(request.user):
        return JsonResponse({'success': False, 'message': '仅 Amazon 运营或 555 权限用户可访问'}, status=403)

    stores = []
    for shop in get_visible_lingxing_shops(request.user):
        stores.append({
            'sid': str(shop.sid),
            'name': shop.name or f"sid_{shop.sid}",
            'amazon_shop_id': shop.amazon_shop_id,
            'amazon_shop_name': shop.amazon_shop.shop_name if shop.amazon_shop else '',
        })

    return JsonResponse({'success': True, 'data': stores})


@login_required(login_url='/login/')
@require_http_methods(["GET"])
def approval_draft_list_api(request):
    if not has_approval_access(request.user):
        return JsonResponse({'success': False, 'message': '仅 Amazon 运营或 555 权限用户可访问'}, status=403)

    drafts = (
        Approval.objects
        .filter(
            company=request.user.company,
            applicant=request.user,
            approval_type=ApprovalType.AMAZON_AD,
            status=ApprovalStatus.DRAFT,
            original_approval__isnull=False,
        )
        .select_related('original_approval', 'ad_detail')
        .order_by('-updated_at', '-id')
    )

    data = []
    for draft in drafts:
        if hasattr(draft, 'ad_detail'):
            shop_configs = draft.ad_detail
        else:
            shop_configs = None
        config_count = shop_configs.shop_configs.count() if shop_configs else 0
        asin_count = 0
        if shop_configs:
            asin_count = sum(config.asins.count() for config in shop_configs.shop_configs.prefetch_related('asins'))

        data.append({
            'approval_id': draft.id,
            'approval_no': draft.approval_no,
            'original_approval_id': draft.original_approval_id,
            'original_approval_no': draft.original_approval.approval_no if draft.original_approval else '',
            'remark': shop_configs.remark if shop_configs else '',
            'updated_at': draft.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
            'config_count': config_count,
            'asin_count': asin_count,
        })

    return JsonResponse({'success': True, 'data': data})


@login_required(login_url='/login/')
@require_http_methods(["GET"])
def approval_draft_detail_api(request, approval_id):
    if not has_approval_access(request.user):
        return JsonResponse({'success': False, 'message': '仅 Amazon 运营或 555 权限用户可访问'}, status=403)

    draft = (
        Approval.objects
        .filter(
            id=approval_id,
            company=request.user.company,
            applicant=request.user,
            approval_type=ApprovalType.AMAZON_AD,
            status=ApprovalStatus.DRAFT,
        )
        .select_related('applicant', 'original_approval', 'ad_detail')
        .first()
    )
    if not draft:
        return JsonResponse({'success': False, 'message': '草稿不存在或无权访问'}, status=404)

    leader, supervisor = get_approval_chain(draft.applicant)
    shop_configs = []
    ad_detail = draft.ad_detail if hasattr(draft, 'ad_detail') else None
    if ad_detail:
        configs = ad_detail.shop_configs.select_related('lingxing_shop', 'negative_keyword_lib').prefetch_related('asins__lingxing_shop').order_by('sequence', 'id')
        for config in configs:
            selected_listings = []
            for listing in config.asins.all():
                shop_name = ''
                if listing.lingxing_shop and listing.lingxing_shop.name:
                    shop_name = listing.lingxing_shop.name
                elif config.lingxing_shop and config.lingxing_shop.name:
                    shop_name = config.lingxing_shop.name
                else:
                    shop_name = f"sid_{listing.sid}"
                selected_listings.append({
                    'id': listing.id,
                    'sid': listing.sid,
                    'asin': listing.asin or '',
                    'shop_name': shop_name,
                    'fulfillment_channel_type': listing.fulfillment_channel_type or '',
                    'fnsku': listing.fnsku or '',
                })

            shop_configs.append({
                'sid': str(config.lingxing_shop.sid),
                'selected_listings': selected_listings,
                'negative_keyword_lib_id': config.negative_keyword_lib_id,
                'negative_keyword_lib_name': config.negative_keyword_lib.name if config.negative_keyword_lib else None,
            })

    return JsonResponse({
        'success': True,
        'data': {
            'approval': {
                'id': draft.id,
                'approval_no': draft.approval_no,
                'approval_type': draft.approval_type,
                'approval_type_label': dict(ApprovalType.choices).get(draft.approval_type, draft.approval_type),
                'total_steps': draft.total_steps,
                'current_step_sequence': draft.current_step_sequence,
                'original_approval_id': draft.original_approval_id,
                'original_approval_no': draft.original_approval.approval_no if draft.original_approval else '',
            },
            'applicant': {
                'id': draft.applicant_id,
                'name': draft.applicant.first_name or draft.applicant.username,
            },
            'leader_name': leader.first_name or leader.username if leader else '',
            'supervisor_name': supervisor.first_name or supervisor.username if supervisor else '',
            'chain_ready': bool(leader or supervisor),
            'remark': ad_detail.remark if ad_detail else '',
            'shop_configs': shop_configs,
        }
    })


@login_required(login_url='/login/')
@require_http_methods(["GET"])
def approval_asins_api(request):
    if not has_approval_access(request.user):
        return JsonResponse({'success': False, 'message': '仅 Amazon 运营或 555 权限用户可访问'}, status=403)

    sid = (request.GET.get('sid') or '').strip()
    if not sid:
        return JsonResponse({'success': False, 'message': '缺少 sid 参数'}, status=400)

    try:
        sid_int = int(sid)
    except ValueError:
        return JsonResponse({'success': False, 'message': 'sid 参数无效'}, status=400)

    search = (request.GET.get('search') or '').strip()

    try:
        page = max(int(request.GET.get('page', 1)), 1)
    except ValueError:
        page = 1

    try:
        page_size = int(request.GET.get('page_size', 20))
    except ValueError:
        page_size = 20

    if page_size not in {20, 50, 100}:
        page_size = 20

    if not user_has_shop_access(request.user, sid_int):
        return JsonResponse({'success': False, 'message': '无权访问该店铺'}, status=403)

    listings = AmazonListingV2.objects.filter(
        sid=sid_int,
        lingxing_shop_id=sid_int,
    ).select_related('lingxing_shop').order_by('asin', 'fulfillment_channel_type', 'id')

    if search:
        listings = listings.filter(asin__icontains=search)

    paginator = Paginator(listings, page_size)
    page_obj = paginator.get_page(page)

    data = []
    for listing in page_obj.object_list:
        data.append({
            'id': listing.id,
            'asin': listing.asin,
            'title': listing.title or '',
            'img_url':listing.small_image_url or '',
            'local_sku': listing.local_sku or '',
            'seller_sku': listing.seller_sku or '',
            'fulfillment_channel_type': listing.fulfillment_channel_type or '',
            'fnsku': listing.fnsku or '',
            'marketplace': listing.marketplace or '',
            'shop_name': listing.lingxing_shop.name if listing.lingxing_shop and listing.lingxing_shop.name else f"sid_{listing.sid}",
            'sid': listing.sid,
        })

    return JsonResponse({
        'success': True,
        'data': data,
        'pagination': {
            'page': page_obj.number,
            'page_size': page_size,
            'total': paginator.count,
            'total_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_prev': page_obj.has_previous(),
        }
    })


@login_required(login_url='/login/')
@require_http_methods(["GET"])
def approval_leader_list_api(request):
    if not has_leader_approval_access(request.user):
        return JsonResponse({'success': False, 'message': '仅运营组长可访问'}, status=403)

    try:
        page = max(int(request.GET.get('page', 1)), 1)
    except ValueError:
        page = 1

    try:
        page_size = int(request.GET.get('page_size', 20))
    except ValueError:
        page_size = 20

    if page_size not in {20, 50, 100}:
        page_size = 20

    approvals_qs = (
        Approval.objects
        .filter(
            company=request.user.company,
            approval_type=ApprovalType.AMAZON_AD,
            status=ApprovalStatus.PENDING,
            current_step_sequence=0,
            steps__sequence=1,
            steps__status=StepStatus.PENDING,
            steps__approver=request.user,
            applicant__manager=request.user,
        )
        .select_related('applicant')
        .order_by('-created_at', '-id')
        .distinct()
    )

    paginator = Paginator(approvals_qs, page_size)
    page_obj = paginator.get_page(page)

    asin_prefetch = Prefetch(
        'asins',
        queryset=AmazonListingV2.objects.select_related('lingxing_shop').order_by('asin', 'id'),
    )

    data = []
    for approval in page_obj.object_list:
        applicant_name = approval.applicant.first_name or approval.applicant.username
        current_status_label = get_current_status_label(approval)

        detail_rows = []
        ad_detail = getattr(approval, 'ad_detail', None)
        if ad_detail:
            configs = (
                ad_detail.shop_configs
                .select_related('lingxing_shop')
                .prefetch_related(asin_prefetch)
                .order_by('sequence', 'id')
            )
            for config in configs:
                for listing in config.asins.all():
                    shop_name = ''
                    if listing.lingxing_shop and listing.lingxing_shop.name:
                        shop_name = listing.lingxing_shop.name
                    elif config.lingxing_shop and config.lingxing_shop.name:
                        shop_name = config.lingxing_shop.name
                    else:
                        shop_name = f"sid_{listing.sid}"

                    detail_rows.append({
                        'row_key': f'{approval.id}-{config.id}-{listing.id}',
                        'config_id': config.id,
                        'asin': listing.asin or '',
                        'shop_name': shop_name,
                    })

        data.append({
            'approval_id': approval.id,
            'approval_no': approval.approval_no,
            'applicant_name': applicant_name,
            'current_step_sequence': approval.current_step_sequence,
            'current_status_label': current_status_label,
            'asin': '--',
            'shop_name': '--',
            'detail_count': len(detail_rows),
            'detail_rows': detail_rows,
        })

    return JsonResponse({
        'success': True,
        'data': data,
        'pagination': {
            'page': page_obj.number,
            'page_size': page_size,
            'total': paginator.count,
            'total_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_prev': page_obj.has_previous(),
        }
    })


@login_required(login_url='/login/')
@require_http_methods(["POST"])
@transaction.atomic
def create_ad_approval_api(request):
    if not has_approval_access(request.user):
        return JsonResponse({'success': False, 'message': '仅 Amazon 运营或 555 权限用户可访问'}, status=403)

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': '请求体不是有效 JSON'}, status=400)

    approval_type = payload.get('approval_type') or ApprovalType.AMAZON_AD
    preview_approval_no = (payload.get('approval_no') or '').strip()
    approval_id = payload.get('approval_id')
    if approval_type != ApprovalType.AMAZON_AD:
        return JsonResponse({'success': False, 'message': '当前仅支持创建广告审批'}, status=400)

    try:
        shop_configs = payload.get('shop_configs') or []
        if not isinstance(shop_configs, list) or not shop_configs:
            return JsonResponse({'success': False, 'message': '至少需要一组店铺与 ASIN 配置'}, status=400)

        normalized_configs = []
        for index, config in enumerate(shop_configs, start=1):
            sid = config.get('sid')
            listing_ids = config.get('listing_ids') or config.get('asin_ids') or []
            negative_keyword_lib_id = config.get('negative_keyword_lib_id')

            if sid in (None, ''):
                return JsonResponse({'success': False, 'message': f'第 {index} 组未选择店铺'}, status=400)

            try:
                sid_int = int(sid)
            except (TypeError, ValueError):
                return JsonResponse({'success': False, 'message': f'第 {index} 组店铺参数无效'}, status=400)

            if not user_has_shop_access(request.user, sid_int):
                return JsonResponse({'success': False, 'message': f'第 {index} 组店铺无访问权限'}, status=403)

            if not isinstance(listing_ids, list) or not listing_ids:
                return JsonResponse({'success': False, 'message': f'第 {index} 组至少选择一个 ASIN'}, status=400)

            if not negative_keyword_lib_id:
                return JsonResponse({'success': False, 'message': f'第 {index} 组未选择否定词库'}, status=400)

            try:
                listing_ids_int = [int(item) for item in listing_ids]
            except (TypeError, ValueError):
                return JsonResponse({'success': False, 'message': f'第 {index} 组 ASIN 参数无效'}, status=400)

            listings = list(
                AmazonListingV2.objects.filter(
                    id__in=listing_ids_int,
                ).select_related('lingxing_shop')
            )

            if len(listings) != len(set(listing_ids_int)):
                return JsonResponse({'success': False, 'message': f'第 {index} 组包含无效 ASIN 记录'}, status=400)

            for listing in listings:
                if not user_has_shop_access(request.user, listing.sid):
                    return JsonResponse({'success': False, 'message': f'第 {index} 组包含无权限 ASIN 记录'}, status=403)
                if int(listing.sid) != sid_int:
                    return JsonResponse({
                        'success': False,
                        'message': f'配置组 #{index} 只能选择店铺 sid={sid_int} 下的 ASIN，如需其他店铺请新增配置组'
                    }, status=400)

            normalized_configs.append({
                'sid': sid_int,
                'listings': listings,
                'negative_keyword_lib_id': negative_keyword_lib_id,
            })

        if approval_id in (None, ''):
            approval = Approval.build_draft(
                applicant=request.user,
                approval_type=approval_type,
            )
            if preview_approval_no:
                approval.approval_no = preview_approval_no
            approval.save()
            ad_approval = AmazonAdApproval.objects.create(
                company=request.user.company,
                approval=approval,
                remark=(payload.get('remark') or '').strip(),
            )
        else:
            try:
                approval_id = int(approval_id)
            except (TypeError, ValueError):
                return JsonResponse({'success': False, 'message': 'approval_id 参数无效'}, status=400)

            approval = (
                Approval.objects
                .select_for_update()
                .filter(
                    id=approval_id,
                    company=request.user.company,
                    applicant=request.user,
                    approval_type=ApprovalType.AMAZON_AD,
            status__in=[ApprovalStatus.DRAFT, ApprovalStatus.REJECTED],
                )
                .first()
            )
            if not approval:
                return JsonResponse({'success': False, 'message': '草稿不存在或已不可编辑'}, status=404)

            ad_approval, _ = AmazonAdApproval.objects.get_or_create(
                approval=approval,
                defaults={
                    'company': request.user.company,
                    'remark': '',
                }
            )
            ad_approval.remark = (payload.get('remark') or '').strip()
            ad_approval.save()
            approval.steps.all().delete()
            ad_approval.shop_configs.all().delete()

        step_1, step_2, skipped = create_approval_steps(approval, request.user)

        for sequence, config in enumerate(normalized_configs, start=1):
            lingxing_shop = LingXingAmazonShop.objects.filter(sid=config['sid']).first()
            if not lingxing_shop:
                return JsonResponse({
                    'success': False,
                    'message': f'店铺 sid={config["sid"]} 不存在或已被删除，请刷新页面后重新选择'
                }, status=404)

            lib_id = config.get('negative_keyword_lib_id')
            negative_keyword_lib = (
                NegativeKeywordLibrary.objects.filter(id=lib_id, company=request.user.company, is_active=True).first()
                if lib_id else None
            )

            shop_config = AmazonAdShopConfig.objects.create(
                company=request.user.company,
                amazon_ad=ad_approval,
                lingxing_shop=lingxing_shop,
                sequence=sequence,
                negative_keyword_lib=negative_keyword_lib,
            )
            shop_config.asins.set(config['listings'])

        if skipped:
            approval.status = ApprovalStatus.WAITING
            approval.current_step_sequence = approval.total_steps
            approval.submitted_at = timezone.now()
            approval.completed_at = timezone.now()
            approval.save()
            _send_approval_webhook(approval)
            if approval.original_approval_id:
                approval.original_approval.delete()
            return JsonResponse({
                'success': True,
                'message': '广告审批已提交（该员工已配置免审批，直接进入执行队列）',
                'data': {
                    'approval_id': approval.id,
                    'approval_no': approval.approval_no,
                    'total_steps': approval.total_steps,
                    'current_step_sequence': approval.current_step_sequence,
                }
            })

        approval.status = ApprovalStatus.PENDING
        approval.current_step_sequence = 0
        approval.submitted_at = timezone.now()
        approval.completed_at = None
        approval.save()

        if approval.original_approval_id:
            approval.original_approval.delete()

        return JsonResponse({
            'success': True,
            'message': '广告审批提交成功',
            'data': {
                'approval_id': approval.id,
                'approval_no': approval.approval_no,
                'total_steps': approval.total_steps,
                'current_step_sequence': approval.current_step_sequence,
            }
        })
    except Exception as exc:
        return JsonResponse({'success': False, 'message': f'广告审批提交失败: {exc}'}, status=500)


@login_required(login_url='/login/')
@require_http_methods(["POST"])
@transaction.atomic
def approval_leader_action_api(request):
    if not has_leader_approval_access(request.user):
        return JsonResponse({'success': False, 'message': '仅运营组长可操作审批'}, status=403)

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': '请求体不是有效 JSON'}, status=400)

    approval_id = payload.get('approval_id')
    action = (payload.get('action') or '').strip()
    comment = (payload.get('comment') or '').strip()

    if not approval_id:
        return JsonResponse({'success': False, 'message': '缺少 approval_id'}, status=400)

    if action not in {RecordResult.APPROVED, RecordResult.REJECTED}:
        return JsonResponse({'success': False, 'message': 'action 参数无效'}, status=400)

    try:
        approval_id = int(approval_id)
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'message': 'approval_id 参数无效'}, status=400)

    approval = (
        Approval.objects
        .select_for_update()
        .select_related('applicant')
        .filter(
            id=approval_id,
            company=request.user.company,
            approval_type=ApprovalType.AMAZON_AD,
            status=ApprovalStatus.PENDING,
            current_step_sequence=0,
            applicant__manager=request.user,
        )
        .first()
    )
    if not approval:
        return JsonResponse({'success': False, 'message': '审批单不存在或当前不可审批'}, status=404)

    current_step = (
        approval.steps
        .select_for_update()
        .filter(sequence=1, status=StepStatus.PENDING, approver=request.user)
        .first()
    )
    if not current_step:
        return JsonResponse({'success': False, 'message': '当前审批单不属于你审批或已处理'}, status=403)

    ApprovalRecord.objects.create(
        company=request.user.company,
        step=current_step,
        approver=request.user,
        result=action,
        comment=comment,
    )
    current_step.status = StepStatus.COMPLETED
    current_step.save()

    if action == RecordResult.APPROVED:
        next_step = approval.steps.filter(sequence=2).first()
        if next_step and next_step.approver:
            approval.status = ApprovalStatus.PENDING
            approval.current_step_sequence = 1
            approval.completed_at = None
            approval.save()
            return JsonResponse({
                'success': True,
                'message': '审批已通过，已流转至组长上级审核',
                'data': {
                    'approval_id': approval.id,
                    'approval_no': approval.approval_no,
                    'next_step_sequence': 2,
                }
            })

        if next_step and next_step.status == StepStatus.PENDING:
            next_step.status = StepStatus.SKIPPED
            next_step.save()

        approval.status = ApprovalStatus.WAITING
        approval.current_step_sequence = 2
        approval.completed_at = timezone.now()
        approval.save()
        _send_approval_webhook(approval)
        return JsonResponse({
            'success': True,
            'message': '审批已通过',
            'data': {
                'approval_id': approval.id,
                'approval_no': approval.approval_no,
            }
        })

    pending_following_steps = approval.steps.filter(sequence__gt=1, status=StepStatus.PENDING)
    for step in pending_following_steps:
        step.status = StepStatus.SKIPPED
        step.save()

    approval.status = ApprovalStatus.REJECTED
    approval.completed_at = timezone.now()
    approval.save()

    cloned_approval = clone_rejected_approval(approval)
    return JsonResponse({
        'success': True,
        'message': f'审批已驳回，已生成草稿 {cloned_approval.approval_no} 可重新编辑提交',
        'data': {
            'approval_id': approval.id,
            'approval_no': approval.approval_no,
            'cloned_approval_id': cloned_approval.id,
        }
    })


def _send_approval_webhook(approval):
    try:
        ad_detail = (
            Approval.objects
            .select_related('ad_detail', 'applicant')
            .filter(pk=approval.pk)
            .first()
        )
        ad_detail = getattr(ad_detail, 'ad_detail', None) if ad_detail else None
        if not ad_detail:
            return

        configs = (
            AmazonAdShopConfig.objects
            .filter(amazon_ad=ad_detail)
            .select_related('lingxing_shop','negative_keyword_lib')
            .prefetch_related('asins')
            .order_by('sequence')
        )

        subtask_list = []
        for config in configs:
            asin_list = list(config.asins.values_list('asin', flat=True))
            subtask_list.append({
                '子任务序号': config.sequence,
                '店铺名称': config.lingxing_shop.name if config.lingxing_shop else '',
                'ASIN列表': asin_list,
                '否定词库': config.negative_keyword_lib.keywords if config.negative_keyword_lib else '',
            })

        payload = {
            '审批单号': approval.approval_no,
            '企业微信通知url': approval.applicant.wx_url or '',
            '任务类型': dict(ApprovalType.choices).get(approval.approval_type, approval.approval_type),
            '子任务列表': subtask_list,
        }

        def _post(data):
            url = "https://api.yingdao.com/api/tool/ipaas/webhook/callback/937960756270653440"
            try:
                _requests.post(url, json=data, timeout=10)
                logger.info("Webhook sent successfully: %s", data.get('审批单号'))
            except Exception as e:
                logger.error("Webhook send failed: %s", e)

        transaction.on_commit(lambda: threading.Thread(target=_post, args=(payload,)).start())
    except Exception as e:
        logger.error("Error preparing approval webhook: %s", e)


def _has_approval_operate_permission(user):
    if not getattr(user, 'is_authenticated', False):
        return False

    return user.permission_configs.filter(code__in=[555, 2]).exists()


def _process_approval_action(approval, user, action, comment=''):
    current_step = (
        approval.steps
        .filter(status=StepStatus.PENDING, approver__isnull=False)
        .order_by('sequence')
        .first()
    )
    if not current_step:
        return None, JsonResponse({'success': False, 'message': '没有找到待审批步骤'}, status=400)

    ApprovalRecord.objects.create(
        company=user.company,
        step=current_step,
        approver=user,
        result=action,
        comment=comment,
    )
    current_step.status = StepStatus.COMPLETED
    current_step.save()

    if action == RecordResult.APPROVED:
        next_step = approval.steps.filter(sequence__gt=current_step.sequence, status=StepStatus.PENDING).first()
        if next_step and next_step.approver:
            approval.current_step_sequence = next_step.sequence - 1
            approval.save()
            return current_step, JsonResponse({
                'success': True,
                'message': f'审批已通过，流转至 {next_step.step_name}',
                'data': {'approval_id': approval.id, 'approval_no': approval.approval_no}
            })

        for s in approval.steps.filter(sequence__gt=current_step.sequence, status=StepStatus.PENDING):
            s.status = StepStatus.SKIPPED
            s.save()

        approval.status = ApprovalStatus.WAITING
        approval.current_step_sequence = approval.total_steps
        approval.completed_at = timezone.now()
        approval.save()
        _send_approval_webhook(approval)
        return current_step, JsonResponse({
            'success': True,
            'message': '审批已通过',
            'data': {'approval_id': approval.id, 'approval_no': approval.approval_no}
        })

    for s in approval.steps.filter(sequence__gt=current_step.sequence, status=StepStatus.PENDING):
        s.status = StepStatus.SKIPPED
        s.save()

    approval.status = ApprovalStatus.REJECTED
    approval.completed_at = timezone.now()
    approval.save()

    cloned_approval = clone_rejected_approval(approval)
    return current_step, JsonResponse({
        'success': True,
        'message': f'审批已驳回，已生成草稿 {cloned_approval.approval_no} 可重新编辑提交',
        'data': {
            'approval_id': approval.id,
            'approval_no': approval.approval_no,
            'cloned_approval_id': cloned_approval.id,
        }
    })


@login_required(login_url='/login/')
def approval_ad_page(request):
    can_operate = _has_approval_operate_permission(request.user)
    can_configure_flow = (
        has_admin_555(request.user)
        or (hasattr(request.user, 'is_group_leader') and request.user.is_group_leader())
    )
    return render(request, 'approval_list.html', {
        'active_nav': 'task',
        'active_page': 'approval_ad_page',
        'can_operate_approval': can_operate,
        'can_configure_flow': can_configure_flow,
    })


@login_required(login_url='/login/')
@require_http_methods(["GET"])
def approval_list_stats_api(request):
    base_qs = Approval.objects.filter(company=request.user.company)
    return JsonResponse({
        'success': True,
        'data': {
            'total': base_qs.count(),
            'pending': base_qs.filter(status=ApprovalStatus.PENDING).count(),
            'approved': base_qs.filter(
                status__in=[
                    ApprovalStatus.APPROVED,
                    ApprovalStatus.WAITING,
                    ApprovalStatus.EXECUTING,
                    ApprovalStatus.SUCCESS,
                    ApprovalStatus.FAILED,
                ]
            ).count(),
            'rejected': base_qs.filter(status=ApprovalStatus.REJECTED).count(),
        }
    })


@login_required(login_url='/login/')
@require_http_methods(["GET"])
def approval_list_data_api(request):
    can_operate = _has_approval_operate_permission(request.user)

    try:
        page = max(int(request.GET.get('page', 1)), 1)
    except ValueError:
        page = 1

    try:
        page_size = int(request.GET.get('page_size', 20))
    except ValueError:
        page_size = 20

    if page_size not in {20, 50, 100}:
        page_size = 20

    tab = request.GET.get('tab', 'all')
    search = (request.GET.get('search') or '').strip()

    base_qs = Approval.objects.filter(company=request.user.company).select_related('applicant', 'ad_detail')

    if tab == 'pending':
        base_qs = base_qs.filter(status=ApprovalStatus.PENDING)

    if search:
        base_qs = base_qs.filter(
            models.Q(approval_no__icontains=search)
            | models.Q(applicant__first_name__icontains=search)
            | models.Q(applicant__username__icontains=search)
        )

    base_qs = base_qs.order_by('-created_at', '-id')

    paginator = Paginator(base_qs, page_size)
    page_obj = paginator.get_page(page)

    asin_prefetch = Prefetch(
        'asins',
        queryset=AmazonListingV2.objects.select_related('lingxing_shop').order_by('asin', 'id'),
    )

    data = []
    for approval in page_obj.object_list:
        applicant_name = approval.applicant.first_name or approval.applicant.username
        status_label = get_current_status_label(approval)
        exec_status_label, exec_status_code = get_exec_status_summary(approval)

        shop_names_set = set()
        ad_detail = getattr(approval, 'ad_detail', None)
        if ad_detail:
            configs = ad_detail.shop_configs.select_related('lingxing_shop').all()
            for config in configs:
                if config.lingxing_shop and config.lingxing_shop.name:
                    shop_names_set.add(config.lingxing_shop.name)

        # 当前待审批步骤信息
        pending_step = None
        pending_step_name = None
        pending_approver_name = None
        if approval.status == ApprovalStatus.PENDING:
            pending_step = (
                approval.steps
                .filter(status=StepStatus.PENDING, approver__isnull=False)
                .order_by('sequence')
                .select_related('approver')
                .first()
            )
            if pending_step:
                pending_step_name = pending_step.step_name
                pending_approver_name = pending_step.approver.first_name or pending_step.approver.username if pending_step.approver else None

        # 当前用户是否为此审批单的指定审批人
        can_operate_this = False
        if approval.status == ApprovalStatus.PENDING and pending_step:
            can_operate_this = pending_step.approver_id == request.user.id
        # 管理员（555权限）始终可操作
        if not can_operate_this:
            can_operate_this = has_admin_555(request.user)

        can_edit = (
            approval.applicant_id == request.user.id
            and approval.status in (ApprovalStatus.DRAFT, ApprovalStatus.REJECTED)
        )

        draft_approval_id = None
        if can_edit:
            if approval.status == ApprovalStatus.DRAFT:
                draft_approval_id = approval.id
            elif approval.status == ApprovalStatus.REJECTED:
                cloned = Approval.objects.filter(
                    original_approval=approval,
                    status=ApprovalStatus.DRAFT,
                ).first()
                if cloned:
                    draft_approval_id = cloned.id

        data.append({
            'approval_id': approval.id,
            'approval_no': approval.approval_no,
            'approval_type': approval.approval_type,
            'approval_type_label': dict(ApprovalType.choices).get(approval.approval_type, approval.approval_type),
            'applicant_id': approval.applicant_id,
            'applicant_name': applicant_name,
            'status': approval.status,
            'status_label': status_label,
            'exec_status': exec_status_code,
            'pending_step_name': pending_step_name,
            'pending_approver_name': pending_approver_name,
            'can_operate_this': can_operate_this,
            'shop_count': len(shop_names_set),
            'shop_names': ', '.join(sorted(shop_names_set)),
            'created_at': approval.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'submitted_at': approval.submitted_at.strftime('%Y-%m-%d %H:%M:%S') if approval.submitted_at else None,
            'can_operate': can_operate,
            'can_delete': has_admin_555(request.user),
            'can_edit': can_edit,
            'draft_approval_id': draft_approval_id,
        })

    return JsonResponse({
        'success': True,
        'data': data,
        'pagination': {
            'page': page_obj.number,
            'page_size': page_size,
            'total': paginator.count,
            'total_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_prev': page_obj.has_previous(),
        }
    })


@login_required(login_url='/login/')
@require_http_methods(["GET"])
def approval_detail_api(request, approval_id):
    approval = (
        Approval.objects
        .filter(id=approval_id, company=request.user.company)
        .select_related('applicant', 'ad_detail')
        .prefetch_related('steps__records__approver')
        .first()
    )
    if not approval:
        return JsonResponse({'success': False, 'message': '审批单不存在'}, status=404)

    asin_prefetch = Prefetch(
        'asins',
        queryset=AmazonListingV2.objects.select_related('lingxing_shop').order_by('asin', 'id'),
    )

    status_label = get_current_status_label(approval)
    exec_status_label, exec_status_code = get_exec_status_summary(approval)

    detail_rows = []
    negative_keyword_lib_names = []
    ad_detail = getattr(approval, 'ad_detail', None)
    rpa_progress = []
    if ad_detail:
        configs = ad_detail.shop_configs.select_related('lingxing_shop', 'negative_keyword_lib').prefetch_related(asin_prefetch).order_by('sequence', 'id')
        for config in configs:
            if config.negative_keyword_lib and config.negative_keyword_lib.name not in negative_keyword_lib_names:
                negative_keyword_lib_names.append(config.negative_keyword_lib.name)
        for config in configs:
            shop_name = config.lingxing_shop.name if config.lingxing_shop else f"sid_未知"
            rpa_progress.append({
                'sequence': config.sequence,
                'shop_name': shop_name,
                'exec_status': config.exec_status,
                'exec_status_label': dict(ExecStatus.choices).get(config.exec_status, config.exec_status),
            })
            for listing in config.asins.all():
                shop_name = ''
                if listing.lingxing_shop and listing.lingxing_shop.name:
                    shop_name = listing.lingxing_shop.name
                elif config.lingxing_shop and config.lingxing_shop.name:
                    shop_name = config.lingxing_shop.name
                else:
                    shop_name = f"sid_{listing.sid}"

                detail_rows.append({
                    'row_key': f'{approval.id}-{config.id}-{listing.id}',
                    'config_id': config.id,
                    'asin': listing.asin or '',
                    'shop_name': shop_name,
                    'fulfillment_channel_type': listing.fulfillment_channel_type or '',
                })

    # 审批记录
    records = []
    for step in approval.steps.all().order_by('sequence'):
        step_record = step.records.order_by('-created_at').first()
        records.append({
            'step_name': step.step_name,
            'sequence': step.sequence,
            'approver_name': step.approver.first_name or step.approver.username if step.approver else '—',
            'result': step_record.result if step_record else None,
            'comment': step_record.comment if step_record else '',
            'created_at': step_record.created_at.strftime('%Y-%m-%d %H:%M:%S') if step_record else None,
            'is_pending': step.status == StepStatus.PENDING and not step_record,
        })

    # 审批链
    leader, supervisor = get_approval_chain(approval.applicant)

    # 当前用户是否可操作此审批单
    can_operate_this = False
    if approval.status == ApprovalStatus.PENDING:
        pending_step = approval.steps.filter(status=StepStatus.PENDING, approver__isnull=False).order_by('sequence').first()
        if pending_step:
            can_operate_this = pending_step.approver_id == request.user.id
    if not can_operate_this:
        can_operate_this = has_admin_555(request.user)

    return JsonResponse({
        'success': True,
        'data': {
            'approval_id': approval.id,
            'approval_no': approval.approval_no,
            'approval_type_label': dict(ApprovalType.choices).get(approval.approval_type, approval.approval_type),
            'applicant_name': approval.applicant.first_name or approval.applicant.username,
            'status': approval.status,
            'status_label': status_label,
            'exec_status': exec_status_code,
            'remark': ad_detail.remark if ad_detail else '',
            'negative_keyword_lib_names': negative_keyword_lib_names,
            'detail_rows': detail_rows,
            'records': records,
            'approval_chain': {
                'leader_name': leader.first_name or leader.username if leader else '未配置',
                'supervisor_name': supervisor.first_name or supervisor.username if supervisor else '未配置',
            },
            'rpa_progress': rpa_progress,
            'can_operate_this': can_operate_this,
            'created_at': approval.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'submitted_at': approval.submitted_at.strftime('%Y-%m-%d %H:%M:%S') if approval.submitted_at else '',
        }
    })


@login_required(login_url='/login/')
@require_http_methods(["DELETE"])
@transaction.atomic
def approval_delete_api(request, approval_id):
    try:
        approval = Approval.objects.get(id=approval_id, company=request.user.company)
    except Approval.DoesNotExist:
        return JsonResponse({'success': False, 'message': '审批单不存在'}, status=404)

    if not has_admin_555(request.user):
        return JsonResponse({'success': False, 'message': '无权删除该审批单'}, status=403)

    approval_no = approval.approval_no
    approval.delete()
    return JsonResponse({'success': True, 'message': f'审批单 {approval_no} 已删除'})


@login_required(login_url='/login/')
@require_http_methods(["POST"])
@transaction.atomic
def approval_list_action_api(request):
    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': '请求体不是有效 JSON'}, status=400)

    approval_id = payload.get('approval_id')
    action = (payload.get('action') or '').strip()
    comment = (payload.get('comment') or '').strip()

    if not approval_id:
        return JsonResponse({'success': False, 'message': '缺少 approval_id'}, status=400)

    if action not in {RecordResult.APPROVED, RecordResult.REJECTED}:
        return JsonResponse({'success': False, 'message': 'action 参数无效'}, status=400)

    try:
        approval_id = int(approval_id)
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'message': 'approval_id 参数无效'}, status=400)

    approval = (
        Approval.objects
        .select_for_update()
        .select_related('applicant')
        .filter(
            id=approval_id,
            company=request.user.company,
            status=ApprovalStatus.PENDING,
        )
        .first()
    )
    if not approval:
        return JsonResponse({'success': False, 'message': '审批单不存在或当前不可审批'}, status=404)

    # 权限校验：当前用户必须是指定审批人，或 555 权限
    is_approver = False
    pending_step = approval.steps.filter(status=StepStatus.PENDING, approver__isnull=False).order_by('sequence').first()
    if pending_step and pending_step.approver_id == request.user.id:
        is_approver = True
    is_admin = has_admin_555(request.user)
    if not is_approver and not is_admin:
        return JsonResponse({'success': False, 'message': '你不是该审批单的指定审批人'}, status=403)

    step, response = _process_approval_action(approval, request.user, action, comment)
    return response



@csrf_exempt
@require_http_methods(["POST"])
def external_update_exec_status_api(request):
    """
    对外执行状态更新接口（无需登录）
    POST /api/external/approval/update-exec-status/

    {
        "approval_no": "xxx",
        "sequence": 1,              # 可选，不传则更新该审批下全部 shop_config
        "exec_status": "completed"
    }
    """
    try:
        data = {}
        if request.body:
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                data = {}

        if not data:
            data = request.POST.dict()

        approval_no = (data.get('approval_no') or '').strip()
        sequence_raw = data.get('sequence')
        exec_status = (data.get('exec_status') or '').strip()

        if not approval_no:
            return JsonResponse({
                'success': False,
                'message': '缺少必要参数: approval_no'
            }, status=400)

        if not exec_status:
            return JsonResponse({
                'success': False,
                'message': '缺少必要参数: exec_status'
            }, status=400)

        valid_statuses = [choice.value for choice in ExecStatus]
        if exec_status not in valid_statuses:
            return JsonResponse({
                'success': False,
                'message': f'无效的执行状态，必须是: {", ".join(valid_statuses)}'
            }, status=400)

        sequence = None
        if sequence_raw is not None and str(sequence_raw).strip() != '':
            try:
                sequence = int(str(sequence_raw).strip())
            except (TypeError, ValueError):
                return JsonResponse({
                    'success': False,
                    'message': 'sequence 必须为整数'
                }, status=400)

        with transaction.atomic():
            approval = Approval.objects.select_related('ad_detail').filter(approval_no=approval_no).first()
            if not approval:
                return JsonResponse({
                    'success': False,
                    'message': '审批单不存在'
                }, status=404)

            ad_detail = getattr(approval, 'ad_detail', None)
            if not ad_detail:
                return JsonResponse({
                    'success': False,
                    'message': '该审批单无关联的开广告配置'
                }, status=404)

            if sequence is not None:
                config = AmazonAdShopConfig.objects.filter(
                    amazon_ad=ad_detail, sequence=sequence
                ).first()
                if not config:
                    return JsonResponse({
                        'success': False,
                        'message': f'未找到 sequence={sequence} 的店铺配置'
                    }, status=404)
                config.exec_status = exec_status
                config.save(update_fields=['exec_status', 'updated_at'])
                updated_count = 1
            else:
                updated_count = AmazonAdShopConfig.objects.filter(
                    amazon_ad=ad_detail
                ).update(exec_status=exec_status)

            # 同步更新 Approval.status
            all_configs = AmazonAdShopConfig.objects.filter(amazon_ad=ad_detail)
            exec_statuses = list(all_configs.values_list('exec_status', flat=True))
            
            new_approval_status = None
            if 'failed' in exec_statuses:
                new_approval_status = ApprovalStatus.FAILED
            elif all(s == 'success' for s in exec_statuses):
                new_approval_status = ApprovalStatus.SUCCESS
            elif all(s == 'executing' for s in exec_statuses):
                new_approval_status = ApprovalStatus.EXECUTING
            
            if new_approval_status and approval.status != new_approval_status:
                approval.status = new_approval_status
                approval.save(update_fields=['status', 'updated_at'])

        resp_data = {
            'approval_no': approval_no,
            'exec_status': exec_status,
        }
        if sequence is not None:
            resp_data['sequence'] = sequence
        else:
            resp_data['sequence'] = None
            resp_data['updated_count'] = updated_count

        return JsonResponse({
            'success': True,
            'data': resp_data
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': f'更新执行状态失败: {str(e)}'
        }, status=500)


# ==================== 审批流程配置 API ====================

def _get_configurable_members(user):
    """返回当前用户可配置审批流程的组员列表（QuerySet）"""
    if has_admin_555(user):
        return User.objects.filter(company=user.company, is_active=True).exclude(id=user.id)
    return User.objects.filter(company=user.company, manager=user, is_active=True)


def _can_configure_applicant(configurator, applicant):
    """检查 configurator 是否有权限配置 applicant 的审批流程"""
    if has_admin_555(configurator):
        return True
    return applicant.manager_id == configurator.id


@login_required(login_url='/login/')
@require_http_methods(["GET"])
def approval_flow_config_list_api(request):
    """
    GET /api/task/approvals/flow-config/
    列出当前用户可配置的组员及他们的审批流程配置
    """
    if not (has_admin_555(request.user) or (hasattr(request.user, 'is_group_leader') and request.user.is_group_leader())):
        return JsonResponse({'success': False, 'message': '无权访问'}, status=403)

    members_qs = _get_configurable_members(request.user)
    configs_qs = ApprovalFlowConfig.objects.filter(
        company=request.user.company,
        applicant__in=members_qs,
    )

    config_map = {}
    for cfg in configs_qs:
        key = (cfg.applicant_id, cfg.approval_type)
        config_map[key] = {
            'skip_approval': cfg.skip_approval,
            'step1_approver_id': cfg.proxy_approver_id,
            'step1_approver_name': (
                cfg.proxy_approver.first_name or cfg.proxy_approver.username
                if cfg.proxy_approver else None
            ),
            'step2_approver_id': cfg.step2_approver_id,
            'step2_approver_name': (
                cfg.step2_approver.first_name or cfg.step2_approver.username
                if cfg.step2_approver else None
            ),
        }

    members = []
    for user in members_qs.order_by('first_name', 'username'):
        member_configs = {}
        for atype, _ in ApprovalType.choices:
            key = (user.id, atype)
            if key in config_map:
                member_configs[atype] = config_map[key]
        members.append({
            'user_id': user.id,
            'user_name': user.first_name or user.username,
            'configs': member_configs,
        })

    proxies = []
    for user in members_qs.order_by('first_name', 'username'):
        proxies.append({
            'user_id': user.id,
            'user_name': user.first_name or user.username,
        })

    return JsonResponse({
        'success': True,
        'data': {
            'is_admin': has_admin_555(request.user),
            'members': members,
            'available_proxies': proxies,
        }
    })


@login_required(login_url='/login/')
@require_http_methods(["POST"])
@csrf_exempt
def approval_flow_config_save_api(request):
    """
    POST /api/task/approvals/flow-config/save/
    保存/更新某个组员的审批流程配置
    """
    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': '请求体不是有效 JSON'}, status=400)

    applicant_id = payload.get('applicant_id')
    approval_type = payload.get('approval_type') or ApprovalType.AMAZON_AD
    skip_approval = bool(payload.get('skip_approval', False))
    step1_approver_id = payload.get('step1_approver_id')
    step2_approver_id = payload.get('step2_approver_id')

    if not applicant_id:
        return JsonResponse({'success': False, 'message': '缺少 applicant_id'}, status=400)

    try:
        applicant = User.objects.get(id=int(applicant_id), company=request.user.company, is_active=True)
    except (User.DoesNotExist, ValueError, TypeError):
        return JsonResponse({'success': False, 'message': '员工不存在'}, status=404)

    if not _can_configure_applicant(request.user, applicant):
        return JsonResponse({'success': False, 'message': '无权配置该员工的审批流程'}, status=403)

    if skip_approval and (step1_approver_id or step2_approver_id):
        return JsonResponse({'success': False, 'message': '跳过审批与设置审批人不能同时设置'}, status=400)

    step1_approver = None
    if step1_approver_id:
        try:
            step1_approver = User.objects.get(
                id=int(step1_approver_id),
                company=request.user.company,
                is_active=True,
            )
        except (User.DoesNotExist, ValueError, TypeError):
            return JsonResponse({'success': False, 'message': '一级审批人不存在'}, status=404)

    step2_approver = None
    if step2_approver_id:
        try:
            step2_approver = User.objects.get(
                id=int(step2_approver_id),
                company=request.user.company,
                is_active=True,
            )
        except (User.DoesNotExist, ValueError, TypeError):
            return JsonResponse({'success': False, 'message': '二级审批人不存在'}, status=404)

    # 如果 skip=False 且 step1=None 且 step2=None，视为删除配置
    if not skip_approval and not step1_approver and not step2_approver:
        ApprovalFlowConfig.objects.filter(
            company=request.user.company,
            applicant=applicant,
            approval_type=approval_type,
        ).delete()
        return JsonResponse({
            'success': True,
            'message': '已恢复默认审批流程',
            'data': {'applicant_id': applicant.id, 'approval_type': approval_type}
        })

    config, created = ApprovalFlowConfig.objects.update_or_create(
        company=request.user.company,
        applicant=applicant,
        approval_type=approval_type,
        defaults={
            'skip_approval': skip_approval,
            'proxy_approver': step1_approver,
            'step2_approver': step2_approver,
        }
    )

    return JsonResponse({
        'success': True,
        'message': '配置已保存',
        'data': {
            'applicant_id': applicant.id,
            'approval_type': approval_type,
            'skip_approval': config.skip_approval,
            'step1_approver_id': config.proxy_approver_id,
            'step1_approver_name': (
                config.proxy_approver.first_name or config.proxy_approver.username
                if config.proxy_approver else None
            ),
            'step2_approver_id': config.step2_approver_id,
            'step2_approver_name': (
                config.step2_approver.first_name or config.step2_approver.username
                if config.step2_approver else None
            ),
        }
    })


@login_required(login_url='/login/')
@require_http_methods(["DELETE"])
@csrf_exempt
def approval_flow_config_delete_api(request):
    """
    DELETE /api/task/approvals/flow-config/delete/
    删除某个组员的审批流程配置，恢复默认
    """
    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': '请求体不是有效 JSON'}, status=400)

    applicant_id = payload.get('applicant_id')
    approval_type = payload.get('approval_type') or ApprovalType.AMAZON_AD

    if not applicant_id:
        return JsonResponse({'success': False, 'message': '缺少 applicant_id'}, status=400)

    try:
        applicant = User.objects.get(id=int(applicant_id), company=request.user.company, is_active=True)
    except (User.DoesNotExist, ValueError, TypeError):
        return JsonResponse({'success': False, 'message': '员工不存在'}, status=404)

    if not _can_configure_applicant(request.user, applicant):
        return JsonResponse({'success': False, 'message': '无权配置该员工的审批流程'}, status=403)

    deleted, _ = ApprovalFlowConfig.objects.filter(
        company=request.user.company,
        applicant=applicant,
        approval_type=approval_type,
    ).delete()

    return JsonResponse({
        'success': True,
        'message': '配置已删除，恢复默认审批流程',
        'data': {'applicant_id': applicant.id, 'approval_type': approval_type, 'deleted': deleted > 0}
    })
