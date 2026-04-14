"""Products app - TLD Badge Import, Bulk Update, Duplicate Check, History, Audit, Print views."""

# pylint: disable=broad-exception-caught,import-error,invalid-name,overlapping-except,relative-beyond-top-level

from ..models import CustomUser as CU_bulk
from ._helpers import (
    ALLOWED_EXCEL_EXTENSIONS,
    ALLOWED_EXCEL_TYPES,
    MAX_EXCEL_SIZE,
    JsonResponse,
    Q,
    Stream,
    TLDBadgeAuditLog,
    TLDBadgeRecord,
    can_access_tld_badges,
    csv,
    date,
    get_current_bu,
    get_object_or_404,
    io,
    json,
    logger,
    login_required,
    openpyxl,
    require_POST,
    validate_uploaded_file,
)

__all__ = [
    "tld_badge_bulk_import",
    "tld_badge_bulk_update",
    "tld_badge_check_duplicate",
    "tld_badge_history",
    "tld_badge_audit_log",
    "tld_badge_print",
]


@login_required
@require_POST
def tld_badge_bulk_import(request):  # noqa: C901, CCR001
    """Bulk import TLD Badge records from CSV or Excel."""
    # pylint: disable=too-complex,too-many-branches,too-many-locals,too-many-return-statements,too-many-statements
    if not can_access_tld_badges(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    upload = request.FILES.get("file")
    if not upload:
        return JsonResponse({"success": False, "error": "No file uploaded."}, status=400)

    # Validate file type and size
    is_valid, error_msg = validate_uploaded_file(upload, ALLOWED_EXCEL_TYPES, ALLOWED_EXCEL_EXTENSIONS, MAX_EXCEL_SIZE)
    if not is_valid:
        return JsonResponse({"success": False, "error": error_msg}, status=400)

    fname = upload.name.lower()
    rows_data = []

    try:
        if fname.endswith((".xlsx", ".xls")):
            wb = openpyxl.load_workbook(upload, read_only=True, data_only=True)
            ws = wb.active
            headers = [str(c.value or "").strip().lower() for c in next(ws.iter_rows(min_row=1, max_row=1))]
            for row in ws.iter_rows(min_row=2, values_only=True):
                rows_data.append(dict(zip(headers, [str(v).strip() if v is not None else "" for v in row])))
        elif fname.endswith(".csv"):
            text = upload.read().decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                rows_data.append({k.strip().lower(): v.strip() for k, v in row.items()})
        else:
            return JsonResponse({"success": False, "error": "Unsupported file format. Use .csv or .xlsx"}, status=400)
    except Exception:
        logger.exception("Error reading TLD badge import file")
        return JsonResponse(
            {"success": False, "error": "Error reading file. Please ensure it is a valid spreadsheet."}, status=400
        )

    if not rows_data:
        return JsonResponse({"success": False, "error": "File is empty."}, status=400)

    created = 0
    skipped = 0
    errors_list = []
    valid_quarters = [c[0] for c in TLDBadgeRecord.QUARTER_CHOICES]
    valid_statuses = [c[0] for c in TLDBadgeRecord.RENEWAL_STATUS_CHOICES]

    for i, row in enumerate(rows_data, start=2):
        name = row.get("name", "")
        email = row.get("email", "")
        tld_number = row.get("tld_number", "") or row.get("tld number", "") or row.get("tld#", "")
        code1_id = row.get("code1_id", "") or row.get("code1 id", "")
        employee_id = row.get("employee_id", "") or row.get("employee id", "")
        year_str = row.get("year", str(date.today().year))
        quarter_val = row.get("quarter", "Q1").upper()
        status = row.get("renewal_status", "") or row.get("status", "") or "active"
        stream_name = row.get("stream", "")
        notes = row.get("notes", "")

        if not name or not email or not tld_number:
            errors_list.append(f"Row {i}: Missing required fields (name/email/tld_number)")
            skipped += 1
            continue

        try:
            year_val = int(year_str)
        except (ValueError, TypeError):
            year_val = date.today().year

        if quarter_val not in valid_quarters:
            quarter_val = "Q1"
        if status not in valid_statuses:
            status = "active"

        stream_obj = None
        if stream_name:
            stream_obj = Stream.objects.filter(name=stream_name, business_unit=bu, is_active=True).first()

        if TLDBadgeRecord.objects.filter(
            business_unit=bu, stream=stream_obj, tld_number=tld_number, year=year_val, quarter=quarter_val
        ).exists():
            skipped += 1
            errors_list.append(f"Row {i}: TLD#{tld_number} already exists for {quarter_val} {year_val}")
            continue

        TLDBadgeRecord.objects.create(
            business_unit=bu,
            stream=stream_obj,
            year=year_val,
            quarter=quarter_val,
            name=name,
            email=email,
            tld_number=tld_number,
            code1_id=code1_id,
            employee_id=employee_id,
            renewal_status=status,
            notes=notes,
            created_by=request.user,
        )
        created += 1

    # Audit trail
    TLDBadgeAuditLog.objects.create(
        business_unit=bu,
        action="bulk_import",
        performed_by=request.user,
        badge_name=f"{created} records",
        badge_tld_number="",
        details=f"Bulk imported {created} records from {upload.name}. Skipped {skipped}.",
    )

    return JsonResponse(
        {
            "success": True,
            "message": f"Imported {created} records. Skipped {skipped} duplicates/errors.",
            "created": created,
            "skipped": skipped,
            "errors": errors_list[:20],
        }
    )


# ─── TLD Bulk Status Update ──────────────────────────────────────────────────


@login_required
@require_POST
def tld_badge_bulk_update(request):
    """Bulk update status of selected TLD Badge records."""
    if not can_access_tld_badges(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    try:
        data = json.loads(request.body)
        pks = data.get("ids", [])
        new_status = data.get("status", "")
    except (json.JSONDecodeError, Exception):
        return JsonResponse({"success": False, "error": "Invalid request data."}, status=400)

    valid_statuses = [c[0] for c in TLDBadgeRecord.RENEWAL_STATUS_CHOICES]
    if new_status not in valid_statuses:
        return JsonResponse({"success": False, "error": f"Invalid status: {new_status}"}, status=400)

    if not pks:
        return JsonResponse({"success": False, "error": "No records selected."}, status=400)

    records = TLDBadgeRecord.objects.filter(pk__in=pks, business_unit=bu)

    # Scope to user's accessible streams
    cp_bulk, _ = CU_bulk.objects.get_or_create(user=request.user)
    user_streams = cp_bulk.get_accessible_streams(business_unit=bu).filter(is_active=True)
    records = records.filter(stream__in=user_streams)

    updated = records.update(renewal_status=new_status)

    # Audit trail
    status_label = dict(TLDBadgeRecord.RENEWAL_STATUS_CHOICES).get(new_status, new_status)
    TLDBadgeAuditLog.objects.create(
        business_unit=bu,
        action="bulk_status",
        performed_by=request.user,
        badge_name=f"{updated} records",
        badge_tld_number="",
        details=f"Bulk status update: {updated} records → {status_label}. IDs: {pks[:50]}",
    )

    return JsonResponse(
        {
            "success": True,
            "message": f'{updated} record(s) updated to "{status_label}".',
            "updated": updated,
        }
    )


# ─── TLD Duplicate Check (AJAX) ──────────────────────────────────────────────


@login_required
def tld_badge_check_duplicate(request):  # noqa: C901, CCR001
    """Check if a TLD number already exists for the given quarter/year/stream."""
    # pylint: disable=too-complex
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"exists": False})

    tld_number = request.GET.get("tld_number", "").strip()
    year = request.GET.get("year", "")
    quarter = request.GET.get("quarter", "")
    stream_name = request.GET.get("stream", "")
    exclude_pk = request.GET.get("exclude_pk", "")

    if not tld_number:
        return JsonResponse({"exists": False})

    stream_obj = None
    if stream_name:
        stream_obj = Stream.objects.filter(name=stream_name, business_unit=bu, is_active=True).first()

    qs = TLDBadgeRecord.objects.filter(
        business_unit=bu,
        tld_number=tld_number,
    )
    if year:
        try:
            qs = qs.filter(year=int(year))
        except ValueError:
            pass
    if quarter:
        qs = qs.filter(quarter=quarter)
    if stream_obj:
        qs = qs.filter(stream=stream_obj)
    else:
        qs = qs.filter(stream__isnull=True)

    if exclude_pk:
        try:
            qs = qs.exclude(pk=int(exclude_pk))
        except ValueError:
            pass

    exists = qs.exists()
    existing = None
    if exists:
        rec = qs.first()
        existing = f"{rec.name} ({rec.get_quarter_display()} {rec.year})"

    return JsonResponse({"exists": exists, "existing": existing})


# ─── TLD Renewal History Timeline ────────────────────────────────────────────


@login_required
def tld_badge_history(request, pk):
    """Return renewal history for a person's TLD across all quarters/years."""
    if not can_access_tld_badges(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    record = get_object_or_404(TLDBadgeRecord, pk=pk, business_unit=bu)

    # Find all records for the same person (by email or tld_number)
    history = (
        TLDBadgeRecord.objects.filter(
            business_unit=bu,
        )
        .filter(Q(email=record.email) | Q(tld_number=record.tld_number))
        .order_by("-year", "-quarter")[:5]
    )

    timeline = []
    for h in history:
        timeline.append(
            {
                "pk": h.pk,
                "year": h.year,
                "quarter": h.quarter,
                "quarter_display": h.get_quarter_display(),
                "tld_number": h.tld_number,
                "renewal_status": h.renewal_status,
                "renewal_status_display": h.get_renewal_status_display(),
                "stream": h.stream.name if h.stream else "",
                "name": h.name,
                "created_at": h.created_at.strftime("%Y-%m-%d %H:%M") if h.created_at else "",
            }
        )

    # Also fetch audit logs for this person
    audit_logs = (
        TLDBadgeAuditLog.objects.filter(
            business_unit=bu,
        )
        .filter(Q(badge_record=record) | Q(badge_tld_number=record.tld_number) | Q(badge_name=record.name))
        .order_by("-timestamp")[:20]
    )

    audit = []
    for a in audit_logs:
        audit.append(
            {
                "action": a.get_action_display(),
                "performed_by": str(a.performed_by) if a.performed_by else "System",
                "timestamp": a.timestamp.strftime("%Y-%m-%d %H:%M"),
                "details": a.details,
            }
        )

    return JsonResponse(
        {
            "success": True,
            "person": {
                "name": record.name,
                "email": record.email,
                "tld_number": record.tld_number,
            },
            "timeline": timeline,
            "audit_log": audit,
        }
    )


# ─── TLD Audit Log List ──────────────────────────────────────────────────────


@login_required
def tld_badge_audit_log(request):
    """Return paginated audit log entries for TLD Badge management."""
    if not can_access_tld_badges(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    logs = TLDBadgeAuditLog.objects.filter(business_unit=bu).order_by("-timestamp")[:50]
    entries = []
    for log in logs:
        entries.append(
            {
                "action": log.get_action_display(),
                "action_code": log.action,
                "performed_by": str(log.performed_by) if log.performed_by else "System",
                "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M"),
                "badge_name": log.badge_name,
                "badge_tld_number": log.badge_tld_number,
                "details": log.details,
            }
        )

    return JsonResponse({"success": True, "entries": entries})


# ─── TLD Print Badge Cards ───────────────────────────────────────────────────


@login_required
def tld_badge_print(request):
    """Return badge card data for printing selected records."""
    if not can_access_tld_badges(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    pks_str = request.GET.get("ids", "")
    if not pks_str:
        return JsonResponse({"success": False, "error": "No records selected."}, status=400)

    try:
        pks = [int(x) for x in pks_str.split(",") if x.strip()]
    except ValueError:
        return JsonResponse({"success": False, "error": "Invalid IDs."}, status=400)

    records = TLDBadgeRecord.objects.filter(pk__in=pks, business_unit=bu)
    cards = []
    for r in records:
        cards.append(
            {
                "pk": r.pk,
                "name": r.name,
                "email": r.email,
                "tld_number": r.tld_number,
                "code1_id": r.code1_id or "",
                "employee_id": r.employee_id or "",
                "quarter": r.get_quarter_display(),
                "year": r.year,
                "stream": r.stream.name if r.stream else "",
                "renewal_status": r.renewal_status,
                "renewal_status_display": r.get_renewal_status_display(),
                "bu_name": bu.bu_name if hasattr(bu, "bu_name") else str(bu),
            }
        )

    return JsonResponse({"success": True, "cards": cards})


# =============================================================================
# SUPPORT TICKETS  —  raise issues / feature requests / enhancements
# =============================================================================
