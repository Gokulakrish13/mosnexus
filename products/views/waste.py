"""Products app — Waste views."""

# pylint: disable=broad-exception-caught,else-if-used,invalid-name,too-many-lines,unused-variable

from ._helpers import (
    AuditLog,
    JsonResponse,
    Product,
    Q,
    Stream,
    WasteAuditLog,
    WasteCategory,
    WasteDisposalSchedule,
    WasteRecord,
    can_access_waste,
    date,
    get_bu_streams,
    get_current_bu,
    is_super_admin,
    json,
    logger,
    login_required,
    redirect,
    render,
)
from ..approval_triggers import fire_approval_trigger

__all__ = [
    "waste_dashboard",
    "waste_stream_detail",
    "waste_record_create",
    "waste_record_update",
    "waste_record_delete",
    "waste_record_detail_api",
    "waste_category_api",
    "waste_category_delete",
]


@login_required
def waste_dashboard(request):
    """Waste Management Hub — stream selector with per-stream stats."""
    if not can_access_waste(request.user):
        return redirect("dashboard")
    bu = get_current_bu(request)
    if not bu:
        return redirect("select_bu")

    streams = list(get_bu_streams(request).order_by("name"))

    # Per-stream summary stats — attached directly to stream objects
    all_records = WasteRecord.objects.filter(business_unit=bu)
    for s in streams:
        qs = all_records.filter(stream=s)
        s.w_total = qs.count()
        s.w_pending = qs.exclude(status__in=["disposed", "collected"]).count()
        s.w_hazardous = qs.filter(category__hazard_level="hazardous").count()
        s.w_overdue = sum(1 for r in qs.exclude(status__in=["disposed", "collected"]) if r.is_overdue)

    # Global summary for "All Streams" card — super admin only
    user_is_super = is_super_admin(request.user)
    total_all = pending_all = hazardous_all = overdue_all = 0
    if user_is_super:
        total_all = all_records.count()
        pending_all = all_records.exclude(status__in=["disposed", "collected"]).count()
        hazardous_all = all_records.filter(category__hazard_level="hazardous").count()
        overdue_all = sum(1 for r in all_records.exclude(status__in=["disposed", "collected"]) if r.is_overdue)

    context = {
        "streams": streams,
        "total_all": total_all,
        "pending_all": pending_all,
        "hazardous_all": hazardous_all,
        "overdue_all": overdue_all,
        "is_super_admin": user_is_super,
    }
    return render(request, "products/waste_hub.html", context)


@login_required
def waste_stream_detail(request, stream="all"):  # noqa: C901, CCR001
    """Waste detail page — per-stream or combined."""
    # pylint: disable=too-complex,too-many-branches,too-many-locals
    if not can_access_waste(request.user):
        return redirect("dashboard")
    bu = get_current_bu(request)
    if not bu:
        return redirect("select_bu")

    streams = get_bu_streams(request)
    current_stream = None
    user_is_super = is_super_admin(request.user)
    if stream != "all":
        current_stream = Stream.objects.filter(name=stream, business_unit=bu).first()
        if not current_stream:
            return redirect("waste_dashboard")
    else:
        # Only super admins can view all streams combined
        if not user_is_super:
            return redirect("waste_dashboard")

    status_filter = request.GET.get("status", "")
    hazard_filter = request.GET.get("hazard", "")
    search_q = request.GET.get("q", "")

    records = WasteRecord.objects.filter(business_unit=bu).select_related(
        "category", "stream", "source_product", "created_by"
    )
    if current_stream:
        records = records.filter(stream=current_stream)

    if status_filter:
        records = records.filter(status=status_filter)
    if hazard_filter:
        records = records.filter(category__hazard_level=hazard_filter)
    if search_q:
        records = records.filter(
            Q(tracking_number__icontains=search_q)
            | Q(description__icontains=search_q)
            | Q(category__name__icontains=search_q)
            | Q(source_reference__icontains=search_q)
            | Q(manifest_number__icontains=search_q)
        )

    # Stats scoped to current view
    stat_qs = WasteRecord.objects.filter(business_unit=bu)
    if current_stream:
        stat_qs = stat_qs.filter(stream=current_stream)
    total_records = stat_qs.count()
    pending_disposal = stat_qs.exclude(status__in=["disposed", "collected"]).count()
    hazardous_count = stat_qs.filter(category__hazard_level="hazardous").count()
    overdue_count = sum(1 for r in stat_qs.exclude(status__in=["disposed", "collected"]) if r.is_overdue)
    disposed_this_month = stat_qs.filter(
        status="disposed",
        disposal_date__month=date.today().month,
        disposal_date__year=date.today().year,
    ).count()

    # Upcoming schedules
    sched_qs = (
        WasteDisposalSchedule.objects.filter(
            business_unit=bu,
            scheduled_date__gte=date.today(),
            status__in=["scheduled", "confirmed"],
        )
        .select_related("stream", "category")
        .prefetch_related("waste_records")
    )
    if current_stream:
        sched_qs = sched_qs.filter(Q(stream=current_stream) | Q(stream__isnull=True))
    upcoming_schedules = list(sched_qs[:10])
    for s in upcoming_schedules:
        s.record_count = s.waste_records.count()

    categories = WasteCategory.objects.filter(business_unit=bu, is_active=True)

    # Scrapped products
    scrap_qs = (
        Product.objects.filter(stream__business_unit=bu, status="Scraped")
        .exclude(waste_records__isnull=False)
        .select_related("stream", "category")
    )
    if current_stream:
        scrap_qs = scrap_qs.filter(stream=current_stream)
    scrapped_products = scrap_qs[:10]

    context = {
        "records": records.order_by("-generated_date", "-created_at")[:100],
        "streams": streams,
        "categories": categories,
        "current_stream": current_stream,
        "stream_slug": stream,
        "is_super_admin": user_is_super,
        "status_filter": status_filter,
        "hazard_filter": hazard_filter,
        "search_q": search_q,
        "total_records": total_records,
        "pending_disposal": pending_disposal,
        "hazardous_count": hazardous_count,
        "overdue_count": overdue_count,
        "disposed_this_month": disposed_this_month,
        "upcoming_schedules": upcoming_schedules,
        "scrapped_products": scrapped_products,
        "status_choices": WasteRecord.STATUS_CHOICES,
        "hazard_choices": WasteCategory.HAZARD_LEVELS,
        "unit_choices": WasteRecord.UNIT_CHOICES,
        "source_choices": WasteRecord.SOURCE_CHOICES,
        "disposal_method_choices": [c for c in WasteRecord._meta.get_field("disposal_method").choices if c[0]],
        "frequency_choices": WasteDisposalSchedule.FREQUENCY_CHOICES,
    }
    return render(request, "products/waste_detail.html", context)


@login_required
def waste_record_create(request):
    """Create a new waste record (AJAX POST)."""
    if not can_access_waste(request.user):
        return JsonResponse({"success": False, "error": "Access denied"}, status=403)
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)

    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    try:
        data = json.loads(request.body) if request.content_type == "application/json" else request.POST
        stream = Stream.objects.get(name=data.get("stream"), business_unit=bu)
        category = WasteCategory.objects.get(pk=data.get("category"), business_unit=bu)

        record = WasteRecord(
            business_unit=bu,
            stream=stream,
            category=category,
            description=data.get("description", ""),
            quantity=data.get("quantity", 1),
            unit=data.get("unit", "units"),
            weight_kg=data.get("weight_kg") or None,
            source=data.get("source", "manual"),
            source_reference=data.get("source_reference", ""),
            storage_location=data.get("storage_location", ""),
            container_type=data.get("container_type", ""),
            container_id=data.get("container_id", ""),
            generated_date=data.get("generated_date", date.today().isoformat()),
            disposal_deadline=data.get("disposal_deadline") or None,
            notes=data.get("notes", ""),
            created_by=request.user,
            updated_by=request.user,
        )
        # Link to scrapped product if provided
        source_product_id = data.get("source_product")
        if source_product_id:
            try:
                record.source_product = Product.objects.get(pk=source_product_id)
                record.source = "product_scrap"
            except Product.DoesNotExist:
                pass

        record.save()

        WasteAuditLog.objects.create(
            waste_record=record,
            action="created",
            details=f"Waste record {record.tracking_number} created for {category.name}",
            performed_by=request.user,
        )

        return JsonResponse(
            {
                "success": True,
                "id": record.pk,
                "tracking_number": record.tracking_number,
                "message": f"Waste record {record.tracking_number} created.",
            }
        )
    except (Stream.DoesNotExist, WasteCategory.DoesNotExist) as e:  # noqa: F841
        return JsonResponse({"success": False, "error": "Invalid stream or waste category."}, status=400)
    except Exception:
        logger.error("Waste record creation error")
        return JsonResponse({"success": False, "error": "An unexpected error occurred. Please try again."}, status=500)


@login_required
def waste_record_update(request, pk):  # noqa: C901, CCR001
    """Update a waste record (AJAX POST)."""
    # pylint: disable=too-complex,too-many-locals
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)

    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    try:
        record = WasteRecord.objects.get(pk=pk, business_unit=bu)
        data = json.loads(request.body) if request.content_type == "application/json" else request.POST

        changes = []
        # Update allowed fields
        field_map = {
            "description": "description",
            "quantity": "quantity",
            "unit": "unit",
            "weight_kg": "weight_kg",
            "storage_location": "storage_location",
            "container_type": "container_type",
            "container_id": "container_id",
            "disposal_deadline": "disposal_deadline",
            "disposal_method": "disposal_method",
            "disposal_vendor": "disposal_vendor",
            "disposal_cost": "disposal_cost",
            "manifest_number": "manifest_number",
            "notes": "notes",
            "source_reference": "source_reference",
        }
        for field_key, attr in field_map.items():
            if field_key in data:
                old_val = getattr(record, attr)
                new_val = data[field_key] if data[field_key] != "" else None
                if str(old_val) != str(new_val):
                    changes.append(f"{field_key}: '{old_val}' → '{new_val}'")
                    setattr(
                        record, attr, new_val if new_val is not None else ("" if isinstance(old_val, str) else None)
                    )

        # Status change
        new_status = data.get("status")
        if new_status and new_status != record.status:
            old_status = record.get_status_display()
            record.status = new_status
            changes.append(f"Status: '{old_status}' → '{record.get_status_display()}'")
            if new_status == "disposed" and not record.disposal_date:
                record.disposal_date = date.today()
            # ── Fire audit trigger for waste disposal / rejection ──
            if new_status in ("disposed", "rejected"):
                _event = "waste_disposed" if new_status == "disposed" else "waste_rejected"
                fire_approval_trigger(
                    _event,
                    bu,
                    request.user,
                    entity_obj=record,
                    title=f"Waste '{record.tracking_number}' \u2192 {record.get_status_display()}",
                    description=f"Waste record {record.tracking_number} status changed to {new_status}",
                )
        # Category change
        new_cat = data.get("category")
        if new_cat and int(new_cat) != record.category_id:
            old_cat = record.category.name
            record.category = WasteCategory.objects.get(pk=new_cat, business_unit=bu)
            changes.append(f"Category: '{old_cat}' → '{record.category.name}'")

        # Stream change
        new_stream = data.get("stream")
        if new_stream and new_stream != record.stream.name:
            old_stream = record.stream.name
            record.stream = Stream.objects.get(name=new_stream, business_unit=bu)
            changes.append(f"Stream: '{old_stream}' → '{record.stream.name}'")

        record.updated_by = request.user
        record.save()

        if changes:
            WasteAuditLog.objects.create(
                waste_record=record,
                action="updated" if "Status" not in "".join(changes) else "status_changed",
                details="; ".join(changes),
                performed_by=request.user,
            )

        return JsonResponse(
            {
                "success": True,
                "message": f"Record {record.tracking_number} updated.",
            }
        )
    except WasteRecord.DoesNotExist:
        return JsonResponse({"success": False, "error": "Record not found"}, status=404)
    except Exception:
        logger.error("Waste record update error")
        return JsonResponse({"success": False, "error": "An unexpected error occurred. Please try again."}, status=500)


@login_required
def waste_record_delete(request, pk):
    """Delete a waste record (POST)."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)

    bu = get_current_bu(request)
    try:
        record = WasteRecord.objects.get(pk=pk, business_unit=bu)
        tn = record.tracking_number
        AuditLog.log(
            "delete",
            f'Deleted waste record "{tn}"',
            user=request.user,
            request=request,
            module="other",
            severity="warning",
        )
        record.delete()
        return JsonResponse({"success": True, "message": f"Record {tn} deleted."})
    except WasteRecord.DoesNotExist:
        return JsonResponse({"success": False, "error": "Record not found"}, status=404)


@login_required
def waste_record_detail_api(request, pk):
    """Return full waste record details as JSON."""
    if not can_access_waste(request.user):
        return JsonResponse({"success": False, "error": "Access denied"}, status=403)
    bu = get_current_bu(request)
    try:
        r = WasteRecord.objects.select_related("category", "stream", "source_product", "created_by", "updated_by").get(
            pk=pk, business_unit=bu
        )

        audit_logs = list(r.audit_logs.values("action", "details", "performed_at", "performed_by__username")[:20])

        return JsonResponse(
            {
                "success": True,
                "record": {
                    "id": r.pk,
                    "tracking_number": r.tracking_number,
                    "stream": r.stream.name,
                    "category_id": r.category_id,
                    "category_name": r.category.name,
                    "hazard_level": r.category.hazard_level,
                    "hazard_display": r.category.get_hazard_level_display(),
                    "category_color": r.category.color,
                    "description": r.description,
                    "quantity": str(r.quantity),
                    "unit": r.unit,
                    "unit_display": r.get_unit_display(),
                    "weight_kg": str(r.weight_kg) if r.weight_kg else "",
                    "source": r.source,
                    "source_display": r.get_source_display(),
                    "source_product_id": r.source_product_id,
                    "source_product_name": str(r.source_product) if r.source_product else "",
                    "source_reference": r.source_reference,
                    "storage_location": r.storage_location,
                    "container_type": r.container_type,
                    "container_id": r.container_id,
                    "status": r.status,
                    "status_display": r.get_status_display(),
                    "generated_date": r.generated_date.isoformat() if r.generated_date else "",
                    "disposal_deadline": r.disposal_deadline.isoformat() if r.disposal_deadline else "",
                    "disposal_date": r.disposal_date.isoformat() if r.disposal_date else "",
                    "disposal_method": r.disposal_method,
                    "disposal_vendor": r.disposal_vendor,
                    "disposal_cost": str(r.disposal_cost) if r.disposal_cost else "",
                    "manifest_number": r.manifest_number,
                    "notes": r.notes,
                    "is_compliant": r.is_compliant,
                    "compliance_notes": r.compliance_notes,
                    "is_overdue": r.is_overdue,
                    "days_until_deadline": r.days_until_deadline,
                    "created_by": r.created_by.username if r.created_by else "",
                    "created_at": r.created_at.strftime("%Y-%m-%d %H:%M"),
                    "updated_by": r.updated_by.username if r.updated_by else "",
                    "updated_at": r.updated_at.strftime("%Y-%m-%d %H:%M"),
                    "audit_logs": [
                        {
                            "action": l["action"],
                            "details": l["details"],
                            "by": l["performed_by__username"] or "",
                            "at": l["performed_at"].strftime("%Y-%m-%d %H:%M"),
                        }
                        for l in audit_logs  # noqa: E741
                    ],
                    "linked_schedules": [
                        {
                            "id": s.pk,
                            "vendor": s.vendor,
                            "scheduled_date": s.scheduled_date.isoformat(),
                            "status": s.status,
                            "status_display": s.get_status_display(),
                        }
                        for s in r.disposal_schedules.all()[:5]
                    ],
                },
            }
        )
    except WasteRecord.DoesNotExist:
        return JsonResponse({"success": False, "error": "Record not found"}, status=404)


@login_required
def waste_category_api(request):
    """GET: list categories. POST: create a new category."""
    # pylint: disable=too-many-return-statements
    if not can_access_waste(request.user):
        return JsonResponse({"success": False, "error": "Access denied"}, status=403)
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    if request.method == "GET":
        cats = WasteCategory.objects.filter(business_unit=bu, is_active=True).values(
            "id",
            "name",
            "hazard_level",
            "color",
            "icon_class",
            "handling_instructions",
            "regulatory_code",
            "description",
        )
        return JsonResponse({"success": True, "categories": list(cats)})

    if request.method == "POST":
        data = json.loads(request.body) if request.content_type == "application/json" else request.POST
        name = (data.get("name") or "").strip()
        if not name:
            return JsonResponse({"success": False, "error": "Name is required"}, status=400)

        if WasteCategory.objects.filter(name__iexact=name, business_unit=bu).exists():
            return JsonResponse({"success": False, "error": f'Category "{name}" already exists'}, status=400)

        cat = WasteCategory.objects.create(
            name=name,
            hazard_level=data.get("hazard_level", "non_hazardous"),
            description=data.get("description", ""),
            color=data.get("color", "#6c757d"),
            icon_class=data.get("icon_class", "fas fa-trash-alt"),
            handling_instructions=data.get("handling_instructions", ""),
            regulatory_code=data.get("regulatory_code", ""),
            business_unit=bu,
            created_by=request.user,
        )
        return JsonResponse(
            {
                "success": True,
                "id": cat.pk,
                "name": cat.name,
                "message": f'Category "{cat.name}" created.',
            }
        )

    return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)


@login_required
def waste_category_delete(request, pk):
    """Delete (deactivate) a waste category."""
    if not can_access_waste(request.user):
        return JsonResponse({"success": False, "error": "Access denied"}, status=403)
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)
    bu = get_current_bu(request)
    try:
        cat = WasteCategory.objects.get(pk=pk, business_unit=bu)
        cat.is_active = False
        cat.save()
        return JsonResponse({"success": True, "message": f'Category "{cat.name}" deactivated.'})
    except WasteCategory.DoesNotExist:
        return JsonResponse({"success": False, "error": "Category not found"}, status=404)
