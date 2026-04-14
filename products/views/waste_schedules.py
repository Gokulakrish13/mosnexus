"""Products app - Waste Schedules, Stats, and Export views."""

# pylint: disable=broad-exception-caught,invalid-name

from ._helpers import (
    AuditLog,
    Count,
    HttpResponse,
    JsonResponse,
    Stream,
    Sum,
    TruncMonth,
    WasteAuditLog,
    WasteCategory,
    WasteDisposalSchedule,
    WasteRecord,
    can_access_waste,
    date,
    get_column_letter,
    get_current_bu,
    json,
    logger,
    login_required,
    openpyxl,
    redirect,
    timedelta,
)

__all__ = [
    "waste_schedule_create",
    "waste_schedule_update",
    "waste_schedule_delete",
    "waste_schedule_detail_api",
    "waste_schedule_assign",
    "waste_stats_api",
    "waste_export",
]


@login_required
def waste_schedule_create(request):
    """Create a disposal schedule (AJAX POST)."""
    if not can_access_waste(request.user):
        return JsonResponse({"success": False, "error": "Access denied"}, status=403)
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)

    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    try:
        data = json.loads(request.body) if request.content_type == "application/json" else request.POST
        stream = None
        if data.get("stream"):
            stream = Stream.objects.get(name=data["stream"], business_unit=bu)

        category = None
        if data.get("category"):
            category = WasteCategory.objects.get(pk=data["category"], business_unit=bu)

        sched = WasteDisposalSchedule.objects.create(
            business_unit=bu,
            stream=stream,
            category=category,
            vendor=data.get("vendor", ""),
            scheduled_date=data.get("scheduled_date"),
            scheduled_time=data.get("scheduled_time") or None,
            frequency=data.get("frequency", "one_time"),
            contact_name=data.get("contact_name", ""),
            contact_phone=data.get("contact_phone", ""),
            notes=data.get("notes", ""),
            created_by=request.user,
        )

        # Link waste records if provided
        record_ids = data.get("waste_record_ids", [])
        if record_ids:
            records = WasteRecord.objects.filter(pk__in=record_ids, business_unit=bu)
            sched.waste_records.set(records)
            records.update(status="scheduled")

        WasteAuditLog.objects.create(
            schedule=sched,
            action="schedule_created",
            details=f"Disposal schedule created with {sched.vendor} on {sched.scheduled_date}",
            performed_by=request.user,
        )

        return JsonResponse(
            {
                "success": True,
                "id": sched.pk,
                "message": f"Disposal schedule created for {sched.scheduled_date}.",
            }
        )
    except Exception:
        logger.error("Waste schedule creation error")
        return JsonResponse({"success": False, "error": "An unexpected error occurred. Please try again."}, status=500)


@login_required
def waste_schedule_update(request, pk):
    """Update disposal schedule status."""
    if not can_access_waste(request.user):
        return JsonResponse({"success": False, "error": "Access denied"}, status=403)
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)

    bu = get_current_bu(request)
    try:
        sched = WasteDisposalSchedule.objects.get(pk=pk, business_unit=bu)
        data = json.loads(request.body) if request.content_type == "application/json" else request.POST

        new_status = data.get("status")
        if new_status and new_status != sched.status:
            old = sched.get_status_display()
            sched.status = new_status
            sched.save()

            # If completed, mark linked records as collected
            if new_status == "completed":
                sched.waste_records.exclude(status="disposed").update(status="collected")
                WasteAuditLog.objects.create(
                    schedule=sched,
                    action="schedule_completed",
                    details=f"Schedule completed — {sched.waste_records.count()} records collected",
                    performed_by=request.user,
                )
            else:
                WasteAuditLog.objects.create(
                    schedule=sched,
                    action="updated",
                    details=f"Status: '{old}' → '{sched.get_status_display()}'",
                    performed_by=request.user,
                )

        return JsonResponse({"success": True, "message": "Schedule updated."})
    except WasteDisposalSchedule.DoesNotExist:
        return JsonResponse({"success": False, "error": "Schedule not found"}, status=404)


@login_required
def waste_schedule_delete(request, pk):
    """Delete a disposal schedule."""
    if not can_access_waste(request.user):
        return JsonResponse({"success": False, "error": "Access denied"}, status=403)
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)
    bu = get_current_bu(request)
    try:
        sched = WasteDisposalSchedule.objects.get(pk=pk, business_unit=bu)
        AuditLog.log(
            "delete",
            f"Deleted waste disposal schedule (ID: {sched.pk}, date: {sched.scheduled_date})",
            user=request.user,
            request=request,
            module="other",
            severity="warning",
        )
        sched.delete()
        return JsonResponse({"success": True, "message": "Schedule deleted."})
    except WasteDisposalSchedule.DoesNotExist:
        return JsonResponse({"success": False, "error": "Schedule not found"}, status=404)


@login_required
def waste_schedule_detail_api(request, pk):
    """Return full schedule details with linked waste records."""
    if not can_access_waste(request.user):
        return JsonResponse({"success": False, "error": "Access denied"}, status=403)
    bu = get_current_bu(request)
    try:
        sched = WasteDisposalSchedule.objects.select_related("stream", "category", "created_by").get(
            pk=pk, business_unit=bu
        )

        linked = list(sched.waste_records.select_related("category", "stream").order_by("-generated_date"))
        linked_data = [
            {
                "id": r.pk,
                "tracking_number": r.tracking_number,
                "category_name": r.category.name,
                "category_color": r.category.color,
                "stream": r.stream.name,
                "quantity": str(r.quantity),
                "unit_display": r.get_unit_display(),
                "status": r.status,
                "status_display": r.get_status_display(),
                "generated_date": r.generated_date.isoformat() if r.generated_date else "",
                "is_overdue": r.is_overdue,
            }
            for r in linked
        ]

        # Eligible (unassigned) records that could be linked to this schedule
        eligible_qs = (
            WasteRecord.objects.filter(
                business_unit=bu,
                status__in=["generated", "stored"],
            )
            .exclude(disposal_schedules__isnull=False)
            .select_related("category", "stream")
            .order_by("-generated_date")
        )
        if sched.stream:
            eligible_qs = eligible_qs.filter(stream=sched.stream)
        if sched.category:
            eligible_qs = eligible_qs.filter(category=sched.category)

        eligible_data = [
            {
                "id": r.pk,
                "tracking_number": r.tracking_number,
                "category_name": r.category.name,
                "category_color": r.category.color,
                "stream": r.stream.name,
                "quantity": str(r.quantity),
                "unit_display": r.get_unit_display(),
                "status_display": r.get_status_display(),
                "generated_date": r.generated_date.isoformat() if r.generated_date else "",
            }
            for r in eligible_qs[:50]
        ]

        return JsonResponse(
            {
                "success": True,
                "schedule": {
                    "id": sched.pk,
                    "vendor": sched.vendor,
                    "scheduled_date": sched.scheduled_date.isoformat(),
                    "scheduled_time": sched.scheduled_time.strftime("%H:%M") if sched.scheduled_time else "",
                    "frequency": sched.frequency,
                    "frequency_display": sched.get_frequency_display(),
                    "status": sched.status,
                    "status_display": sched.get_status_display(),
                    "stream": sched.stream.name if sched.stream else "",
                    "category": sched.category.name if sched.category else "",
                    "contact_name": sched.contact_name,
                    "contact_phone": sched.contact_phone,
                    "notes": sched.notes,
                    "created_by": sched.created_by.username if sched.created_by else "",
                    "created_at": sched.created_at.strftime("%Y-%m-%d %H:%M"),
                    "linked_records": linked_data,
                    "record_count": len(linked_data),
                },
                "eligible_records": eligible_data,
            }
        )
    except WasteDisposalSchedule.DoesNotExist:
        return JsonResponse({"success": False, "error": "Schedule not found"}, status=404)


@login_required
def waste_schedule_assign(request, pk):
    """Assign or unassign waste records to/from a schedule (AJAX POST)."""
    # pylint: disable=too-many-return-statements
    if not can_access_waste(request.user):
        return JsonResponse({"success": False, "error": "Access denied"}, status=403)
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)
    bu = get_current_bu(request)
    try:
        sched = WasteDisposalSchedule.objects.get(pk=pk, business_unit=bu)
        data = json.loads(request.body) if request.content_type == "application/json" else request.POST
        action = data.get("action")  # 'assign' or 'unassign'
        record_ids = data.get("record_ids", [])
        if not record_ids:
            return JsonResponse({"success": False, "error": "No records specified"}, status=400)

        records = WasteRecord.objects.filter(pk__in=record_ids, business_unit=bu)
        if action == "assign":
            sched.waste_records.add(*records)
            records.filter(status__in=["generated", "stored"]).update(status="scheduled")
            msg = f"{records.count()} record(s) assigned to pickup."
        elif action == "unassign":
            sched.waste_records.remove(*records)
            records.filter(status="scheduled").update(status="stored")
            msg = f"{records.count()} record(s) removed from pickup."
        else:
            return JsonResponse({"success": False, "error": "Action must be assign or unassign"}, status=400)

        WasteAuditLog.objects.create(
            schedule=sched,
            action="updated",
            details=f"{action.title()}: {', '.join(r.tracking_number for r in records)} — by {request.user.username}",
            performed_by=request.user,
        )
        return JsonResponse({"success": True, "message": msg, "record_count": sched.waste_records.count()})
    except WasteDisposalSchedule.DoesNotExist:
        return JsonResponse({"success": False, "error": "Schedule not found"}, status=404)
    except Exception:
        logger.error("Waste schedule manage error")
        return JsonResponse({"success": False, "error": "An unexpected error occurred. Please try again."}, status=500)


@login_required
def waste_stats_api(request):
    """Return waste statistics as JSON for dashboard charts."""
    if not can_access_waste(request.user):
        return JsonResponse({"success": False, "error": "Access denied"}, status=403)
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    records = WasteRecord.objects.filter(business_unit=bu)

    # By category
    by_category = list(
        records.values("category__name", "category__color")
        .annotate(
            count=Count("id"),
            total_qty=Sum("quantity"),
        )
        .order_by("-count")
    )

    # By status
    by_status = list(records.values("status").annotate(count=Count("id")).order_by("status"))

    # By stream
    by_stream = list(
        records.values("stream__name")
        .annotate(
            count=Count("id"),
            total_qty=Sum("quantity"),
        )
        .order_by("-count")
    )

    # By hazard level
    by_hazard = list(records.values("category__hazard_level").annotate(count=Count("id")))

    # Monthly trend (last 6 months)
    monthly = list(
        records.filter(generated_date__gte=date.today() - timedelta(days=180))
        .annotate(month=TruncMonth("generated_date"))
        .values("month")
        .annotate(
            count=Count("id"),
            total_qty=Sum("quantity"),
        )
        .order_by("month")
    )

    return JsonResponse(
        {
            "success": True,
            "by_category": by_category,
            "by_status": by_status,
            "by_stream": by_stream,
            "by_hazard": by_hazard,
            "monthly": [
                {
                    "month": m["month"].strftime("%Y-%m") if m["month"] else "",
                    "count": m["count"],
                    "total_qty": float(m["total_qty"] or 0),
                }
                for m in monthly
            ],
        }
    )


@login_required
def waste_export(request):  # noqa: CCR001
    """Export waste records to Excel."""
    if not can_access_waste(request.user):
        return redirect("dashboard")
    bu = get_current_bu(request)
    if not bu:
        return redirect("waste_dashboard")

    records = (
        WasteRecord.objects.filter(business_unit=bu)
        .select_related("category", "stream", "source_product", "created_by")
        .order_by("-generated_date")
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Waste Records"
    headers = [
        "Tracking #",
        "Stream",
        "Category",
        "Hazard Level",
        "Description",
        "Quantity",
        "Unit",
        "Weight (kg)",
        "Source",
        "Status",
        "Generated Date",
        "Disposal Deadline",
        "Disposal Date",
        "Disposal Method",
        "Vendor",
        "Cost",
        "Manifest #",
        "Compliant",
        "Notes",
        "Created By",
        "Created At",
    ]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = openpyxl.styles.Font(bold=True)

    for row_idx, r in enumerate(records, 2):
        ws.cell(row=row_idx, column=1, value=r.tracking_number)
        ws.cell(row=row_idx, column=2, value=r.stream.name)
        ws.cell(row=row_idx, column=3, value=r.category.name)
        ws.cell(row=row_idx, column=4, value=r.category.get_hazard_level_display())
        ws.cell(row=row_idx, column=5, value=r.description)
        ws.cell(row=row_idx, column=6, value=float(r.quantity))
        ws.cell(row=row_idx, column=7, value=r.get_unit_display())
        ws.cell(row=row_idx, column=8, value=float(r.weight_kg) if r.weight_kg else "")
        ws.cell(row=row_idx, column=9, value=r.get_source_display())
        ws.cell(row=row_idx, column=10, value=r.get_status_display())
        ws.cell(row=row_idx, column=11, value=r.generated_date.isoformat() if r.generated_date else "")
        ws.cell(row=row_idx, column=12, value=r.disposal_deadline.isoformat() if r.disposal_deadline else "")
        ws.cell(row=row_idx, column=13, value=r.disposal_date.isoformat() if r.disposal_date else "")
        ws.cell(row=row_idx, column=14, value=r.disposal_method)
        ws.cell(row=row_idx, column=15, value=r.disposal_vendor)
        ws.cell(row=row_idx, column=16, value=float(r.disposal_cost) if r.disposal_cost else "")
        ws.cell(row=row_idx, column=17, value=r.manifest_number)
        ws.cell(row=row_idx, column=18, value="Yes" if r.is_compliant else "No")
        ws.cell(row=row_idx, column=19, value=r.notes)
        ws.cell(row=row_idx, column=20, value=r.created_by.username if r.created_by else "")
        ws.cell(row=row_idx, column=21, value=r.created_at.strftime("%Y-%m-%d %H:%M"))

    # Autofit columns
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 16

    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="waste_records_{bu.slug}_{date.today().isoformat()}.xlsx"'
    wb.save(response)
    return response


# =============================================================================
# VENDOR / SUPPLIER MANAGEMENT
# =============================================================================
