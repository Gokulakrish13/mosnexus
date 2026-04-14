"""Products app - Inventory Alerts, Thresholds, and Threshold Check views."""

# pylint: disable=broad-exception-caught

from ._helpers import (
    AuditLog,
    Category,
    InventoryAlert,
    InventoryThreshold,
    Paginator,
    Q,
    SubLevel,
    SubLevelTool,
    get_object_or_404,
    get_stream_or_404,
    is_super_admin,
    login_required,
    messages,
    redirect,
    render,
    require_POST,
    timezone,
    user_passes_test,
)

__all__ = [
    "inventory_alerts_list",
    "inventory_thresholds_list",
    "inventory_threshold_create",
    "inventory_threshold_edit",
    "inventory_threshold_delete",
    "inventory_alert_acknowledge",
    "inventory_alert_resolve",
    "inventory_check_all_thresholds",
]


@user_passes_test(is_super_admin)
@login_required
def inventory_alerts_list(request, stream=None):
    """View all inventory alerts for a stream."""
    stream_obj = get_stream_or_404(stream)

    alerts = InventoryAlert.objects.filter(stream=stream_obj).select_related("threshold")

    status_filter = request.GET.get("status", "")
    severity_filter = request.GET.get("severity", "")

    if status_filter:
        alerts = alerts.filter(status=status_filter)
    if severity_filter:
        alerts = alerts.filter(severity=severity_filter)

    paginator = Paginator(alerts, 25)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    active_count = InventoryAlert.objects.filter(stream=stream_obj, status="active").count()
    critical_count = InventoryAlert.objects.filter(stream=stream_obj, severity="critical", status="active").count()

    context = {
        "page_obj": page_obj,
        "active_count": active_count,
        "critical_count": critical_count,
        "stream": stream,
        "selected_stream": stream,
        "selected_status": status_filter,
        "selected_severity": severity_filter,
    }
    return render(request, "products/inventory_alerts_list.html", context)


@user_passes_test(is_super_admin)
@login_required
def inventory_thresholds_list(request, stream=None):
    """Manage inventory threshold rules."""
    stream_obj = get_stream_or_404(stream)

    thresholds = InventoryThreshold.objects.filter(Q(stream=stream_obj) | Q(stream__isnull=True)).select_related(
        "sublevel", "sublevel_tool", "category", "stream"
    )

    context = {
        "thresholds": thresholds,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/inventory_thresholds_list.html", context)


@user_passes_test(is_super_admin)
@login_required
def inventory_threshold_create(request, stream=None):  # noqa: CCR001
    """Create a new inventory threshold."""
    stream_obj = get_stream_or_404(stream)

    if request.method == "POST":
        try:
            applies_to = request.POST.get("applies_to")
            threshold = InventoryThreshold(
                name=request.POST.get("name", "").strip(),
                applies_to=applies_to,
                stream=stream_obj,
                minimum_quantity=int(request.POST.get("minimum_quantity", 5)),
                critical_quantity=int(request.POST.get("critical_quantity", 2)),
                maximum_quantity=(
                    int(request.POST.get("maximum_quantity")) if request.POST.get("maximum_quantity") else None
                ),
                reorder_point=int(request.POST.get("reorder_point")) if request.POST.get("reorder_point") else None,
                reorder_quantity=(
                    int(request.POST.get("reorder_quantity")) if request.POST.get("reorder_quantity") else None
                ),
                notify_lab_incharge=request.POST.get("notify_lab_incharge") == "on",
                notify_admin=request.POST.get("notify_admin") == "on",
                auto_create_alert=request.POST.get("auto_create_alert", "on") == "on",
                created_by=request.user,
            )
            if applies_to == "sublevel":
                threshold.sublevel_id = request.POST.get("sublevel_id")
            elif applies_to == "sublevel_tool":
                threshold.sublevel_tool_id = request.POST.get("sublevel_tool_id")
            elif applies_to == "category":
                threshold.category_id = request.POST.get("category_id")
            threshold.save()

            AuditLog.log(
                "create",
                f"Created inventory threshold: {threshold.name}",
                user=request.user,
                request=request,
                obj=threshold,
                module="inventory",
                stream=stream_obj,
            )
            messages.success(request, f'Threshold "{threshold.name}" created.')
            return redirect("inventory_thresholds_list", stream=stream)
        except Exception:
            form_error = "An error occurred. Please try again."
    else:
        form_error = None

    context = {
        "sublevels": SubLevel.objects.filter(stream=stream),
        "sublevel_tools": SubLevelTool.objects.filter(stream=stream),
        "categories": Category.objects.filter(stream=stream_obj),
        "stream": stream,
        "selected_stream": stream,
        "form_error": form_error,
    }
    return render(request, "products/inventory_threshold_form.html", context)


@user_passes_test(is_super_admin)
@login_required
def inventory_threshold_edit(request, stream=None, pk=None):
    """Edit an inventory threshold."""
    stream_obj = get_stream_or_404(stream)
    threshold = get_object_or_404(InventoryThreshold, pk=pk)

    if request.method == "POST":
        try:
            threshold.name = request.POST.get("name", "").strip()
            threshold.minimum_quantity = int(request.POST.get("minimum_quantity", 5))
            threshold.critical_quantity = int(request.POST.get("critical_quantity", 2))
            threshold.maximum_quantity = (
                int(request.POST.get("maximum_quantity")) if request.POST.get("maximum_quantity") else None
            )
            threshold.reorder_point = (
                int(request.POST.get("reorder_point")) if request.POST.get("reorder_point") else None
            )
            threshold.reorder_quantity = (
                int(request.POST.get("reorder_quantity")) if request.POST.get("reorder_quantity") else None
            )
            threshold.notify_lab_incharge = request.POST.get("notify_lab_incharge") == "on"
            threshold.notify_admin = request.POST.get("notify_admin") == "on"
            threshold.auto_create_alert = request.POST.get("auto_create_alert", "on") == "on"
            threshold.is_active = request.POST.get("is_active", "on") == "on"
            threshold.save()
            messages.success(request, f'Threshold "{threshold.name}" updated.')
            return redirect("inventory_thresholds_list", stream=stream)
        except Exception:
            form_error = "An error occurred. Please try again."
    else:
        form_error = None

    context = {
        "threshold": threshold,
        "sublevels": SubLevel.objects.filter(stream=stream),
        "sublevel_tools": SubLevelTool.objects.filter(stream=stream),
        "categories": Category.objects.filter(stream=stream_obj),
        "stream": stream,
        "selected_stream": stream,
        "is_edit": True,
        "form_error": form_error,
    }
    return render(request, "products/inventory_threshold_form.html", context)


@user_passes_test(is_super_admin)
@login_required
@require_POST
def inventory_threshold_delete(request, stream=None, pk=None):
    """Delete an inventory threshold."""
    threshold = get_object_or_404(InventoryThreshold, pk=pk)
    threshold.delete()
    messages.success(request, "Threshold deleted.")
    return redirect("inventory_thresholds_list", stream=stream)


@user_passes_test(is_super_admin)
@login_required
@require_POST
def inventory_alert_acknowledge(request, stream=None, pk=None):
    """Acknowledge an inventory alert."""
    alert = get_object_or_404(InventoryAlert, pk=pk)
    alert.status = "acknowledged"
    alert.acknowledged_by = request.user
    alert.acknowledged_at = timezone.now()
    alert.save()
    messages.success(request, "Alert acknowledged.")
    return redirect("inventory_alerts_list", stream=stream)


@user_passes_test(is_super_admin)
@login_required
@require_POST
def inventory_alert_resolve(request, stream=None, pk=None):
    """Resolve an inventory alert."""
    alert = get_object_or_404(InventoryAlert, pk=pk)
    alert.status = "resolved"
    alert.resolved_by = request.user
    alert.resolved_at = timezone.now()
    alert.resolution_notes = request.POST.get("resolution_notes", "")
    alert.save()
    messages.success(request, "Alert resolved.")
    return redirect("inventory_alerts_list", stream=stream)


@user_passes_test(is_super_admin)
@login_required
def inventory_check_all_thresholds(request, stream=None):  # noqa: CCR001
    """Run a check on all active thresholds and generate alerts."""
    stream_obj = get_stream_or_404(stream)

    thresholds = InventoryThreshold.objects.filter(Q(stream=stream_obj) | Q(stream__isnull=True), is_active=True)

    alerts_created = 0
    for threshold in thresholds:
        alert_type = threshold.check_threshold()
        if alert_type and threshold.auto_create_alert:
            current = threshold.get_current_stock()
            target_name = str(threshold.sublevel or threshold.sublevel_tool or threshold.category or "Unknown")

            existing = InventoryAlert.objects.filter(
                threshold=threshold, status="active", alert_type=alert_type
            ).exists()
            if not existing:
                severity = "critical" if alert_type == "critical_stock" else "warning"
                InventoryAlert.objects.create(
                    threshold=threshold,
                    alert_type=alert_type,
                    severity=severity,
                    title=f"{dict(InventoryThreshold.ALERT_TYPES).get(alert_type)}: {target_name}",
                    message=f'Stock level ({current}) has crossed the threshold for "{target_name}".',
                    item_name=target_name,
                    current_quantity=current,
                    threshold_value=(
                        threshold.critical_quantity if alert_type == "critical_stock" else threshold.minimum_quantity
                    ),
                    stream=stream_obj,
                )
                alerts_created += 1

        threshold.last_checked = timezone.now()
        threshold.save(update_fields=["last_checked"])

    if alerts_created:
        messages.warning(request, f"{alerts_created} new inventory alert(s) generated!")
    else:
        messages.success(request, "All inventory levels are within thresholds.")

    return redirect("inventory_alerts_list", stream=stream)


# =============================================================================
# FEATURE 5: FILE VERSIONING FOR COMPLIANCE DOCUMENTS
# =============================================================================
