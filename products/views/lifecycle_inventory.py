"""Products app - Asset Lifecycle, Inventory Alerts, and Threshold Management views."""

# pylint: disable=too-many-lines,broad-exception-caught

from ._helpers import (
    AssetLifecycleRecord,
    AssetLifecycleStage,
    AssetLifecycleTransition,
    AuditLog,
    CalibrationSchedule,
    Category,
    ComplianceAlert,
    ComplianceDocument,
    Count,
    DashboardWidget,
    InventoryAlert,
    JsonResponse,
    Paginator,
    Product,
    Project,
    Q,
    RecurringReservationInstance,
    Stream,
    SubLevel,
    System,
    User,
    UserSession,
    VendorModel,
    date,
    get_current_bu,
    get_object_or_404,
    get_stream_or_404,
    is_admin,
    is_super_admin,
    login_required,
    messages,
    redirect,
    render,
    require_POST,
    timedelta,
    user_passes_test,
)
from ..approval_triggers import check_approval_required

__all__ = [
    "dashboard_widget_data",
    "asset_lifecycle_list",
    "asset_lifecycle_bulk_enroll",
    "asset_lifecycle_create",
    "asset_lifecycle_detail",
    "asset_lifecycle_edit",
    "asset_lifecycle_transition",
    "asset_lifecycle_dashboard",
]


@user_passes_test(is_super_admin)
@login_required
def dashboard_widget_data(request, widget_type):  # noqa: C901, CCR001
    """Get data for a specific widget type."""
    # pylint: disable=too-complex
    stream_name = request.GET.get("stream", "")
    stream_obj = None
    if stream_name:
        stream_obj = Stream.objects.filter(name=stream_name).first()

    data = {}

    if widget_type == "stat_card":
        data = {
            "products": Product.objects.count(),
            "systems": System.objects.filter(stream=stream_obj).count() if stream_obj else System.objects.count(),
            "users": User.objects.filter(is_active=True).count(),
            "online": UserSession.objects.filter(is_active=True).count(),
            "categories": (
                Category.objects.filter(stream=stream_obj).count() if stream_obj else Category.objects.count()
            ),
        }

    elif widget_type == "system_health":
        systems = System.objects.filter(stream=stream_obj) if stream_obj else System.objects.all()
        data = {
            "total": systems.count(),
            "active": systems.filter(status="Active").count(),
            "not_active": systems.filter(status="Not Active").count(),
            "issue": systems.filter(status="Issue").count(),
            "removed": systems.filter(status="Removed").count(),
        }

    elif widget_type == "timeline":
        recent = AuditLog.objects.select_related("user").all()[:10]
        data = {
            "events": [
                {
                    "timestamp": e.timestamp.isoformat(),
                    "action": e.get_action_display(),
                    "user": e.user_display_name,
                    "title": e.title,
                    "severity": e.severity,
                    "module": e.get_module_display(),
                }
                for e in recent
            ]
        }

    elif widget_type == "alerts":
        active_alerts = InventoryAlert.objects.filter(status="active")[:10]
        compliance_alerts = ComplianceAlert.objects.filter(status="active")[:5]
        data = {
            "inventory_alerts": [
                {
                    "title": a.title,
                    "severity": a.severity,
                    "created_at": a.created_at.isoformat(),
                }
                for a in active_alerts
            ],
            "compliance_alerts": [
                {
                    "title": a.title,
                    "severity": a.severity,
                    "created_at": a.created_at.isoformat(),
                }
                for a in compliance_alerts
            ],
        }

    elif widget_type == "reservations":
        user_reservations = RecurringReservationInstance.objects.filter(
            recurring_reservation__created_by=request.user, status__in=["scheduled", "confirmed"]
        ).order_by("reservation_date")[:10]
        data = {
            "reservations": [
                {
                    "title": r.recurring_reservation.title,
                    "date": r.reservation_date.isoformat(),
                    "start_time": r.start_time.strftime("%H:%M"),
                    "end_time": r.end_time.strftime("%H:%M"),
                    "status": r.status,
                }
                for r in user_reservations
            ]
        }

    elif widget_type == "calibration":
        overdue = CalibrationSchedule.objects.filter(status="overdue").count()
        due_soon = CalibrationSchedule.objects.filter(
            next_calibration_date__lte=date.today() + timedelta(days=30), status__in=["scheduled", "due"]
        ).count()
        completed = CalibrationSchedule.objects.filter(status="completed").count()
        data = {"overdue": overdue, "due_soon": due_soon, "completed": completed}

    elif widget_type == "projects":
        projects = Project.objects.all()[:10]
        data = {
            "projects": [
                {
                    "name": p.name,
                    "status": p.status,
                    "progress": p.progress_percentage,
                    "expected": p.expected_progress,
                    "priority": p.priority,
                }
                for p in projects
            ]
        }

    elif widget_type == "inventory":
        data = {
            "total_sublevels": SubLevel.objects.count(),
            "low_stock_alerts": InventoryAlert.objects.filter(
                alert_type__in=["low_stock", "critical_stock"], status="active"
            ).count(),
        }

    elif widget_type == "compliance":
        data = {
            "documents": ComplianceDocument.objects.count(),
            "active_alerts": ComplianceAlert.objects.filter(status="active").count(),
            "pending_review": ComplianceDocument.objects.filter(status="pending_review").count(),
        }

    elif widget_type == "utilization":
        systems = System.objects.filter(stream=stream_obj) if stream_obj else System.objects.all()
        data = {
            "systems": [
                {
                    "name": s.name,
                    "utilization": s.utilization_percentage,
                }
                for s in systems[:10]
            ]
        }

    return JsonResponse({"success": True, "data": data})


def _ensure_default_widgets_exist():
    """Create default DashboardWidget definitions if they don't exist."""
    defaults = [
        ("stat_card", "Statistics Overview", "fas fa-chart-pie", "full", False),
        ("system_health", "System Health", "fas fa-heartbeat", "medium", True),
        ("timeline", "Activity Timeline", "fas fa-stream", "medium", False),
        ("alerts", "Active Alerts", "fas fa-exclamation-triangle", "medium", False),
        ("reservations", "My Reservations", "fas fa-calendar-check", "medium", True),
        ("calibration", "Calibration Status", "fas fa-tools", "medium", True),
        ("projects", "Project Status", "fas fa-project-diagram", "medium", False),
        ("inventory", "Inventory Summary", "fas fa-boxes", "medium", True),
        ("compliance", "Compliance Status", "fas fa-shield-alt", "medium", True),
        ("utilization", "Utilization Overview", "fas fa-chart-bar", "medium", True),
        ("notes", "My Notes", "fas fa-sticky-note", "medium", False),
        ("quick_links", "Quick Links", "fas fa-link", "small", False),
    ]
    for wtype, name, icon, size, req_stream in defaults:
        DashboardWidget.objects.get_or_create(
            widget_type=wtype,
            defaults={
                "name": name,
                "icon_class": icon,
                "default_size": size,
                "requires_stream": req_stream,
            },
        )


# =============================================================================
# FEATURE 3: ASSET LIFECYCLE MANAGEMENT
# =============================================================================


def _ensure_lifecycle_stages_exist():
    """Create default lifecycle stages if they don't exist."""
    stages = [
        ("Procurement", "procurement", "fas fa-shopping-cart", "#d4a017", 1, False),
        ("Receiving", "receiving", "fas fa-truck-loading", "#0B5FFF", 2, False),
        ("Commissioning", "commissioning", "fas fa-cogs", "#0B5FFF", 3, False),
        ("Active", "active", "fas fa-check-circle", "#11998e", 4, False),
        ("Maintenance", "maintenance", "fas fa-wrench", "#FF9800", 5, False),
        ("Repair", "repair", "fas fa-tools", "#dc3545", 6, True),
        ("Idle", "idle", "fas fa-pause-circle", "#6c757d", 7, False),
        ("Hand-Over", "handover", "fas fa-handshake", "#0044CC", 8, True),
        ("Decommissioning", "decommission", "fas fa-power-off", "#e74c3c", 9, True),
        ("Disposal", "disposal", "fas fa-trash-alt", "#343a40", 10, True),
        ("Archived", "archived", "fas fa-archive", "#495057", 11, False),
    ]
    for name, stype, icon, color, order, requires_approval in stages:
        AssetLifecycleStage.objects.get_or_create(
            stage_type=stype,
            defaults={
                "name": name,
                "icon_class": icon,
                "color": color,
                "order": order,
                "requires_approval": requires_approval,
            },
        )


@user_passes_test(is_super_admin)
@login_required
def asset_lifecycle_list(request, stream=None):
    """List all asset lifecycle records for a stream."""
    # pylint: disable=too-many-locals
    stream_obj = get_stream_or_404(stream)
    _ensure_lifecycle_stages_exist()

    records = AssetLifecycleRecord.objects.select_related(
        "product", "current_stage", "product__category", "vendor_link"
    ).filter(product__stream=stream_obj)

    stage = request.GET.get("stage", "")
    condition = request.GET.get("condition", "")
    search = request.GET.get("search", "")

    if stage:
        records = records.filter(current_stage__stage_type=stage)
    if condition:
        records = records.filter(condition=condition)
    if search:
        records = records.filter(
            Q(product__name__icontains=search)
            | Q(product__serial_number__icontains=search)
            | Q(vendor__icontains=search)
        )

    records = records.order_by("-updated_at", "-pk")
    paginator = Paginator(records, 25)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    stages = AssetLifecycleStage.objects.filter(is_active=True)

    total = records.count()
    total_value = sum(float(r.purchase_cost or 0) for r in records)
    warranty_expiring = sum(1 for r in records if r.warranty_status == "expiring_soon")

    # Products in this stream that don't have lifecycle records yet
    enrolled_product_ids = AssetLifecycleRecord.objects.values_list("product_id", flat=True)
    unenrolled_products = (
        Product.objects.filter(stream=stream_obj).exclude(pk__in=enrolled_product_ids).order_by("name")
    )

    if search:
        unenrolled_products = unenrolled_products.filter(Q(name__icontains=search) | Q(serial_number__icontains=search))

    context = {
        "page_obj": page_obj,
        "stages": stages,
        "stream": stream,
        "selected_stream": stream,
        "total": total,
        "total_value": total_value,
        "warranty_expiring": warranty_expiring,
        "selected_stage": stage,
        "selected_condition": condition,
        "search_query": search,
        "condition_choices": AssetLifecycleRecord.CONDITION_CHOICES,
        "unenrolled_products": unenrolled_products,
        "unenrolled_count": unenrolled_products.count(),
    }
    return render(request, "products/asset_lifecycle_list.html", context)


@user_passes_test(is_super_admin)
@login_required
@require_POST
def asset_lifecycle_bulk_enroll(request, stream=None):
    """Bulk-enroll all products in a stream into the lifecycle system."""
    stream_obj = get_stream_or_404(stream)
    _ensure_lifecycle_stages_exist()

    default_stage = AssetLifecycleStage.objects.filter(stage_type="procurement", is_active=True).first()

    enrolled_product_ids = AssetLifecycleRecord.objects.values_list("product_id", flat=True)
    unenrolled = Product.objects.filter(stream=stream_obj).exclude(pk__in=enrolled_product_ids)

    count = 0
    for product in unenrolled:
        AssetLifecycleRecord.objects.create(
            product=product,
            current_stage=default_stage,
            condition="good",
            created_by=request.user,
        )
        count += 1

    if count:
        AuditLog.log(
            "create",
            f"Bulk-enrolled {count} product(s) into lifecycle tracking",
            user=request.user,
            request=request,
            module="inventory",
            stream=stream_obj,
        )
        messages.success(request, f"Successfully enrolled {count} product(s) into lifecycle tracking.")
    else:
        messages.info(request, "All products are already enrolled.")

    return redirect("asset_lifecycle_list", stream=stream)


@user_passes_test(is_super_admin)
@login_required
def asset_lifecycle_create(request, stream=None, product_id=None):  # noqa: CCR001
    """Create a lifecycle record for a product."""
    stream_obj = get_stream_or_404(stream)
    product = get_object_or_404(Product, pk=product_id, stream=stream_obj)
    _ensure_lifecycle_stages_exist()

    if hasattr(product, "lifecycle"):
        messages.info(request, "This product already has a lifecycle record.")
        return redirect("asset_lifecycle_detail", stream=stream, pk=product.lifecycle.pk)

    stages = AssetLifecycleStage.objects.filter(is_active=True)
    bu = get_current_bu(request)
    vendors = VendorModel.objects.filter(business_unit=bu, stream=stream_obj, status="active").order_by("name")

    if request.method == "POST":
        try:
            vendor_link_id = request.POST.get("vendor_link") or None
            vendor_link_obj = None
            if vendor_link_id:
                try:
                    vendor_link_obj = VendorModel.objects.get(pk=vendor_link_id, business_unit=bu, stream=stream_obj)
                except VendorModel.DoesNotExist:
                    vendor_link_obj = None
            # If a vendor is linked and no manual vendor name typed, auto-fill vendor text
            vendor_text = request.POST.get("vendor", "")
            if vendor_link_obj and not vendor_text:
                vendor_text = vendor_link_obj.name
            record = AssetLifecycleRecord.objects.create(
                product=product,
                current_stage_id=request.POST.get("current_stage"),
                purchase_date=request.POST.get("purchase_date") or None,
                purchase_cost=request.POST.get("purchase_cost") or None,
                vendor=vendor_text,
                vendor_link=vendor_link_obj,
                purchase_order_number=request.POST.get("purchase_order_number", ""),
                invoice_number=request.POST.get("invoice_number", ""),
                warranty_start_date=request.POST.get("warranty_start_date") or None,
                warranty_end_date=request.POST.get("warranty_end_date") or None,
                warranty_provider=request.POST.get("warranty_provider", ""),
                warranty_terms=request.POST.get("warranty_terms", ""),
                expected_lifespan_years=request.POST.get("expected_lifespan_years") or None,
                salvage_value=request.POST.get("salvage_value") or None,
                depreciation_method=request.POST.get("depreciation_method", "straight_line"),
                condition=request.POST.get("condition", "new"),
                insurance_policy=request.POST.get("insurance_policy", ""),
                insured_value=request.POST.get("insured_value") or None,
                created_by=request.user,
            )
            AuditLog.log(
                "create",
                f"Created lifecycle record for {product.name}",
                user=request.user,
                request=request,
                obj=record,
                module="inventory",
                stream=stream_obj,
            )
            messages.success(request, f'Lifecycle record created for "{product.name}".')
            return redirect("asset_lifecycle_detail", stream=stream, pk=record.pk)
        except Exception:
            form_error = "An error occurred. Please try again."
    else:
        form_error = None

    context = {
        "product": product,
        "stages": stages,
        "vendors": vendors,
        "stream": stream,
        "selected_stream": stream,
        "condition_choices": AssetLifecycleRecord.CONDITION_CHOICES,
        "form_error": form_error,
    }
    return render(request, "products/asset_lifecycle_form.html", context)


@user_passes_test(is_super_admin)
@login_required
def asset_lifecycle_detail(request, stream=None, pk=None):
    """View lifecycle details for a product."""
    stream_obj = get_stream_or_404(stream)
    record = get_object_or_404(
        AssetLifecycleRecord.objects.select_related("product", "current_stage", "created_by", "vendor_link"),
        pk=pk,
        product__stream=stream_obj,
    )

    transitions = record.transitions.select_related("from_stage", "to_stage", "transitioned_by", "approved_by").all()
    stages = AssetLifecycleStage.objects.filter(is_active=True)

    context = {
        "record": record,
        "transitions": transitions,
        "stages": stages,
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/asset_lifecycle_detail.html", context)


@user_passes_test(is_super_admin)
@login_required
def asset_lifecycle_edit(request, stream=None, pk=None):  # noqa: CCR001
    """Edit a lifecycle record."""
    stream_obj = get_stream_or_404(stream)
    record = get_object_or_404(AssetLifecycleRecord, pk=pk, product__stream=stream_obj)
    stages = AssetLifecycleStage.objects.filter(is_active=True)
    bu = get_current_bu(request)
    vendors = VendorModel.objects.filter(business_unit=bu, stream=stream_obj, status="active").order_by("name")

    if request.method == "POST":
        try:
            vendor_link_id = request.POST.get("vendor_link") or None
            vendor_link_obj = None
            if vendor_link_id:
                try:
                    vendor_link_obj = VendorModel.objects.get(pk=vendor_link_id, business_unit=bu, stream=stream_obj)
                except VendorModel.DoesNotExist:
                    vendor_link_obj = None
            vendor_text = request.POST.get("vendor", "")
            if vendor_link_obj and not vendor_text:
                vendor_text = vendor_link_obj.name
            record.purchase_date = request.POST.get("purchase_date") or None
            record.purchase_cost = request.POST.get("purchase_cost") or None
            record.vendor = vendor_text
            record.vendor_link = vendor_link_obj
            record.purchase_order_number = request.POST.get("purchase_order_number", "")
            record.invoice_number = request.POST.get("invoice_number", "")
            record.warranty_start_date = request.POST.get("warranty_start_date") or None
            record.warranty_end_date = request.POST.get("warranty_end_date") or None
            record.warranty_provider = request.POST.get("warranty_provider", "")
            record.warranty_terms = request.POST.get("warranty_terms", "")
            record.expected_lifespan_years = request.POST.get("expected_lifespan_years") or None
            record.salvage_value = request.POST.get("salvage_value") or None
            record.depreciation_method = request.POST.get("depreciation_method", "straight_line")
            record.condition = request.POST.get("condition", "new")
            record.insurance_policy = request.POST.get("insurance_policy", "")
            record.insured_value = request.POST.get("insured_value") or None
            record.next_maintenance_due = request.POST.get("next_maintenance_due") or None
            record.save()

            AuditLog.log(
                "update",
                f"Updated lifecycle for {record.product.name}",
                user=request.user,
                request=request,
                obj=record,
                module="inventory",
                stream=stream_obj,
            )
            messages.success(request, "Lifecycle record updated.")
            return redirect("asset_lifecycle_detail", stream=stream, pk=record.pk)
        except Exception:
            form_error = "An error occurred. Please try again."
    else:
        form_error = None

    context = {
        "record": record,
        "stages": stages,
        "vendors": vendors,
        "stream": stream,
        "selected_stream": stream,
        "condition_choices": AssetLifecycleRecord.CONDITION_CHOICES,
        "is_edit": True,
        "form_error": form_error,
    }
    return render(request, "products/asset_lifecycle_form.html", context)


@user_passes_test(is_super_admin)
@login_required
@require_POST
def asset_lifecycle_transition(request, stream=None, pk=None):
    """Transition an asset to a new lifecycle stage."""
    stream_obj = get_stream_or_404(stream)
    record = get_object_or_404(AssetLifecycleRecord, pk=pk, product__stream=stream_obj)

    new_stage_id = request.POST.get("new_stage")
    note = request.POST.get("note", "")

    try:
        new_stage = AssetLifecycleStage.objects.get(pk=new_stage_id)
        old_stage_name = record.current_stage.name

        # ── Pre-action enforcement: block high-impact lifecycle transitions ──
        _event_map = {"decommission": "asset_decommission", "disposal": "asset_disposal", "handover": "asset_handover"}
        if new_stage.stage_type in _event_map:
            _approval = check_approval_required(
                _event_map[new_stage.stage_type],
                stream_obj.business_unit,
                request.user,
                entity_obj=record,
                stream=stream_obj,
                title=f"Asset '{record.product.name}' \u2192 {new_stage.name}",
                description=(
                    f"Asset lifecycle transition for {record.product.name} "
                    f"from {old_stage_name} to {new_stage.name}"
                ),
                intended_changes={
                    "action_type": "status_change",
                    "model_label": "products.AssetLifecycleRecord",
                    "pk": record.pk,
                    "changes": {"current_stage_id": new_stage.pk},
                    "revert": {"current_stage_id": record.current_stage.pk},
                    "metadata": {"entity_name": record.product.name, "new_stage": new_stage.name},
                },
            )
            if _approval:
                messages.warning(
                    request,
                    f'\u23f3 Transitioning asset "{record.product.name}" to "{new_stage.name}" '
                    f'requires approval. Request #{_approval.id} submitted.',
                )
                return redirect("asset_lifecycle_detail", stream=stream, pk=record.pk)

        approved_by = request.user if new_stage.requires_approval and is_admin(request.user) else None
        record.transition_to(new_stage, user=request.user, note=note, approved_by=approved_by)

        AuditLog.log(
            "status_change",
            f'Lifecycle transition: {record.product.name} from "{old_stage_name}" to "{new_stage.name}"',
            user=request.user,
            request=request,
            obj=record,
            module="inventory",
            stream=stream_obj,
            old_values={"stage": old_stage_name},
            new_values={"stage": new_stage.name},
        )

        messages.success(request, f'Asset transitioned to "{new_stage.name}" successfully.')
    except ValueError:
        messages.error(request, "Invalid transition. Please check requirements.")
    except Exception:
        messages.error(request, "An error occurred. Please try again.")

    return redirect("asset_lifecycle_detail", stream=stream, pk=record.pk)


@user_passes_test(is_super_admin)
@login_required
def asset_lifecycle_dashboard(request, stream=None):
    """Lifecycle analytics dashboard."""
    # pylint: disable=too-many-locals
    stream_obj = get_stream_or_404(stream)
    _ensure_lifecycle_stages_exist()

    records = AssetLifecycleRecord.objects.filter(product__stream=stream_obj)
    stages = AssetLifecycleStage.objects.filter(is_active=True)

    stage_distribution = []
    for stage in stages:
        count = records.filter(current_stage=stage).count()
        stage_distribution.append({"name": stage.name, "count": count, "color": stage.color})

    condition_dist = list(records.values("condition").annotate(count=Count("id")))

    total_purchase_value = sum(float(r.purchase_cost or 0) for r in records)
    total_book_value = sum(float(r.current_book_value or 0) for r in records)
    total_maintenance_cost = sum(float(r.total_maintenance_cost or 0) for r in records)

    warranty_active = sum(1 for r in records if r.warranty_status == "active")
    warranty_expiring = sum(1 for r in records if r.warranty_status == "expiring_soon")
    warranty_expired = sum(1 for r in records if r.warranty_status == "expired")

    recent_transitions = AssetLifecycleTransition.objects.filter(lifecycle__product__stream=stream_obj).select_related(
        "lifecycle__product", "from_stage", "to_stage", "transitioned_by"
    )[:15]

    context = {
        "stage_distribution": stage_distribution,
        "condition_dist": condition_dist,
        "total_purchase_value": total_purchase_value,
        "total_book_value": total_book_value,
        "total_maintenance_cost": total_maintenance_cost,
        "warranty_active": warranty_active,
        "warranty_expiring": warranty_expiring,
        "warranty_expired": warranty_expired,
        "recent_transitions": recent_transitions,
        "total_assets": records.count(),
        "stream": stream,
        "selected_stream": stream,
    }
    return render(request, "products/asset_lifecycle_dashboard.html", context)


# =============================================================================
# FEATURE 4: INVENTORY ALERTS & THRESHOLDS
# =============================================================================
