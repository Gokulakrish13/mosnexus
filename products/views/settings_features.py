"""Products app - Compliance Versions, Maintenance Calendar, Feature Access, Health, Showcase views."""

# pylint: disable=broad-exception-caught

from django.utils.dateparse import parse_datetime

from ._helpers import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    ALLOWED_DOCUMENT_TYPES,
    MAX_DOCUMENT_SIZE,
    AuditLog,
    BuildServer,
    BuildServerMaintenanceLog,
    CalibrationSchedule,
    ComplianceDocument,
    ComplianceDocumentVersion,
    FileResponse,
    IntegrityError,
    JsonResponse,
    MaintenanceEvent,
    Notification,
    Stream,
    System,
    User,
    get_bu_streams,
    get_object_or_404,
    get_stream_or_404,
    is_super_admin,
    json,
    logger,
    login_required,
    messages,
    redirect,
    render,
    require_POST,
    timezone,
    user_passes_test,
    validate_uploaded_file,
)

__all__ = [
    "compliance_document_versions",
    "compliance_document_version_upload",
    "compliance_document_version_restore",
    "compliance_document_version_download",
    "maintenance_calendar",
    "maintenance_calendar_events_api",
    "maintenance_event_create_api",
    "maintenance_event_update_api",
    "maintenance_event_delete_api",
    "maintenance_event_complete_api",
]


@user_passes_test(is_super_admin)
@login_required
def compliance_document_versions(request, stream=None, pk=None):
    """View all versions of a compliance document."""
    stream_obj = get_stream_or_404(stream)
    document = get_object_or_404(ComplianceDocument, pk=pk, stream=stream_obj)

    versions = document.versions.select_related("created_by", "reviewed_by", "approved_by").all()

    context = {
        "document": document,
        "versions": versions,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/compliance_document_versions.html", context)


@user_passes_test(is_super_admin)
@login_required
@require_POST
def compliance_document_version_upload(request, stream=None, pk=None):
    """Upload a new version of a compliance document."""
    stream_obj = get_stream_or_404(stream)
    document = get_object_or_404(ComplianceDocument, pk=pk, stream=stream_obj)

    try:
        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            messages.error(request, "No file provided.")
            return redirect("compliance_document_versions", stream=stream, pk=pk)

        is_valid, error_msg = validate_uploaded_file(
            uploaded_file, ALLOWED_DOCUMENT_TYPES, ALLOWED_DOCUMENT_EXTENSIONS, MAX_DOCUMENT_SIZE
        )
        if not is_valid:
            messages.error(request, f"File upload error: {error_msg}")
            return redirect("compliance_document_versions", stream=stream, pk=pk)

        version_number = request.POST.get("version_number", "").strip()
        if not version_number:
            messages.error(request, "Version number is required.")
            return redirect("compliance_document_versions", stream=stream, pk=pk)

        version = ComplianceDocumentVersion.objects.create(
            document=document,
            version_number=version_number,
            version_label=request.POST.get("version_label", "").strip(),
            is_current=request.POST.get("make_current") == "on",
            file=uploaded_file,
            original_filename=uploaded_file.name,
            file_size=uploaded_file.size,
            status_at_version=document.status,
            change_summary=request.POST.get("change_summary", "").strip(),
            change_type=request.POST.get("change_type", "minor"),
            created_by=request.user,
            notes=request.POST.get("notes", "").strip(),
        )

        if version.is_current:
            version.make_current()

        AuditLog.log(
            "create",
            f'Uploaded version {version_number} of "{document.title}"',
            user=request.user,
            request=request,
            obj=document,
            module="compliance",
            stream=stream_obj,
        )
        messages.success(request, f"Version {version_number} uploaded successfully.")
    except IntegrityError:
        messages.error(request, f'Version "{version_number}" already exists.')
    except Exception:
        messages.error(request, "An error occurred. Please try again.")

    return redirect("compliance_document_versions", stream=stream, pk=pk)


@user_passes_test(is_super_admin)
@login_required
@require_POST
def compliance_document_version_restore(request, stream=None, pk=None, version_id=None):
    """Restore a previous version as the current version."""
    stream_obj = get_stream_or_404(stream)
    document = get_object_or_404(ComplianceDocument, pk=pk, stream=stream_obj)
    version = get_object_or_404(ComplianceDocumentVersion, pk=version_id, document=document)

    version.make_current()

    AuditLog.log(
        "update",
        f'Restored version {version.version_number} of "{document.title}"',
        user=request.user,
        request=request,
        obj=document,
        module="compliance",
        stream=stream_obj,
    )
    messages.success(request, f"Version {version.version_number} restored as current.")
    return redirect("compliance_document_versions", stream=stream, pk=pk)


@user_passes_test(is_super_admin)
@login_required
def compliance_document_version_download(request, stream=None, pk=None, version_id=None):
    """Download a specific version of a compliance document."""
    stream_obj = get_stream_or_404(stream)
    document = get_object_or_404(ComplianceDocument, pk=pk, stream=stream_obj)
    version = get_object_or_404(ComplianceDocumentVersion, pk=version_id, document=document)

    if version.file:
        response = FileResponse(
            version.file, as_attachment=True, filename=f"v{version.version_number}_{version.original_filename}"
        )
        return response

    messages.error(request, "File not found.")
    return redirect("compliance_document_versions", stream=stream, pk=pk)


# =============================================================================
# FEATURE 6: MAINTENANCE CALENDAR VIEW
# =============================================================================


@user_passes_test(is_super_admin)
@login_required
def maintenance_calendar(request, stream=None):
    """Full-page maintenance calendar view."""
    streams = get_bu_streams(request)
    stream_obj = None
    if stream:
        stream_obj = get_stream_or_404(stream)

    users = User.objects.filter(is_active=True).order_by("username")
    systems = System.objects.filter(stream=stream_obj) if stream_obj else System.objects.filter(stream__in=streams)
    build_servers = (
        BuildServer.objects.filter(stream=stream_obj) if stream_obj else BuildServer.objects.filter(stream__in=streams)
    )

    context = {
        "stream": stream,
        "selected_stream": stream or "",
        "streams": streams,
        "users": users,
        "systems": systems,
        "build_servers": build_servers,
        "event_types": MaintenanceEvent.EVENT_TYPES,
        "priority_choices": MaintenanceEvent.PRIORITY_CHOICES,
        "status_choices": MaintenanceEvent.STATUS_CHOICES,
        "color_choices": MaintenanceEvent.COLOR_CHOICES,
    }
    return render(request, "products/maintenance_calendar.html", context)


@user_passes_test(is_super_admin)
@login_required
def maintenance_calendar_events_api(request):  # noqa: C901, CCR001
    """API: Get calendar events for a date range."""
    # pylint: disable=too-complex
    start = request.GET.get("start", "")
    end = request.GET.get("end", "")
    stream_name = request.GET.get("stream", "")
    event_type = request.GET.get("event_type", "")
    status = request.GET.get("status", "")

    events = MaintenanceEvent.objects.select_related("build_server", "system", "assigned_to", "stream")

    if start:
        events = events.filter(start_datetime__gte=start)
    if end:
        events = events.filter(end_datetime__lte=end)
    if stream_name:
        events = events.filter(stream__name=stream_name)
    if event_type:
        events = events.filter(event_type=event_type)
    if status:
        events = events.filter(status=status)

    calendar_events = [e.to_calendar_event() for e in events]

    # Also pull in existing data: calibration schedules, build server maintenance
    if not event_type or event_type == "calibration":
        cal_schedules = CalibrationSchedule.objects.filter(status__in=["scheduled", "due", "overdue"])
        if stream_name:
            cal_schedules = cal_schedules.filter(stream__name=stream_name)
        for cs in cal_schedules:
            if cs.next_calibration_date:
                cal_color = "#dc3545" if cs.status == "overdue" else "#d4a017" if cs.status == "due" else "#0B5FFF"
                calendar_events.append(
                    {
                        "id": f"cal_{cs.pk}",
                        "title": f"⚙ {cs.title}",
                        "start": cs.next_calibration_date.isoformat(),
                        "end": cs.next_calibration_date.isoformat(),
                        "allDay": True,
                        "color": cal_color,
                        "extendedProps": {
                            "event_type": "calibration",
                            "status": cs.status,
                            "priority": cs.priority,
                            "description": cs.description or "",
                            "linked_object": cs.get_equipment_name(),
                            "stream": cs.stream.name if cs.stream else "",
                            "is_auto": True,
                        },
                    }
                )

    if not event_type or event_type == "build_server":
        logs = BuildServerMaintenanceLog.objects.select_related("build_server").filter(completed=False)
        if stream_name:
            logs = logs.filter(build_server__stream__name=stream_name)
        for ml in logs:
            calendar_events.append(
                {
                    "id": f"bsm_{ml.pk}",
                    "title": f"🖥 {ml.build_server.hostname}: {ml.get_maintenance_type_display()}",
                    "start": ml.scheduled_date.isoformat(),
                    "end": (ml.actual_date or ml.scheduled_date).isoformat(),
                    "allDay": False,
                    "color": "#0B5FFF",
                    "extendedProps": {
                        "event_type": "build_server",
                        "status": "completed" if ml.completed else "scheduled",
                        "description": ml.description,
                        "linked_object": f"Server: {ml.build_server.hostname}",
                        "stream": ml.build_server.stream.name if ml.build_server.stream else "",
                        "is_auto": True,
                    },
                }
            )

    return JsonResponse(calendar_events, safe=False)


@user_passes_test(is_super_admin)
@login_required
@require_POST
def maintenance_event_create_api(request):  # noqa: CCR001
    """API: Create a new maintenance event."""
    try:
        body = json.loads(request.body)

        stream_obj = None
        if body.get("stream"):
            stream_obj = Stream.objects.filter(name=body["stream"]).first()

        # Parse datetime strings into timezone-aware objects
        start_dt = parse_datetime(body.get("start_datetime", ""))
        if start_dt is None and body.get("start_datetime"):
            start_dt = parse_datetime(body["start_datetime"] + ":00")
        if start_dt and timezone.is_naive(start_dt):
            start_dt = timezone.make_aware(start_dt)

        end_dt = parse_datetime(body.get("end_datetime", "") or body.get("start_datetime", ""))
        if end_dt is None and (body.get("end_datetime") or body.get("start_datetime")):
            end_dt = parse_datetime((body.get("end_datetime") or body["start_datetime"]) + ":00")
        if end_dt and timezone.is_naive(end_dt):
            end_dt = timezone.make_aware(end_dt)

        event = MaintenanceEvent.objects.create(
            title=body.get("title", "").strip(),
            description=body.get("description", "").strip(),
            event_type=body.get("event_type", "custom"),
            status=body.get("status", "scheduled"),
            priority=body.get("priority", "normal"),
            color=body.get("color", "#0B5FFF"),
            start_datetime=start_dt,
            end_datetime=end_dt,
            all_day=body.get("all_day", False),
            recurrence=body.get("recurrence", "none"),
            recurrence_end_date=body.get("recurrence_end_date") or None,
            build_server_id=body.get("build_server_id") or None,
            system_id=body.get("system_id") or None,
            calibration_schedule_id=body.get("calibration_schedule_id") or None,
            product_id=body.get("product_id") or None,
            stream=stream_obj,
            assigned_to_id=body.get("assigned_to_id") or None,
            created_by=request.user,
            estimated_cost=body.get("estimated_cost") or None,
            reminder_hours_before=body.get("reminder_hours_before", 24),
            notes=body.get("notes", ""),
        )

        AuditLog.log(
            "create",
            f"Created maintenance event: {event.title}",
            user=request.user,
            request=request,
            obj=event,
            module="maintenance",
            stream=stream_obj,
        )
        if event.assigned_to and event.assigned_to != request.user:
            Notification.notify(
                event.assigned_to, f"Maintenance event '{event.title}' has been assigned to you.", "maintenance"
            )

        return JsonResponse({"success": True, "event": event.to_calendar_event()})
    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"})


@user_passes_test(is_super_admin)
@login_required
@require_POST
def maintenance_event_update_api(request, pk):  # noqa: C901, CCR001
    """API: Update an existing maintenance event."""
    # pylint: disable=too-complex,too-many-branches
    try:
        event = get_object_or_404(MaintenanceEvent, pk=pk)
        body = json.loads(request.body)

        for field in ["title", "description", "event_type", "status", "priority", "color", "notes", "recurrence"]:
            if field in body:
                setattr(event, field, body[field])

        for dt_field in ["start_datetime", "end_datetime"]:
            if dt_field in body and body[dt_field]:
                parsed = parse_datetime(body[dt_field])
                if parsed is None:
                    # Handle datetime-local format (no seconds/timezone)
                    parsed = parse_datetime(body[dt_field] + ":00")
                if parsed:
                    if timezone.is_naive(parsed):
                        parsed = timezone.make_aware(parsed)
                    setattr(event, dt_field, parsed)

        if "all_day" in body:
            event.all_day = body["all_day"]
        if "assigned_to_id" in body:
            event.assigned_to_id = body["assigned_to_id"] or None
        if "build_server_id" in body:
            event.build_server_id = body["build_server_id"] or None
        if "system_id" in body:
            event.system_id = body["system_id"] or None
        if "stream" in body:
            stream_obj = None
            if body["stream"]:
                stream_obj = Stream.objects.filter(name=body["stream"]).first()
            event.stream = stream_obj

        event.save()
        return JsonResponse({"success": True, "event": event.to_calendar_event()})
    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"})


@user_passes_test(is_super_admin)
@login_required
@require_POST
def maintenance_event_delete_api(request, pk):
    """API: Delete a maintenance event."""
    try:
        event = get_object_or_404(MaintenanceEvent, pk=pk)
        AuditLog.log(
            "delete",
            f"Deleted maintenance event: {event.title}",
            user=request.user,
            request=request,
            module="maintenance",
            stream=event.stream,
        )
        event.delete()
        return JsonResponse({"success": True})
    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"})


@user_passes_test(is_super_admin)
@login_required
@require_POST
def maintenance_event_complete_api(request, pk):
    """API: Mark a maintenance event as completed."""
    try:
        event = get_object_or_404(MaintenanceEvent, pk=pk)
        body = json.loads(request.body)

        event.status = "completed"
        event.completed_at = timezone.now()
        event.completed_by = request.user
        event.completion_notes = body.get("completion_notes", "")
        event.actual_duration_hours = body.get("actual_duration_hours") or None
        event.actual_cost = body.get("actual_cost") or None
        event.save()

        AuditLog.log(
            "update",
            f"Completed maintenance event: {event.title}",
            user=request.user,
            request=request,
            obj=event,
            module="maintenance",
            stream=event.stream,
        )
        return JsonResponse({"success": True, "event": event.to_calendar_event()})
    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"})


# =============================================================================
# FEATURE HUB — Dedicated page for selecting streams per feature
# =============================================================================
