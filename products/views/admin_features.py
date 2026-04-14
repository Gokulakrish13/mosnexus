"""Products app — Admin Features views."""

# pylint: disable=too-many-lines,broad-exception-caught

from datetime import timedelta as td

from ..models import SiteSetting  # pylint: disable=relative-beyond-top-level
from ._helpers import (
    AuditLog,
    DashboardWidget,
    HttpResponse,
    JsonResponse,
    Paginator,
    Q,
    Stream,
    User,
    UserDashboardLayout,
    UserDashboardWidget,
    _fac_granted,
    csv,
    date,
    get_bu_streams,
    is_admin,
    is_super_admin,
    json,
    logger,
    login_required,
    messages,
    redirect,
    render,
    require_POST,
    timedelta,
    timezone,
    transaction,
    user_passes_test,
)
from .lifecycle_inventory import _ensure_default_widgets_exist

__all__ = [
    "audit_log_list",
    "audit_log_export",
    "audit_log_api_data",
    "audit_log_clear",
    "audit_log_settings",
    "dashboard_widgets_api",
    "dashboard_save_layout",
    "dashboard_reset_widgets",
]


@user_passes_test(is_super_admin)
@login_required
def audit_log_list(request):  # noqa: C901, CCR001, E501
    # pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-complex
    """Full-page audit log viewer with filtering and search."""
    if not is_admin(request.user):
        messages.error(request, "Access denied. Admin privileges required.")
        return redirect("dashboard")

    bu_streams = get_bu_streams(request)
    logs = AuditLog.objects.select_related("user", "stream", "content_type").filter(
        Q(stream__in=bu_streams) | Q(stream__isnull=True)
    )

    action = request.GET.get("action", "")
    module = request.GET.get("module", "")
    severity = request.GET.get("severity", "")
    user_id = request.GET.get("user_id", "")
    stream_name = request.GET.get("stream", "")
    search = request.GET.get("search", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")

    if action:
        logs = logs.filter(action=action)
    if module:
        logs = logs.filter(module=module)
    if severity:
        logs = logs.filter(severity=severity)
    if user_id:
        logs = logs.filter(user_id=user_id)
    if stream_name:
        logs = logs.filter(stream__name=stream_name)
    if search:
        logs = logs.filter(
            Q(title__icontains=search)
            | Q(description__icontains=search)
            | Q(object_repr__icontains=search)
            | Q(user_display_name__icontains=search)
        )
    if date_from:
        logs = logs.filter(timestamp__date__gte=date_from)
    if date_to:
        logs = logs.filter(timestamp__date__lte=date_to)

    paginator = Paginator(logs, 50)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    total_logs = AuditLog.objects.filter(Q(stream__in=bu_streams) | Q(stream__isnull=True)).count()
    today_logs = AuditLog.objects.filter(
        Q(stream__in=bu_streams) | Q(stream__isnull=True), timestamp__date=date.today()
    ).count()
    warning_count = AuditLog.objects.filter(
        Q(stream__in=bu_streams) | Q(stream__isnull=True),
        severity__in=["warning", "error", "critical"],
        timestamp__date=date.today(),
    ).count()

    # Check if current user is app_admin for showing clear button
    custom_user = getattr(request.user, "custom_profile", None)
    user_is_app_admin = (custom_user and custom_user.is_app_admin()) or request.user.is_superuser

    # Get oldest log date for retention info
    oldest_log = (
        AuditLog.objects.filter(Q(stream__in=bu_streams) | Q(stream__isnull=True))
        .order_by("timestamp")
        .values_list("timestamp", flat=True)
        .first()
    )

    # Load site settings for retention config
    site_settings = SiteSetting.load()

    # Auto-cleanup: if enabled, clean old logs automatically on page load (max once per day)
    if site_settings.audit_log_auto_cleanup:
        should_run = site_settings.audit_log_last_cleanup is None or (
            timezone.now() - site_settings.audit_log_last_cleanup
        ) > td(days=1)
        if should_run:
            cutoff = timezone.now() - td(days=site_settings.audit_log_retention_months * 30)
            cleanup_qs = AuditLog.objects.filter(timestamp__lt=cutoff)
            if site_settings.audit_log_keep_critical:
                cleanup_qs = cleanup_qs.exclude(severity="critical")
            cleaned = cleanup_qs.count()
            if cleaned > 0:
                cleanup_qs.delete()
                AuditLog.log(
                    action="system_event",
                    title=(
                        f"Auto-cleanup: Removed {cleaned} audit log entries older than "
                        f"{site_settings.audit_log_retention_months} months"
                    ),
                    module="settings",
                    severity="info",
                    description=(
                        f"Retention: {site_settings.audit_log_retention_months} months, "
                        f"Keep critical: {site_settings.audit_log_keep_critical}"
                    ),
                )
            site_settings.audit_log_last_cleanup = timezone.now()
            site_settings.save(update_fields=["audit_log_last_cleanup"])
            # Refresh counts after cleanup
            total_logs = AuditLog.objects.filter(Q(stream__in=bu_streams) | Q(stream__isnull=True)).count()

    context = {
        "page_obj": page_obj,
        "total_logs": total_logs,
        "today_logs": today_logs,
        "warning_count": warning_count,
        "action_choices": AuditLog.ACTION_CATEGORIES,
        "module_choices": AuditLog.MODULE_CHOICES,
        "severity_choices": AuditLog.SEVERITY_LEVELS,
        "streams": bu_streams.order_by("name"),
        "users": User.objects.filter(is_active=True).order_by("username"),
        "selected_action": action,
        "selected_module": module,
        "selected_severity": severity,
        "selected_user_id": user_id,
        "selected_stream": stream_name,
        "search_query": search,
        "date_from": date_from,
        "date_to": date_to,
        "is_app_admin": user_is_app_admin,
        "oldest_log_date": oldest_log,
        "retention_months": site_settings.audit_log_retention_months,
        "auto_cleanup": site_settings.audit_log_auto_cleanup,
        "keep_critical": site_settings.audit_log_keep_critical,
        "last_cleanup": site_settings.audit_log_last_cleanup,
    }
    return render(request, "products/audit_log_list.html", context)


@user_passes_test(is_super_admin)
@login_required
def audit_log_export(request):
    """Export audit logs to CSV."""
    if not is_admin(request.user):
        return HttpResponse("Unauthorized", status=401)

    bu_streams = get_bu_streams(request)
    logs = AuditLog.objects.select_related("user", "stream").filter(Q(stream__in=bu_streams) | Q(stream__isnull=True))[
        :5000
    ]

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="audit_log_{date.today()}.csv"'

    writer = csv.writer(response)
    writer.writerow(
        ["Timestamp", "Severity", "Action", "Module", "User", "Title", "Object", "Stream", "IP Address", "Description"]
    )

    for log in logs:
        writer.writerow(
            [
                log.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                log.get_severity_display(),
                log.get_action_display(),
                log.get_module_display(),
                log.user_display_name,
                log.title,
                log.object_repr,
                log.stream.name if log.stream else "",
                log.ip_address or "",
                log.description[:200],
            ]
        )

    AuditLog.log("export", "Exported audit log to CSV", user=request.user, request=request, module="settings")
    return response


@user_passes_test(is_super_admin)
@login_required
def audit_log_api_data(request):
    """API endpoint for audit log data (used by dashboard widget)."""
    if not (
        request.user.is_superuser
        or (hasattr(request.user, "custom_profile") and request.user.custom_profile.is_super_admin())
    ):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    limit = int(request.GET.get("limit", 20))
    module = request.GET.get("module", "")

    bu_streams = get_bu_streams(request)
    logs = AuditLog.objects.select_related("user", "stream").filter(Q(stream__in=bu_streams) | Q(stream__isnull=True))
    if module:
        logs = logs.filter(module=module)

    logs = logs[:limit]

    data = [
        {
            "id": log.id,
            "timestamp": log.timestamp.isoformat(),
            "action": log.action,
            "action_display": log.get_action_display(),
            "severity": log.severity,
            "module": log.module,
            "module_display": log.get_module_display(),
            "user": log.user_display_name,
            "title": log.title,
            "object_repr": log.object_repr,
            "stream": log.stream.name if log.stream else "",
        }
        for log in logs
    ]

    return JsonResponse({"success": True, "data": data})


@login_required
def audit_log_clear(request):
    """Clear audit logs. Only accessible to app_admin users.

    Supports clearing all logs or logs older than a specified number of months.
    Requires password confirmation for safety.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    user = request.user
    custom_user = getattr(user, "custom_profile", None)
    is_app_admin_user = _fac_granted(user) or (custom_user and custom_user.is_app_admin()) or user.is_superuser

    if not is_app_admin_user:
        return JsonResponse({"error": "Permission denied. App Admin access required."}, status=403)

    # Verify password for safety
    password = request.POST.get("password", "")
    if not user.check_password(password):
        return JsonResponse({"error": "Invalid password. Please try again."}, status=400)

    clear_type = request.POST.get("clear_type", "older_than")  # 'all' or 'older_than'
    months = int(request.POST.get("months", 6))

    bu_streams = get_bu_streams(request)
    base_qs = AuditLog.objects.filter(Q(stream__in=bu_streams) | Q(stream__isnull=True))

    if clear_type == "all":
        count = base_qs.count()
        base_qs.delete()
        description = f"Cleared all {count} audit log entries"
    else:
        cutoff_date = timezone.now() - timedelta(days=months * 30)
        old_logs = base_qs.filter(timestamp__lt=cutoff_date)
        count = old_logs.count()
        old_logs.delete()
        description = f"Cleared {count} audit log entries older than {months} months"

    # Log the clear action itself (this entry survives since it's created after the delete)
    AuditLog.log(
        action="delete",
        title=description,
        user=user,
        request=request,
        module="settings",
        severity="critical",
        description=f"{description} by {user.username}",
    )

    return JsonResponse(
        {
            "success": True,
            "deleted_count": count,
            "message": description,
        }
    )


@login_required
def audit_log_settings(request):
    """Save audit log retention settings. App Admin only.

    GET: returns current settings as JSON.
    POST: updates settings.
    """
    user = request.user
    custom_user = getattr(user, "custom_profile", None)
    is_app_admin_user = _fac_granted(user) or (custom_user and custom_user.is_app_admin()) or user.is_superuser

    if not is_app_admin_user:
        return JsonResponse({"error": "Permission denied. App Admin access required."}, status=403)

    site = SiteSetting.load()

    if request.method == "GET":
        return JsonResponse(
            {
                "success": True,
                "auto_cleanup": site.audit_log_auto_cleanup,
                "retention_months": site.audit_log_retention_months,
                "keep_critical": site.audit_log_keep_critical,
                "last_cleanup": site.audit_log_last_cleanup.isoformat() if site.audit_log_last_cleanup else None,
            }
        )

    if request.method == "POST":
        auto_cleanup = request.POST.get("auto_cleanup", "true") == "true"
        retention_months = int(request.POST.get("retention_months", 6))
        keep_critical = request.POST.get("keep_critical", "true") == "true"

        # Validate retention range
        if retention_months < 1:
            retention_months = 1
        elif retention_months > 24:
            retention_months = 24

        old_values = {
            "auto_cleanup": site.audit_log_auto_cleanup,
            "retention_months": site.audit_log_retention_months,
            "keep_critical": site.audit_log_keep_critical,
        }

        site.audit_log_auto_cleanup = auto_cleanup
        site.audit_log_retention_months = retention_months
        site.audit_log_keep_critical = keep_critical
        site.updated_by = user
        site.save()

        new_values = {
            "auto_cleanup": auto_cleanup,
            "retention_months": retention_months,
            "keep_critical": keep_critical,
        }

        AuditLog.log(
            action="update",
            title="Updated audit log retention settings",
            user=user,
            request=request,
            obj=site,
            module="settings",
            severity="warning",
            description=f"Auto-cleanup: {auto_cleanup}, Retention: {retention_months} months, Keep critical: {keep_critical}",  # noqa: E501
            old_values=old_values,
            new_values=new_values,
        )

        return JsonResponse(
            {
                "success": True,
                "message": "Audit log retention settings updated successfully.",
            }
        )

    return JsonResponse({"error": "Method not allowed"}, status=405)


# =============================================================================
# FEATURE 2: DASHBOARD WIDGETS / CUSTOMIZABLE HOME
# =============================================================================


@user_passes_test(is_super_admin)
@login_required
def dashboard_widgets_api(request):
    """Get the current user's dashboard widget configuration."""
    layout, created = UserDashboardLayout.objects.get_or_create(
        user=request.user, defaults={"stream": Stream.objects.first()}
    )

    if created or not layout.widgets.exists():
        _ensure_default_widgets_exist()
        UserDashboardWidget.create_default_widgets(layout)

    widgets = layout.get_widgets_ordered()

    data = {
        "layout": {
            "theme": layout.theme,
            "sidebar_collapsed": layout.sidebar_collapsed,
            "is_customized": layout.is_customized,
        },
        "widgets": [
            {
                "id": w.id,
                "widget_type": w.widget.widget_type,
                "title": w.get_title(),
                "icon": w.widget.icon_class,
                "size": w.size,
                "row": w.position_row,
                "col": w.position_col,
                "is_visible": w.is_visible,
                "is_collapsed": w.is_collapsed,
                "config": w.get_config(),
            }
            for w in widgets
        ],
        "available_widgets": [
            {
                "widget_type": w.widget_type,
                "name": w.name,
                "description": w.description,
                "icon": w.icon_class,
                "default_size": w.default_size,
            }
            for w in DashboardWidget.objects.filter(is_active=True)
        ],
    }
    return JsonResponse({"success": True, "data": data})


@user_passes_test(is_super_admin)
@login_required
@require_POST
def dashboard_save_layout(request):
    """Save the user's customized dashboard layout."""
    try:
        body = json.loads(request.body)
        layout, _ = UserDashboardLayout.objects.get_or_create(
            user=request.user, defaults={"stream": Stream.objects.first()}
        )

        layout.is_customized = True
        if "theme" in body:
            layout.theme = body["theme"]
        if "sidebar_collapsed" in body:
            layout.sidebar_collapsed = body["sidebar_collapsed"]
        layout.save()

        if "widgets" in body:
            with transaction.atomic():
                layout.widgets.all().delete()
                for w_data in body["widgets"]:
                    widget_def = DashboardWidget.objects.filter(widget_type=w_data["widget_type"]).first()
                    if widget_def:
                        UserDashboardWidget.objects.create(
                            layout=layout,
                            widget=widget_def,
                            position_row=w_data.get("row", 0),
                            position_col=w_data.get("col", 0),
                            size=w_data.get("size", "medium"),
                            is_visible=w_data.get("is_visible", True),
                            is_collapsed=w_data.get("is_collapsed", False),
                            custom_title=w_data.get("custom_title", ""),
                            config=w_data.get("config"),
                        )

        AuditLog.log("update", "Customized dashboard layout", user=request.user, request=request, module="settings")
        return JsonResponse({"success": True})
    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"})


@user_passes_test(is_super_admin)
@login_required
@require_POST
def dashboard_reset_widgets(request):
    """Reset dashboard to default layout."""
    layout, _ = UserDashboardLayout.objects.get_or_create(
        user=request.user, defaults={"stream": Stream.objects.first()}
    )
    _ensure_default_widgets_exist()
    layout.reset_to_default()
    return JsonResponse({"success": True, "message": "Dashboard reset to default."})
