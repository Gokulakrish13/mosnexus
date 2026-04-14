"""Products app — Tld views."""

# pylint: disable=broad-exception-caught,import-error,invalid-name,relative-beyond-top-level

from ..models import CustomUser as CU  # noqa: N817
from ._helpers import (
    HttpResponse,
    JsonResponse,
    Paginator,
    Q,
    Stream,
    TLDBadgeAuditLog,
    TLDBadgeRecord,
    can_access_tld_badges,
    date,
    get_column_letter,
    get_current_bu,
    get_object_or_404,
    is_super_admin,
    json,
    logger,
    login_required,
    messages,
    openpyxl,
    redirect,
    render,
    require_POST,
)

__all__ = [
    "tld_badge_dashboard",
    "tld_badge_create",
    "tld_badge_edit",
    "tld_badge_delete",
    "tld_badge_export",
]


@login_required
def tld_badge_dashboard(request):  # noqa: C901, CCR001
    """TLD Badge Management dashboard with year/quarter/stream filtering and CRUD."""
    # pylint: disable=too-complex,too-many-branches,too-many-locals,too-many-statements
    if not can_access_tld_badges(request.user):
        messages.error(request, "You do not have permission to access TLD Badge Management.")
        return redirect("dashboard")
    bu = get_current_bu(request)
    if not bu:
        return redirect("select_bu")

    current_year = date.today().year

    # Determine current quarter
    current_month = date.today().month
    if current_month <= 3:
        current_quarter = "Q1"
    elif current_month <= 6:
        current_quarter = "Q2"
    elif current_month <= 9:
        current_quarter = "Q3"
    else:
        current_quarter = "Q4"

    # Year & quarter filters – default to current quarter
    year = request.GET.get("year", str(current_year))
    quarter = request.GET.get("quarter", current_quarter)
    search_q = request.GET.get("q", "")
    status_filter = request.GET.get("status", "")
    stream_filter = request.GET.get("stream", "")

    try:
        year = int(year)
    except (ValueError, TypeError):
        year = current_year

    # Available streams for this BU – scoped to user's access
    custom_profile, _ = CU.objects.get_or_create(user=request.user)
    bu_streams = custom_profile.get_accessible_streams(business_unit=bu).filter(is_active=True).order_by("name")
    accessible_stream_ids = list(bu_streams.values_list("id", flat=True))

    # Base queryset scoped to BU + year + user-accessible streams
    records = TLDBadgeRecord.objects.filter(business_unit=bu, year=year, stream_id__in=accessible_stream_ids).order_by(
        "quarter", "name"
    )

    # Stream filter
    if stream_filter:
        records = records.filter(stream__name=stream_filter)
    if quarter:
        records = records.filter(quarter=quarter)
    if status_filter:
        records = records.filter(renewal_status=status_filter)
    if search_q:
        records = records.filter(
            Q(name__icontains=search_q)
            | Q(email__icontains=search_q)
            | Q(tld_number__icontains=search_q)
            | Q(code1_id__icontains=search_q)
            | Q(employee_id__icontains=search_q)
        )

    # Stats – scoped to current quarter + stream + user-accessible streams
    stats_qs = TLDBadgeRecord.objects.filter(
        business_unit=bu, year=year, quarter=current_quarter, stream_id__in=accessible_stream_ids
    )
    if stream_filter:
        stats_qs = stats_qs.filter(stream__name=stream_filter)
    total_badges = stats_qs.count()
    active_badges = stats_qs.filter(renewal_status="active").count()
    pending_renewal = stats_qs.filter(renewal_status="pending").count()
    expired_badges = stats_qs.filter(renewal_status="expired").count()

    # Current quarter display label
    quarter_labels = dict(TLDBadgeRecord.QUARTER_CHOICES)
    current_quarter_label = f"{current_quarter} ({quarter_labels.get(current_quarter, '')})"

    # ── Chart data: status distribution for selected year + filters ──
    chart_base = TLDBadgeRecord.objects.filter(business_unit=bu, year=year, stream_id__in=accessible_stream_ids)
    if stream_filter:
        chart_base = chart_base.filter(stream__name=stream_filter)
    if quarter:
        chart_base = chart_base.filter(quarter=quarter)
    status_dist = {}
    for val, label in TLDBadgeRecord.RENEWAL_STATUS_CHOICES:
        status_dist[val] = {"label": label, "count": chart_base.filter(renewal_status=val).count()}

    # ── Quarter-over-Quarter comparison ──
    qoq_data = []
    for q_val, q_label in TLDBadgeRecord.QUARTER_CHOICES:
        q_qs = TLDBadgeRecord.objects.filter(
            business_unit=bu, year=year, quarter=q_val, stream_id__in=accessible_stream_ids
        )
        if stream_filter:
            q_qs = q_qs.filter(stream__name=stream_filter)
        qoq_data.append(
            {
                "quarter": q_val,
                "label": q_label,
                "total": q_qs.count(),
                "active": q_qs.filter(renewal_status="active").count(),
                "pending": q_qs.filter(renewal_status="pending").count(),
                "expired": q_qs.filter(renewal_status="expired").count(),
            }
        )

    # ── Expiry alert: check if we're within 2 weeks of quarter end ──
    today = date.today()
    quarter_end_dates = {
        "Q1": date(today.year, 3, 31),
        "Q2": date(today.year, 6, 30),
        "Q3": date(today.year, 9, 30),
        "Q4": date(today.year, 12, 31),
    }
    quarter_end = quarter_end_dates.get(current_quarter, today)
    days_to_end = (quarter_end - today).days
    expiry_alert = None
    if 0 <= days_to_end <= 14 and pending_renewal > 0:
        expiry_alert = {
            "days_left": days_to_end,
            "pending_count": pending_renewal,
            "quarter": current_quarter,
        }

    # Available years (existing + surrounding) – scoped to accessible streams
    existing_years = list(
        TLDBadgeRecord.objects.filter(business_unit=bu, stream_id__in=accessible_stream_ids)
        .values_list("year", flat=True)
        .distinct()
        .order_by("year")
    )
    available_years = sorted(set(existing_years + [current_year - 1, current_year, current_year + 1, current_year + 2]))

    paginator = Paginator(records, 25)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    # ── AJAX JSON response ──────────────────────────────────────
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        rows = []
        for r in page_obj:
            rows.append(
                {
                    "pk": r.pk,
                    "name": r.name,
                    "email": r.email,
                    "tld_number": r.tld_number,
                    "stream": r.stream.name if r.stream else "",
                    "code1_id": r.code1_id or "",
                    "employee_id": r.employee_id or "",
                    "quarter": r.get_quarter_display(),
                    "quarter_raw": r.quarter,
                    "year": r.year,
                    "renewal_status": r.renewal_status,
                    "renewal_status_display": r.get_renewal_status_display(),
                    "notes": r.notes or "",
                }
            )
        return JsonResponse(
            {
                "records": rows,
                "stats": {
                    "total": total_badges,
                    "active": active_badges,
                    "pending": pending_renewal,
                    "expired": expired_badges,
                },
                "current_quarter_label": current_quarter_label,
                "chart_data": {
                    "status_distribution": {k: v["count"] for k, v in status_dist.items()},
                    "status_labels": {k: v["label"] for k, v in status_dist.items()},
                },
                "qoq_data": qoq_data,
                "expiry_alert": expiry_alert,
                "pagination": {
                    "has_previous": page_obj.has_previous(),
                    "has_next": page_obj.has_next(),
                    "page": page_obj.number,
                    "num_pages": paginator.num_pages,
                    "total_count": paginator.count,
                    "start_index": page_obj.start_index() if paginator.count else 0,
                    "end_index": page_obj.end_index() if paginator.count else 0,
                },
            }
        )

    context = {
        "records": page_obj,
        "page_obj": page_obj,
        "selected_year": year,
        "selected_quarter": quarter,
        "current_quarter": current_quarter,
        "current_quarter_label": current_quarter_label,
        "search_q": search_q,
        "status_filter": status_filter,
        "stream_filter": stream_filter,
        "bu_streams": bu_streams,
        "available_years": available_years,
        "total_badges": total_badges,
        "active_badges": active_badges,
        "pending_renewal": pending_renewal,
        "expired_badges": expired_badges,
        "quarter_choices": TLDBadgeRecord.QUARTER_CHOICES,
        "status_choices": TLDBadgeRecord.RENEWAL_STATUS_CHOICES,
        "is_super_admin": is_super_admin(request.user),
        "status_dist_json": json.dumps({k: v["count"] for k, v in status_dist.items()}),
        "status_labels_json": json.dumps({k: v["label"] for k, v in status_dist.items()}),
        "qoq_data_json": json.dumps(qoq_data),
        "expiry_alert": expiry_alert,
    }
    return render(request, "products/tld_badge_dashboard.html", context)


@login_required
@require_POST
def tld_badge_create(request):
    """Create a new TLD Badge record via AJAX."""
    # pylint: disable=too-many-return-statements
    if not can_access_tld_badges(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    try:
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip()
        tld_number = request.POST.get("tld_number", "").strip()
        code1_id = request.POST.get("code1_id", "").strip()
        employee_id = request.POST.get("employee_id", "").strip()
        year = int(request.POST.get("year", date.today().year))
        quarter = request.POST.get("quarter", "Q1")
        renewal_status = request.POST.get("renewal_status", "active")
        notes = request.POST.get("notes", "").strip()
        stream_name = request.POST.get("stream", "").strip()

        # Resolve stream
        stream_obj = None
        if stream_name:
            stream_obj = Stream.objects.filter(name=stream_name, business_unit=bu, is_active=True).first()

        if not name or not email or not tld_number:
            return JsonResponse({"success": False, "error": "Name, Email and TLD Number are required."}, status=400)

        if not stream_obj:
            return JsonResponse({"success": False, "error": "Stream is required."}, status=400)

        # Check for duplicate
        if TLDBadgeRecord.objects.filter(
            business_unit=bu, stream=stream_obj, tld_number=tld_number, year=year, quarter=quarter
        ).exists():
            return JsonResponse(
                {"success": False, "error": f"TLD #{tld_number} already exists for {quarter} {year}."}, status=400
            )

        record = TLDBadgeRecord.objects.create(
            business_unit=bu,
            stream=stream_obj,
            year=year,
            quarter=quarter,
            name=name,
            email=email,
            tld_number=tld_number,
            code1_id=code1_id,
            employee_id=employee_id,
            renewal_status=renewal_status,
            notes=notes,
            created_by=request.user,
        )
        # Audit trail
        TLDBadgeAuditLog.objects.create(
            business_unit=bu,
            badge_record=record,
            action="create",
            performed_by=request.user,
            badge_name=name,
            badge_tld_number=tld_number,
            details=f"Created badge for {name} (TLD#{tld_number}) – {quarter} {year}",
        )
        return JsonResponse({"success": True, "id": record.pk, "message": "TLD Badge record created successfully."})
    except Exception:
        logger.error("TLD badge creation error")
        return JsonResponse(
            {"success": False, "error": "An error occurred while creating the badge record."}, status=400
        )


@login_required
@require_POST
def tld_badge_edit(request, pk):  # noqa: C901, CCR001
    """Edit a TLD Badge record via AJAX."""
    # pylint: disable=too-complex
    if not can_access_tld_badges(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    record = get_object_or_404(TLDBadgeRecord, pk=pk, business_unit=bu)
    try:
        old_status = record.renewal_status
        record.name = request.POST.get("name", record.name).strip()
        record.email = request.POST.get("email", record.email).strip()
        record.tld_number = request.POST.get("tld_number", record.tld_number).strip()
        record.code1_id = request.POST.get("code1_id", record.code1_id).strip()
        record.employee_id = request.POST.get("employee_id", record.employee_id).strip()
        record.renewal_status = request.POST.get("renewal_status", record.renewal_status)
        record.notes = request.POST.get("notes", record.notes).strip()

        # Update year, quarter, stream if provided
        year_val = request.POST.get("year", "")
        if year_val:
            try:
                record.year = int(year_val)
            except (ValueError, TypeError):
                pass
        quarter_val = request.POST.get("quarter", "")
        if quarter_val and quarter_val in [c[0] for c in TLDBadgeRecord.QUARTER_CHOICES]:
            record.quarter = quarter_val
        stream_name = request.POST.get("stream", "").strip()
        if stream_name:
            stream_obj = Stream.objects.filter(name=stream_name, business_unit=bu, is_active=True).first()
            if stream_obj:
                record.stream = stream_obj

        record.save()
        # Audit trail
        changes = []
        if old_status != record.renewal_status:
            changes.append(f"Status: {old_status} → {record.renewal_status}")
        TLDBadgeAuditLog.objects.create(
            business_unit=bu,
            badge_record=record,
            action="edit",
            performed_by=request.user,
            badge_name=record.name,
            badge_tld_number=record.tld_number,
            details=f"Edited badge #{pk}. " + ("; ".join(changes) if changes else "Fields updated."),
        )
        return JsonResponse({"success": True, "message": "TLD Badge record updated."})
    except Exception:
        logger.error("TLD badge edit error")
        return JsonResponse(
            {"success": False, "error": "An error occurred while updating the badge record."}, status=400
        )


@login_required
@require_POST
def tld_badge_delete(request, pk):
    """Delete a TLD Badge record via AJAX."""
    if not can_access_tld_badges(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    record = get_object_or_404(TLDBadgeRecord, pk=pk, business_unit=bu)
    # Audit trail before deletion
    TLDBadgeAuditLog.objects.create(
        business_unit=bu,
        badge_record=None,
        action="delete",
        performed_by=request.user,
        badge_name=record.name,
        badge_tld_number=record.tld_number,
        details=f"Deleted badge #{pk} – {record.name} (TLD#{record.tld_number}) {record.get_quarter_display()} {record.year}",  # noqa: E501
    )
    record.delete()
    return JsonResponse({"success": True, "message": "TLD Badge record deleted."})


@login_required
def tld_badge_export(request):
    """Export TLD Badge records to Excel."""
    # pylint: disable=too-many-locals
    if not can_access_tld_badges(request.user):
        return redirect("dashboard")
    bu = get_current_bu(request)
    if not bu:
        return redirect("select_bu")

    year = request.GET.get("year", str(date.today().year))
    quarter = request.GET.get("quarter", "")
    try:
        year = int(year)
    except (ValueError, TypeError):
        year = date.today().year

    records = TLDBadgeRecord.objects.filter(business_unit=bu, year=year).order_by("quarter", "name")

    # Scope to user's accessible streams
    custom_profile, _ = CU.objects.get_or_create(user=request.user)
    user_streams = custom_profile.get_accessible_streams(business_unit=bu).filter(is_active=True)
    records = records.filter(stream__in=user_streams)

    if quarter:
        records = records.filter(quarter=quarter)

    stream_filter = request.GET.get("stream", "")
    if stream_filter:
        records = records.filter(stream__name=stream_filter)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"TLD Badges {year}"
    headers = [
        "ID",
        "Name",
        "Email",
        "TLD Number",
        "CODE1 ID",
        "Employee ID",
        "Year",
        "Quarter",
        "Renewal Status",
        "Notes",
    ]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = openpyxl.styles.Font(bold=True)

    for row, r in enumerate(records, 2):
        ws.cell(row=row, column=1, value=r.pk)
        ws.cell(row=row, column=2, value=r.name)
        ws.cell(row=row, column=3, value=r.email)
        ws.cell(row=row, column=4, value=r.tld_number)
        ws.cell(row=row, column=5, value=r.code1_id)
        ws.cell(row=row, column=6, value=r.employee_id)
        ws.cell(row=row, column=7, value=r.year)
        ws.cell(row=row, column=8, value=r.get_quarter_display())
        ws.cell(row=row, column=9, value=r.get_renewal_status_display())
        ws.cell(row=row, column=10, value=r.notes)

    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 18

    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    q_label = f"_{quarter}" if quarter else ""
    response["Content-Disposition"] = f"attachment; filename=TLD_Badges_{year}{q_label}.xlsx"
    wb.save(response)
    return response


# ─── TLD Bulk Import (CSV / Excel) ───────────────────────────────────────────
