"""Products app - Calibration, Compliance, Regulatory, and Alert views."""

# pylint: disable=too-many-lines,broad-exception-caught

from ._helpers import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    ALLOWED_DOCUMENT_TYPES,
    MAX_DOCUMENT_SIZE,
    AuditLog,
    BuildServer,
    CalibrationCertificate,
    CalibrationRecord,
    CalibrationSchedule,
    Notification,
    Paginator,
    Product,
    Q,
    RegulatoryRequirement,
    System,
    SystemAllocation,
    User,
    check_user_access,
    date,
    datetime,
    get_object_or_404,
    get_stream_or_404,
    login_required,
    messages,
    redirect,
    render,
    timedelta,
    validate_uploaded_file,
)
from ..approval_triggers import check_approval_required, fire_approval_trigger

__all__ = [
    "calibration_dashboard",
    "calibration_schedule_list",
    "calibration_schedule_create",
    "calibration_schedule_detail",
    "calibration_schedule_edit",
    "calibration_schedule_delete",
    "calibration_record_complete",
    "calibration_record_create",
    "calibration_records_list",
]


@login_required
def calibration_dashboard(request, stream=None):
    # pylint: disable=too-many-locals
    """Main dashboard for calibration management."""
    stream_obj = get_stream_or_404(stream)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        messages.error(request, error_message)
        return redirect("dashboard")

    today = date.today()
    # Capture items that will transition to overdue
    _newly_overdue_ids = list(
        CalibrationSchedule.objects.filter(
            stream=stream_obj, next_calibration_date__lt=today, status__in=["scheduled", "due"]
        ).values_list("id", flat=True)
    )
    CalibrationSchedule.objects.filter(
        stream=stream_obj, next_calibration_date__lt=today, status__in=["scheduled", "due"]
    ).update(status="overdue")

    # Fire audit triggers for newly-overdue items
    if _newly_overdue_ids:
        for _sched in CalibrationSchedule.objects.filter(id__in=_newly_overdue_ids):
            fire_approval_trigger(
                "calibration_overdue",
                stream_obj.business_unit,
                request.user,
                entity_obj=_sched,
                stream=stream_obj,
                title=f"Calibration '{_sched}' is overdue",
                description=f"Calibration schedule {_sched.pk} became overdue (due date: {_sched.next_calibration_date})",
            )

    overdue = CalibrationSchedule.objects.filter(stream=stream_obj, status="overdue")
    due_soon = CalibrationSchedule.objects.filter(
        stream=stream_obj, status="scheduled", next_calibration_date__lte=today + timedelta(days=30)
    )
    upcoming = CalibrationSchedule.objects.filter(
        stream=stream_obj, status="scheduled", next_calibration_date__gt=today + timedelta(days=30)
    )

    recent_records = (
        CalibrationRecord.objects.filter(calibration_schedule__stream=stream_obj)
        .select_related("calibration_schedule")
        .order_by("-calibration_date")[:10]
    )

    expiring_certificates = CalibrationCertificate.objects.filter(
        calibration_record__calibration_schedule__stream=stream_obj, expiry_date__lte=today + timedelta(days=60)
    ).order_by("expiry_date")[:10]

    due_this_week = CalibrationSchedule.objects.filter(
        stream=stream_obj, status="scheduled", next_calibration_date__lte=today + timedelta(days=7)
    )

    on_schedule = CalibrationSchedule.objects.filter(
        stream=stream_obj, status="scheduled", next_calibration_date__gt=today + timedelta(days=30)
    )

    stats = {
        "total_schedules": CalibrationSchedule.objects.filter(stream=stream_obj).count(),
        "overdue_count": overdue.count(),
        "overdue": overdue.count(),
        "due_soon_count": due_soon.count(),
        "due_this_week": due_this_week.count(),
        "completed_this_month": CalibrationRecord.objects.filter(
            calibration_schedule__stream=stream_obj,
            calibration_date__month=today.month,
            calibration_date__year=today.year,
        ).count(),
    }

    chart_data = {
        "on_schedule": on_schedule.count(),
        "due_soon": due_soon.count(),
        "overdue": overdue.count(),
    }

    # Calibration alerts (overdue items as alerts)
    alerts = []
    for cal in overdue[:5]:
        alerts.append(
            {
                "id": cal.id,
                "severity": "critical",
                "title": f"Overdue: {cal.title}",
                "message": f"Calibration was due on {cal.next_calibration_date}",
                "created_at": cal.next_calibration_date,
            }
        )
    for cal in due_soon[:5]:
        alerts.append(
            {
                "id": cal.id,
                "severity": "warning",
                "title": f"Due Soon: {cal.title}",
                "message": f"Calibration due on {cal.next_calibration_date}",
                "created_at": cal.next_calibration_date,
            }
        )

    context = {
        "overdue": overdue.select_related("product", "system", "build_server"),
        "due_soon": due_soon.select_related("product", "system", "build_server"),
        "upcoming": upcoming.select_related("product", "system", "build_server")[:10],
        "upcoming_calibrations": upcoming.select_related("product", "system", "build_server")[:10],
        "recent_records": recent_records,
        "expiring_certificates": expiring_certificates,
        "stats": stats,
        "chart_data": chart_data,
        "alerts": alerts,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/calibration_dashboard.html", context)


@login_required
def calibration_schedule_list(request, stream=None):  # noqa: C901, CCR001
    # pylint: disable=too-many-locals,too-many-branches,too-complex
    """List all calibration schedules."""
    stream_obj = get_stream_or_404(stream)

    status_filter = request.GET.get("status", "")
    priority_filter = request.GET.get("priority", "")
    type_filter = request.GET.get("type", "")
    equipment_filter = request.GET.get("equipment", "")
    search_query = request.GET.get("q", "").strip()

    schedules = CalibrationSchedule.objects.filter(stream=stream_obj)

    # Calculate stats before filtering
    today = date.today()
    week_from_now = today + timedelta(days=7)
    month_start = today.replace(day=1)

    total_schedules = schedules.count()
    upcoming_count = schedules.filter(
        next_calibration_date__gte=today, next_calibration_date__lte=week_from_now, status__in=["scheduled", "due"]
    ).count()
    overdue_count = schedules.filter(
        next_calibration_date__lt=today, status__in=["scheduled", "due", "overdue"]
    ).count()
    completed_count = schedules.filter(status="completed", updated_at__gte=month_start).count()

    if status_filter:
        schedules = schedules.filter(status=status_filter)

    if priority_filter:
        schedules = schedules.filter(priority=priority_filter)

    if type_filter:
        schedules = schedules.filter(calibration_type=type_filter)

    if equipment_filter == "product":
        schedules = schedules.filter(product__isnull=False)
    elif equipment_filter == "system":
        schedules = schedules.filter(system__isnull=False)
    elif equipment_filter == "server":
        schedules = schedules.filter(build_server__isnull=False)

    if search_query:
        schedules = schedules.filter(
            Q(title__icontains=search_query)
            | Q(product__name__icontains=search_query)
            | Q(system__name__icontains=search_query)
            | Q(build_server__hostname__icontains=search_query)
        )

    # Add computed properties to schedules
    schedules_list = list(schedules.select_related("product", "system", "build_server", "responsible_person"))
    for schedule in schedules_list:
        # Add equipment name
        if schedule.system:
            schedule.equipment_name = schedule.system.name
            schedule.equipment_id = f"SYS-{schedule.system.id}"
        elif schedule.product:
            schedule.equipment_name = schedule.product.name
            schedule.equipment_id = f"PRD-{schedule.product.id}"
        elif schedule.build_server:
            schedule.equipment_name = schedule.build_server.hostname
            schedule.equipment_id = f"SRV-{schedule.build_server.id}"
        else:
            schedule.equipment_name = "Unknown"
            schedule.equipment_id = None

        # Calculate days until due
        if schedule.next_calibration_date:
            schedule.days_until_due = (schedule.next_calibration_date - today).days
        else:
            schedule.days_until_due = None

        # Set assigned_to from responsible_person if not set
        if not hasattr(schedule, "assigned_to") or not schedule.assigned_to:
            schedule.assigned_to = schedule.responsible_person

    context = {
        "schedules": schedules_list,
        "stream": stream,
        "selected_stream": stream,
        "status_filter": status_filter,
        "priority_filter": priority_filter,
        "type_filter": type_filter,
        "equipment_filter": equipment_filter,
        "search_query": search_query,
        "status_choices": CalibrationSchedule.STATUS_CHOICES,
        "type_choices": CalibrationSchedule.CALIBRATION_TYPES,
        "total_schedules": total_schedules,
        "upcoming_count": upcoming_count,
        "overdue_count": overdue_count,
        "completed_count": completed_count,
    }
    return render(request, "products/calibration_schedule_list.html", context)


@login_required
def calibration_schedule_create(request, stream=None):  # noqa: C901, CCR001
    # pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-complex
    """Create a new calibration schedule."""
    stream_obj = get_stream_or_404(stream)

    products = Product.objects.filter(stream=stream_obj)
    systems = System.objects.filter(stream=stream_obj)
    build_servers = BuildServer.objects.filter(stream=stream_obj)
    users = User.objects.filter(is_active=True)
    requirements = RegulatoryRequirement.objects.filter(applicable_streams=stream_obj)

    if request.method == "POST":
        try:
            equipment_type = request.POST.get("equipment_type", "system")
            equipment_id = request.POST.get("equipment_id") or request.POST.get("system")

            # Get the next calibration date - handle different form field names
            next_cal_date = request.POST.get("next_calibration_date") or request.POST.get("next_due_date")
            if not next_cal_date:
                messages.error(request, "Next calibration date is required")
                raise ValueError("Next calibration date is required")

            # Convert frequency to interval
            frequency = request.POST.get("frequency", "monthly")
            interval_map = {
                "weekly": (1, "weeks"),
                "monthly": (1, "months"),
                "quarterly": (3, "months"),
                "biannual": (6, "months"),
                "annual": (1, "years"),
            }
            cal_interval, interval_unit = interval_map.get(frequency, (1, "months"))

            schedule = CalibrationSchedule(
                stream=stream_obj,
                title=request.POST.get("title", "").strip() or f"Calibration for {equipment_type}",
                description=request.POST.get("description", "").strip(),
                calibration_type=request.POST.get("calibration_type", "periodic"),
                parameters=request.POST.get("parameters", "").strip() or request.POST.get("tolerance", "").strip(),
                procedures=request.POST.get("procedures", "").strip()
                or request.POST.get("calibration_procedure", "").strip(),
                equipment_required=request.POST.get("equipment_required", "").strip(),
                calibration_interval=cal_interval,
                interval_unit=interval_unit,
                last_calibration_date=request.POST.get("last_calibration_date") or None,
                next_calibration_date=next_cal_date,
                reminder_days_before=int(
                    request.POST.get("reminder_days", 30) or request.POST.get("reminder_days_before", 30)
                ),
                priority=request.POST.get("priority", "normal"),
                service_provider=request.POST.get("service_provider", "").strip(),
                service_provider_contact=request.POST.get("service_provider_contact", "").strip(),
                estimated_cost=request.POST.get("estimated_cost") or None,
                responsible_person_id=request.POST.get("responsible_person") or None,
                backup_person_id=request.POST.get("backup_person") or None,
                regulatory_requirement_id=request.POST.get("regulatory_requirement") or None,
                notify_responsible=request.POST.get("notify_responsible") == "on"
                or request.POST.get("email_notifications") == "on",
                notify_lab_incharge=request.POST.get("notify_lab_incharge") == "on",
                escalate_if_overdue=request.POST.get("escalate_if_overdue") == "on",
                escalation_days=int(request.POST.get("escalation_days", 7)),
                notes=request.POST.get("notes", "").strip() or request.POST.get("regulatory_standard", "").strip(),
                created_by=request.user,
            )

            # Set equipment association
            if equipment_type == "product" and equipment_id:
                schedule.product_id = equipment_id
            elif (equipment_type == "system" or not equipment_type) and equipment_id:
                schedule.system_id = equipment_id
            elif equipment_type == "server" and equipment_id:
                schedule.build_server_id = equipment_id

            # Check if we should block the system on calibration date - VALIDATE FIRST
            block_system = request.POST.get("block_system") == "on"
            if block_system and schedule.system_id and schedule.next_calibration_date:
                # Get the system name for validation
                system_obj = System.objects.get(id=schedule.system_id)

                # Ensure we have a date object
                cal_date = schedule.next_calibration_date
                if isinstance(cal_date, str):
                    cal_date = datetime.strptime(cal_date, "%Y-%m-%d").date()

                # Check if allocation already exists for this system on this date
                existing = SystemAllocation.objects.filter(
                    stream=stream_obj, system_type=system_obj.name, start_date__date=cal_date
                ).exists()

                if existing:
                    # Don't save the schedule, re-render the form
                    context = {
                        "products": products,
                        "systems": systems,
                        "build_servers": build_servers,
                        "users": users,
                        "requirements": requirements,
                        "stream": stream,
                        "selected_stream": stream,
                        "calibration_types": CalibrationSchedule.CALIBRATION_TYPES,
                        "interval_units": CalibrationSchedule.INTERVAL_UNITS,
                        "priority_choices": CalibrationSchedule.PRIORITY_CHOICES,
                        "form_error": (
                            f'Cannot create schedule: System "{system_obj.name}" is already blocked on '
                            f'{cal_date}. Please choose a different date or uncheck "Block System".'
                        ),
                    }
                    return render(request, "products/calibration_schedule_form.html", context)

            # Now save the schedule (only if validation passed)
            schedule.save()

            # Create the system allocation to block the system (if requested and validation passed)
            if block_system and schedule.system and schedule.next_calibration_date:
                # Ensure we have a date object
                cal_date = schedule.next_calibration_date
                if isinstance(cal_date, str):
                    cal_date = datetime.strptime(cal_date, "%Y-%m-%d").date()

                # Convert date to datetime for SystemAllocation (which uses DateTimeField)
                start_datetime = datetime.combine(cal_date, datetime.strptime("09:00", "%H:%M").time())
                end_datetime = datetime.combine(cal_date, datetime.strptime("17:00", "%H:%M").time())

                allocation = SystemAllocation.objects.create(
                    stream=stream_obj,
                    system_type=schedule.system.name,
                    user=request.user,
                    start_date=start_datetime,
                    end_date=end_datetime,
                )
                # Link allocation to the schedule in notes
                schedule.notes = (schedule.notes or "") + f"\n[System Allocation ID: {allocation.id} - CALIBRATION]"
                schedule.save()
                messages.info(
                    request, f'System "{schedule.system.name}" has been blocked on {cal_date} for calibration.'
                )

            AuditLog.log(
                "create",
                f"Created calibration schedule: {schedule.title}",
                request=request,
                obj=schedule,
                module="calibration",
                severity="info",
                stream=stream_obj,
            )

            messages.success(request, f'Calibration schedule "{schedule.title}" created successfully!')
            notify_targets = []
            if (
                hasattr(schedule, "responsible_person")
                and schedule.responsible_person
                and schedule.responsible_person != request.user
            ):
                notify_targets.append(schedule.responsible_person)
            if hasattr(schedule, "backup_person") and schedule.backup_person and schedule.backup_person != request.user:
                notify_targets.append(schedule.backup_person)
            if notify_targets:
                Notification.notify(
                    notify_targets, f"Calibration schedule '{schedule.title}' has been assigned to you.", "calibration"
                )
            return redirect("calibration_schedule_list", stream=stream)

        except Exception:
            form_error = "An error occurred. Please try again."
    else:
        form_error = None

    context = {
        "products": products,
        "systems": systems,
        "build_servers": build_servers,
        "users": users,
        "requirements": requirements,
        "stream": stream,
        "selected_stream": stream,
        "calibration_types": CalibrationSchedule.CALIBRATION_TYPES,
        "interval_units": CalibrationSchedule.INTERVAL_UNITS,
        "priority_choices": CalibrationSchedule.PRIORITY_CHOICES,
        "form_error": form_error,
    }
    return render(request, "products/calibration_schedule_form.html", context)


@login_required
def calibration_schedule_detail(request, stream=None, pk=None):
    """View calibration schedule details."""
    stream_obj = get_stream_or_404(stream)
    schedule = get_object_or_404(CalibrationSchedule, pk=pk, stream=stream_obj)

    # Add computed property for template
    if schedule.next_calibration_date:
        schedule.days_until_due = (schedule.next_calibration_date - date.today()).days
    else:
        schedule.days_until_due = None

    records = schedule.records.order_by("-calibration_date")
    certificates = CalibrationCertificate.objects.filter(calibration_record__calibration_schedule=schedule).order_by(
        "-expiry_date"
    )

    context = {
        "schedule": schedule,
        "records": records,
        "certificates": certificates,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/calibration_schedule_detail.html", context)


@login_required
def calibration_schedule_edit(request, stream=None, pk=None):  # noqa: CCR001
    # pylint: disable=too-many-statements
    """Edit a calibration schedule."""
    stream_obj = get_stream_or_404(stream)
    schedule = get_object_or_404(CalibrationSchedule, pk=pk, stream=stream_obj)

    products = Product.objects.filter(stream=stream_obj)
    systems = System.objects.filter(stream=stream_obj)
    build_servers = BuildServer.objects.filter(stream=stream_obj)
    users = User.objects.filter(is_active=True)
    requirements = RegulatoryRequirement.objects.filter(applicable_streams=stream_obj)

    if request.method == "POST":
        try:
            _old_cal_status = schedule.status
            equipment_type = request.POST.get("equipment_type")
            equipment_id = request.POST.get("equipment_id")

            schedule.title = request.POST.get("title", "").strip()
            schedule.description = request.POST.get("description", "").strip()
            schedule.calibration_type = request.POST.get("calibration_type")
            schedule.parameters = request.POST.get("parameters", "").strip()
            schedule.procedures = request.POST.get("procedures", "").strip()
            schedule.equipment_required = request.POST.get("equipment_required", "").strip()
            schedule.calibration_interval = int(request.POST.get("calibration_interval", 12))
            schedule.interval_unit = request.POST.get("interval_unit", "months")
            schedule.next_calibration_date = request.POST.get("next_calibration_date")
            schedule.reminder_days_before = int(request.POST.get("reminder_days_before", 30))
            schedule.priority = request.POST.get("priority", "normal")
            _requested_cal_status = request.POST.get("status", "scheduled")

            # ── Pre-action enforcement: block waiver/cancellation if approval required ──
            _cal_approval = None
            if _old_cal_status != _requested_cal_status:
                if _requested_cal_status == "deferred":
                    _cal_approval = check_approval_required(
                        "calibration_waiver",
                        stream_obj.business_unit,
                        request.user,
                        entity_obj=schedule,
                        stream=stream_obj,
                        title=f"Calibration '{schedule.title}' deferred (waiver)",
                        description=f"Calibration schedule '{schedule.title}' deferred from '{_old_cal_status}' by {request.user.username}",
                        intended_changes={
                            "action_type": "status_change",
                            "model_label": "products.CalibrationSchedule",
                            "pk": schedule.pk,
                            "changes": {"status": "deferred"},
                            "revert": {"status": _old_cal_status},
                            "metadata": {"entity_name": schedule.title, "stream_name": stream},
                        },
                    )
                elif _requested_cal_status == "cancelled":
                    _cal_approval = check_approval_required(
                        "calibration_cancelled",
                        stream_obj.business_unit,
                        request.user,
                        entity_obj=schedule,
                        stream=stream_obj,
                        title=f"Calibration '{schedule.title}' cancelled",
                        description=f"Calibration schedule '{schedule.title}' cancelled from '{_old_cal_status}' by {request.user.username}",
                        intended_changes={
                            "action_type": "status_change",
                            "model_label": "products.CalibrationSchedule",
                            "pk": schedule.pk,
                            "changes": {"status": "cancelled"},
                            "revert": {"status": _old_cal_status},
                            "metadata": {"entity_name": schedule.title, "stream_name": stream},
                        },
                    )

            schedule.status = _old_cal_status if _cal_approval else _requested_cal_status

            schedule.service_provider = request.POST.get("service_provider", "").strip()
            schedule.service_provider_contact = request.POST.get("service_provider_contact", "").strip()
            schedule.estimated_cost = request.POST.get("estimated_cost") or None
            schedule.responsible_person_id = request.POST.get("responsible_person") or None
            schedule.backup_person_id = request.POST.get("backup_person") or None
            schedule.regulatory_requirement_id = request.POST.get("regulatory_requirement") or None
            schedule.notify_responsible = request.POST.get("notify_responsible") == "on"
            schedule.notify_lab_incharge = request.POST.get("notify_lab_incharge") == "on"
            schedule.escalate_if_overdue = request.POST.get("escalate_if_overdue") == "on"
            schedule.escalation_days = int(request.POST.get("escalation_days", 7))
            schedule.notes = request.POST.get("notes", "").strip()

            # Clear and reset equipment association
            schedule.product = None
            schedule.system = None
            schedule.build_server = None

            if equipment_type == "product" and equipment_id:
                schedule.product_id = equipment_id
            elif equipment_type == "system" and equipment_id:
                schedule.system_id = equipment_id
            elif equipment_type == "server" and equipment_id:
                schedule.build_server_id = equipment_id

            schedule.save()

            AuditLog.log(
                "update",
                f"Updated calibration schedule: {schedule.title}",
                request=request,
                obj=schedule,
                module="calibration",
                severity="info",
                stream=stream_obj,
            )

            messages.success(request, f'Calibration schedule "{schedule.title}" updated successfully!')

            # ── Notify if waiver/cancellation was blocked by approval ──
            if _cal_approval:
                messages.warning(
                    request,
                    f'\u23f3 Status change to "{_requested_cal_status}" requires approval. '
                    f'Request #{_cal_approval.id} submitted.',
                )

            return redirect("calibration_schedule_detail", stream=stream, pk=pk)

        except Exception:
            messages.error(request, "An error occurred. Please try again.")

    # Determine current equipment type
    current_equipment_type = ""
    current_equipment_id = ""
    if schedule.product:
        current_equipment_type = "product"
        current_equipment_id = schedule.product.id
    elif schedule.system:
        current_equipment_type = "system"
        current_equipment_id = schedule.system.id
    elif schedule.build_server:
        current_equipment_type = "server"
        current_equipment_id = schedule.build_server.id

    context = {
        "schedule": schedule,
        "products": products,
        "systems": systems,
        "build_servers": build_servers,
        "users": users,
        "requirements": requirements,
        "stream": stream,
        "selected_stream": stream,
        "calibration_types": CalibrationSchedule.CALIBRATION_TYPES,
        "interval_units": CalibrationSchedule.INTERVAL_UNITS,
        "priority_choices": CalibrationSchedule.PRIORITY_CHOICES,
        "status_choices": CalibrationSchedule.STATUS_CHOICES,
        "current_equipment_type": current_equipment_type,
        "current_equipment_id": current_equipment_id,
        "is_edit": True,
    }
    return render(request, "products/calibration_schedule_form.html", context)


@login_required
def calibration_schedule_delete(request, stream=None, pk=None):
    """Delete a calibration schedule."""
    stream_obj = get_stream_or_404(stream)
    schedule = get_object_or_404(CalibrationSchedule, pk=pk, stream=stream_obj)

    if request.method == "POST":
        title = schedule.title
        AuditLog.log(
            "delete",
            f"Deleted calibration schedule: {schedule.title}",
            request=request,
            obj=schedule,
            module="calibration",
            severity="warning",
            stream=stream_obj,
        )
        schedule.delete()
        messages.success(request, f'Calibration schedule "{title}" deleted successfully!')
        return redirect("calibration_schedule_list", stream=stream)

    context = {
        "schedule": schedule,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/calibration_schedule_confirm_delete.html", context)


@login_required
def calibration_record_complete(request, stream=None, pk=None):
    """Mark a calibration schedule as completed."""
    stream_obj = get_stream_or_404(stream)
    schedule = get_object_or_404(CalibrationSchedule, pk=pk, stream=stream_obj)

    if request.method == "POST":
        try:
            schedule.status = "completed"
            schedule.last_calibration_date = date.today()
            schedule.save()

            CalibrationRecord.objects.create(
                calibration_schedule=schedule,
                calibration_date=date.today(),
                performed_by=request.user.get_full_name() or request.user.username,
                performed_by_user=request.user,
                result="pass",
                result_details="Marked as complete via quick action",
            )

            AuditLog.log(
                "calibration",
                f"Completed calibration: {schedule.title}",
                request=request,
                obj=schedule,
                module="calibration",
                severity="info",
                stream=stream_obj,
            )

            messages.success(request, f'Calibration schedule "{schedule.title}" marked as completed!')
        except Exception:
            messages.error(request, "An error occurred. Please try again.")

    return redirect("calibration_schedule_detail", stream=stream, pk=pk)


@login_required
def calibration_record_create(request, stream=None, schedule_id=None):  # noqa: CCR001
    """Record a completed calibration."""
    stream_obj = get_stream_or_404(stream)
    schedule = get_object_or_404(CalibrationSchedule, pk=schedule_id, stream=stream_obj)

    if request.method == "POST":
        try:
            calibration_date_str = request.POST.get("calibration_date")
            calibration_date = (
                datetime.strptime(calibration_date_str, "%Y-%m-%d").date() if calibration_date_str else None
            )

            record = CalibrationRecord.objects.create(
                calibration_schedule=schedule,
                calibration_date=calibration_date,
                performed_by=request.POST.get("performed_by", "").strip(),
                performed_by_user=request.user,
                result=request.POST.get("result"),
                result_details=request.POST.get("result_details", "").strip(),
                before_values=request.POST.get("before_values", "").strip(),
                after_values=request.POST.get("after_values", "").strip(),
                adjustments_made=request.POST.get("adjustments_made", "").strip(),
                equipment_condition=request.POST.get("equipment_condition", "").strip(),
                issues_found=request.POST.get("issues_found", "").strip(),
                recommendations=request.POST.get("recommendations", "").strip(),
                actual_cost=request.POST.get("actual_cost") or None,
                labor_hours=request.POST.get("labor_hours") or None,
                duration_minutes=request.POST.get("duration_minutes") or None,
                temperature=request.POST.get("temperature") or None,
                humidity=request.POST.get("humidity") or None,
                notes=request.POST.get("notes", "").strip(),
            )

            schedule.last_calibration_date = record.calibration_date
            schedule.next_calibration_date = schedule.calculate_next_due_date()
            schedule.status = "scheduled"
            schedule.save()

            if "certificate_file" in request.FILES:
                cert_file = request.FILES["certificate_file"]
                is_valid, error_msg = validate_uploaded_file(
                    cert_file, ALLOWED_DOCUMENT_TYPES, ALLOWED_DOCUMENT_EXTENSIONS, MAX_DOCUMENT_SIZE
                )
                if not is_valid:
                    messages.error(request, f"Certificate file: {error_msg}")
                    return redirect("calibration_schedule_detail", stream=stream, pk=schedule_id)
                CalibrationCertificate.objects.create(
                    calibration_record=record,
                    certificate_number=request.POST.get("certificate_number", "").strip(),
                    certificate_file=cert_file,
                    original_filename=cert_file.name,
                    issued_by=request.POST.get("issued_by", "").strip(),
                    issuing_organization=request.POST.get("issuing_organization", "").strip(),
                    accreditation_number=request.POST.get("accreditation_number", "").strip(),
                    issue_date=request.POST.get("cert_issue_date"),
                    expiry_date=request.POST.get("cert_expiry_date"),
                    scope=request.POST.get("cert_scope", "").strip(),
                    traceability_info=request.POST.get("traceability_info", "").strip(),
                    uploaded_by=request.user,
                )

            messages.success(request, "Calibration record created successfully!")
            return redirect("calibration_schedule_detail", stream=stream, pk=schedule_id)

        except Exception:
            form_error = "An error occurred. Please try again."
    else:
        form_error = None

    context = {
        "schedule": schedule,
        "stream": stream,
        "selected_stream": stream,
        "result_choices": CalibrationRecord.RESULT_CHOICES,
        "form_error": form_error,
    }
    return render(request, "products/calibration_record_form.html", context)


@login_required
def calibration_records_list(request, stream=None):
    # pylint: disable=too-many-locals
    """List all calibration records for a stream."""
    stream_obj = get_stream_or_404(stream)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        messages.error(request, error_message)
        return redirect("dashboard")

    result_filter = request.GET.get("result", "")
    search_query = request.GET.get("q", "").strip()
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")

    records = (
        CalibrationRecord.objects.filter(calibration_schedule__stream=stream_obj)
        .select_related("calibration_schedule", "performed_by_user")
        .order_by("-calibration_date")
    )

    if result_filter:
        records = records.filter(result=result_filter)

    if search_query:
        records = records.filter(
            Q(calibration_schedule__equipment_name__icontains=search_query)
            | Q(calibration_schedule__equipment_id__icontains=search_query)
            | Q(notes__icontains=search_query)
        )

    if date_from:
        try:
            records = records.filter(calibration_date__gte=date_from)
        except Exception:
            pass

    if date_to:
        try:
            records = records.filter(calibration_date__lte=date_to)
        except Exception:
            pass

    total_records = records.count()
    passed_count = records.filter(result="pass").count()
    failed_count = records.filter(result="fail").count()
    adjusted_count = records.filter(result="adjusted").count()

    paginator = Paginator(records, 20)
    page = request.GET.get("page", 1)
    records_page = paginator.get_page(page)

    context = {
        "stream": stream,
        "selected_stream": stream,
        "records": records_page,
        "total_records": total_records,
        "passed_count": passed_count,
        "failed_count": failed_count,
        "adjusted_count": adjusted_count,
        "result_filter": result_filter,
        "search_query": search_query,
        "date_from": date_from,
        "date_to": date_to,
        "result_choices": CalibrationRecord.RESULT_CHOICES,
    }
    return render(request, "products/calibration_records_list.html", context)


# Compliance Document Views
