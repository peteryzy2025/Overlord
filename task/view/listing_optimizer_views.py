# -*- coding: utf-8 -*-
import json
import os

from django.conf import settings
from django.db import transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods

from task.models import ListingOptimizationJob, ListingOptimizationRow
from task.services.listing_optimizer_service import (
    ListingValidationError,
    OUTPUT_KEYS,
    create_job_from_excel,
    ensure_listing_job_running,
    generate_optimized_excel,
    get_listing_optimizer_config,
    pause_listing_optimization_job,
    retry_failed_listing_rows,
    serialize_job,
    start_listing_infringement_check_job,
    start_listing_optimization_job,
    update_row_optimized_data,
)


LISTING_OPTIMIZER_VIEW_ALL_CODE = 555


def _can_view_all_listing_jobs(user) -> bool:
    try:
        return user.permission_configs.filter(code=LISTING_OPTIMIZER_VIEW_ALL_CODE).exists()
    except Exception:
        return False


def _listing_job_queryset(user):
    queryset = ListingOptimizationJob.objects.select_related("created_by")
    if _can_view_all_listing_jobs(user):
        return queryset
    return queryset.filter(created_by=user)


def _get_accessible_listing_job(user, job_id, *, prefetch_rows=False):
    queryset = _listing_job_queryset(user)
    if prefetch_rows:
        queryset = queryset.prefetch_related("rows")
    return get_object_or_404(queryset, id=job_id)


def _get_accessible_listing_row(user, row_id):
    return get_object_or_404(
        ListingOptimizationRow.objects.select_related("job", "job__created_by").filter(
            job_id__in=_listing_job_queryset(user).values("id")
        ),
        id=row_id,
    )


@login_required(login_url="/login/")
def listing_optimizer_page(request):
    return render(request, "listing_optimizer.html", {
        "active_nav": "task",
        "active_page": "listing_optimizer_page",
        "optimizer_config": get_listing_optimizer_config(),
    })


@login_required
@require_http_methods(["GET"])
def listing_optimizer_jobs_api(request):
    can_view_all = _can_view_all_listing_jobs(request.user)
    jobs = _listing_job_queryset(request.user).order_by("-created_at")[:30]
    return JsonResponse({
        "success": True,
        "data": [serialize_job(job, include_owner=can_view_all) for job in jobs],
    })


@login_required
@require_http_methods(["POST"])
def listing_optimizer_upload_api(request):
    if "file" not in request.FILES:
        return JsonResponse({"success": False, "message": "未找到上传文件。"}, status=400)

    try:
        job = create_job_from_excel(
            request.FILES["file"],
            request.user,
            prompt_profile=request.POST.get("prompt_profile", ""),
            ai_model=request.POST.get("ai_model", ""),
            enable_infringement_check=_truthy(request.POST.get("enable_infringement_check")),
        )
        transaction.on_commit(lambda: start_listing_optimization_job(job.id))
        job = ListingOptimizationJob.objects.prefetch_related("rows").get(id=job.id)
        return JsonResponse({
            "success": True,
            "message": "文件已上传，正在后台逐行优化。",
            "data": serialize_job(job, include_rows=True, include_owner=_can_view_all_listing_jobs(request.user)),
            "output_keys": OUTPUT_KEYS,
        })
    except ListingValidationError as exc:
        return JsonResponse({"success": False, "message": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({"success": False, "message": f"上传解析失败: {str(exc)}"}, status=500)


@login_required
@require_http_methods(["GET"])
def listing_optimizer_job_detail_api(request, job_id):
    job = _get_accessible_listing_job(request.user, job_id, prefetch_rows=True)
    ensure_listing_job_running(job)
    return JsonResponse({
        "success": True,
        "data": serialize_job(job, include_rows=True, include_owner=_can_view_all_listing_jobs(request.user)),
        "output_keys": OUTPUT_KEYS,
    })


@login_required
@require_http_methods(["POST"])
def listing_optimizer_pause_api(request, job_id):
    job = _get_accessible_listing_job(request.user, job_id)
    pause_listing_optimization_job(job)
    job.refresh_from_db()
    return JsonResponse({
        "success": True,
        "message": "已暂停。当前正在请求中的行可能会完成，但不会继续优化下一行。",
        "data": serialize_job(job, include_owner=_can_view_all_listing_jobs(request.user)),
    })


@login_required
@require_http_methods(["POST"])
def listing_optimizer_resume_api(request, job_id):
    job = _get_accessible_listing_job(request.user, job_id)
    if job.status != ListingOptimizationJob.STATUS_PAUSED:
        return JsonResponse({
            "success": False,
            "message": "只有已暂停的任务可以继续优化。",
        }, status=400)

    job.status = ListingOptimizationJob.STATUS_PENDING
    job.save(update_fields=["status", "updated_at"])
    transaction.on_commit(lambda: start_listing_optimization_job(job.id))
    job.refresh_from_db()
    return JsonResponse({
        "success": True,
        "message": "已继续优化，将从未完成的行接着处理。",
        "data": serialize_job(job, include_owner=_can_view_all_listing_jobs(request.user)),
    })


@login_required
@require_http_methods(["POST"])
def listing_optimizer_retry_failed_api(request, job_id):
    job = _get_accessible_listing_job(request.user, job_id)
    try:
        job, retry_count, should_start = retry_failed_listing_rows(job)
        if retry_count == 0:
            return JsonResponse({
                "success": False,
                "message": "没有失败行需要重试。",
            }, status=400)

        if should_start:
            transaction.on_commit(lambda: start_listing_optimization_job(job.id))
            message = f"已重新提交 {retry_count} 行失败数据，后台正在重试。"
        else:
            message = f"已将 {retry_count} 行失败数据放回待优化，点击继续优化后会处理。"

        job = ListingOptimizationJob.objects.prefetch_related("rows").get(id=job.id)
        return JsonResponse({
            "success": True,
            "message": message,
            "data": serialize_job(job, include_rows=True, include_owner=_can_view_all_listing_jobs(request.user)),
        })
    except ListingValidationError as exc:
        return JsonResponse({"success": False, "message": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({"success": False, "message": f"重试失败行失败: {str(exc)}"}, status=500)


@login_required
@require_http_methods(["POST"])
def listing_optimizer_row_retry_api(request, row_id):
    row = _get_accessible_listing_row(request.user, row_id)
    try:
        job, retry_count, should_start = retry_failed_listing_rows(row.job, row_ids=[row.id])
        if retry_count == 0:
            return JsonResponse({
                "success": False,
                "message": "这一行不是失败状态，不能重试。",
            }, status=400)

        if should_start:
            transaction.on_commit(lambda: start_listing_optimization_job(job.id))
            message = "已重新提交本行，后台正在重试。"
        else:
            message = "已将本行放回待优化，点击继续优化后会处理。"

        job = ListingOptimizationJob.objects.prefetch_related("rows").get(id=job.id)
        return JsonResponse({
            "success": True,
            "message": message,
            "data": serialize_job(job, include_rows=True, include_owner=_can_view_all_listing_jobs(request.user)),
        })
    except ListingValidationError as exc:
        return JsonResponse({"success": False, "message": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({"success": False, "message": f"重试本行失败: {str(exc)}"}, status=500)


@login_required
@require_http_methods(["POST"])
def listing_optimizer_row_save_api(request, row_id):
    row = _get_accessible_listing_row(request.user, row_id)
    try:
        body = _json_body(request)
        optimized_data = body.get("optimized_data", {})
        if not isinstance(optimized_data, dict):
            return JsonResponse({"success": False, "message": "optimized_data 必须是对象。"}, status=400)
        row = update_row_optimized_data(row, optimized_data)
        return JsonResponse({
            "success": True,
            "data": {
                "row": {
                    "id": row.id,
                    "optimized_data": row.optimized_data,
                    "updated_at": row.updated_at.strftime("%Y-%m-%d %H:%M:%S") if row.updated_at else "",
                }
            },
        })
    except Exception as exc:
        return JsonResponse({"success": False, "message": f"保存失败: {str(exc)}"}, status=500)


@login_required
@require_http_methods(["POST"])
def listing_optimizer_generate_api(request, job_id):
    job = _get_accessible_listing_job(request.user, job_id)
    try:
        body = _json_body(request)
        rows_payload = body.get("rows", [])
        if rows_payload:
            _save_rows_payload(job, rows_payload)

        generate_optimized_excel(job)
        job.refresh_from_db()
        return JsonResponse({
            "success": True,
            "message": "文件已生成。",
            "data": serialize_job(job, include_owner=_can_view_all_listing_jobs(request.user)),
        })
    except Exception as exc:
        return JsonResponse({"success": False, "message": f"生成文件失败: {str(exc)}"}, status=500)


@login_required
@require_http_methods(["POST"])
def listing_optimizer_infringement_check_api(request, job_id):
    job = _get_accessible_listing_job(request.user, job_id)
    if job.status in {ListingOptimizationJob.STATUS_PENDING, ListingOptimizationJob.STATUS_PROCESSING}:
        return JsonResponse({
            "success": False,
            "message": "任务还在优化中，请等优化结束后再做侵权检测。",
        }, status=400)

    try:
        body = _json_body(request)
        rows_payload = body.get("rows", [])
        if rows_payload:
            _save_rows_payload(job, rows_payload)

        completed_count = ListingOptimizationRow.objects.filter(
            job=job,
            status=ListingOptimizationRow.STATUS_COMPLETED,
        ).count()
        if completed_count == 0:
            return JsonResponse({
                "success": False,
                "message": "没有已完成的优化行可检测。",
            }, status=400)

        started = start_listing_infringement_check_job(job.id)
        job = ListingOptimizationJob.objects.prefetch_related("rows").get(id=job.id)
        return JsonResponse({
            "success": True,
            "message": "侵权检测已提交，后台正在按组词方式检测。" if started else "侵权检测正在进行中，请稍候。",
            "data": serialize_job(job, include_rows=True, include_owner=_can_view_all_listing_jobs(request.user)),
        })
    except Exception as exc:
        return JsonResponse({"success": False, "message": f"侵权检测提交失败: {str(exc)}"}, status=500)


@login_required
@require_http_methods(["GET"])
def listing_optimizer_download_api(request, job_id):
    job = _get_accessible_listing_job(request.user, job_id)
    if not job.output_file_path:
        raise Http404("文件尚未生成")

    full_path = os.path.abspath(os.path.join(settings.MEDIA_ROOT, job.output_file_path))
    media_root = os.path.abspath(settings.MEDIA_ROOT)
    if os.path.commonpath([media_root, full_path]) != media_root or not os.path.exists(full_path):
        raise Http404("文件不存在")

    return FileResponse(
        open(full_path, "rb"),
        as_attachment=True,
        filename=os.path.basename(full_path),
    )


def _json_body(request):
    if not request.body:
        return {}
    return json.loads(request.body.decode("utf-8"))


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "y"}


def _save_rows_payload(job: ListingOptimizationJob, rows_payload):
    if not isinstance(rows_payload, list):
        raise ValueError("rows 必须是数组。")

    rows_by_id = {
        row.id: row
        for row in ListingOptimizationRow.objects.filter(job=job)
    }
    for item in rows_payload:
        if not isinstance(item, dict):
            continue
        row_id = item.get("id")
        optimized_data = item.get("optimized_data", {})
        row = rows_by_id.get(int(row_id)) if str(row_id).isdigit() else None
        if row and isinstance(optimized_data, dict):
            update_row_optimized_data(row, optimized_data)
