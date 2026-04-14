"""Products app - Regulatory Requirements, Checklists, and Alerts views."""

# pylint: disable=broad-exception-caught,too-many-lines

from datetime import date as _date

from ._helpers import (
    AuditLog,
    CalibrationSchedule,
    ComplianceAlert,
    ComplianceDocument,
    Count,
    JsonResponse,
    Notification,
    Q,
    RegulatoryChecklist,
    RegulatoryChecklistItem,
    RegulatoryRequirement,
    ReservationWaitlist,
    System,
    User,
    can_manage_users,
    datetime,
    get_bu_streams,
    get_object_or_404,
    get_stream_or_404,
    logger,
    login_required,
    messages,
    redirect,
    render,
    require_POST,
    timezone,
)
from .recurring import check_reservation_conflict
from ..approval_triggers import check_approval_required, fire_approval_trigger

__all__ = [
    "regulatory_requirements_list",
    "regulatory_requirement_create",
    "regulatory_requirement_detail",
    "regulatory_requirement_edit",
    "regulatory_requirement_delete",
    "regulatory_checklists_list",
    "regulatory_checklist_create",
    "regulatory_checklist_detail",
    "regulatory_checklist_verify",
    "regulatory_checklist_edit",
    "regulatory_checklist_delete",
    "compliance_alerts_list",
    "compliance_alert_create",
    "compliance_alert_detail",
    "compliance_alert_acknowledge",
    "compliance_alert_resolve",
    "compliance_alert_edit",
    "compliance_alert_delete",
    "api_get_waitlist_position",
    "api_check_slot_availability",
    "api_calibration_stats",
]


@login_required
def regulatory_requirements_list(request, stream=None):
    """List all regulatory requirements."""
    stream_obj = get_stream_or_404(stream)

    status_filter = request.GET.get("status", "")
    priority_filter = request.GET.get("priority", "")
    search_query = request.GET.get("q", "").strip()

    all_reqs = RegulatoryRequirement.objects.filter(applicable_streams=stream_obj)

    # Stats from unfiltered queryset
    total_count = all_reqs.count()
    compliant_count = all_reqs.filter(compliance_status="compliant").count()
    partial_count = all_reqs.filter(compliance_status="partial").count()
    non_compliant_count = all_reqs.filter(compliance_status="non_compliant").count()
    under_review_count = all_reqs.filter(compliance_status="under_review").count()

    requirements = all_reqs

    if status_filter:
        requirements = requirements.filter(compliance_status=status_filter)

    if priority_filter:
        requirements = requirements.filter(priority=priority_filter)

    if search_query:
        requirements = requirements.filter(
            Q(title__icontains=search_query)
            | Q(requirement_id__icontains=search_query)
            | Q(regulatory_body__icontains=search_query)
            | Q(regulation_name__icontains=search_query)
        )

    context = {
        "requirements": requirements.select_related("responsible_person"),
        "stream": stream,
        "selected_stream": stream,
        "status_filter": status_filter,
        "priority_filter": priority_filter,
        "search_query": search_query,
        "compliance_statuses": RegulatoryRequirement.COMPLIANCE_STATUS,
        "priority_choices": RegulatoryRequirement.PRIORITY_CHOICES,
        "total_count": total_count,
        "compliant_count": compliant_count,
        "partial_count": partial_count,
        "non_compliant_count": non_compliant_count,
        "under_review_count": under_review_count,
        "today": _date.today(),
    }
    return render(request, "products/regulatory_requirements_list.html", context)


@login_required
def regulatory_requirement_create(request, stream=None):
    """Create a new regulatory requirement."""
    stream_obj = get_stream_or_404(stream)

    users = User.objects.filter(is_active=True)
    streams = get_bu_streams(request)

    if request.method == "POST":
        try:
            requirement = RegulatoryRequirement.objects.create(
                requirement_id=request.POST.get("requirement_id", "").strip(),
                title=request.POST.get("title", "").strip(),
                regulatory_body=request.POST.get("regulatory_body", "").strip(),
                regulation_name=request.POST.get("regulation_name", "").strip(),
                regulation_section=request.POST.get("regulation_section", "").strip(),
                description=request.POST.get("description", "").strip(),
                interpretation=request.POST.get("interpretation", "").strip(),
                applies_to_products=request.POST.get("applies_to_products") == "on",
                applies_to_systems=request.POST.get("applies_to_systems") == "on",
                applies_to_processes=request.POST.get("applies_to_processes") == "on",
                compliance_status=request.POST.get("compliance_status", "under_review"),
                compliance_evidence=request.POST.get("compliance_evidence", "").strip(),
                compliance_gap=request.POST.get("compliance_gap", "").strip(),
                priority=request.POST.get("priority", "high"),
                effective_date=request.POST.get("effective_date") or None,
                compliance_deadline=request.POST.get("compliance_deadline") or None,
                next_audit_date=request.POST.get("next_audit_date") or None,
                responsible_person_id=request.POST.get("responsible_person") or None,
                control_measures=request.POST.get("control_measures", "").strip(),
                verification_method=request.POST.get("verification_method", "").strip(),
                external_url=request.POST.get("external_url", "").strip() or None,
                created_by=request.user,
                notes=request.POST.get("notes", "").strip(),
            )

            applicable_stream_ids = request.POST.getlist("applicable_streams")
            requirement.applicable_streams.set(applicable_stream_ids)

            AuditLog.log(
                "create",
                f"Created regulatory requirement: {requirement.title}",
                request=request,
                obj=requirement,
                module="compliance",
                severity="info",
                stream=stream_obj,
            )

            messages.success(request, f'Regulatory requirement "{requirement.title}" created successfully!')

            # ── Fire audit trigger for critical compliance statuses ──
            if requirement.compliance_status == "non_compliant":
                fire_approval_trigger(
                    "regulatory_non_compliant",
                    stream_obj.business_unit,
                    request.user,
                    entity_obj=requirement,
                    stream=stream_obj,
                    title=f"Regulatory '{requirement.title}' \u2192 Non-Compliant",
                    description=f"Regulatory requirement {requirement.title} created as non-compliant",
                )
            elif requirement.compliance_status == "under_review":
                fire_approval_trigger(
                    "regulatory_under_review",
                    stream_obj.business_unit,
                    request.user,
                    entity_obj=requirement,
                    stream=stream_obj,
                    title=f"Regulatory '{requirement.title}' \u2192 Under Review",
                    description=f"Regulatory requirement {requirement.title} created as under review",
                )

            return redirect("regulatory_requirements_list", stream=stream)

        except Exception:
            form_error = "An error occurred. Please try again."
    else:
        form_error = None

    context = {
        "users": users,
        "streams": streams,
        "stream": stream,
        "selected_stream": stream,
        "compliance_statuses": RegulatoryRequirement.COMPLIANCE_STATUS,
        "priority_choices": RegulatoryRequirement.PRIORITY_CHOICES,
        "form_error": form_error,
    }
    return render(request, "products/regulatory_requirement_form.html", context)


@login_required
def regulatory_requirement_detail(request, stream=None, pk=None):
    """View regulatory requirement details."""
    stream_obj = get_stream_or_404(stream)
    requirement = get_object_or_404(RegulatoryRequirement, pk=pk, applicable_streams=stream_obj)

    checklists = requirement.checklists.all()
    documents = requirement.documents.all()
    calibrations = requirement.calibration_schedules.all()

    context = {
        "requirement": requirement,
        "checklists": checklists,
        "documents": documents,
        "calibrations": calibrations,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/regulatory_requirement_detail.html", context)


@login_required
def regulatory_requirement_edit(request, stream=None, pk=None):
    """Edit an existing regulatory requirement."""
    stream_obj = get_stream_or_404(stream)
    requirement = get_object_or_404(RegulatoryRequirement, pk=pk, applicable_streams=stream_obj)

    users = User.objects.filter(is_active=True)
    streams = get_bu_streams(request)

    if request.method == "POST":
        try:
            requirement.requirement_id = request.POST.get("requirement_id", "").strip()
            requirement.title = request.POST.get("title", "").strip()
            requirement.regulatory_body = request.POST.get("regulatory_body", "").strip()
            requirement.regulation_name = request.POST.get("regulation_name", "").strip()
            requirement.regulation_section = request.POST.get("regulation_section", "").strip()
            requirement.description = request.POST.get("description", "").strip()
            requirement.interpretation = request.POST.get("interpretation", "").strip()
            requirement.applies_to_products = request.POST.get("applies_to_products") == "on"
            requirement.applies_to_systems = request.POST.get("applies_to_systems") == "on"
            requirement.applies_to_processes = request.POST.get("applies_to_processes") == "on"
            _old_compliance_status = requirement.compliance_status
            requirement.compliance_status = request.POST.get("compliance_status", "under_review")
            requirement.compliance_evidence = request.POST.get("compliance_evidence", "").strip()
            requirement.compliance_gap = request.POST.get("compliance_gap", "").strip()
            requirement.priority = request.POST.get("priority", "high")
            requirement.effective_date = request.POST.get("effective_date") or None
            requirement.compliance_deadline = request.POST.get("compliance_deadline") or None
            requirement.next_audit_date = request.POST.get("next_audit_date") or None
            requirement.responsible_person_id = request.POST.get("responsible_person") or None
            requirement.control_measures = request.POST.get("control_measures", "").strip()
            requirement.verification_method = request.POST.get("verification_method", "").strip()
            requirement.external_url = request.POST.get("external_url", "").strip() or None
            requirement.notes = request.POST.get("notes", "").strip()

            # ── Pre-action enforcement for non-compliant status change ──
            if _old_compliance_status != requirement.compliance_status and requirement.compliance_status == "non_compliant":
                _reg_approval = check_approval_required(
                    "regulatory_non_compliant",
                    stream_obj.business_unit,
                    request.user,
                    entity_obj=requirement,
                    stream=stream_obj,
                    title=f"Regulatory '{requirement.title}' → Non-Compliant",
                    description=f"Regulatory requirement {requirement.title} changed from {_old_compliance_status} to non-compliant",
                    intended_changes={
                        "action_type": "status_change",
                        "model_label": "products.RegulatoryRequirement",
                        "pk": requirement.pk,
                        "changes": {"compliance_status": "non_compliant"},
                        "revert": {"compliance_status": _old_compliance_status},
                        "metadata": {"entity_name": requirement.title},
                    },
                )
                if _reg_approval:
                    requirement.compliance_status = _old_compliance_status  # revert
                    messages.warning(request, f'⏳ Marking "{requirement.title}" as non-compliant requires approval. Request #{_reg_approval.id} submitted.')

            requirement.save()

            # ── Post-save audit trigger for under-review ──
            if _old_compliance_status != requirement.compliance_status and requirement.compliance_status == "under_review":
                fire_approval_trigger(
                    "regulatory_under_review",
                    stream_obj.business_unit,
                    request.user,
                    entity_obj=requirement,
                    stream=stream_obj,
                    title=f"Regulatory '{requirement.title}' → Under Review",
                    description=f"Regulatory requirement {requirement.title} changed from {_old_compliance_status} to under review",
                )

            applicable_stream_ids = request.POST.getlist("applicable_streams")
            requirement.applicable_streams.set(applicable_stream_ids)

            AuditLog.log(
                "update",
                f"Updated regulatory requirement: {requirement.title}",
                request=request,
                obj=requirement,
                module="compliance",
                severity="info",
                stream=stream_obj,
            )

            if not _reg_approval:
                messages.success(request, f'Regulatory requirement "{requirement.title}" updated successfully!')
            return redirect("regulatory_requirements_list", stream=stream)

        except Exception:
            form_error = "An error occurred. Please try again."
    else:
        form_error = None

    context = {
        "requirement": requirement,
        "users": users,
        "streams": streams,
        "stream": stream,
        "selected_stream": stream,
        "compliance_statuses": RegulatoryRequirement.COMPLIANCE_STATUS,
        "priority_choices": RegulatoryRequirement.PRIORITY_CHOICES,
        "form_error": form_error,
    }
    return render(request, "products/regulatory_requirement_form.html", context)


@login_required
def regulatory_requirement_delete(request, stream=None, pk=None):
    """Delete a regulatory requirement."""
    stream_obj = get_stream_or_404(stream)
    requirement = get_object_or_404(RegulatoryRequirement, pk=pk, applicable_streams=stream_obj)

    if request.method == "POST":
        title = requirement.title
        AuditLog.log(
            "delete",
            f"Deleted regulatory requirement: {requirement.title}",
            request=request,
            obj=requirement,
            module="compliance",
            severity="warning",
            stream=stream_obj,
        )
        requirement.delete()
        messages.success(request, f'Regulatory requirement "{title}" deleted successfully!')
        return redirect("regulatory_requirements_list", stream=stream)

    context = {
        "requirement": requirement,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/regulatory_requirement_confirm_delete.html", context)


# Regulatory Checklists Views


@login_required
def regulatory_checklists_list(request, stream=None):
    """List all regulatory checklists."""
    stream_obj = get_stream_or_404(stream)

    status_filter = request.GET.get("status", "")
    requirement_filter = request.GET.get("requirement", "")

    checklists = RegulatoryChecklist.objects.filter(stream=stream_obj)

    if status_filter:
        checklists = checklists.filter(status=status_filter)

    if requirement_filter:
        checklists = checklists.filter(regulatory_requirement_id=requirement_filter)

    requirements = RegulatoryRequirement.objects.filter(applicable_streams=stream_obj)

    context = {
        "checklists": checklists.select_related("regulatory_requirement", "assigned_to"),
        "requirements": requirements,
        "stream": stream,
        "selected_stream": stream,
        "status_filter": status_filter,
        "requirement_filter": requirement_filter,
        "status_choices": RegulatoryChecklist.STATUS_CHOICES,
    }
    return render(request, "products/regulatory_checklists_list.html", context)


@login_required
def regulatory_checklist_create(request, stream=None):  # noqa: CCR001
    """Create a new regulatory checklist."""
    stream_obj = get_stream_or_404(stream)

    requirements = RegulatoryRequirement.objects.filter(applicable_streams=stream_obj)
    users = User.objects.filter(is_active=True)

    if request.method == "POST":
        try:
            checklist = RegulatoryChecklist.objects.create(
                title=request.POST.get("title", "").strip(),
                description=request.POST.get("description", "").strip(),
                regulatory_requirement_id=request.POST.get("regulatory_requirement"),
                stream=stream_obj,
                target_date=request.POST.get("target_date") or None,
                assigned_to_id=request.POST.get("assigned_to") or None,
                created_by=request.user,
                notes=request.POST.get("notes", "").strip(),
            )

            item_descriptions = request.POST.getlist("item_description")
            item_guidances = request.POST.getlist("item_guidance")
            item_priorities = request.POST.getlist("item_priority")
            item_evidence_required = request.POST.getlist("item_evidence_required")
            item_due_dates = request.POST.getlist("item_due_date")

            for i, description in enumerate(item_descriptions):
                if description.strip():
                    RegulatoryChecklistItem.objects.create(
                        checklist=checklist,
                        item_number=i + 1,
                        description=description.strip(),
                        guidance=item_guidances[i].strip() if i < len(item_guidances) else "",
                        priority=item_priorities[i] if i < len(item_priorities) else "medium",
                        evidence_required=item_evidence_required[i].strip() if i < len(item_evidence_required) else "",
                        due_date=item_due_dates[i] if i < len(item_due_dates) and item_due_dates[i] else None,
                    )

            messages.success(request, f'Regulatory checklist "{checklist.title}" created successfully!')
            return redirect("regulatory_checklist_detail", stream=stream, pk=checklist.pk)

        except Exception:
            form_error = "An error occurred. Please try again."
    else:
        form_error = None

    context = {
        "requirements": requirements,
        "users": users,
        "stream": stream,
        "selected_stream": stream,
        "priority_choices": RegulatoryChecklistItem.PRIORITY_CHOICES,
        "form_error": form_error,
    }
    return render(request, "products/regulatory_checklist_form.html", context)


@login_required
def regulatory_checklist_detail(request, stream=None, pk=None):  # noqa: CCR001
    """View and work on a regulatory checklist."""
    stream_obj = get_stream_or_404(stream)
    checklist = get_object_or_404(RegulatoryChecklist, pk=pk, stream=stream_obj)

    items = checklist.items.order_by("item_number")

    if request.method == "POST":
        item_id = request.POST.get("item_id")
        action = request.POST.get("action")

        if item_id:
            try:
                item = RegulatoryChecklistItem.objects.get(pk=item_id, checklist=checklist)

                if action == "complete":
                    item.is_completed = True
                    item.completed_by = request.user
                    item.completed_date = timezone.now()
                    item.completion_notes = request.POST.get("completion_notes", "").strip()
                    item.evidence_provided = request.POST.get("evidence_provided", "").strip()
                    item.save()

                    if checklist.status == "not_started":
                        checklist.status = "in_progress"
                        checklist.save()

                    messages.success(request, f"Item {item.item_number} marked as completed.")

                elif action == "not_applicable":
                    item.is_not_applicable = True
                    item.completion_notes = request.POST.get("completion_notes", "").strip()
                    item.save()
                    messages.success(request, f"Item {item.item_number} marked as not applicable.")

            except RegulatoryChecklistItem.DoesNotExist:
                pass

    context = {
        "checklist": checklist,
        "items": items,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/regulatory_checklist_detail.html", context)


@login_required
@require_POST
def regulatory_checklist_verify(request, stream=None, pk=None):
    """Verify a completed checklist."""
    stream_obj = get_stream_or_404(stream)
    checklist = get_object_or_404(RegulatoryChecklist, pk=pk, stream=stream_obj)

    if not can_manage_users(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    if checklist.completion_percentage < 100:
        return JsonResponse({"success": False, "error": "Checklist is not fully completed"})

    checklist.status = "verified"
    checklist.verified_by = request.user
    checklist.verification_date = timezone.now()
    checklist.save()

    return JsonResponse({"success": True, "message": "Checklist verified successfully!"})


@login_required
def regulatory_checklist_edit(request, stream=None, pk=None):
    """Edit a regulatory checklist."""
    stream_obj = get_stream_or_404(stream)
    checklist = get_object_or_404(RegulatoryChecklist, pk=pk, stream=stream_obj)

    requirements = RegulatoryRequirement.objects.filter(applicable_streams=stream_obj)
    users = User.objects.filter(is_active=True)

    if request.method == "POST":
        try:
            checklist.title = request.POST.get("title", "").strip()
            checklist.description = request.POST.get("description", "").strip()
            checklist.category = request.POST.get("category", "general")
            checklist.due_date = request.POST.get("due_date") or None
            checklist.assigned_to_id = request.POST.get("assigned_to") or None
            checklist.regulatory_requirement_id = request.POST.get("regulatory_requirement") or None
            checklist.notes = request.POST.get("notes", "").strip()
            checklist.save()

            messages.success(request, f'Checklist "{checklist.title}" updated successfully!')
            return redirect("regulatory_checklist_detail", stream=stream, pk=pk)
        except Exception:
            form_error = "An error occurred. Please try again."
    else:
        form_error = None

    context = {
        "checklist": checklist,
        "requirements": requirements,
        "users": users,
        "stream": stream,
        "selected_stream": stream,
        "category_choices": (
            RegulatoryChecklist.CATEGORY_CHOICES if hasattr(RegulatoryChecklist, "CATEGORY_CHOICES") else []
        ),
        "form_error": form_error,
    }
    return render(request, "products/regulatory_checklist_form.html", context)


@login_required
def regulatory_checklist_delete(request, stream=None, pk=None):
    """Delete a regulatory checklist."""
    stream_obj = get_stream_or_404(stream)
    checklist = get_object_or_404(RegulatoryChecklist, pk=pk, stream=stream_obj)

    if request.method == "POST":
        title = checklist.title
        checklist.delete()
        messages.success(request, f'Checklist "{title}" deleted successfully!')
        return redirect("regulatory_checklists_list", stream=stream)

    context = {
        "checklist": checklist,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/regulatory_checklist_confirm_delete.html", context)


# Compliance Alerts Views


@login_required
def compliance_alerts_list(request, stream=None):
    """List all compliance alerts."""
    stream_obj = get_stream_or_404(stream)

    status_filter = request.GET.get("status", "")
    severity_filter = request.GET.get("severity", "")
    type_filter = request.GET.get("type", "")

    all_alerts = ComplianceAlert.objects.filter(stream=stream_obj)

    # Stats from unfiltered queryset
    critical_count = all_alerts.filter(severity="critical").count()
    urgent_count = all_alerts.filter(severity="urgent").count()
    active_count = all_alerts.filter(status="active").count()
    resolved_count = all_alerts.filter(status="resolved").count()

    alerts = all_alerts

    if status_filter:
        alerts = alerts.filter(status=status_filter)

    if severity_filter:
        alerts = alerts.filter(severity=severity_filter)

    if type_filter:
        alerts = alerts.filter(alert_type=type_filter)

    context = {
        "alerts": alerts,
        "stream": stream,
        "selected_stream": stream,
        "status_filter": status_filter,
        "severity_filter": severity_filter,
        "type_filter": type_filter,
        "status_choices": ComplianceAlert.STATUS_CHOICES,
        "severity_choices": ComplianceAlert.SEVERITY_CHOICES,
        "alert_types": ComplianceAlert.ALERT_TYPES,
        "critical_count": critical_count,
        "urgent_count": urgent_count,
        "active_count": active_count,
        "resolved_count": resolved_count,
    }
    return render(request, "products/compliance_alerts_list.html", context)


@login_required
def compliance_alert_create(request, stream=None):
    """Create a new compliance alert."""
    stream_obj = get_stream_or_404(stream)

    if request.method == "POST":
        try:
            alert = ComplianceAlert.objects.create(
                stream=stream_obj,
                title=request.POST.get("title", "").strip(),
                message=request.POST.get("message", "").strip(),
                alert_type=request.POST.get("alert_type", "calibration_due"),
                severity=request.POST.get("severity", "warning"),
                related_requirement_id=request.POST.get("related_requirement") or None,
                related_document_id=request.POST.get("related_document") or None,
                target_user_id=request.POST.get("target_user") or None,
                resolution_notes=request.POST.get("resolution_notes", "").strip(),
                auto_dismiss_date=request.POST.get("auto_dismiss_date") or None,
            )
            AuditLog.log(
                "create",
                f"Created compliance alert: {alert.title}",
                request=request,
                obj=alert,
                module="compliance",
                severity="info",
                stream=stream_obj,
            )
            if alert.target_user_id and alert.target_user != request.user:
                Notification.notify(
                    alert.target_user,
                    f"Compliance alert: [{alert.get_severity_display()}] {alert.title}.",
                    "compliance",
                )
            messages.success(request, f'Alert "{alert.title}" created successfully!')
            return redirect("compliance_alerts_list", stream=stream)
        except Exception:
            form_error = "An error occurred. Please try again."
    else:
        form_error = None

    context = {
        "stream": stream,
        "selected_stream": stream,
        "alert_types": ComplianceAlert.ALERT_TYPES,
        "severity_choices": ComplianceAlert.SEVERITY_CHOICES,
        "requirements": RegulatoryRequirement.objects.filter(applicable_streams=stream_obj),
        "documents": ComplianceDocument.objects.filter(stream=stream_obj),
        "users": User.objects.filter(is_active=True),
        "form_error": form_error,
    }
    return render(request, "products/compliance_alert_form.html", context)


@login_required
def compliance_alert_detail(request, stream=None, pk=None):
    """View compliance alert details."""
    stream_obj = get_stream_or_404(stream)
    alert = get_object_or_404(ComplianceAlert, pk=pk, stream=stream_obj)

    context = {
        "alert": alert,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/compliance_alert_detail.html", context)


@login_required
@require_POST
def compliance_alert_acknowledge(request, stream=None, pk=None):
    """Acknowledge a compliance alert."""
    stream_obj = get_stream_or_404(stream)
    alert = get_object_or_404(ComplianceAlert, pk=pk, stream=stream_obj)

    alert.status = "acknowledged"
    alert.acknowledged_by = request.user
    alert.acknowledged_at = timezone.now()
    alert.save()

    AuditLog.log(
        "status_change",
        f"Acknowledged compliance alert: {alert.title}",
        request=request,
        obj=alert,
        module="compliance",
        severity="info",
        stream=stream_obj,
    )

    messages.success(request, f'Alert "{alert.title}" acknowledged successfully!')
    return redirect("compliance_alerts_list", stream=stream)


@login_required
@require_POST
def compliance_alert_resolve(request, stream=None, pk=None):
    """Resolve a compliance alert."""
    stream_obj = get_stream_or_404(stream)
    alert = get_object_or_404(ComplianceAlert, pk=pk, stream=stream_obj)

    resolution_notes = request.POST.get("resolution_notes", "")

    alert.status = "resolved"
    alert.resolved_by = request.user
    alert.resolved_at = timezone.now()
    alert.resolution_notes = resolution_notes
    alert.save()

    AuditLog.log(
        "status_change",
        f"Resolved compliance alert: {alert.title}",
        request=request,
        obj=alert,
        module="compliance",
        severity="info",
        stream=stream_obj,
    )

    messages.success(request, f'Alert "{alert.title}" resolved successfully!')
    return redirect("compliance_alerts_list", stream=stream)


@login_required
def compliance_alert_edit(request, stream=None, pk=None):
    """Edit a compliance alert."""
    stream_obj = get_stream_or_404(stream)
    alert = get_object_or_404(ComplianceAlert, pk=pk, stream=stream_obj)

    if request.method == "POST":
        try:
            alert.title = request.POST.get("title", "").strip()
            alert.description = request.POST.get("description", "").strip()
            alert.alert_type = request.POST.get("alert_type", "general")
            alert.priority = request.POST.get("priority", "medium")
            alert.related_equipment = request.POST.get("related_equipment", "").strip()
            alert.due_date = request.POST.get("due_date") or None
            alert.save()

            messages.success(request, f'Alert "{alert.title}" updated successfully!')
            return redirect("compliance_alerts_list", stream=stream)
        except Exception:
            form_error = "An error occurred. Please try again."
    else:
        form_error = None

    context = {
        "alert": alert,
        "stream": stream,
        "selected_stream": stream,
        "alert_types": ComplianceAlert.ALERT_TYPES if hasattr(ComplianceAlert, "ALERT_TYPES") else [],
        "priority_choices": [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")],
        "form_error": form_error,
    }
    return render(request, "products/compliance_alert_form.html", context)


@login_required
def compliance_alert_delete(request, stream=None, pk=None):
    """Delete a compliance alert."""
    stream_obj = get_stream_or_404(stream)
    alert = get_object_or_404(ComplianceAlert, pk=pk, stream=stream_obj)

    if request.method == "POST":
        title = alert.title
        AuditLog.log(
            "delete",
            f"Deleted compliance alert: {alert.title}",
            request=request,
            obj=alert,
            module="compliance",
            severity="warning",
            stream=stream_obj,
        )
        alert.delete()
        messages.success(request, f'Alert "{title}" deleted successfully!')
        return redirect("compliance_alerts_list", stream=stream)

    context = {
        "alert": alert,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/compliance_alert_confirm_delete.html", context)


# API Endpoints for AJAX operations


@login_required
def api_get_waitlist_position(request, stream=None, system_id=None, date=None):
    """Get current waitlist position for a system on a date."""
    stream_obj = get_stream_or_404(stream)

    count = ReservationWaitlist.objects.filter(
        system_id=system_id, stream=stream_obj, desired_date=date, status="waiting"
    ).count()

    return JsonResponse({"success": True, "position": count + 1})


@login_required
def api_check_slot_availability(request, stream=None):
    """Check if a time slot is available."""
    stream_obj = get_stream_or_404(stream)

    system_id = request.GET.get("system_id")
    date_str = request.GET.get("date")
    start_time = request.GET.get("start_time")
    end_time = request.GET.get("end_time")

    try:
        system = System.objects.get(id=system_id, stream=stream_obj)
        check_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        start = datetime.strptime(start_time, "%H:%M").time()
        end = datetime.strptime(end_time, "%H:%M").time()

        has_conflict, details = check_reservation_conflict(system, check_date, start, end)

        return JsonResponse({"success": True, "available": not has_conflict, "conflict_details": details})

    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"})


@login_required
def api_calibration_stats(request, stream=None):
    """Get calibration statistics for charts."""
    stream_obj = get_stream_or_404(stream)

    stats = {
        "by_status": list(
            CalibrationSchedule.objects.filter(stream=stream_obj).values("status").annotate(count=Count("id"))
        ),
        "by_type": list(
            CalibrationSchedule.objects.filter(stream=stream_obj).values("calibration_type").annotate(count=Count("id"))
        ),
        "monthly_completed": [],  # Could add monthly completion data
    }

    return JsonResponse({"success": True, "stats": stats})


# =============================================================================
# FEATURE 1: GLOBAL AUDIT LOG / ACTIVITY TIMELINE
# =============================================================================
