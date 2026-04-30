import json
import traceback

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from general.models import Project, ProjectLingxingLogisticsCode
from general.views_amazon_management import has_perm_code


def _current_company(user):
    return getattr(user, 'company', None)


def _can_access_project_management(user):
    return has_perm_code(user, '5555')


def _project_payload(project):
    configs = []
    for config in project.lingxing_logistics_codes.all():
        configs.append({
            'id': config.id,
            'logistics_key': config.logistics_key,
            'logistics_key_display': config.get_logistics_key_display(),
            'logistics_name': config.logistics_name,
            'logistics_type_id': config.logistics_type_id,
            'enabled': config.enabled,
            'remark': config.remark,
        })

    return {
        'id': project.id,
        'name': project.name,
        'code': project.code,
        'description': project.description or '',
        'manager_id': project.manager_id,
        'manager_name': project.manager.first_name if project.manager else '',
        'sort_order': project.sort_order,
        'is_active': project.is_active,
        'lingxing_app_id': project.lingxing_app_id or '',
        'lingxing_app_secret': project.lingxing_app_secret or '',
        'divi_partner_code': project.divi_partner_code or '',
        'divi_secret': project.divi_secret or '',
        'lingxing_sync_enabled': project.lingxing_sync_enabled,
        'divi_sync_enabled': project.divi_sync_enabled,
        'created_at': project.created_at.strftime('%Y-%m-%d %H:%M:%S') if project.created_at else '',
        'updated_at': project.updated_at.strftime('%Y-%m-%d %H:%M:%S') if project.updated_at else '',
        'logistics_codes': configs,
    }


def _get_project_or_404(project_id, company):
    return Project.objects.prefetch_related('lingxing_logistics_codes').select_related(
        'company', 'manager'
    ).get(id=project_id, company=company)


def _int_value(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_logistics_rows(rows):
    allowed_keys = {value for value, _ in ProjectLingxingLogisticsCode.LogisticsKey.choices}
    seen = set()
    normalized_rows = []

    for idx, row in enumerate(rows or [], 1):
        key = (row.get('logistics_key') or '').strip()
        logistics_type_id = (row.get('logistics_type_id') or '').strip()
        if not key and not logistics_type_id:
            continue
        if key not in allowed_keys:
            raise ValueError(f'第 {idx} 行物流识别键无效')
        if not logistics_type_id:
            raise ValueError(f'第 {idx} 行领星物流编码不能为空')
        if key in seen:
            raise ValueError(f'物流识别键 {key} 重复')
        seen.add(key)
        normalized_rows.append({
            'logistics_key': key,
            'logistics_name': (row.get('logistics_name') or '').strip(),
            'logistics_type_id': logistics_type_id,
            'enabled': bool(row.get('enabled', True)),
            'remark': (row.get('remark') or '').strip(),
        })

    return normalized_rows, seen


@login_required
def project_management_view(request):
    """项目和项目级领星物流编码配置页面。"""
    if not _can_access_project_management(request.user):
        return redirect('general:main')

    choices = [
        {'value': value, 'label': label}
        for value, label in ProjectLingxingLogisticsCode.LogisticsKey.choices
    ]
    return render(request, 'management/project_management.html', {
        'active_page': 'project_management',
        'active_nav': 'management',
        'logistics_choices_json': json.dumps(choices, ensure_ascii=False),
    })


@require_GET
@login_required
def get_projects_api(request):
    """获取当前公司项目列表，附带物流编码配置。"""
    try:
        if not _can_access_project_management(request.user):
            return JsonResponse({'success': False, 'error': '无权限访问'}, status=403)

        company = _current_company(request.user)
        if not company:
            return JsonResponse({'success': False, 'error': '当前用户无公司归属'}, status=403)

        projects = Project.objects.filter(company=company).select_related(
            'company', 'manager'
        ).prefetch_related('lingxing_logistics_codes').order_by(
            'sort_order', '-created_at'
        )

        return JsonResponse({
            'success': True,
            'data': [_project_payload(project) for project in projects],
        })
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'获取项目列表失败: {str(e)}'}, status=500)


@require_GET
@login_required
def get_logistics_choices_api(request):
    """获取可维护的物流识别键。"""
    if not _can_access_project_management(request.user):
        return JsonResponse({'success': False, 'error': '无权限访问'}, status=403)

    return JsonResponse({
        'success': True,
        'data': [
            {'value': value, 'label': label}
            for value, label in ProjectLingxingLogisticsCode.LogisticsKey.choices
        ]
    })


@require_POST
@csrf_exempt
@login_required
def create_project_api(request):
    """创建项目。"""
    try:
        if not _can_access_project_management(request.user):
            return JsonResponse({'success': False, 'error': '无权限访问'}, status=403)

        company = _current_company(request.user)
        if not company:
            return JsonResponse({'success': False, 'error': '当前用户无公司归属'}, status=403)

        data = json.loads(request.body or '{}')
        name = (data.get('name') or '').strip()
        code = (data.get('code') or '').strip()
        if not name:
            return JsonResponse({'success': False, 'error': '项目名称不能为空'}, status=400)
        if not code:
            return JsonResponse({'success': False, 'error': '项目代码不能为空'}, status=400)
        if Project.objects.filter(company=company, name=name).exists():
            return JsonResponse({'success': False, 'error': '该公司下已存在同名项目'}, status=400)

        with transaction.atomic():
            project = Project.objects.create(
                company=company,
                name=name,
                code=code,
                description=(data.get('description') or '').strip(),
                sort_order=_int_value(data.get('sort_order'), 0),
                is_active=bool(data.get('is_active', True)),
                lingxing_app_id=(data.get('lingxing_app_id') or '').strip() or None,
                lingxing_app_secret=(data.get('lingxing_app_secret') or '').strip() or None,
                divi_partner_code=(data.get('divi_partner_code') or '').strip() or None,
                divi_secret=(data.get('divi_secret') or '').strip() or None,
                lingxing_sync_enabled=bool(data.get('lingxing_sync_enabled', False)),
                divi_sync_enabled=bool(data.get('divi_sync_enabled', False)),
            )

        return JsonResponse({'success': True, 'message': '项目创建成功', 'data': _project_payload(project)})
    except IntegrityError:
        return JsonResponse({'success': False, 'error': '项目代码或名称已存在'}, status=400)
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'创建项目失败: {str(e)}'}, status=500)


@require_POST
@csrf_exempt
@login_required
def update_project_api(request, project_id):
    """更新项目基础信息。"""
    try:
        if not _can_access_project_management(request.user):
            return JsonResponse({'success': False, 'error': '无权限访问'}, status=403)

        company = _current_company(request.user)
        if not company:
            return JsonResponse({'success': False, 'error': '当前用户无公司归属'}, status=403)

        data = json.loads(request.body or '{}')
        project = Project.objects.get(id=project_id, company=company)

        name = (data.get('name') or '').strip()
        code = (data.get('code') or '').strip()
        if not name:
            return JsonResponse({'success': False, 'error': '项目名称不能为空'}, status=400)
        if not code:
            return JsonResponse({'success': False, 'error': '项目代码不能为空'}, status=400)
        if Project.objects.filter(company=company, name=name).exclude(id=project.id).exists():
            return JsonResponse({'success': False, 'error': '该公司下已存在同名项目'}, status=400)

        with transaction.atomic():
            project.name = name
            project.code = code
            project.description = (data.get('description') or '').strip()
            project.sort_order = _int_value(data.get('sort_order'), project.sort_order)
            project.is_active = bool(data.get('is_active', project.is_active))
            project.lingxing_app_id = (data.get('lingxing_app_id') or '').strip() or None
            project.lingxing_app_secret = (data.get('lingxing_app_secret') or '').strip() or None
            project.divi_partner_code = (data.get('divi_partner_code') or '').strip() or None
            project.divi_secret = (data.get('divi_secret') or '').strip() or None
            project.lingxing_sync_enabled = bool(data.get('lingxing_sync_enabled', project.lingxing_sync_enabled))
            project.divi_sync_enabled = bool(data.get('divi_sync_enabled', project.divi_sync_enabled))
            project.save()

        project = _get_project_or_404(project.id, company)
        return JsonResponse({'success': True, 'message': '项目更新成功', 'data': _project_payload(project)})
    except Project.DoesNotExist:
        return JsonResponse({'success': False, 'error': '项目不存在或不属于当前公司'}, status=404)
    except IntegrityError:
        return JsonResponse({'success': False, 'error': '项目代码或名称已存在'}, status=400)
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'更新项目失败: {str(e)}'}, status=500)


@require_POST
@csrf_exempt
@login_required
def save_project_logistics_codes_api(request, project_id):
    """覆盖保存项目的领星物流编码配置。"""
    try:
        if not _can_access_project_management(request.user):
            return JsonResponse({'success': False, 'error': '无权限访问'}, status=403)

        company = _current_company(request.user)
        if not company:
            return JsonResponse({'success': False, 'error': '当前用户无公司归属'}, status=403)

        data = json.loads(request.body or '{}')
        rows = data.get('logistics_codes') or []
        project = Project.objects.get(id=project_id, company=company)
        normalized_rows, seen = _normalize_logistics_rows(rows)

        with transaction.atomic():
            ProjectLingxingLogisticsCode.objects.filter(project=project).exclude(
                logistics_key__in=seen
            ).delete()

            for row in normalized_rows:
                ProjectLingxingLogisticsCode.objects.update_or_create(
                    project=project,
                    logistics_key=row['logistics_key'],
                    defaults={
                        'logistics_name': row['logistics_name'],
                        'logistics_type_id': row['logistics_type_id'],
                        'enabled': row['enabled'],
                        'remark': row['remark'],
                    }
                )

        project = _get_project_or_404(project.id, company)
        return JsonResponse({'success': True, 'message': '物流编码配置已保存', 'data': _project_payload(project)})
    except ValueError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Project.DoesNotExist:
        return JsonResponse({'success': False, 'error': '项目不存在或不属于当前公司'}, status=404)
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'保存物流编码失败: {str(e)}'}, status=500)


@require_POST
@csrf_exempt
@login_required
def copy_project_logistics_codes_api(request, project_id):
    """把当前项目的物流编码复制到另一个项目。"""
    try:
        if not _can_access_project_management(request.user):
            return JsonResponse({'success': False, 'error': '无权限访问'}, status=403)

        company = _current_company(request.user)
        if not company:
            return JsonResponse({'success': False, 'error': '当前用户无公司归属'}, status=403)

        data = json.loads(request.body or '{}')
        target_project_id = data.get('target_project_id')
        overwrite = bool(data.get('overwrite', True))

        if not target_project_id:
            return JsonResponse({'success': False, 'error': '请选择目标项目'}, status=400)
        if str(project_id) == str(target_project_id):
            return JsonResponse({'success': False, 'error': '不能复制到当前项目'}, status=400)

        source_project = Project.objects.get(id=project_id, company=company)
        target_project = Project.objects.get(id=target_project_id, company=company)

        if 'logistics_codes' in data:
            normalized_rows, _ = _normalize_logistics_rows(data.get('logistics_codes') or [])
        else:
            normalized_rows = [
                {
                    'logistics_key': row.logistics_key,
                    'logistics_name': row.logistics_name,
                    'logistics_type_id': row.logistics_type_id,
                    'enabled': row.enabled,
                    'remark': row.remark,
                }
                for row in ProjectLingxingLogisticsCode.objects.filter(project=source_project)
            ]

        if not normalized_rows:
            return JsonResponse({'success': False, 'error': '当前项目没有可复制的物流编码'}, status=400)

        created = 0
        updated = 0
        skipped = 0
        with transaction.atomic():
            existing_keys = set(
                ProjectLingxingLogisticsCode.objects.filter(
                    project=target_project
                ).values_list('logistics_key', flat=True)
            )
            for row in normalized_rows:
                if not overwrite and row['logistics_key'] in existing_keys:
                    skipped += 1
                    continue

                _, was_created = ProjectLingxingLogisticsCode.objects.update_or_create(
                    project=target_project,
                    logistics_key=row['logistics_key'],
                    defaults={
                        'logistics_name': row['logistics_name'],
                        'logistics_type_id': row['logistics_type_id'],
                        'enabled': row['enabled'],
                        'remark': row['remark'],
                    }
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        target_project = _get_project_or_404(target_project.id, company)
        return JsonResponse({
            'success': True,
            'message': (
                f'已复制到 {target_project.name}：新增 {created}，'
                f'更新 {updated}，跳过 {skipped}'
            ),
            'data': {
                'source_project': _project_payload(source_project),
                'target_project': _project_payload(target_project),
                'created': created,
                'updated': updated,
                'skipped': skipped,
            }
        })
    except ValueError as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Project.DoesNotExist:
        return JsonResponse({'success': False, 'error': '项目不存在或不属于当前公司'}, status=404)
    except Exception as e:
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': f'复制物流编码失败: {str(e)}'}, status=500)
