"""HTTP views for the SQLite-backed local dashboard."""

from __future__ import annotations

import json
import mimetypes
import sqlite3
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from usage_database import dashboard_data
from workflow_api import board, card_details, criterion_catalog, create_command, decide_card_proposal, metrics, submit_session_opinion, submit_card_proposal, submit_delivery, submit_quality, transition_assigned_card


ASSET_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_SHARED_ASSETS = ASSET_ROOT / "shared_identity"
SOURCE_SHARED_ASSETS = ASSET_ROOT.parent.parent / "docs" / "coordination" / "assets"
SHARED_ASSETS = BUNDLED_SHARED_ASSETS if BUNDLED_SHARED_ASSETS.is_dir() else SOURCE_SHARED_ASSETS
IDENTITY_ASSETS = {
    "identity.css": SHARED_ASSETS / "identity.css",
    "cairo-arabic.woff2": SHARED_ASSETS / "fonts" / "cairo-arabic.woff2",
    "ibm-plex-sans-arabic.woff2": SHARED_ASSETS / "fonts" / "ibm-plex-sans-arabic.woff2",
    "manrope-latin.woff2": SHARED_ASSETS / "fonts" / "manrope-latin.woff2",
    "plus-jakarta-sans-latin.woff2": SHARED_ASSETS / "fonts" / "plus-jakarta-sans-latin.woff2",
}
DASHBOARD_ASSETS = {"dashboard.js", "workflow.js", "workflow.css"}


def _json(data: dict, status: int = 200) -> JsonResponse:
    response = JsonResponse(
        data, status=status,
        json_dumps_params={"ensure_ascii": False, "separators": (",", ":")},
    )
    response["Cache-Control"] = "no-store"
    return response


def _service_error(message: str, exc: Exception) -> JsonResponse:
    return _json({"error": {"message": f"{message}: {exc}"}}, status=503)


@require_GET
@ensure_csrf_cookie
def dashboard(request: HttpRequest) -> HttpResponse:
    return FileResponse((ASSET_ROOT / "dashboard.html").open("rb"), content_type="text/html; charset=utf-8")


@require_GET
def dashboard_api(request: HttpRequest) -> JsonResponse:
    try:
        return _json(dashboard_data(settings.USAGE_DATABASE))
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        return _service_error("تعذر قراءة بيانات لوحة الاستهلاك", exc)


@require_GET
def workflow_board_api(request: HttpRequest) -> JsonResponse:
    try:
        data = board(
            settings.USAGE_DATABASE,
            status=request.GET.get("status", ""),
            actor_id=request.GET.get("actor_id", ""),
            query=request.GET.get("q", "").strip()[:200],
        )
        return _json(data)
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        return _service_error("تعذر قراءة بيانات مصنع البطاقات", exc)


@require_GET
def workflow_metrics_api(request: HttpRequest) -> JsonResponse:
    try:
        return _json(metrics(settings.USAGE_DATABASE))
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        return _service_error("تعذر قراءة مؤشرات المصنع", exc)


@require_GET
def workflow_criteria_api(request: HttpRequest) -> JsonResponse:
    try:
        return _json(criterion_catalog(settings.USAGE_DATABASE))
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        return _service_error("تعذر قراءة قائمة معايير الإنجاز", exc)


@require_GET
def workflow_card_api(request: HttpRequest, card_id: str) -> JsonResponse:
    try:
        data = card_details(settings.USAGE_DATABASE, card_id)
        if data is None:
            return _json({"error": {"message": "البطاقة غير موجودة."}}, status=404)
        return _json(data)
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        return _service_error("تعذر قراءة بيانات البطاقة", exc)


@require_POST
def workflow_commands_api(request: HttpRequest) -> JsonResponse:
    expected_origin = f"http://{request.get_host()}"
    if request.headers.get("Origin") != expected_origin or request.headers.get("X-Workflow-Request") != "1":
        return _json({"error": {"message": "الطلب المحلي غير موثّق."}}, status=403)
    try:
        if not request.body or len(request.body) > 128_000:
            raise ValueError("حجم الطلب غير صالح.")
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise ValueError("صيغة الأمر غير صالحة.")
        result = create_command(settings.USAGE_DATABASE, payload)
        return _json(result, status=201 if result.get("created") else 200)
    except (ValueError, json.JSONDecodeError) as exc:
        return _json({"error": {"message": str(exc)}}, status=400)
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        return _service_error("تعذر تسجيل الأمر في قاعدة البيانات", exc)


@csrf_exempt
@require_POST
def workflow_opinions_api(request: HttpRequest) -> JsonResponse:
    expected_origin = f"http://{request.get_host()}"
    if request.headers.get("Origin") != expected_origin or request.headers.get("X-Workflow-Request") != "1":
        return _json({"error": {"message": "الطلب المحلي غير موثّق."}}, status=403)
    try:
        if not request.body or len(request.body) > 64_000:
            raise ValueError("حجم التوصية غير صالح.")
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise ValueError("صيغة التوصية غير صالحة.")
        result = submit_session_opinion(settings.USAGE_DATABASE, payload)
        return _json(result, status=201 if result.get("created") else 200)
    except KeyError as exc:
        return _json({"error": {"message": str(exc.args[0])}}, status=404)
    except (ValueError, json.JSONDecodeError) as exc:
        return _json({"error": {"message": str(exc)}}, status=400)
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        return _service_error("تعذر تسجيل توصية البطاقة", exc)


@csrf_exempt
@require_POST
def workflow_proposals_api(request: HttpRequest) -> JsonResponse:
    expected_origin = f"http://{request.get_host()}"
    if request.headers.get("Origin") != expected_origin or request.headers.get("X-Workflow-Request") != "1":
        return _json({"error": {"message": "الطلب المحلي غير موثّق."}}, status=403)
    try:
        if not request.body or len(request.body) > 64_000:
            raise ValueError("حجم التوصية غير صالح.")
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise ValueError("صيغة التوصية غير صالحة.")
        result = submit_card_proposal(settings.USAGE_DATABASE, payload)
        return _json(result, status=201 if result.get("created") else 200)
    except KeyError as exc:
        return _json({"error": {"message": str(exc.args[0])}}, status=404)
    except (ValueError, json.JSONDecodeError) as exc:
        return _json({"error": {"message": str(exc)}}, status=400)
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        return _service_error("تعذر تسجيل توصية البطاقة", exc)


@csrf_exempt
@require_POST
def workflow_proposal_decision_api(request: HttpRequest, proposal_id: str) -> JsonResponse:
    expected_origin = f"http://{request.get_host()}"
    if request.headers.get("Origin") != expected_origin or request.headers.get("X-Workflow-Request") != "1":
        return _json({"error": {"message": "الطلب المحلي غير موثّق."}}, status=403)
    try:
        if not request.body or len(request.body) > 8_000:
            raise ValueError("حجم قرار المالك غير صالح.")
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise ValueError("صيغة قرار المالك غير صالحة.")
        result = decide_card_proposal(settings.USAGE_DATABASE, proposal_id, payload)
        return _json(result)
    except KeyError as exc:
        return _json({"error": {"message": str(exc.args[0])}}, status=404)
    except (ValueError, json.JSONDecodeError) as exc:
        return _json({"error": {"message": str(exc)}}, status=400)
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        return _service_error("تعذر تسجيل قرار المالك", exc)


@csrf_exempt
@require_POST
def workflow_card_lifecycle_api(request: HttpRequest, card_id: str) -> JsonResponse:
    expected_origin = f"http://{request.get_host()}"
    if request.headers.get("Origin") != expected_origin or request.headers.get("X-Workflow-Request") != "1":
        return _json({"error": {"message": "الطلب المحلي غير موثّق."}}, status=403)
    try:
        if not request.body or len(request.body) > 16_000:
            raise ValueError("حجم الطلب غير صالح.")
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise ValueError("صيغة تحديث الحالة غير صالحة.")
        result = transition_assigned_card(settings.USAGE_DATABASE, card_id,
            str(payload.get("actor_id") or "").strip(), str(payload.get("status_code") or "").strip(),
            str(payload.get("summary") or ""))
        return _json(result)
    except KeyError as exc:
        return _json({"error": {"message": str(exc.args[0])}}, status=404)
    except (ValueError, json.JSONDecodeError) as exc:
        return _json({"error": {"message": str(exc)}}, status=400)
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        return _service_error("تعذر تحديث حالة البطاقة", exc)


@csrf_exempt
@require_POST
def workflow_card_delivery_api(request: HttpRequest, card_id: str) -> JsonResponse:
    expected_origin = f"http://{request.get_host()}"
    if request.headers.get("Origin") != expected_origin or request.headers.get("X-Workflow-Request") != "1":
        return _json({"error": {"message": "الطلب المحلي غير موثّق."}}, status=403)
    try:
        if not request.body or len(request.body) > 64_000:
            raise ValueError("حجم طلب التسليم غير صالح.")
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise ValueError("صيغة التسليم غير صالحة.")
        result = submit_delivery(settings.USAGE_DATABASE, card_id, payload)
        return _json(result, status=201 if not result.get("duplicate") else 200)
    except KeyError as exc:
        return _json({"error": {"message": str(exc.args[0])}}, status=404)
    except (ValueError, json.JSONDecodeError) as exc:
        return _json({"error": {"message": str(exc)}}, status=400)
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        return _service_error("تعذر تسجيل تسليم البطاقة", exc)


@csrf_exempt
@require_POST
def workflow_card_quality_api(request: HttpRequest, card_id: str) -> JsonResponse:
    expected_origin = f"http://{request.get_host()}"
    if request.headers.get("Origin") != expected_origin or request.headers.get("X-Workflow-Request") != "1":
        return _json({"error": {"message": "الطلب المحلي غير موثّق."}}, status=403)
    try:
        if not request.body or len(request.body) > 64_000:
            raise ValueError("حجم طلب فحوص الجودة غير صالح.")
        payload = json.loads(request.body)
        if not isinstance(payload, dict):
            raise ValueError("صيغة فحوص الجودة غير صالحة.")
        result = submit_quality(settings.USAGE_DATABASE, card_id, payload)
        return _json(result, status=201)
    except KeyError as exc:
        return _json({"error": {"message": str(exc.args[0])}}, status=404)
    except (ValueError, json.JSONDecodeError) as exc:
        return _json({"error": {"message": str(exc)}}, status=400)
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        return _service_error("تعذر تسجيل فحوص الجودة", exc)


@require_GET
def identity_asset(request: HttpRequest, font_name: str | None = None) -> HttpResponse:
    asset_name = font_name or "identity.css"
    asset = IDENTITY_ASSETS.get(asset_name)
    if asset is None or not asset.is_file():
        return HttpResponse(status=404)
    content_type = "text/css; charset=utf-8" if asset.suffix == ".css" else "font/woff2"
    response = FileResponse(asset.open("rb"), content_type=content_type)
    response["Cache-Control"] = "no-store"
    return response


@require_GET
def dashboard_asset(request: HttpRequest, asset_name: str) -> HttpResponse:
    if asset_name not in DASHBOARD_ASSETS:
        return HttpResponse(status=404)
    asset = ASSET_ROOT / asset_name
    response = FileResponse(asset.open("rb"), content_type="text/css; charset=utf-8" if asset.suffix == ".css" else "text/javascript; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response


@require_GET
def admin_static_asset(request: HttpRequest, asset_path: str) -> HttpResponse:
    asset = finders.find(asset_path)
    if not asset:
        return HttpResponse(status=404)
    response = FileResponse(
        Path(asset).open("rb"),
        content_type=mimetypes.guess_type(asset)[0] or "application/octet-stream",
    )
    response["Cache-Control"] = "public, max-age=3600"
    return response
