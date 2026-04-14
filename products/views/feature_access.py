"""Products app - Feature Hub, Feature Access Control, Health Check, and Showcase views."""

# pylint: disable=too-many-lines,broad-exception-caught,import-error,import-outside-toplevel

import platform
import shutil

from inventory.version import RELEASE_CODENAME, RELEASE_DATE, get_build_info, get_full_version, get_version

from django.db import connection

from ..models import SiteSetting  # pylint: disable=relative-beyond-top-level
from ._helpers import (
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_SIZE,
    AuditLog,
    BUShowcaseProduct,
    Feature,
    FeatureRoleAccess,
    JsonResponse,
    _fac_granted,
    _is_app_admin_user,
    get_bu_streams,
    get_current_bu,
    get_object_or_404,
    is_app_admin,
    is_super_admin,
    json,
    logger,
    login_not_required,
    login_required,
    messages,
    redirect,
    render,
    require_GET,
    require_POST,
    user_passes_test,
    validate_uploaded_file,
)

__all__ = [
    "feature_hub",
    "feature_access_control",
    "feature_access_toggle",
    "feature_access_bulk_toggle",
    "feature_access_export",
    "feature_access_import",
    "feature_access_reset",
    "feature_access_copy_role",
    "feature_access_history",
    "feature_access_compare",
    "feature_access_summary",
    "health_check",
    "version_info",
    "page_nav_action",
    "toggle_devtools_protection",
    "get_site_settings",
    "showcase_products_api",
    "showcase_product_update",
    "showcase_product_delete",
]


@user_passes_test(is_super_admin)
@login_required
def feature_hub(request):
    """Feature Hub – central page to select a stream and navigate to advanced.

    features (Asset Lifecycle, Maintenance Calendar, Inventory Alerts, etc.).
    Mirrors the Reservations Hub / Calibration Hub pattern.
    """
    streams = get_bu_streams(request).order_by("name")

    is_admin = request.user.is_superuser or (
        hasattr(request.user, "custom_profile") and request.user.custom_profile.is_super_admin()
    )

    context = {
        "streams": streams,
        "is_admin": is_admin,
    }
    return render(request, "products/feature_hub.html", context)


# =============================================================================
# AI FEATURE 1: AUTO-GENERATE CALIBRATION REPORTS
# =============================================================================


@login_required
def feature_access_control(request):
    # pylint: disable=too-many-locals
    """Render the Feature Access Control panel (app_admin only)."""
    if not _is_app_admin_user(request.user):
        messages.error(request, "Only Application Admins can access the Feature Access Control panel.")
        return redirect("dashboard")

    features = Feature.objects.filter(is_active=True).prefetch_related("role_access")
    _modules_dict = dict(Feature.MODULE_CHOICES)  # noqa: F841
    roles = [
        ("user", "User"),
        ("lab_incharge", "Lab Incharge"),
        ("admin", "Admin"),
        ("super_admin", "Super Admin"),
        ("app_admin", "App Admin"),
    ]

    # Build grouped data
    modules_data = []
    for mod_code, mod_label in Feature.MODULE_CHOICES:
        mod_features = [f for f in features if f.module == mod_code]
        if not mod_features:
            continue
        rows = []
        for feat in mod_features:
            access_map = {ra.role: ra.has_access for ra in feat.role_access.all()}
            # app_admin always True
            access_map.setdefault("app_admin", True)
            rows.append(
                {
                    "feature": feat,
                    "access": access_map,
                    "url_count": len(feat.url_names) if feat.url_names else 0,
                }
            )
        modules_data.append(
            {
                "code": mod_code,
                "label": mod_label,
                "features": rows,
                "count": len(rows),
            }
        )

    # Stats
    total_features = sum(m["count"] for m in modules_data)
    role_stats = {}
    for r_code, _r_label in roles:
        cnt = FeatureRoleAccess.objects.filter(role=r_code, has_access=True, feature__is_active=True).count()
        role_stats[r_code] = cnt

    return render(
        request,
        "products/feature_access_control.html",
        {
            "modules_data": modules_data,
            "roles": roles,
            "total_features": total_features,
            "role_stats": role_stats,
        },
    )


@login_required
@require_POST
def feature_access_toggle(request):
    """AJAX: toggle a single feature × role access cell."""
    if not _is_app_admin_user(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)

    feature_id = request.POST.get("feature_id")
    role = request.POST.get("role")
    enabled = request.POST.get("enabled") == "true"

    if role == "app_admin":
        return JsonResponse({"error": "Cannot modify app_admin access"}, status=400)

    feature = get_object_or_404(Feature, id=feature_id)
    access, _ = FeatureRoleAccess.objects.get_or_create(feature=feature, role=role, defaults={"has_access": enabled})
    if access.has_access != enabled:
        access.has_access = enabled
        access.save(update_fields=["has_access"])

    AuditLog.log(
        action="permission_change",
        title=f'Feature access {"granted" if enabled else "revoked"}: ' f"{feature.name} for role {role}",
        user=request.user,
        request=request,
        module="admin",
        severity="warning",
    )

    return JsonResponse({"status": "ok", "feature_id": feature_id, "role": role, "enabled": enabled})


@login_required
@require_POST
def feature_access_bulk_toggle(request):
    """AJAX: toggle ALL features in a module for a role."""
    if not _is_app_admin_user(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)

    module = request.POST.get("module")
    role = request.POST.get("role")
    enabled = request.POST.get("enabled") == "true"

    if role == "app_admin":
        return JsonResponse({"error": "Cannot modify app_admin access"}, status=400)

    features = Feature.objects.filter(module=module, is_active=True)
    updated = 0
    for feat in features:
        access, created = FeatureRoleAccess.objects.get_or_create(
            feature=feat, role=role, defaults={"has_access": enabled}
        )
        if not created and access.has_access != enabled:
            access.has_access = enabled
            access.save(update_fields=["has_access"])
        updated += 1

    AuditLog.log(
        action="permission_change",
        title=f'Bulk feature access {"granted" if enabled else "revoked"}: '
        f"module {module} for role {role} ({updated} features)",
        user=request.user,
        request=request,
        module="admin",
        severity="warning",
    )

    return JsonResponse({"status": "ok", "module": module, "role": role, "enabled": enabled, "count": updated})


@login_required
@require_GET
def feature_access_export(request):
    """Export current FAC configuration as JSON for backup / transfer."""
    if not _is_app_admin_user(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)

    config = {}
    for feat in Feature.objects.filter(is_active=True).prefetch_related("role_access"):
        config[feat.code] = {ra.role: ra.has_access for ra in feat.role_access.all()}

    AuditLog.log(
        action="export",
        title="Feature access configuration exported",
        user=request.user,
        request=request,
        module="admin",
        severity="info",
    )

    response = JsonResponse(config, json_dumps_params={"indent": 2})
    response["Content-Disposition"] = 'attachment; filename="fac_config.json"'
    return response


@login_required
@require_POST
def feature_access_import(request):  # noqa: CCR001
    """Import a FAC configuration from uploaded JSON."""
    if not _is_app_admin_user(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)

    try:
        uploaded = request.FILES.get("config_file") or request.FILES.get("file")
        if uploaded:
            raw = uploaded.read().decode("utf-8")
        else:
            raw = request.body.decode("utf-8")
        config = json.loads(raw)
    except Exception as exc:
        return JsonResponse({"error": f"Invalid JSON: {exc}"}, status=400)

    updated = 0
    skipped = 0
    features = {f.code: f for f in Feature.objects.filter(is_active=True)}

    for code, roles_map in config.items():
        feat = features.get(code)
        if not feat:
            skipped += 1
            continue
        for role, access in roles_map.items():
            if role == "app_admin":
                continue
            obj, created = FeatureRoleAccess.objects.get_or_create(
                feature=feat, role=role, defaults={"has_access": bool(access)}
            )
            if not created and obj.has_access != bool(access):
                obj.has_access = bool(access)
                obj.save(update_fields=["has_access"])
            updated += 1

    AuditLog.log(
        action="import",
        title=f"Feature access configuration imported ({updated} updated, {skipped} skipped)",
        user=request.user,
        request=request,
        module="admin",
        severity="warning",
    )

    return JsonResponse({"status": "ok", "updated": updated, "skipped": skipped})


@login_required
@require_POST
def feature_access_reset(request):
    """Reset all FAC rows back to seed defaults."""
    if not _is_app_admin_user(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)

    from products.management.commands.seed_features import FEATURES

    lookup = {code: defaults for code, _n, _m, _i, _d, _u, defaults in FEATURES}
    updated = 0

    for feat in Feature.objects.filter(is_active=True):
        defaults = lookup.get(feat.code, {})
        for ra in feat.role_access.all():
            if ra.role == "app_admin":
                continue
            should = defaults.get(ra.role, False)
            if ra.has_access != should:
                ra.has_access = should
                ra.save(update_fields=["has_access"])
                updated += 1

    AuditLog.log(
        action="permission_change",
        title=f"Feature access reset to defaults ({updated} permissions changed)",
        user=request.user,
        request=request,
        module="admin",
        severity="critical",
    )

    return JsonResponse({"status": "ok", "updated": updated})


@login_required
@require_POST
def feature_access_copy_role(request):
    """Copy all permissions from one role to another."""
    if not _is_app_admin_user(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)

    source = request.POST.get("source_role")
    target = request.POST.get("target_role")
    valid_roles = {"user", "lab_incharge", "admin", "super_admin"}

    if source not in valid_roles or target not in valid_roles:
        return JsonResponse({"error": "Invalid role"}, status=400)
    if source == target:
        return JsonResponse({"error": "Source and target must differ"}, status=400)

    updated = 0
    for feat in Feature.objects.filter(is_active=True).prefetch_related("role_access"):
        src_access = feat.role_access.filter(role=source).first()
        tgt_access, _ = FeatureRoleAccess.objects.get_or_create(
            feature=feat, role=target, defaults={"has_access": src_access.has_access if src_access else False}
        )
        val = src_access.has_access if src_access else False
        if tgt_access.has_access != val:
            tgt_access.has_access = val
            tgt_access.save(update_fields=["has_access"])
            updated += 1

    AuditLog.log(
        action="permission_change",
        title=f"Copied permissions from {source} → {target} ({updated} changed)",
        user=request.user,
        request=request,
        module="admin",
        severity="warning",
    )

    return JsonResponse({"status": "ok", "source": source, "target": target, "updated": updated})


@login_required
@require_GET
def feature_access_history(request):
    """Return recent FAC-related audit log entries as JSON."""
    if not _is_app_admin_user(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)

    logs = AuditLog.objects.filter(
        action__in=["permission_change", "export", "import"],
        module="admin",
    ).order_by(
        "-timestamp"
    )[:15]

    entries = []
    for log in logs:
        entries.append(
            {
                "id": log.id,
                "title": log.title,
                "description": log.description or log.title,
                "user": log.user.get_full_name() or log.user.username if log.user else "System",
                "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "severity": log.severity,
            }
        )

    return JsonResponse({"entries": entries})


@login_required
@require_GET
def feature_access_compare(request):
    """Return side-by-side permission comparison between two roles."""
    if not _is_app_admin_user(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)

    role_a = request.GET.get("role_a", "")
    role_b = request.GET.get("role_b", "")
    valid_roles = {"user", "lab_incharge", "admin", "super_admin"}
    if role_a not in valid_roles or role_b not in valid_roles:
        return JsonResponse({"error": "Invalid role"}, status=400)

    features = Feature.objects.filter(is_active=True).prefetch_related("role_access").order_by("module", "name")
    modules_dict = dict(Feature.MODULE_CHOICES)
    results = []
    same = 0
    diff = 0
    for feat in features:
        access_map = {ra.role: ra.has_access for ra in feat.role_access.all()}
        a_val = access_map.get(role_a, False)
        b_val = access_map.get(role_b, False)
        is_diff = a_val != b_val
        if is_diff:
            diff += 1
        else:
            same += 1
        results.append(
            {
                "id": feat.id,
                "name": feat.name,
                "code": feat.code,
                "module": modules_dict.get(feat.module, feat.module),
                "icon": feat.icon,
                "role_a": a_val,
                "role_b": b_val,
                "different": is_diff,
            }
        )

    return JsonResponse(
        {
            "features": results,
            "role_a": role_a,
            "role_b": role_b,
            "same": same,
            "diff": diff,
        }
    )


@login_required
@require_GET
def feature_access_summary(request):
    """Return full role-vs-feature matrix for summary report / print."""
    if not _is_app_admin_user(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)

    features = Feature.objects.filter(is_active=True).prefetch_related("role_access").order_by("module", "name")
    modules_dict = dict(Feature.MODULE_CHOICES)
    roles_order = ["user", "lab_incharge", "admin", "super_admin", "app_admin"]
    rows = []
    for feat in features:
        access_map = {ra.role: ra.has_access for ra in feat.role_access.all()}
        access_map.setdefault("app_admin", True)
        row = {
            "name": feat.name,
            "code": feat.code,
            "module": modules_dict.get(feat.module, feat.module),
            "icon": feat.icon,
        }
        for role in roles_order:
            row[role] = access_map.get(role, False)
        rows.append(row)

    return JsonResponse({"roles": roles_order, "features": rows})


@require_GET
@login_not_required
def health_check(request):
    """Production health-check endpoint for load balancers, Docker HEALTHCHECK,.

    and monitoring systems. Returns JSON with system status.

    GET /api/health/         → 200 OK (healthy) or 503 (unhealthy)
    GET /api/health/?full=1  → Detailed diagnostics (admin only)
    """
    status = "healthy"
    checks = {}
    http_status = 200

    # ── Database Check ───────────────────────────────────────────────────
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = {"status": "ok"}
    except Exception as e:  # pylint: disable=invalid-name
        logger.error("Health check DB error: %s", e)  # pylint: disable=logging-too-many-args
        checks["database"] = {"status": "error", "detail": "Database connection failed"}
        status = "unhealthy"
        http_status = 503

    # ── Disk Check ───────────────────────────────────────────────────────
    try:
        disk = shutil.disk_usage("/")
        free_pct = (disk.free / disk.total) * 100
        checks["disk"] = {
            "status": "ok" if free_pct > 5 else "warning",
            "free_percent": round(free_pct, 1),  # type: ignore[dict-item]
        }
        if free_pct < 5:
            status = "degraded"
    except Exception:
        checks["disk"] = {"status": "unknown"}

    # ── Build Info ───────────────────────────────────────────────────────
    build_info = get_build_info()

    response_data: dict[str, object] = {
        "status": status,
    }

    # Only expose version/environment to authenticated users
    if request.user.is_authenticated:
        response_data["version"] = build_info["version"]
        response_data["environment"] = build_info["environment"]

    # Full diagnostics for authenticated superusers
    show_full = request.GET.get("full") == "1"
    if show_full and request.user.is_authenticated and request.user.is_superuser:
        response_data.update(
            {
                "checks": checks,
                "build": build_info,
                "system": {
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                },
            }
        )

    return JsonResponse(response_data, status=http_status)


@login_required
@require_GET
def version_info(request):
    """Lightweight version endpoint (requires authentication).

    GET /api/version/ → {"version": "1.0.0", "codename": "NexusOps Enterprise"}
    """
    return JsonResponse(
        {
            "version": get_version(),
            "full_version": get_full_version(),
            "codename": RELEASE_CODENAME,
            "release_date": RELEASE_DATE,
        }
    )


# =============================================================================
# PAGE NAVIGATION — Back / Forward handler
# =============================================================================


@login_required
def page_nav_action(request):
    """Handle back/forward navigation via the global toolbar.

    GET /page-nav/?action=back   → pops back stack, redirects
    GET /page-nav/?action=forward → pops forward stack, redirects
    """
    action = request.GET.get("action", "")
    back = request.session.get("page_nav_back", [])
    fwd = request.session.get("page_nav_fwd", [])
    current = request.session.get("page_nav_current", "/dashboard/")

    if action == "back" and back:
        fwd.append(current)
        target = back.pop()
        request.session["page_nav_back"] = back
        request.session["page_nav_fwd"] = fwd
        request.session["page_nav_current"] = target
        return redirect(target)

    if action == "forward" and fwd:
        back.append(current)
        target = fwd.pop()
        request.session["page_nav_back"] = back
        request.session["page_nav_fwd"] = fwd
        request.session["page_nav_current"] = target
        return redirect(target)

    return redirect(current or "/dashboard/")


# =============================================================================
# SITE SETTINGS — DevTools Protection Toggle
# =============================================================================


@login_required
@require_POST
def toggle_devtools_protection(request):
    """Toggle the DevTools protection setting on/off.

    Only superusers and app-admins can access this.
    Returns JSON with the new state.
    """
    user = request.user
    custom_user = getattr(user, "custom_profile", None)
    is_app_admin_flag = custom_user.is_app_admin() if custom_user else False

    if not _fac_granted(user) and not is_app_admin_flag and not user.is_superuser:
        return JsonResponse({"error": "Permission denied"}, status=403)

    site = SiteSetting.load()
    site.devtools_protection = not site.devtools_protection
    site.updated_by = user
    site.save()

    # Audit log
    AuditLog.log(
        action="update",
        title=f"DevTools protection {'enabled' if site.devtools_protection else 'disabled'}",
        user=user,
        request=request,
        obj=site,
        module="settings",
        severity="warning",
        description=f"DevTools protection {'enabled' if site.devtools_protection else 'disabled'} by {user.username}",
    )

    return JsonResponse(
        {
            "devtools_protection": site.devtools_protection,
            "message": f"DevTools protection {'enabled' if site.devtools_protection else 'disabled'}.",
        }
    )


@login_required
def get_site_settings(request):
    """Return current site settings as JSON (read-only for any authenticated user)."""
    site = SiteSetting.load()
    return JsonResponse(
        {
            "devtools_protection": site.devtools_protection,
        }
    )


# =========================================================================
# BU SHOWCASE PRODUCT CRUD (Application Admin only)
# =========================================================================


@login_required
def showcase_products_api(request):  # noqa: CCR001
    """GET  → list showcase products for the current BU (JSON).

    POST → create a new showcase product (multipart form).
    """
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No Business Unit selected."}, status=400)

    if request.method == "GET":
        products = BUShowcaseProduct.objects.filter(business_unit=bu, is_active=True)
        data = []
        for product in products:
            data.append(
                {
                    "id": product.id,
                    "title": product.title,
                    "description": product.description,
                    "badge": product.badge,
                    "image_url": product.image.url if product.image else "",
                    "spec_1": product.spec_1,
                    "spec_2": product.spec_2,
                    "display_order": product.display_order,
                }
            )
        return JsonResponse({"success": True, "products": data})

    # POST — create
    if not is_app_admin(request.user):
        return JsonResponse(
            {"success": False, "error": "Only Application Admins can manage showcase products."}, status=403
        )

    title = request.POST.get("title", "").strip()
    description = request.POST.get("description", "").strip()
    badge = request.POST.get("badge", "featured").strip()
    spec_1 = request.POST.get("spec_1", "").strip()
    spec_2 = request.POST.get("spec_2", "").strip()
    display_order = request.POST.get("display_order", "0")
    image = request.FILES.get("image")

    if image:
        is_valid, error_msg = validate_uploaded_file(
            image, ALLOWED_IMAGE_TYPES, ALLOWED_IMAGE_EXTENSIONS, MAX_IMAGE_SIZE
        )
        if not is_valid:
            return JsonResponse({"success": False, "error": f"Image: {error_msg}"}, status=400)

    if not title:
        return JsonResponse({"success": False, "error": "Title is required."}, status=400)

    try:
        display_order = int(display_order)
    except (ValueError, TypeError):
        display_order = 0

    product = BUShowcaseProduct.objects.create(
        business_unit=bu,
        title=title,
        description=description,
        badge=badge,
        image=image,
        spec_1=spec_1,
        spec_2=spec_2,
        display_order=display_order,
        created_by=request.user,
    )

    AuditLog.log(
        "create",
        f'Created showcase product "{product.title}"',
        user=request.user,
        request=request,
        obj=product,
        module="products",
        severity="info",
    )

    return JsonResponse(
        {
            "success": True,
            "message": f'Showcase product "{product.title}" created.',
            "product": {
                "id": product.id,
                "title": product.title,
                "description": product.description,
                "badge": product.badge,
                "image_url": product.image.url if product.image else "",
                "spec_1": product.spec_1,
                "spec_2": product.spec_2,
                "display_order": product.display_order,
            },
        }
    )


@login_required
def showcase_product_update(request, pk):  # noqa: C901, CCR001
    # pylint: disable=too-many-branches,too-complex
    """PUT/POST — update a single showcase product (multipart form)."""
    if not is_app_admin(request.user):
        return JsonResponse(
            {"success": False, "error": "Only Application Admins can manage showcase products."}, status=403
        )

    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No Business Unit selected."}, status=400)

    try:
        product = BUShowcaseProduct.objects.get(pk=pk, business_unit=bu)
    except BUShowcaseProduct.DoesNotExist:
        return JsonResponse({"success": False, "error": "Showcase product not found."}, status=404)

    if request.method not in ("POST", "PUT"):
        return JsonResponse({"success": False, "error": "Method not allowed."}, status=405)

    title = request.POST.get("title", "").strip()
    description = request.POST.get("description", "").strip()
    badge = request.POST.get("badge", "").strip()
    spec_1 = request.POST.get("spec_1", "").strip()
    spec_2 = request.POST.get("spec_2", "").strip()
    display_order = request.POST.get("display_order", "")
    image = request.FILES.get("image")
    remove_image = request.POST.get("remove_image", "") == "true"

    if title:
        product.title = title
    if description:
        product.description = description
    if badge:
        product.badge = badge
    if spec_1 is not None:
        product.spec_1 = spec_1
    if spec_2 is not None:
        product.spec_2 = spec_2
    if display_order:
        try:
            product.display_order = int(display_order)
        except (ValueError, TypeError):
            pass
    if remove_image:
        if product.image:
            product.image.delete(save=False)
        product.image = None
    elif image:
        is_valid, error_msg = validate_uploaded_file(
            image, ALLOWED_IMAGE_TYPES, ALLOWED_IMAGE_EXTENSIONS, MAX_IMAGE_SIZE
        )
        if not is_valid:
            return JsonResponse({"success": False, "error": f"Image: {error_msg}"}, status=400)
        if product.image:
            product.image.delete(save=False)
        product.image = image

    product.save()

    AuditLog.log(
        "update",
        f'Updated showcase product "{product.title}"',
        user=request.user,
        request=request,
        obj=product,
        module="products",
        severity="info",
    )

    return JsonResponse(
        {
            "success": True,
            "message": f'Showcase product "{product.title}" updated.',
            "product": {
                "id": product.id,
                "title": product.title,
                "description": product.description,
                "badge": product.badge,
                "image_url": product.image.url if product.image else "",
                "spec_1": product.spec_1,
                "spec_2": product.spec_2,
                "display_order": product.display_order,
            },
        }
    )


@login_required
def showcase_product_delete(request, pk):
    """DELETE/POST — soft-delete (deactivate) a showcase product."""
    if not is_app_admin(request.user):
        return JsonResponse(
            {"success": False, "error": "Only Application Admins can manage showcase products."}, status=403
        )

    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No Business Unit selected."}, status=400)

    try:
        product = BUShowcaseProduct.objects.get(pk=pk, business_unit=bu)
    except BUShowcaseProduct.DoesNotExist:
        return JsonResponse({"success": False, "error": "Showcase product not found."}, status=404)

    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Method not allowed."}, status=405)

    product_title = product.title
    product.is_active = False
    product.save()

    AuditLog.log(
        "delete",
        f'Deleted showcase product "{product_title}"',
        user=request.user,
        request=request,
        obj=product,
        module="products",
        severity="warning",
    )

    return JsonResponse(
        {
            "success": True,
            "message": f'Showcase product "{product_title}" removed.',
        }
    )


# =============================================================================
# LAB WASTE MANAGEMENT
# =============================================================================
