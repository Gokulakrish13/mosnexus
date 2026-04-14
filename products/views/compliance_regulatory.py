"""Products app - Compliance Dashboard, Documents, Regulatory, Checklists, and Alerts views."""

# pylint: disable=too-many-lines,broad-exception-caught

from ._helpers import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    ALLOWED_DOCUMENT_TYPES,
    MAX_DOCUMENT_SIZE,
    AuditLog,
    ComplianceAlert,
    ComplianceDocument,
    HttpResponse,
    Q,
    RegulatoryChecklist,
    RegulatoryRequirement,
    User,
    check_user_access,
    csv,
    date,
    get_object_or_404,
    get_stream_or_404,
    login_required,
    messages,
    redirect,
    render,
    timedelta,
    timezone,
    validate_uploaded_file,
)
from ..approval_triggers import check_approval_required, fire_approval_trigger

__all__ = [
    "compliance_export_report",
    "compliance_dashboard",
    "compliance_documents_list",
    "compliance_document_create",
    "compliance_document_detail",
    "compliance_document_edit",
    "compliance_document_delete",
]


@login_required
def compliance_export_report(request, stream=None):  # noqa: C901, CCR001
    # pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-complex
    """Export compliance reports in various formats."""
    stream_obj = get_stream_or_404(stream)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        messages.error(request, error_message)
        return redirect("dashboard")

    start_date = request.GET.get("start_date", "")
    end_date = request.GET.get("end_date", "")
    report_type = request.GET.get("report_type", "summary")
    export_format = request.GET.get("format", "")

    requirements = RegulatoryRequirement.objects.filter(applicable_streams=stream_obj)
    documents = ComplianceDocument.objects.filter(stream=stream_obj)
    checklists = RegulatoryChecklist.objects.filter(stream=stream_obj)
    alerts = ComplianceAlert.objects.filter(stream=stream_obj)

    if start_date:
        documents = documents.filter(created_at__date__gte=start_date)
        checklists = checklists.filter(created_at__date__gte=start_date)
        alerts = alerts.filter(created_at__date__gte=start_date)
    if end_date:
        documents = documents.filter(created_at__date__lte=end_date)
        checklists = checklists.filter(created_at__date__lte=end_date)
        alerts = alerts.filter(created_at__date__lte=end_date)

    total_req = requirements.count()
    compliant_req = requirements.filter(compliance_status="compliant").count()
    compliance_score = round((compliant_req / total_req * 100) if total_req > 0 else 0, 1)

    stats = {
        "compliance_score": compliance_score,
        "total_requirements": total_req,
        "compliant": compliant_req,
        "partial": requirements.filter(compliance_status="partial").count(),
        "non_compliant": requirements.filter(compliance_status="non_compliant").count(),
        "total_documents": documents.count(),
        "approved_docs": documents.filter(status="approved").count(),
        "pending_docs": documents.filter(status="pending_review").count(),
        "draft_docs": documents.filter(status="draft").count(),
        "total_checklists": checklists.count(),
        "completed_checklists": checklists.filter(status="completed").count(),
        "in_progress_checklists": checklists.filter(status="in_progress").count(),
        "total_alerts": alerts.count(),
        "active_alerts": alerts.filter(status="active").count(),
        "resolved_alerts": alerts.filter(status="resolved").count(),
        "critical_alerts": alerts.filter(severity="critical", status="active").count(),
    }

    if export_format == "csv":

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="compliance_report_{stream}_{date.today()}.csv"'

        writer = csv.writer(response)

        if report_type == "summary":
            writer.writerow(["Compliance Report Summary", f"Stream: {stream}", f"Generated: {date.today()}"])
            writer.writerow([])
            writer.writerow(["Metric", "Value"])
            writer.writerow(["Compliance Score", f'{stats["compliance_score"]}%'])
            writer.writerow(["Total Requirements", stats["total_requirements"]])
            writer.writerow(["Compliant", stats["compliant"]])
            writer.writerow(["Partial", stats["partial"]])
            writer.writerow(["Non-Compliant", stats["non_compliant"]])
            writer.writerow([])
            writer.writerow(["Documents", stats["total_documents"]])
            writer.writerow(["Approved", stats["approved_docs"]])
            writer.writerow(["Pending Review", stats["pending_docs"]])
            writer.writerow([])
            writer.writerow(["Checklists", stats["total_checklists"]])
            writer.writerow(["Completed", stats["completed_checklists"]])
            writer.writerow(["In Progress", stats["in_progress_checklists"]])
            writer.writerow([])
            writer.writerow(["Alerts", stats["total_alerts"]])
            writer.writerow(["Active", stats["active_alerts"]])
            writer.writerow(["Critical Active", stats["critical_alerts"]])

        elif report_type == "requirements":
            writer.writerow(["Requirement ID", "Title", "Regulatory Body", "Status", "Priority", "Due Date"])
            for req in requirements:
                writer.writerow(
                    [
                        req.requirement_id,
                        req.title,
                        req.regulatory_body,
                        req.get_compliance_status_display(),
                        req.get_priority_display(),
                        req.compliance_deadline or "N/A",
                    ]
                )

        elif report_type == "documents":
            writer.writerow(["Document ID", "Title", "Type", "Status", "Version", "Effective Date", "Expiry Date"])
            for doc in documents:
                writer.writerow(
                    [
                        doc.document_id,
                        doc.title,
                        doc.get_document_type_display(),
                        doc.get_status_display(),
                        doc.version,
                        doc.effective_date or "N/A",
                        doc.expiry_date or "N/A",
                    ]
                )

        elif report_type == "checklists":
            writer.writerow(["Checklist", "Requirement", "Status", "Completion %", "Due Date", "Completed Date"])
            for checklist in checklists:
                writer.writerow(
                    [
                        checklist.title,
                        checklist.requirement.title if checklist.requirement else "N/A",
                        checklist.get_status_display(),
                        f"{checklist.completion_percentage}%",
                        checklist.target_date or "N/A",
                        checklist.completed_date or "N/A",
                    ]
                )

        elif report_type == "alerts":
            writer.writerow(["Alert Title", "Type", "Severity", "Status", "Created", "Due Date"])
            for alert in alerts:
                writer.writerow(
                    [
                        alert.title,
                        alert.get_alert_type_display(),
                        alert.get_severity_display(),
                        alert.get_status_display(),
                        alert.created_at.date(),
                        alert.due_date or "N/A",
                    ]
                )

        return response

    recent_documents = documents.order_by("-created_at")[:5]
    recent_checklists = checklists.order_by("-created_at")[:5]
    recent_alerts = alerts.order_by("-created_at")[:5]

    context = {
        "stats": stats,
        "requirements": requirements,
        "documents": documents,
        "checklists": checklists,
        "alerts": alerts,
        "recent_documents": recent_documents,
        "recent_checklists": recent_checklists,
        "recent_alerts": recent_alerts,
        "start_date": start_date,
        "end_date": end_date,
        "report_type": report_type,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/compliance_export_report.html", context)


@login_required
def compliance_dashboard(request, stream=None):
    # pylint: disable=too-many-locals
    """Main compliance tracking dashboard."""
    stream_obj = get_stream_or_404(stream)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        messages.error(request, error_message)
        return redirect("dashboard")

    active_alerts = ComplianceAlert.objects.filter(stream=stream_obj, status="active").order_by(
        "-severity", "-created_at"
    )[:10]

    requirements = RegulatoryRequirement.objects.filter(applicable_streams=stream_obj)
    total_requirements = requirements.count()
    compliant_count = requirements.filter(compliance_status="compliant").count()
    partial_count = requirements.filter(compliance_status="partial").count()
    non_compliant_count = requirements.filter(compliance_status="non_compliant").count()

    requirements_summary = {
        "total": total_requirements,
        "compliant": compliant_count,
        "partial": partial_count,
        "non_compliant": non_compliant_count,
    }

    if total_requirements > 0:
        compliance_score = round((compliant_count / total_requirements) * 100)
    else:
        compliance_score = 0

    documents = ComplianceDocument.objects.filter(stream=stream_obj)
    total_documents = documents.count()
    approved_docs = documents.filter(status="approved").count()
    pending_docs = documents.filter(status="pending_review").count()

    docs_needing_review = ComplianceDocument.objects.filter(
        stream=stream_obj, review_date__lte=date.today() + timedelta(days=30)
    ).order_by("review_date")[:10]

    checklists = RegulatoryChecklist.objects.filter(stream=stream_obj)
    incomplete_checklists = checklists.filter(status__in=["not_started", "in_progress"]).order_by("target_date")[:10]

    upcoming_audits = RegulatoryRequirement.objects.filter(
        applicable_streams=stream_obj,
        next_audit_date__gte=date.today(),
        next_audit_date__lte=date.today() + timedelta(days=90),
    ).order_by("next_audit_date")[:5]

    stats = {
        "compliant_items": compliant_count,
        "pending_items": pending_docs + partial_count,
        "non_compliant": non_compliant_count,
        "total_documents": total_documents,
        "approved_docs": approved_docs,
        "pending_docs": pending_docs,
        "total_requirements": total_requirements,
        "total_checklists": checklists.count(),
        "active_alerts": active_alerts.count(),
    }

    context = {
        "compliance_score": compliance_score,
        "stats": stats,
        "active_alerts": active_alerts,
        "requirements_summary": requirements_summary,
        "requirements": requirements,
        "docs_needing_review": docs_needing_review,
        "incomplete_checklists": incomplete_checklists,
        "upcoming_audits": upcoming_audits,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/compliance_dashboard.html", context)


@login_required
def compliance_documents_list(request, stream=None):
    """List all compliance documents."""
    stream_obj = get_stream_or_404(stream)

    type_filter = request.GET.get("type", "")
    status_filter = request.GET.get("status", "")
    search_query = request.GET.get("q", "").strip()

    all_docs = ComplianceDocument.objects.filter(stream=stream_obj)
    documents = all_docs

    if type_filter:
        documents = documents.filter(document_type=type_filter)

    if status_filter:
        documents = documents.filter(status=status_filter)

    if search_query:
        documents = documents.filter(
            Q(title__icontains=search_query)
            | Q(document_id__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(keywords__icontains=search_query)
        )

    today = timezone.now().date()
    expiry_threshold = today + timedelta(days=30)

    context = {
        "documents": documents.select_related("author", "approved_by"),
        "stream": stream,
        "selected_stream": stream,
        "type_filter": type_filter,
        "status_filter": status_filter,
        "search_query": search_query,
        "document_types": ComplianceDocument.DOCUMENT_TYPES,
        "status_choices": ComplianceDocument.STATUS_CHOICES,
        "today": today,
        "total_count": all_docs.count(),
        "approved_count": all_docs.filter(status="approved").count(),
        "pending_count": all_docs.filter(status="pending_review").count(),
        "draft_count": all_docs.filter(status="draft").count(),
        "expiring_count": all_docs.filter(expiry_date__lte=expiry_threshold, expiry_date__gte=today)
        .exclude(status="archived")
        .count(),
    }
    return render(request, "products/compliance_documents_list.html", context)


@login_required
def compliance_document_create(request, stream=None):  # noqa: CCR001
    """Create/upload a new compliance document."""
    stream_obj = get_stream_or_404(stream)

    requirements = RegulatoryRequirement.objects.filter(applicable_streams=stream_obj)
    users = User.objects.filter(is_active=True)

    if request.method == "POST":
        try:
            doc_file = request.FILES.get("file")
            if doc_file:
                is_valid, error_msg = validate_uploaded_file(
                    doc_file, ALLOWED_DOCUMENT_TYPES, ALLOWED_DOCUMENT_EXTENSIONS, MAX_DOCUMENT_SIZE
                )
                if not is_valid:
                    messages.error(request, f"File upload error: {error_msg}")
                    return redirect("compliance_document_create", stream=stream)

            document = ComplianceDocument.objects.create(
                title=request.POST.get("title", "").strip(),
                document_id=request.POST.get("document_id", "").strip(),
                document_type=request.POST.get("document_type"),
                file=doc_file,
                original_filename=doc_file.name if doc_file else "",
                file_size=doc_file.size if doc_file else 0,
                version=request.POST.get("version", "1.0"),
                revision_date=request.POST.get("revision_date"),
                description=request.POST.get("description", "").strip(),
                scope=request.POST.get("scope", "").strip(),
                keywords=request.POST.get("keywords", "").strip(),
                status=request.POST.get("status", "draft"),
                effective_date=request.POST.get("effective_date") or None,
                expiry_date=request.POST.get("expiry_date") or None,
                review_date=request.POST.get("review_date") or None,
                stream=stream_obj,
                regulatory_requirement_id=request.POST.get("regulatory_requirement") or None,
                author_id=request.POST.get("author") or request.user.id,
                distribution_list=request.POST.get("distribution_list", "").strip(),
                is_confidential=request.POST.get("is_confidential") == "on",
                change_summary=request.POST.get("change_summary", "").strip(),
                uploaded_by=request.user,
                notes=request.POST.get("notes", "").strip(),
            )

            AuditLog.log(
                "create",
                f"Created compliance document: {document.title}",
                request=request,
                obj=document,
                module="compliance",
                severity="info",
                stream=stream_obj,
            )

            messages.success(request, f'Compliance document "{document.title}" uploaded successfully!')

            # ── Auto-trigger approval for compliance doc creation ──
            fire_approval_trigger(
                "compliance_doc_created",
                stream_obj.business_unit,
                request.user,
                entity_obj=document,
                stream=stream_obj,
                title=f"Compliance doc '{document.title}' created",
                description=f"Compliance document {document.title} (ID: {document.document_id}) created with status '{document.status}'",
            )
            _new_status = document.status
            if _new_status in ("approved", "pending_review"):
                fire_approval_trigger(
                    "compliance_doc_approved",
                    stream_obj.business_unit,
                    request.user,
                    entity_obj=document,
                    stream=stream_obj,
                    title=f"Compliance doc '{document.title}' created as {_new_status}",
                    description=f"Compliance document {document.title} (ID: {document.document_id}) created with status '{_new_status}'",
                )

            return redirect("compliance_documents_list", stream=stream)

        except Exception:
            form_error = "An error occurred. Please try again."
    else:
        form_error = None

    context = {
        "requirements": requirements,
        "users": users,
        "stream": stream,
        "selected_stream": stream,
        "document_types": ComplianceDocument.DOCUMENT_TYPES,
        "status_choices": ComplianceDocument.STATUS_CHOICES,
        "form_error": form_error,
    }
    return render(request, "products/compliance_document_form.html", context)


@login_required
def compliance_document_detail(request, stream=None, pk=None):
    """View compliance document details."""
    stream_obj = get_stream_or_404(stream)
    document = get_object_or_404(ComplianceDocument, pk=pk, stream=stream_obj)

    version_history = ComplianceDocument.objects.filter(
        Q(pk=document.pk) | Q(previous_version=document) | Q(pk=document.previous_version_id)
        if document.previous_version_id
        else Q()
    ).order_by("-revision_date")

    context = {
        "document": document,
        "version_history": version_history,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/compliance_document_detail.html", context)


@login_required
def compliance_document_edit(request, stream=None, pk=None):  # noqa: CCR001
    """Edit an existing compliance document."""
    stream_obj = get_stream_or_404(stream)
    document = get_object_or_404(ComplianceDocument, pk=pk, stream=stream_obj)

    requirements = RegulatoryRequirement.objects.filter(applicable_streams=stream_obj)
    users = User.objects.filter(is_active=True)

    if request.method == "POST":
        try:
            _old_status = document.status
            document.title = request.POST.get("title", "").strip()
            document.document_id = request.POST.get("document_id", "").strip()
            document.document_type = request.POST.get("document_type")
            document.version = request.POST.get("version", "1.0")
            document.revision_date = request.POST.get("revision_date")
            document.description = request.POST.get("description", "").strip()
            document.scope = request.POST.get("scope", "").strip()
            document.keywords = request.POST.get("keywords", "").strip()

            _requested_status = request.POST.get("status", "draft")

            # ── Pre-action enforcement: block major compliance status changes ──
            _approval_block = None
            if _old_status != _requested_status:
                if _requested_status == "approved":
                    _approval_block = check_approval_required(
                        "compliance_doc_approved",
                        stream_obj.business_unit,
                        request.user,
                        entity_obj=document,
                        stream=stream_obj,
                        title=f"Compliance doc '{document.title}' \u2192 approved",
                        description=f"Compliance document {document.title} (ID: {document.document_id}) status change to approved",
                        intended_changes={
                            "action_type": "status_change",
                            "model_label": "products.ComplianceDocument",
                            "pk": document.pk,
                            "changes": {"status": "approved"},
                            "revert": {"status": _old_status},
                            "metadata": {"entity_name": document.title, "stream_name": stream},
                        },
                    )
                elif _requested_status in ("archived", "superseded"):
                    _approval_block = check_approval_required(
                        "compliance_doc_archived",
                        stream_obj.business_unit,
                        request.user,
                        entity_obj=document,
                        stream=stream_obj,
                        title=f"Compliance doc '{document.title}' \u2192 {_requested_status}",
                        description=f"Compliance document {document.title} (ID: {document.document_id}) status change to {_requested_status}",
                        intended_changes={
                            "action_type": "status_change",
                            "model_label": "products.ComplianceDocument",
                            "pk": document.pk,
                            "changes": {"status": _requested_status},
                            "revert": {"status": _old_status},
                            "metadata": {"entity_name": document.title, "stream_name": stream},
                        },
                    )

            document.status = _old_status if _approval_block else _requested_status

            document.effective_date = request.POST.get("effective_date") or None
            document.expiry_date = request.POST.get("expiry_date") or None
            document.review_date = request.POST.get("review_date") or None
            document.regulatory_requirement_id = request.POST.get("regulatory_requirement") or None
            document.author_id = request.POST.get("author") or request.user.id
            document.distribution_list = request.POST.get("distribution_list", "").strip()
            document.is_confidential = request.POST.get("is_confidential") == "on"
            document.change_summary = request.POST.get("change_summary", "").strip()
            document.notes = request.POST.get("notes", "").strip()

            doc_file = request.FILES.get("file")
            if doc_file:
                is_valid, error_msg = validate_uploaded_file(
                    doc_file, ALLOWED_DOCUMENT_TYPES, ALLOWED_DOCUMENT_EXTENSIONS, MAX_DOCUMENT_SIZE
                )
                if not is_valid:
                    messages.error(request, f"File upload error: {error_msg}")
                    return redirect("compliance_document_edit", stream=stream, pk=document.pk)
                document.file = doc_file
                document.original_filename = doc_file.name
                document.file_size = doc_file.size

            document.save()

            AuditLog.log(
                "update",
                f"Updated compliance document: {document.title}",
                request=request,
                obj=document,
                module="compliance",
                severity="info",
                stream=stream_obj,
            )

            messages.success(request, f'Compliance document "{document.title}" updated successfully!')

            # ── Show warning if status change was blocked by approval ──
            if _approval_block:
                messages.warning(
                    request,
                    f'\u23f3 Status change to "{_requested_status}" requires approval. '
                    f'Request #{_approval_block.id} submitted.',
                )

            return redirect("compliance_documents_list", stream=stream)

        except Exception:
            form_error = "An error occurred. Please try again."
    else:
        form_error = None

    context = {
        "document": document,
        "requirements": requirements,
        "users": users,
        "stream": stream,
        "selected_stream": stream,
        "document_types": ComplianceDocument.DOCUMENT_TYPES,
        "status_choices": ComplianceDocument.STATUS_CHOICES,
        "form_error": form_error,
    }
    return render(request, "products/compliance_document_form.html", context)


@login_required
def compliance_document_delete(request, stream=None, pk=None):
    """Delete a compliance document."""
    stream_obj = get_stream_or_404(stream)
    document = get_object_or_404(ComplianceDocument, pk=pk, stream=stream_obj)

    if request.method == "POST":
        title = document.title
        _bu = stream_obj.business_unit

        # ── Pre-action enforcement: block delete if approval required ──
        _approval = check_approval_required(
            "compliance_doc_deleted",
            _bu,
            request.user,
            entity_obj=document,
            stream=stream_obj,
            title=f"Compliance doc '{title}' deletion",
            description=f"Compliance document '{title}' delete requested from stream {stream}",
            intended_changes={
                "action_type": "delete",
                "model_label": "products.ComplianceDocument",
                "pk": document.pk,
                "metadata": {"entity_name": title, "stream_name": stream},
            },
        )
        if _approval:
            messages.warning(
                request,
                f'\u23f3 Deleting "{title}" requires approval. Request #{_approval.id} submitted.',
            )
            return redirect("compliance_documents_list", stream=stream)

        AuditLog.log(
            "delete",
            f"Deleted compliance document: {document.title}",
            request=request,
            obj=document,
            module="compliance",
            severity="warning",
            stream=stream_obj,
        )
        document.delete()
        messages.success(request, f'Compliance document "{title}" deleted successfully!')
        return redirect("compliance_documents_list", stream=stream)

    context = {
        "document": document,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/compliance_document_confirm_delete.html", context)


# Regulatory Requirements Views
