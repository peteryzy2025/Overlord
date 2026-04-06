import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Prefetch
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from amazon.listing_models import AmazonListingV2
from amazon.models import LingXingAmazonShop
from general.models import OperationalAccount
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
    if approval.status == ApprovalStatus.APPROVED:
        return '已通过'
    if approval.status == ApprovalStatus.REJECTED:
        return '已驳回'
    if approval.status == ApprovalStatus.DRAFT:
        return '草稿'
    if approval.current_step_sequence == 0:
        return '组长审核中'
    if approval.current_step_sequence == 1:
        return '主管审核中'
    if approval.current_step_sequence == 2:
        return '已通过'
    return f'第{approval.current_step_sequence}步审核中'


def create_approval_steps(approval, applicant):
    leader, supervisor = get_approval_chain(applicant)
    step_1 = ApprovalStep.objects.create(
        company=approval.company,
        approval=approval,
        sequence=1,
        step_name='组长审核',
        approver=leader,
        status=StepStatus.PENDING,
    )
    step_2 = ApprovalStep.objects.create(
        company=approval.company,
        approval=approval,
        sequence=2,
        step_name='主管审核',
        approver=supervisor,
        status=StepStatus.PENDING,
    )
    return step_1, step_2


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
        'active_page': 'task_create_page',
    })


@login_required(login_url='/login/')
def approval_draft_page(request):
    if not has_approval_access(request.user):
        return redirect('/')

    return render(request, 'approval_draft_list.html', {
        'active_nav': 'task',
        'active_page': 'approval_draft_page',
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
        configs = ad_detail.shop_configs.select_related('lingxing_shop').prefetch_related('asins__lingxing_shop').order_by('sequence', 'id')
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
                })

            shop_configs.append({
                'sid': str(config.lingxing_shop.sid),
                'selected_listings': selected_listings,
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
            'local_sku': listing.local_sku or '',
            'seller_sku': listing.seller_sku or '',
            'fulfillment_channel_type': listing.fulfillment_channel_type or '',
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

    asin_prefetch = Prefetch(
        'asins',
        queryset=AmazonListingV2.objects.select_related('lingxing_shop').order_by('asin', 'id'),
    )
    shop_configs = (
        AmazonAdShopConfig.objects
        .filter(
            company=request.user.company,
            amazon_ad__approval__approval_type=ApprovalType.AMAZON_AD,
            amazon_ad__approval__status=ApprovalStatus.PENDING,
            amazon_ad__approval__current_step_sequence=0,
            amazon_ad__approval__steps__sequence=1,
            amazon_ad__approval__steps__status=StepStatus.PENDING,
            amazon_ad__approval__steps__approver=request.user,
        )
        .select_related('amazon_ad__approval__applicant', 'amazon_ad__approval', 'lingxing_shop')
        .prefetch_related(asin_prefetch)
        .order_by('-amazon_ad__approval__created_at', 'sequence', 'id')
        .distinct()
    )

    rows = []
    for config in shop_configs:
        approval = config.amazon_ad.approval
        applicant_name = approval.applicant.first_name or approval.applicant.username
        current_status_label = get_current_status_label(approval)
        for listing in config.asins.all():
            shop_name = ''
            if listing.lingxing_shop and listing.lingxing_shop.name:
                shop_name = listing.lingxing_shop.name
            elif config.lingxing_shop and config.lingxing_shop.name:
                shop_name = config.lingxing_shop.name
            else:
                shop_name = f"sid_{listing.sid}"

            rows.append({
                'row_key': f'{approval.id}-{config.id}-{listing.id}',
                'approval_id': approval.id,
                'approval_no': approval.approval_no,
                'applicant_name': applicant_name,
                'current_step_sequence': approval.current_step_sequence,
                'current_status_label': current_status_label,
                'asin': listing.asin or '',
                'shop_name': shop_name,
            })

    paginator = Paginator(rows, page_size)
    page_obj = paginator.get_page(page)

    return JsonResponse({
        'success': True,
        'data': list(page_obj.object_list),
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

    shop_configs = payload.get('shop_configs') or []
    if not isinstance(shop_configs, list) or not shop_configs:
        return JsonResponse({'success': False, 'message': '至少需要一组店铺与 ASIN 配置'}, status=400)

    normalized_configs = []
    for index, config in enumerate(shop_configs, start=1):
        sid = config.get('sid')
        listing_ids = config.get('listing_ids') or config.get('asin_ids') or []

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
                status=ApprovalStatus.DRAFT,
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

    create_approval_steps(approval, request.user)

    for sequence, config in enumerate(normalized_configs, start=1):
        lingxing_shop = LingXingAmazonShop.objects.get(sid=config['sid'])
        shop_config = AmazonAdShopConfig.objects.create(
            company=request.user.company,
            amazon_ad=ad_approval,
            lingxing_shop=lingxing_shop,
            sequence=sequence,
        )
        shop_config.asins.set(config['listings'])

    approval.status = ApprovalStatus.PENDING
    approval.current_step_sequence = 0
    approval.submitted_at = timezone.now()
    approval.completed_at = None
    approval.save()

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
                'message': '审批已通过，已流转至主管审核',
                'data': {
                    'approval_id': approval.id,
                    'approval_no': approval.approval_no,
                    'next_step_sequence': 2,
                }
            })

        if next_step and next_step.status == StepStatus.PENDING:
            next_step.status = StepStatus.SKIPPED
            next_step.save()

        approval.status = ApprovalStatus.APPROVED
        approval.current_step_sequence = 2
        approval.completed_at = timezone.now()
        approval.save()
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
        'message': f'审批已驳回，并自动生成复制草稿 {cloned_approval.approval_no}',
        'data': {
            'approval_id': approval.id,
            'approval_no': approval.approval_no,
            'cloned_approval_id': cloned_approval.id,
            'cloned_approval_no': cloned_approval.approval_no,
        }
    })
