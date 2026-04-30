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
    pause_listing_optimization_job,
    serialize_job,
    start_listing_optimization_job,
    update_row_optimized_data,
)


@login_required(login_url="/login/")
def listing_optimizer_page(request):
    return render(request, "listing_optimizer.html", {
        "active_nav": "task",
        "active_page": "listing_optimizer_page",
    })


@login_required
@require_http_methods(["GET"])
def listing_optimizer_jobs_api(request):
    jobs = ListingOptimizationJob.objects.filter(created_by=request.user).order_by("-created_at")[:30]
    return JsonResponse({
        "success": True,
        "data": [serialize_job(job) for job in jobs],
    })


@login_required
@require_http_methods(["POST"])
def listing_optimizer_upload_api(request):
    if "file" not in request.FILES:
        return JsonResponse({"success": False, "message": "未找到上传文件。"}, status=400)

    try:
        job = create_job_from_excel(request.FILES["file"], request.user)
        transaction.on_commit(lambda: start_listing_optimization_job(job.id))
        job = ListingOptimizationJob.objects.prefetch_related("rows").get(id=job.id)
        return JsonResponse({
            "success": True,
            "message": "文件已上传，正在后台逐行优化。",
            "data": serialize_job(job, include_rows=True),
            "output_keys": OUTPUT_KEYS,
        })
    except ListingValidationError as exc:
        return JsonResponse({"success": False, "message": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({"success": False, "message": f"上传解析失败: {str(exc)}"}, status=500)


@login_required
@require_http_methods(["GET"])
def listing_optimizer_job_detail_api(request, job_id):
    job = get_object_or_404(
        ListingOptimizationJob.objects.prefetch_related("rows"),
        id=job_id,
        created_by=request.user,
    )
    ensure_listing_job_running(job)
    return JsonResponse({
        "success": True,
        "data": serialize_job(job, include_rows=True),
        "output_keys": OUTPUT_KEYS,
    })


@login_required
@require_http_methods(["POST"])
def listing_optimizer_pause_api(request, job_id):
    job = get_object_or_404(ListingOptimizationJob, id=job_id, created_by=request.user)
    pause_listing_optimization_job(job)
    job.refresh_from_db()
    return JsonResponse({
        "success": True,
        "message": "已暂停。当前正在请求中的行可能会完成，但不会继续优化下一行。",
        "data": serialize_job(job),
    })


@login_required
@require_http_methods(["POST"])
def listing_optimizer_row_save_api(request, row_id):
    row = get_object_or_404(
        ListingOptimizationRow.objects.select_related("job"),
        id=row_id,
        job__created_by=request.user,
    )
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
    job = get_object_or_404(ListingOptimizationJob, id=job_id, created_by=request.user)
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
            "data": serialize_job(job),
        })
    except Exception as exc:
        return JsonResponse({"success": False, "message": f"生成文件失败: {str(exc)}"}, status=500)


@login_required
@require_http_methods(["GET"])
def listing_optimizer_download_api(request, job_id):
    job = get_object_or_404(ListingOptimizationJob, id=job_id, created_by=request.user)
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
