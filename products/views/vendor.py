"""Products app — Vendor views."""

# pylint: disable=invalid-name,too-many-lines,wrong-import-position

import datetime as _dt

from django.db.models import Sum

from ._helpers import (
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_SIZE,
    Avg,
    Count,
    F,
    HttpResponse,
    JsonResponse,
    Notification,
    Q,
    Vendor,
    VendorContract,
    VendorDeliveryReceipt,
    VendorDeliveryReceiptItem,
    VendorPerformanceLog,
    VendorPurchaseOrder,
    VendorPurchaseOrderItem,
    Workbook,
    date,
    get_bu_streams,
    get_column_letter,
    get_current_bu,
    get_object_or_404,
    get_stream_or_404,
    is_app_admin,
    is_super_admin,
    login_required,
    messages,
    redirect,
    render,
    timezone,
    validate_uploaded_file,
)
from ..approval_triggers import check_approval_required, fire_approval_trigger

__all__ = [
    "vendor_hub",
    "vendor_list",
    "vendor_analytics_api",
    "vendor_create",
    "vendor_edit",
    "vendor_detail",
    "vendor_delete",
    "vendor_contract_create",
    "vendor_contract_delete",
    "vendor_performance_log_create",
    "vendor_export",
    "vendor_po_create",
    "vendor_po_detail",
    "vendor_po_update_status",
    "vendor_po_receive",
    "vendor_po_delete",
]


@login_required
def vendor_hub(request):
    """Vendor Hub — stream selector for vendor management."""
    streams = get_bu_streams(request).order_by("name")
    bu = get_current_bu(request)
    if not bu:
        return redirect("select_bu")

    # per-stream vendor counts
    all_vendors = Vendor.objects.filter(business_unit=bu)
    for s in streams:
        s.v_total = all_vendors.filter(stream=s).count()
        s.v_active = all_vendors.filter(stream=s, status="active").count()
        s.v_contracts = VendorContract.objects.filter(
            vendor__stream=s, vendor__business_unit=bu, status="active"
        ).count()

    user_is_super = is_super_admin(request.user)
    total_all = all_vendors.count()
    active_all = all_vendors.filter(status="active").count()
    contracts_all = VendorContract.objects.filter(vendor__business_unit=bu, status="active").count()

    context = {
        "streams": streams,
        "total_all": total_all,
        "active_all": active_all,
        "contracts_all": contracts_all,
        "is_super_admin": user_is_super,
    }
    return render(request, "products/vendor_hub.html", context)


@login_required
def vendor_list(request, stream):
    """List all vendors for a given stream."""
    stream_obj = get_stream_or_404(stream)
    bu = get_current_bu(request)
    if not bu:
        return redirect("select_bu")

    vendors = Vendor.objects.filter(business_unit=bu, stream=stream_obj)

    status_filter = request.GET.get("status", "")
    category_filter = request.GET.get("category", "")
    search_q = request.GET.get("q", "")

    if status_filter:
        vendors = vendors.filter(status=status_filter)
    if category_filter:
        vendors = vendors.filter(category__icontains=category_filter)
    if search_q:
        vendors = vendors.filter(
            Q(name__icontains=search_q)
            | Q(code__icontains=search_q)
            | Q(contact_person__icontains=search_q)
            | Q(email__icontains=search_q)
        )

    categories = (
        Vendor.objects.filter(business_unit=bu, stream=stream_obj)
        .values_list("category", flat=True)
        .distinct()
        .order_by("category")
    )
    user_is_admin = is_super_admin(request.user) or is_app_admin(request.user)

    context = {
        "stream": stream,
        "selected_stream": stream,
        "stream_obj": stream_obj,
        "vendors": vendors,
        "categories": [c for c in categories if c],
        "status_filter": status_filter,
        "category_filter": category_filter,
        "search_q": search_q,
        "is_admin": user_is_admin,
    }
    return render(request, "products/vendor_list.html", context)


@login_required
def vendor_analytics_api(request, stream):  # noqa: CCR001
    """Return JSON analytics data for the vendor list analytics popup."""
    # pylint: disable=too-many-locals
    stream_obj = get_stream_or_404(stream)
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"error": "No BU selected"}, status=400)

    vendors = Vendor.objects.filter(business_unit=bu, stream=stream_obj)
    today = _dt.date.today()

    # 1) Vendor Status Distribution
    status_dist = list(vendors.values("status").annotate(count=Count("id")).order_by("status"))

    # 2) Category Breakdown
    category_dist = list(
        vendors.exclude(category="").values("category").annotate(count=Count("id")).order_by("-count")[:10]
    )

    # 3) Rating Distribution
    rating_dist = list(
        vendors.exclude(rating__isnull=True).values("rating").annotate(count=Count("id")).order_by("rating")
    )
    avg_rating = vendors.exclude(rating__isnull=True).aggregate(avg=Avg("rating"))["avg"]

    # 4) Contract Health
    contracts = VendorContract.objects.filter(vendor__in=vendors)
    contract_status_dist = list(contracts.values("status").annotate(count=Count("id")).order_by("status"))
    expiring_soon = contracts.filter(
        status="active", end_date__isnull=False, end_date__gte=today, end_date__lte=today + _dt.timedelta(days=90)
    ).count()
    expired_contracts = contracts.filter(status="active", end_date__isnull=False, end_date__lt=today).count()
    total_contract_value = contracts.filter(status="active").aggregate(total=Sum("value"))["total"] or 0

    # 5) PO Status Pipeline
    pos = VendorPurchaseOrder.objects.filter(vendor__in=vendors)
    po_status_dist = list(pos.values("status").annotate(count=Count("id")).order_by("status"))
    po_priority_dist = list(pos.values("priority").annotate(count=Count("id")).order_by("priority"))
    total_po_value = pos.aggregate(total=Sum("total_amount"))["total"] or 0
    overdue_pos = (
        pos.filter(expected_delivery_date__lt=today).exclude(status__in=["delivered", "closed", "cancelled"]).count()
    )

    # 6) Spending by Month (last 12 months)
    twelve_months_ago = today - _dt.timedelta(days=365)
    monthly_spending: dict[str, float] = defaultdict(float)
    recent_pos = pos.filter(order_date__gte=twelve_months_ago)
    for po in recent_pos:
        key = po.order_date.strftime("%Y-%m")
        monthly_spending[key] += float(po.total_amount)
    spending_labels = sorted(monthly_spending.keys())
    spending_values = [monthly_spending[k] for k in spending_labels]

    # 7) Delivery Performance
    po_items = VendorPurchaseOrderItem.objects.filter(purchase_order__in=pos)
    total_ordered_qty = po_items.aggregate(s=Sum("quantity"))["s"] or 0
    total_received_qty = po_items.aggregate(s=Sum("quantity_received"))["s"] or 0
    fully_received_items = po_items.filter(quantity_received__gte=F("quantity")).count()
    total_items = po_items.count()

    # 8) Performance Logs stats
    perf_logs = VendorPerformanceLog.objects.filter(vendor__in=vendors)
    on_time_pct = 0
    quality_pct = 0
    if perf_logs.exists():
        total_logs = perf_logs.count()
        on_time_pct = round(perf_logs.filter(delivery_on_time=True).count() / total_logs * 100, 1)
        quality_pct = round(perf_logs.filter(quality_ok=True).count() / total_logs * 100, 1)

    # 9) Top vendors by PO value
    top_vendors_by_po = list(
        vendors.annotate(po_total=Sum("purchase_orders__total_amount"), po_count=Count("purchase_orders"))
        .filter(po_total__gt=0)
        .order_by("-po_total")[:5]
        .values("name", "po_total", "po_count")
    )
    for v in top_vendors_by_po:
        v["po_total"] = float(v["po_total"]) if v["po_total"] else 0

    # 10) Spending by vendor category
    category_spending = list(
        VendorPurchaseOrder.objects.filter(vendor__in=vendors)
        .exclude(vendor__category="")
        .values("vendor__category")
        .annotate(total=Sum("total_amount"))
        .filter(total__gt=0)
        .order_by("-total")[:8]
    )
    for c in category_spending:
        c["category"] = c.pop("vendor__category")
        c["total"] = float(c["total"]) if c["total"] else 0

    data = {
        "summary": {
            "total_vendors": vendors.count(),
            "active_vendors": vendors.filter(status="active").count(),
            "total_contracts": contracts.count(),
            "active_contracts": contracts.filter(status="active").count(),
            "total_pos": pos.count(),
            "total_po_value": float(total_po_value),
            "total_contract_value": float(total_contract_value),
            "avg_rating": round(avg_rating, 1) if avg_rating else None,
            "overdue_pos": overdue_pos,
            "expiring_contracts": expiring_soon,
            "expired_contracts": expired_contracts,
            "on_time_delivery_pct": on_time_pct,
            "quality_ok_pct": quality_pct,
        },
        "vendor_status": status_dist,
        "vendor_categories": category_dist,
        "rating_distribution": rating_dist,
        "contract_status": contract_status_dist,
        "po_status": po_status_dist,
        "po_priority": po_priority_dist,
        "monthly_spending": {"labels": spending_labels, "values": spending_values},
        "delivery": {
            "total_ordered": total_ordered_qty,
            "total_received": total_received_qty,
            "fully_received_items": fully_received_items,
            "total_items": total_items,
        },
        "top_vendors": top_vendors_by_po,
        "category_spending": category_spending,
        "currency": vendors.first().currency if vendors.exists() else "EUR",
    }
    return JsonResponse(data)


@login_required
def vendor_create(request, stream):
    """Create a new vendor."""
    stream_obj = get_stream_or_404(stream)
    bu = get_current_bu(request)
    if not bu:
        return redirect("select_bu")

    if request.method == "POST":
        vendor = Vendor(
            business_unit=bu,
            stream=stream_obj,
            name=request.POST.get("name", "").strip(),
            contact_person=request.POST.get("contact_person", "").strip(),
            email=request.POST.get("email", "").strip(),
            phone=request.POST.get("phone", "").strip(),
            website=request.POST.get("website", "").strip(),
            address=request.POST.get("address", "").strip(),
            city=request.POST.get("city", "").strip(),
            country=request.POST.get("country", "").strip(),
            category=request.POST.get("category", "").strip(),
            tax_id=request.POST.get("tax_id", "").strip(),
            payment_terms=request.POST.get("payment_terms", "").strip(),
            currency=request.POST.get("currency", "EUR").strip(),
            notes=request.POST.get("notes", "").strip(),
            status=request.POST.get("status", "active"),
            created_by=request.user,
            updated_by=request.user,
        )
        rating_val = request.POST.get("rating", "")
        if rating_val:
            vendor.rating = int(rating_val)
        if "logo" in request.FILES:
            logo = request.FILES["logo"]
            is_valid, error_msg = validate_uploaded_file(
                logo, ALLOWED_IMAGE_TYPES, ALLOWED_IMAGE_EXTENSIONS, MAX_IMAGE_SIZE
            )
            if not is_valid:
                messages.error(request, f"Logo: {error_msg}")
                return redirect("vendor_create", stream=stream)
            vendor.logo = logo
        vendor.save()
        messages.success(request, f'Vendor "{vendor.name}" created successfully.')
        # ── Auto-trigger approval for vendor onboarding ──
        fire_approval_trigger(
            "vendor_onboarded",
            bu,
            request.user,
            entity_obj=vendor,
            stream=stream_obj,
            title=f"New vendor '{vendor.name}' onboarded",
            description=f"Vendor {vendor.name} ({vendor.email}) created with status '{vendor.status}' in stream {stream}",
        )
        return redirect("vendor_list", stream=stream)

    context = {"stream": stream, "selected_stream": stream, "stream_obj": stream_obj, "mode": "create"}
    return render(request, "products/vendor_form.html", context)


@login_required
def vendor_edit(request, stream, pk):
    """Edit an existing vendor."""
    stream_obj = get_stream_or_404(stream)
    bu = get_current_bu(request)
    vendor = get_object_or_404(Vendor, pk=pk, business_unit=bu, stream=stream_obj)

    if request.method == "POST":
        _old_status = vendor.status
        vendor.name = request.POST.get("name", "").strip()
        vendor.contact_person = request.POST.get("contact_person", "").strip()
        vendor.email = request.POST.get("email", "").strip()
        vendor.phone = request.POST.get("phone", "").strip()
        vendor.website = request.POST.get("website", "").strip()
        vendor.address = request.POST.get("address", "").strip()
        vendor.city = request.POST.get("city", "").strip()
        vendor.country = request.POST.get("country", "").strip()
        vendor.category = request.POST.get("category", "").strip()
        vendor.tax_id = request.POST.get("tax_id", "").strip()
        vendor.payment_terms = request.POST.get("payment_terms", "").strip()
        vendor.currency = request.POST.get("currency", "EUR").strip()
        vendor.notes = request.POST.get("notes", "").strip()
        vendor.status = request.POST.get("status", vendor.status)

        # ── Pre-action enforcement: block vendor blacklisting if approval required ──
        _approval_block = None
        if _old_status != vendor.status and vendor.status == "blacklisted":
            _approval_block = check_approval_required(
                "vendor_blacklisted",
                bu,
                request.user,
                entity_obj=vendor,
                stream=stream_obj,
                title=f"Vendor '{vendor.name}' \u2192 blacklisted",
                description=f"Vendor {vendor.name} status change from {_old_status} to blacklisted",
                intended_changes={
                    "action_type": "status_change",
                    "model_label": "products.Vendor",
                    "pk": vendor.pk,
                    "changes": {"status": "blacklisted"},
                    "revert": {"status": _old_status},
                    "metadata": {"entity_name": vendor.name, "stream_name": stream},
                },
            )
            if _approval_block:
                vendor.status = _old_status  # keep old status
        elif _old_status != vendor.status and vendor.status == "inactive":
            _approval_block = check_approval_required(
                "vendor_deactivated",
                bu,
                request.user,
                entity_obj=vendor,
                stream=stream_obj,
                title=f"Vendor '{vendor.name}' \u2192 inactive",
                description=f"Vendor {vendor.name} status change from {_old_status} to inactive",
                intended_changes={
                    "action_type": "status_change",
                    "model_label": "products.Vendor",
                    "pk": vendor.pk,
                    "changes": {"status": "inactive"},
                    "revert": {"status": _old_status},
                    "metadata": {"entity_name": vendor.name, "stream_name": stream},
                },
            )
            if _approval_block:
                vendor.status = _old_status  # keep old status

        rating_val = request.POST.get("rating", "")
        vendor.rating = int(rating_val) if rating_val else None
        if "logo" in request.FILES:
            logo = request.FILES["logo"]
            is_valid, error_msg = validate_uploaded_file(
                logo, ALLOWED_IMAGE_TYPES, ALLOWED_IMAGE_EXTENSIONS, MAX_IMAGE_SIZE
            )
            if not is_valid:
                messages.error(request, f"Logo: {error_msg}")
                return redirect("vendor_edit", stream=stream, pk=pk)
            vendor.logo = logo
        vendor.updated_by = request.user
        vendor.save()
        # ── Notify if status change was blocked ──
        if _approval_block:
            _blocked_label = "deactivating" if vendor.status == _old_status and _old_status != "blacklisted" else "blacklisting"
            messages.warning(
                request,
                f'\u23f3 {_blocked_label.capitalize()} vendor "{vendor.name}" requires approval. '
                f'Request #{_approval_block.id} submitted.',
            )
        else:
            messages.success(request, f'Vendor "{vendor.name}" updated.')
        return redirect("vendor_detail", stream=stream, pk=pk)

    context = {"stream": stream, "selected_stream": stream, "stream_obj": stream_obj, "vendor": vendor, "mode": "edit"}
    return render(request, "products/vendor_form.html", context)


@login_required
def vendor_detail(request, stream, pk):
    """Vendor detail page with contracts and performance."""
    stream_obj = get_stream_or_404(stream)
    bu = get_current_bu(request)
    vendor = get_object_or_404(Vendor, pk=pk, business_unit=bu, stream=stream_obj)
    contracts = vendor.contracts.all()
    perf_logs = vendor.performance_logs.all()[:20]
    purchase_orders = vendor.purchase_orders.all()[:50]
    lifecycle_records = vendor.lifecycle_records.select_related("product", "product__stream", "current_stage").all()[
        :50
    ]
    user_is_admin = is_super_admin(request.user) or is_app_admin(request.user)

    context = {
        "stream": stream,
        "selected_stream": stream,
        "stream_obj": stream_obj,
        "vendor": vendor,
        "contracts": contracts,
        "perf_logs": perf_logs,
        "purchase_orders": purchase_orders,
        "lifecycle_records": lifecycle_records,
        "is_admin": user_is_admin,
    }
    return render(request, "products/vendor_detail.html", context)


@login_required
def vendor_delete(request, stream, pk):
    """Delete a vendor."""
    stream_obj = get_stream_or_404(stream)
    bu = get_current_bu(request)
    vendor = get_object_or_404(Vendor, pk=pk, business_unit=bu, stream=stream_obj)
    if request.method == "POST":
        name = vendor.name
        _bu = vendor.business_unit

        # ── Pre-action enforcement: block delete if approval required ──
        _approval = check_approval_required(
            "vendor_deleted",
            _bu,
            request.user,
            entity_obj=vendor,
            stream=stream_obj,
            title=f"Vendor '{name}' deletion",
            description=f"Vendor {name} delete requested from stream {stream}",
            intended_changes={
                "action_type": "delete",
                "model_label": "products.Vendor",
                "pk": vendor.pk,
                "metadata": {"entity_name": name, "stream_name": stream},
            },
        )
        if _approval:
            messages.warning(
                request,
                f'\u23f3 Deleting vendor "{name}" requires approval. Request #{_approval.id} submitted.',
            )
            return redirect("vendor_detail", stream=stream, pk=pk)

        vendor.delete()
        messages.success(request, f'Vendor "{name}" deleted.')
        return redirect("vendor_list", stream=stream)
    return redirect("vendor_detail", stream=stream, pk=pk)


@login_required
def vendor_contract_create(request, stream, vendor_id):
    """Add a contract to a vendor."""
    stream_obj = get_stream_or_404(stream)
    bu = get_current_bu(request)
    vendor = get_object_or_404(Vendor, pk=vendor_id, business_unit=bu, stream=stream_obj)

    if request.method == "POST":
        contract = VendorContract(
            vendor=vendor,
            title=request.POST.get("title", "").strip(),
            contract_number=request.POST.get("contract_number", "").strip(),
            status=request.POST.get("status", "draft"),
            start_date=request.POST.get("start_date"),
            notes=request.POST.get("notes", "").strip(),
            created_by=request.user,
        )
        end_date = request.POST.get("end_date", "")
        if end_date:
            contract.end_date = end_date
        value = request.POST.get("value", "")
        if value:
            contract.value = value
        contract.currency = request.POST.get("currency", "EUR")
        if "document" in request.FILES:
            contract.document = request.FILES["document"]
        contract.save()
        messages.success(request, f'Contract "{contract.title}" added.')
        return redirect("vendor_detail", stream=stream, pk=vendor_id)
    return redirect("vendor_detail", stream=stream, pk=vendor_id)


@login_required
def vendor_contract_delete(request, stream, vendor_id, pk):
    """Delete a contract."""
    stream_obj = get_stream_or_404(stream)
    bu = get_current_bu(request)
    vendor = get_object_or_404(Vendor, pk=vendor_id, business_unit=bu, stream=stream_obj)
    contract = get_object_or_404(VendorContract, pk=pk, vendor=vendor)
    if request.method == "POST":
        contract.delete()
        messages.success(request, "Contract deleted.")
    return redirect("vendor_detail", stream=stream, pk=vendor_id)


@login_required
def vendor_performance_log_create(request, stream, vendor_id):
    """Log a performance entry for a vendor."""
    stream_obj = get_stream_or_404(stream)
    bu = get_current_bu(request)
    vendor = get_object_or_404(Vendor, pk=vendor_id, business_unit=bu, stream=stream_obj)

    if request.method == "POST":
        VendorPerformanceLog.objects.create(
            vendor=vendor,
            date=request.POST.get("date", date.today().isoformat()),
            rating=int(request.POST.get("rating", 3)),
            delivery_on_time=request.POST.get("delivery_on_time") == "on",
            quality_ok=request.POST.get("quality_ok") == "on",
            comments=request.POST.get("comments", "").strip(),
            logged_by=request.user,
        )
        # Update vendor average rating
        avg = vendor.performance_logs.aggregate(avg_rating=Avg("rating"))["avg_rating"]
        if avg:
            vendor.rating = round(avg)
            vendor.save(update_fields=["rating"])
        messages.success(request, "Performance log recorded.")
    return redirect("vendor_detail", stream=stream, pk=vendor_id)


@login_required
def vendor_export(request, stream):
    """Export vendors for a stream to Excel."""
    stream_obj = get_stream_or_404(stream)
    bu = get_current_bu(request)
    vendors = Vendor.objects.filter(business_unit=bu, stream=stream_obj)

    wb = Workbook()
    ws = wb.active
    ws.title = "Vendors"
    headers = [
        "Code",
        "Name",
        "Status",
        "Category",
        "Contact Person",
        "Email",
        "Phone",
        "City",
        "Country",
        "Payment Terms",
        "Rating",
        "Active Contracts",
        "Created",
    ]
    for col, h in enumerate(headers, 1):
        ws.cell(row=1, column=col, value=h)

    for row_idx, v in enumerate(vendors, 2):
        ws.cell(row=row_idx, column=1, value=v.code)
        ws.cell(row=row_idx, column=2, value=v.name)
        ws.cell(row=row_idx, column=3, value=v.status)
        ws.cell(row=row_idx, column=4, value=v.category)
        ws.cell(row=row_idx, column=5, value=v.contact_person)
        ws.cell(row=row_idx, column=6, value=v.email)
        ws.cell(row=row_idx, column=7, value=v.phone)
        ws.cell(row=row_idx, column=8, value=v.city)
        ws.cell(row=row_idx, column=9, value=v.country)
        ws.cell(row=row_idx, column=10, value=v.payment_terms)
        ws.cell(row=row_idx, column=11, value=v.rating or "")
        ws.cell(row=row_idx, column=12, value=v.contracts.filter(status="active").count())
        ws.cell(row=row_idx, column=13, value=v.created_at.strftime("%Y-%m-%d"))

    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 18

    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="vendors_{stream}_{date.today().isoformat()}.xlsx"'
    wb.save(response)
    return response


# =============================================================================
# VENDOR PURCHASE ORDERS
# =============================================================================


@login_required
def vendor_po_create(request, stream, vendor_id):  # noqa: CCR001
    """Create a new purchase order for a vendor."""
    # pylint: disable=too-many-locals
    stream_obj = get_stream_or_404(stream)
    bu = get_current_bu(request)
    vendor = get_object_or_404(Vendor, pk=vendor_id, business_unit=bu, stream=stream_obj)

    if request.method == "POST":
        po = VendorPurchaseOrder(
            vendor=vendor,
            title=request.POST.get("title", "").strip(),
            order_date=request.POST.get("order_date", date.today().isoformat()),
            priority=request.POST.get("priority", "normal"),
            shipping_address=request.POST.get("shipping_address", "").strip(),
            notes=request.POST.get("notes", "").strip(),
            currency=request.POST.get("currency", vendor.currency or "EUR"),
            created_by=request.user,
        )
        exp_date = request.POST.get("expected_delivery_date", "")
        if exp_date:
            po.expected_delivery_date = exp_date
        po.save()

        # Add line items
        item_names = request.POST.getlist("item_name")
        item_qtys = request.POST.getlist("item_qty")
        item_units = request.POST.getlist("item_unit")
        item_prices = request.POST.getlist("item_price")
        item_parts = request.POST.getlist("item_part")
        item_descs = request.POST.getlist("item_desc")

        for i, name in enumerate(item_names):
            if name.strip():
                VendorPurchaseOrderItem.objects.create(
                    purchase_order=po,
                    item_name=name.strip(),
                    quantity=int(item_qtys[i]) if i < len(item_qtys) and item_qtys[i] else 1,
                    unit=item_units[i].strip() if i < len(item_units) and item_units[i] else "pcs",
                    unit_price=float(item_prices[i]) if i < len(item_prices) and item_prices[i] else 0,
                    part_number=item_parts[i].strip() if i < len(item_parts) and item_parts[i] else "",
                    description=item_descs[i].strip() if i < len(item_descs) and item_descs[i] else "",
                )

        po.recalculate_total()
        Notification.notify_admins(
            bu,
            f"Purchase Order {po.po_number} created for vendor '{vendor.name}'.",
            "purchase_order",
            exclude_user=request.user,
        )
        messages.success(request, f"Purchase order {po.po_number} created.")
        return redirect("vendor_po_detail", stream=stream, vendor_id=vendor_id, po_id=po.pk)

    context = {
        "stream": stream,
        "selected_stream": stream,
        "stream_obj": stream_obj,
        "vendor": vendor,
        "mode": "create",
    }
    return render(request, "products/vendor_po_form.html", context)


@login_required
def vendor_po_detail(request, stream, vendor_id, po_id):
    """View purchase order details with items and delivery history."""
    stream_obj = get_stream_or_404(stream)
    bu = get_current_bu(request)
    vendor = get_object_or_404(Vendor, pk=vendor_id, business_unit=bu, stream=stream_obj)
    po = get_object_or_404(VendorPurchaseOrder, pk=po_id, vendor=vendor)
    items = po.items.all()
    deliveries = po.deliveries.select_related("received_by").prefetch_related("items__po_item").all()
    user_is_admin = is_super_admin(request.user) or is_app_admin(request.user)

    context = {
        "stream": stream,
        "selected_stream": stream,
        "stream_obj": stream_obj,
        "vendor": vendor,
        "po": po,
        "items": items,
        "deliveries": deliveries,
        "is_admin": user_is_admin,
    }
    return render(request, "products/vendor_po_detail.html", context)


@login_required
def vendor_po_update_status(request, stream, vendor_id, po_id):
    """Update the status of a purchase order."""
    stream_obj = get_stream_or_404(stream)
    bu = get_current_bu(request)
    vendor = get_object_or_404(Vendor, pk=vendor_id, business_unit=bu, stream=stream_obj)
    po = get_object_or_404(VendorPurchaseOrder, pk=po_id, vendor=vendor)

    if request.method == "POST":
        new_status = request.POST.get("status", po.status)
        po.status = new_status
        if new_status == "submitted" and not po.approved_by:
            po.approved_by = request.user
            po.approved_at = timezone.now()
        if new_status == "delivered" and not po.actual_delivery_date:
            po.actual_delivery_date = date.today()
        po.save()
        messages.success(request, f"PO {po.po_number} status updated to {po.get_status_display()}.")
    return redirect("vendor_po_detail", stream=stream, vendor_id=vendor_id, po_id=po_id)


@login_required
def vendor_po_receive(request, stream, vendor_id, po_id):
    """Record a delivery receipt against a purchase order."""
    stream_obj = get_stream_or_404(stream)
    bu = get_current_bu(request)
    vendor = get_object_or_404(Vendor, pk=vendor_id, business_unit=bu, stream=stream_obj)
    po = get_object_or_404(VendorPurchaseOrder, pk=po_id, vendor=vendor)

    if request.method == "POST":
        receipt = VendorDeliveryReceipt.objects.create(
            purchase_order=po,
            receipt_number=request.POST.get("receipt_number", "").strip(),
            received_date=request.POST.get("received_date", date.today().isoformat()),
            received_by=request.user,
            notes=request.POST.get("delivery_notes", "").strip(),
        )

        # Process line items
        for item in po.items.all():
            qty_key = f"recv_qty_{item.id}"
            cond_key = f"recv_cond_{item.id}"
            note_key = f"recv_note_{item.id}"
            qty = request.POST.get(qty_key, "0")
            qty = int(qty) if qty else 0
            if qty > 0:
                VendorDeliveryReceiptItem.objects.create(
                    delivery=receipt,
                    po_item=item,
                    quantity_received=qty,
                    condition_ok=request.POST.get(cond_key) != "damaged",
                    notes=request.POST.get(note_key, "").strip(),
                )

        # Update PO status based on delivery
        summary = po.delivery_status_summary
        if summary["pending"] <= 0:
            po.status = "delivered"
            po.actual_delivery_date = date.today()
        elif summary["received"] > 0:
            po.status = "partially_delivered"
        po.save()

        messages.success(request, f"Delivery receipt recorded for PO {po.po_number}.")
    return redirect("vendor_po_detail", stream=stream, vendor_id=vendor_id, po_id=po_id)


@login_required
def vendor_po_delete(request, stream, vendor_id, po_id):
    """Delete a purchase order."""
    stream_obj = get_stream_or_404(stream)
    bu = get_current_bu(request)
    vendor = get_object_or_404(Vendor, pk=vendor_id, business_unit=bu, stream=stream_obj)
    po = get_object_or_404(VendorPurchaseOrder, pk=po_id, vendor=vendor)
    if request.method == "POST":
        po_num = po.po_number
        po.delete()
        messages.success(request, f"Purchase order {po_num} deleted.")
    return redirect("vendor_detail", stream=stream, pk=vendor_id)


# =============================================================================
# TEAM CHAT / COLLABORATION
# =============================================================================

from collections import defaultdict  # noqa: E402
