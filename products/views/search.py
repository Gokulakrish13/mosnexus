"""Products app — Full-Text Search views."""

# pylint: disable=invalid-name,wrong-import-position

import json
import logging
import re

from ._helpers import (
    CustomUser,
    JsonResponse,
    Q,
    get_current_bu,
    login_required,
    render,
    redirect,
    timezone,
)
from ..models import (
    BuildServer,
    CalibrationRecord,
    ChatMessage,
    ComplianceDocument,
    Note,
    Product,
    Project,
    SupportTicket,
    System,
    SystemTicket,
    Vendor,
    VendorPurchaseOrder,
    WasteRecord,
)

logger = logging.getLogger(__name__)

__all__ = [
    "global_search",
    "global_search_api",
    "search_suggestions_api",
    "search_reindex_api",
    "search_log_click_api",
]

# ── Entity search configs ────────────────────────────────────────────────────
# Each defines how to search a model and format results.
# ``gate_url`` is the URL-name checked against Feature Access Control;
# if the current user doesn't have access to that URL the entity type
# is silently skipped in both the page-render and the API results.
_SEARCH_CONFIGS = [
    {
        "type": "product",
        "icon": "fa-box",
        "color": "#0B5FFF",
        "model": "Product",
        "gate_url": "product_list_stream",
        "fields": ["name", "serial_number", "description", "twelve_nc", "device_serial_number"],
        "title_field": "name",
        "subtitle_tpl": "SN: {serial_number} | {status}",
        "url_tpl": "/stream/{stream__name}/products/{id}/",
    },
    {
        "type": "system",
        "icon": "fa-server",
        "color": "#6366F1",
        "model": "System",
        "gate_url": "system_allocation_stream",
        "fields": ["name", "description", "nc_details"],
        "title_field": "name",
        "subtitle_tpl": "Status: {status} | Health: {health}",
        "url_tpl": "/stream/{stream__name}/system-allocation/",
    },
    {
        "type": "vendor",
        "icon": "fa-building",
        "color": "#10B981",
        "model": "Vendor",
        "gate_url": "vendor_hub",
        "fields": ["name", "code", "contact_person", "email", "phone", "address", "notes"],
        "title_field": "name",
        "subtitle_tpl": "Code: {code} | {status}",
        "url_tpl": "/stream/{stream__name}/vendors/{id}/",
    },
    {
        "type": "project",
        "icon": "fa-project-diagram",
        "color": "#F59E0B",
        "model": "Project",
        "gate_url": "project_status",
        "fields": ["name", "description"],
        "title_field": "name",
        "subtitle_tpl": "Status: {status} | Progress: {progress_percentage}%",
        "url_tpl": "/projects/{id}/",
    },
    {
        "type": "note",
        "icon": "fa-sticky-note",
        "color": "#8B5CF6",
        "model": "Note",
        "gate_url": "notes_list",
        "fields": ["title", "content"],
        "title_field": "title",
        "subtitle_tpl": "Visibility: {visibility}",
        "url_tpl": "/notes/",
    },
    {
        "type": "compliance_doc",
        "icon": "fa-file-shield",
        "color": "#EF4444",
        "model": "ComplianceDocument",
        "gate_url": "compliance_hub",
        "fields": ["title", "document_id", "description"],
        "title_field": "title",
        "subtitle_tpl": "Doc #{document_id} | {status}",
        "url_tpl": "/stream/{stream__name}/compliance/",
    },
    {
        "type": "build_server",
        "icon": "fa-hdd",
        "color": "#14B8A6",
        "model": "BuildServer",
        "gate_url": "build_servers_dashboard",
        "fields": ["hostname", "ip_address", "purpose", "notes"],
        "title_field": "hostname",
        "subtitle_tpl": "IP: {ip_address} | {status}",
        "url_tpl": "/stream/{stream__name}/build-servers/{id}/",
    },
    {
        "type": "support_ticket",
        "icon": "fa-headset",
        "color": "#EC4899",
        "model": "SupportTicket",
        "gate_url": "support_ticket_list",
        "fields": ["title", "description"],
        "title_field": "title",
        "subtitle_tpl": "{category} | {status} | {priority}",
        "url_tpl": "/support/",
    },
]

# Model name → actual model class
_MODEL_MAP = {
    "Product": Product,
    "System": System,
    "Vendor": Vendor,
    "Project": Project,
    "Note": Note,
    "ComplianceDocument": ComplianceDocument,
    "BuildServer": BuildServer,
    "SupportTicket": SupportTicket,
}


def _build_q(fields, query):
    """Build a Q object that OR-matches *query* across all *fields*."""
    q = Q()
    # Tokenize for multi-word matching
    tokens = query.split()
    for field in fields:
        for token in tokens:
            q |= Q(**{f"{field}__icontains": token})
    return q


def _user_allowed_url(request, url_name):
    """Return True if *url_name* is accessible by the current user.

    Mirrors the logic in the ``feature_allowed`` template filter:
    un-gated url-names (not in the Feature table) are always allowed;
    gated ones require the name to be in ``request.FAC_ALLOWED_URLS``.
    """
    if not url_name:
        return True

    # Ensure FAC_ALLOWED_URLS is populated (context processor may not
    # have run for API-only requests)
    allowed = getattr(request, "FAC_ALLOWED_URLS", None)
    if allowed is None:
        from ..context_processors import feature_access_context
        feature_access_context(request)
        allowed = getattr(request, "FAC_ALLOWED_URLS", set())

    from ..middleware import FeatureAccessMiddleware
    if not FeatureAccessMiddleware._cache_built:
        FeatureAccessMiddleware._build_cache()
    # If the url_name is not governed by any Feature, it's always allowed
    if url_name not in FeatureAccessMiddleware._url_feature_cache:
        return True
    return url_name in allowed


def _safe_format(tpl, obj):
    """Format a template string using obj attributes, defaulting missing to '—'."""
    import re as _re

    def _repl(m):
        key = m.group(1)
        val = obj
        for part in key.split("__"):
            val = getattr(val, part, None)
            if val is None:
                return "—"
        return str(val)

    return _re.sub(r"\{(\w+(?:__\w+)*)}", _repl, tpl)


@login_required
def global_search(request):
    """Render the full-page global search view."""
    bu = get_current_bu(request)
    if not bu:
        return redirect("select_bu")
    return render(request, "products/global_search.html", {
        "entity_types": [
            {"value": c["type"], "label": c["type"].replace("_", " ").title(), "icon": c["icon"], "color": c["color"]}
            for c in _SEARCH_CONFIGS
            if _user_allowed_url(request, c.get("gate_url", ""))
        ],
    })


@login_required
def global_search_api(request):
    """API: perform cross-module search."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    query = request.GET.get("q", "").strip()
    entity_filter = request.GET.get("type", "")  # e.g. "product", "vendor", ""
    page = int(request.GET.get("page", 1))
    per_page = int(request.GET.get("per_page", 20))

    if not query or len(query) < 2:
        return JsonResponse({"success": True, "results": [], "total": 0, "query": query})

    results = []

    for cfg in _SEARCH_CONFIGS:
        if entity_filter and cfg["type"] != entity_filter:
            continue

        # ── Feature Access Control: skip entity types the user can't access ──
        gate_url = cfg.get("gate_url", "")
        if gate_url and not _user_allowed_url(request, gate_url):
            continue

        model_cls = _MODEL_MAP.get(cfg["model"])
        if not model_cls:
            continue

        q_filter = _build_q(cfg["fields"], query)

        # Scope to BU where possible
        qs = model_cls.objects.all()
        if hasattr(model_cls, "business_unit"):
            qs = qs.filter(business_unit=bu)
        elif hasattr(model_cls, "stream"):
            qs = qs.filter(stream__business_unit=bu)

        matches = qs.filter(q_filter)[:50]

        for obj in matches:
            title = getattr(obj, cfg["title_field"], str(obj))
            subtitle = _safe_format(cfg["subtitle_tpl"], obj)
            url = _safe_format(cfg["url_tpl"], obj)

            # Build snippet — find matching text
            snippet = ""
            for field in cfg["fields"]:
                val = str(getattr(obj, field, "") or "")
                if val and query.lower() in val.lower():
                    idx = val.lower().index(query.lower())
                    start = max(0, idx - 40)
                    end = min(len(val), idx + len(query) + 40)
                    snippet = ("..." if start > 0 else "") + val[start:end] + ("..." if end < len(val) else "")
                    break

            results.append({
                "type": cfg["type"],
                "type_label": cfg["type"].replace("_", " ").title(),
                "icon": cfg["icon"],
                "color": cfg["color"],
                "id": obj.id,
                "title": str(title),
                "subtitle": subtitle,
                "snippet": snippet,
                "url": url,
                "stream": getattr(getattr(obj, "stream", None), "name", ""),
            })

    # Sort by relevance (exact title match first, then partial)
    ql = query.lower()
    results.sort(key=lambda r: (
        0 if ql == r["title"].lower() else (1 if ql in r["title"].lower() else 2),
        r["type"],
    ))

    total = len(results)
    start = (page - 1) * per_page
    page_results = results[start:start + per_page]

    # Log the search
    try:
        from ..models import SearchQueryLog
        SearchQueryLog.objects.create(
            user=request.user,
            query_text=query,
            results_count=total,
            entity_type_filter=entity_filter,
        )
    except Exception:
        pass

    return JsonResponse({
        "success": True,
        "results": page_results,
        "total": total,
        "page": page,
        "per_page": per_page,
        "query": query,
    })


@login_required
def search_suggestions_api(request):
    """API: Autocomplete suggestions based on recent / popular queries."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU"}, status=400)

    prefix = request.GET.get("q", "").strip()
    if len(prefix) < 1:
        return JsonResponse({"success": True, "suggestions": []})

    from ..models import SearchQueryLog
    from django.db.models import Count

    recent_own = list(
        SearchQueryLog.objects.filter(
            user=request.user,
            query_text__icontains=prefix,
        )
        .values_list("query_text", flat=True)
        .distinct()[:5]
    )

    popular = list(
        SearchQueryLog.objects.filter(query_text__icontains=prefix)
        .values("query_text")
        .annotate(cnt=Count("id"))
        .order_by("-cnt")
        .values_list("query_text", flat=True)[:5]
    )

    # Deduplicate while preserving order
    seen = set()
    suggestions = []
    for s in recent_own + popular:
        sl = s.lower()
        if sl not in seen:
            seen.add(sl)
            suggestions.append(s)

    return JsonResponse({"success": True, "suggestions": suggestions[:8]})


@login_required
def search_reindex_api(request):
    """Admin-only: trigger a full reindex of the SearchIndex table."""
    from ._helpers import is_super_admin

    if not is_super_admin(request.user):
        return JsonResponse({"success": False, "error": "Super Admin required"}, status=403)

    from ..models import SearchIndex

    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU"}, status=400)

    count = 0
    for cfg in _SEARCH_CONFIGS:
        model_cls = _MODEL_MAP.get(cfg["model"])
        if not model_cls:
            continue

        qs = model_cls.objects.all()
        if hasattr(model_cls, "business_unit"):
            qs = qs.filter(business_unit=bu)
        elif hasattr(model_cls, "stream"):
            qs = qs.filter(stream__business_unit=bu)

        for obj in qs:
            title = str(getattr(obj, cfg["title_field"], str(obj)))
            body_parts = [str(getattr(obj, f, "") or "") for f in cfg["fields"]]
            stream_name = getattr(getattr(obj, "stream", None), "name", "")

            SearchIndex.objects.update_or_create(
                entity_type=cfg["type"],
                entity_id=obj.id,
                defaults={
                    "title": title[:500],
                    "subtitle": _safe_format(cfg["subtitle_tpl"], obj)[:500],
                    "body": " ".join(body_parts),
                    "url": _safe_format(cfg["url_tpl"], obj)[:500],
                    "icon": cfg["icon"],
                    "stream_name": stream_name,
                    "business_unit_id": bu.id,
                    "status": str(getattr(obj, "status", "")),
                },
            )
            count += 1

    return JsonResponse({"success": True, "indexed": count, "message": f"Successfully indexed {count} records"})


@login_required
def search_log_click_api(request):
    """Log when a user clicks on a search result (for analytics)."""
    if request.method != "POST":
        return JsonResponse({"success": False}, status=405)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"success": False}, status=400)

    from ..models import SearchQueryLog

    query_text = body.get("query", "")
    result_type = body.get("result_type", "")
    result_id = body.get("result_id")

    # Update the most recent matching log entry
    log = SearchQueryLog.objects.filter(
        user=request.user, query_text=query_text
    ).order_by("-created_at").first()

    if log:
        log.clicked_result_type = result_type
        log.clicked_result_id = result_id
        log.save(update_fields=["clicked_result_type", "clicked_result_id"])

    return JsonResponse({"success": True})
