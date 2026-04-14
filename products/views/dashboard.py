"""Products app — Dashboard views."""

# pylint: disable=too-many-lines

from collections import Counter

from ._helpers import (
    AICalibrationReport,
    AIModelTrainingLog,
    AssetLifecycleRecord,
    AssetLifecycleStage,
    AssetLifecycleTransition,
    AuditLog,
    BuildServer,
    CalibrationCertificate,
    CalibrationRecord,
    CalibrationSchedule,
    Category,
    ComplianceAlert,
    ComplianceDocument,
    ComplianceDocumentVersion,
    Count,
    Floor,
    HolisticSystem,
    InventoryAlert,
    InventoryForecast,
    InventoryThreshold,
    Location,
    MaintenanceEvent,
    NLQueryLog,
    Note,
    OCRProcessingResult,
    OperatingSystem,
    Product,
    ProductHistory,
    Project,
    RecurringReservation,
    RegulatoryChecklist,
    RegulatoryRequirement,
    ReservationConflict,
    ReservationWaitlist,
    SchedulerRecommendation,
    SharedNote,
    SubLevel,
    SubLevelHistory,
    System,
    SystemAllocation,
    SystemDowntime,
    TruncMonth,
    UsageTracking,
    User,
    UserStreamAccess,
    datetime,
    get_bu_streams,
    get_stream_or_404,
    json,
    login_required,
    np,
    render,
    timedelta,
    timezone,
)

__all__ = [
    "analytics_dashboard",
]


@login_required
def analytics_dashboard(request):  # noqa: C901, CCR001
    # pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-complex
    """Analytics dashboard."""
    if not request.user.is_authenticated:
        return render(request, "products/please_login.html")
    selected_stream = request.GET.get("stream", "")

    date_range = request.GET.get("range", "all")  # all, year, quarter, month, custom
    start_date = request.GET.get("start", "")
    end_date = request.GET.get("end", "")

    today = timezone.now().date()
    date_filter = None
    end_date_parsed = None

    if date_range == "year":
        date_filter = today.replace(month=1, day=1)
    elif date_range == "quarter":
        current_quarter = (today.month - 1) // 3
        date_filter = today.replace(month=current_quarter * 3 + 1, day=1)
    elif date_range == "month":
        date_filter = today.replace(day=1)
    elif date_range == "custom" and start_date and end_date:
        try:
            date_filter = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date_parsed = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            date_filter = None
            end_date_parsed = None
    stream_obj = None
    if selected_stream:
        stream_obj = get_stream_or_404(selected_stream, request=request)

    bu_stream_qs = get_bu_streams(request)

    # Category usage (most/least used)
    if stream_obj:
        category_usage = (
            Category.objects.filter(stream=stream_obj)
            .annotate(product_count=Count("products"))
            .order_by("-product_count")
        )
        products_qs = Product.objects.filter(stream=stream_obj)
    else:
        category_usage = (
            Category.objects.filter(stream__in=bu_stream_qs)
            .annotate(product_count=Count("products"))
            .order_by("-product_count")
        )
        products_qs = Product.objects.filter(stream__in=bu_stream_qs)
    if date_filter:
        if date_range == "custom" and end_date_parsed:
            products_qs = products_qs.filter(created_at__date__gte=date_filter, created_at__date__lte=end_date_parsed)
        else:
            products_qs = products_qs.filter(created_at__date__gte=date_filter)
    total_products = products_qs.count()
    most_used = category_usage.first()
    least_used = category_usage.last()  # Product growth over time (monthly)
    status_counts = {
        "Active": products_qs.filter(status="Active").count(),
        "Not Active": products_qs.filter(status="Not Active").count(),
        "Scraped": products_qs.filter(status="Scraped").count(),
        "Hand-Overed": products_qs.filter(status="Hand-Overed").count(),
        "Issue": products_qs.filter(status="Issue").count(),
    }
    status_counts_json = json.dumps(status_counts)
    if stream_obj:
        systems_qs = System.objects.filter(stream=stream_obj)
    else:
        systems_qs = System.objects.filter(stream__in=bu_stream_qs)

    if date_filter:
        if date_range == "custom" and end_date_parsed:
            systems_qs = systems_qs.filter(created_at__date__gte=date_filter, created_at__date__lte=end_date_parsed)
        else:
            systems_qs = systems_qs.filter(created_at__date__gte=date_filter)

    system_health = {
        "Excellent": systems_qs.filter(health="Excellent").count(),
        "Good": systems_qs.filter(health="Good").count(),
        "Warning": systems_qs.filter(health="Warning").count(),
        "Critical": systems_qs.filter(health="Critical").count(),
    }
    system_health_json = json.dumps(system_health)
    total_systems = systems_qs.count()
    active_systems = systems_qs.filter(status="Active").count()

    # Build Server Statistics
    if stream_obj:
        build_servers_qs = BuildServer.objects.filter(stream=stream_obj)
    else:
        build_servers_qs = BuildServer.objects.filter(stream__in=bu_stream_qs)

    build_server_status = {
        "Active": build_servers_qs.filter(status="Active").count(),
        "Inactive": build_servers_qs.filter(status="Inactive").count(),
        "Maintenance": build_servers_qs.filter(status="Maintenance").count(),
        "Offline": build_servers_qs.filter(status="Offline").count(),
    }
    build_server_status_json = json.dumps(build_server_status)
    total_build_servers = build_servers_qs.count()

    # Project Status Overview
    if stream_obj:
        projects_qs = Project.objects.filter(stream=stream_obj)
    else:
        projects_qs = Project.objects.filter(stream__in=bu_stream_qs)

    project_status = {
        "Running": projects_qs.filter(status="running").count(),
        "On Hold": projects_qs.filter(status="hold").count(),
        "Planned": projects_qs.filter(status="planned").count(),
    }
    project_status_json = json.dumps(project_status)
    total_projects = projects_qs.count()

    # Location-wise Product Distribution
    if stream_obj:
        location_dist = (
            Location.objects.filter(stream=stream_obj)
            .annotate(product_count=Count("product"))
            .order_by("-product_count")[:10]
        )
    else:
        location_dist = (
            Location.objects.filter(stream__in=bu_stream_qs)
            .annotate(product_count=Count("product"))
            .order_by("-product_count")[:10]
        )
    location_dist_json = json.dumps([{"name": loc.name, "product_count": loc.product_count} for loc in location_dist])

    # Recent Activity (last 30 days)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    if stream_obj:
        recent_products_created = Product.objects.filter(stream=stream_obj, created_at__gte=thirty_days_ago).count()
        recent_history = ProductHistory.objects.filter(product__stream=stream_obj, timestamp__gte=thirty_days_ago)
    else:
        recent_products_created = Product.objects.filter(
            stream__in=bu_stream_qs, created_at__gte=thirty_days_ago
        ).count()
        recent_history = ProductHistory.objects.filter(product__stream__in=bu_stream_qs, timestamp__gte=thirty_days_ago)

    recent_edits = recent_history.filter(action="edited").count()
    recent_creates = recent_history.filter(action="created").count()

    # User Activity Metrics
    bu_user_ids = set(
        UserStreamAccess.objects.filter(stream__in=bu_stream_qs).values_list("custom_user__user_id", flat=True)
    )
    total_active_users = (
        User.objects.filter(is_active=True, id__in=bu_user_ids).count()
        if bu_user_ids
        else User.objects.filter(is_active=True).count()
    )
    recent_sessions = (
        UsageTracking.objects.filter(timestamp__gte=thirty_days_ago, user_id__in=bu_user_ids)
        .values("user")
        .distinct()
        .count()
        if bu_user_ids
        else UsageTracking.objects.filter(timestamp__gte=thirty_days_ago).values("user").distinct().count()
    )

    # Top Contributors (users who created/edited most products in this BU)
    if stream_obj:
        top_contributors = (
            ProductHistory.objects.filter(timestamp__gte=thirty_days_ago, product__stream=stream_obj)
            .values("user__username")
            .annotate(action_count=Count("id"))
            .order_by("-action_count")[:5]
        )
    else:
        top_contributors = (
            ProductHistory.objects.filter(timestamp__gte=thirty_days_ago, product__stream__in=bu_stream_qs)
            .values("user__username")
            .annotate(action_count=Count("id"))
            .order_by("-action_count")[:5]
        )
    top_contributors_json = json.dumps(list(top_contributors))
    if stream_obj:
        products_by_month = (
            Product.objects.filter(stream=stream_obj)
            .annotate(month=TruncMonth("created_at"))
            .values("month")
            .annotate(count=Count("id"))
            .order_by("month")
        )
    else:
        products_by_month = (
            Product.objects.filter(stream__in=bu_stream_qs)
            .annotate(month=TruncMonth("created_at"))
            .values("month")
            .annotate(count=Count("id"))
            .order_by("month")
        )
    months = [row["month"].strftime("%Y-%m") if row["month"] else "" for row in products_by_month]
    counts = [row["count"] for row in products_by_month]
    growth_trend = {"months": months, "counts": counts}

    # Recommendations for merging/splitting categories
    counts_list = [cat.product_count for cat in category_usage]
    if counts_list:
        mean = np.mean(counts_list)
        std = np.std(counts_list)
        merge_candidates = [cat for cat in category_usage if cat.product_count < mean - std]
        split_candidates = [cat for cat in category_usage if cat.product_count > mean + std]
    else:
        merge_candidates = []
        split_candidates = []

    recommendations = {
        "merge": [cat.name for cat in merge_candidates],
        "split": [cat.name for cat in split_candidates],
    }

    streams = list(get_bu_streams(request).values_list("name", flat=True).order_by("name"))

    category_usage_json = json.dumps([{"name": cat.name, "product_count": cat.product_count} for cat in category_usage])
    months_json = json.dumps(months)
    counts_json = json.dumps(counts)  # Sub Level Distribution (Products)

    def get_sublevel_product_count(sub):
        return (sub.in_stock or 0) + (sub.in_use or 0) + (sub.scraped or 0)

    if stream_obj:
        sublevel_dist = SubLevel.objects.filter(stream=stream_obj)
    else:
        bu_stream_names = list(bu_stream_qs.values_list("name", flat=True))
        sublevel_dist = SubLevel.objects.filter(stream__in=bu_stream_names)
    sublevel_dist_json = json.dumps(
        [{"name": sub.name, "product_count": get_sublevel_product_count(sub)} for sub in sublevel_dist]
    )  # Sub Level Growth Trend
    if stream_obj:
        sublevel_histories = SubLevelHistory.objects.filter(sublevel__stream=stream_obj)
    else:
        sublevel_histories = SubLevelHistory.objects.filter(sublevel__stream__in=bu_stream_names)
    created_histories = [h for h in sublevel_histories if h.action == "Created"]

    def format_month(dt):
        return dt.strftime("%Y-%m")

    month_counts = Counter(format_month(h.at) for h in created_histories)
    months_sorted = sorted(month_counts.keys())
    sublevel_growth_months_json = json.dumps(months_sorted)
    sublevel_growth_counts_json = json.dumps([month_counts[m] for m in months_sorted])
    if stream_obj:
        downtime_events = SystemDowntime.objects.filter(stream=stream_obj)
    else:
        downtime_events = SystemDowntime.objects.filter(stream__in=bu_stream_qs)

    downtime_by_type = {}
    for dt_type, dt_label in SystemDowntime.DOWNTIME_TYPES:
        downtime_by_type[dt_label] = downtime_events.filter(downtime_type=dt_type).count()
    downtime_by_type_json = json.dumps(downtime_by_type)

    downtime_by_status = {
        "Ongoing": downtime_events.filter(status="ongoing").count(),
        "Resolved": downtime_events.filter(status="resolved").count(),
        "Investigating": downtime_events.filter(status="investigating").count(),
        "Escalated": downtime_events.filter(status="escalated").count(),
    }
    downtime_by_status_json = json.dumps(downtime_by_status)
    total_downtime_events = downtime_events.count()
    active_downtime = downtime_events.filter(status="ongoing").count()

    # Notes Statistics (Notes don't have stream filter)
    notes_qs = Note.objects.all()
    total_notes = notes_qs.count()
    recent_notes = notes_qs.filter(created_at__gte=thirty_days_ago).count()

    # Floor Distribution (BuildServers per Floor)
    if stream_obj:
        floor_dist = (
            Floor.objects.filter(stream=stream_obj)
            .annotate(server_count=Count("buildserver"))
            .order_by("-server_count")
        )
    else:
        floor_dist = (
            Floor.objects.filter(stream__in=bu_stream_qs)
            .annotate(server_count=Count("buildserver"))
            .order_by("-server_count")
        )
    floor_dist_json = json.dumps([{"name": f.name, "server_count": f.server_count} for f in floor_dist])
    total_floors = floor_dist.count()

    # Stream-wise Product Distribution
    stream_product_dist = bu_stream_qs.annotate(product_count=Count("products")).order_by("-product_count")
    stream_product_dist_json = json.dumps(
        [{"name": s.name, "product_count": s.product_count} for s in stream_product_dist]
    )

    # ==========================================================================
    # ALLOCATION, CALIBRATION, REGULATORY, RESERVATION, WAITLIST & COMPLIANCE
    # ==========================================================================

    # System Allocations
    if stream_obj:
        allocations_qs = SystemAllocation.objects.filter(stream=stream_obj)
    else:
        allocations_qs = SystemAllocation.objects.filter(stream__in=bu_stream_qs)
    total_allocations = allocations_qs.count()
    active_allocations = allocations_qs.filter(end_date__gte=timezone.now()).count()
    recent_allocations = allocations_qs.filter(created_at__gte=thirty_days_ago).count()

    # Calibration Stats
    if stream_obj:
        calibration_qs = CalibrationSchedule.objects.filter(stream=stream_obj)
    else:
        calibration_qs = CalibrationSchedule.objects.filter(stream__in=bu_stream_qs)
    total_calibrations = calibration_qs.count()
    calibrations_overdue = calibration_qs.filter(status="overdue").count()
    calibrations_due = calibration_qs.filter(status="due").count()
    calibrations_scheduled = calibration_qs.filter(status="scheduled").count()
    calibrations_completed = calibration_qs.filter(status="completed").count()
    calibrations_in_progress = calibration_qs.filter(status="in_progress").count()

    calibration_by_type = {}
    for cal_type, cal_label in CalibrationSchedule.CALIBRATION_TYPES:
        cnt = calibration_qs.filter(calibration_type=cal_type).count()
        if cnt > 0:
            calibration_by_type[cal_label] = cnt
    calibration_by_type_json = json.dumps(calibration_by_type)

    calibration_status_data = {
        "Scheduled": calibrations_scheduled,
        "Due": calibrations_due,
        "Overdue": calibrations_overdue,
        "In Progress": calibrations_in_progress,
        "Completed": calibrations_completed,
    }
    calibration_status_json = json.dumps(calibration_status_data)

    if stream_obj:
        cal_records_qs = CalibrationRecord.objects.filter(calibration_schedule__stream=stream_obj)
    else:
        cal_records_qs = CalibrationRecord.objects.filter(calibration_schedule__stream__in=bu_stream_qs)
    total_cal_records = cal_records_qs.count()
    cal_pass_rate = cal_records_qs.filter(result__in=["pass", "pass_adjusted"]).count()
    cal_fail_count = cal_records_qs.filter(result="fail").count()

    if stream_obj:
        cal_certs_qs = CalibrationCertificate.objects.filter(
            calibration_record__calibration_schedule__stream=stream_obj
        )
    else:
        cal_certs_qs = CalibrationCertificate.objects.filter(
            calibration_record__calibration_schedule__stream__in=bu_stream_qs
        )
    total_certificates = cal_certs_qs.count()
    expired_certificates = sum(1 for c in cal_certs_qs if c.is_expired())
    expiring_soon_certificates = sum(1 for c in cal_certs_qs if c.is_expiring_soon(60) and not c.is_expired())

    # Regulatory / Compliance Stats
    if stream_obj:
        reg_qs = RegulatoryRequirement.objects.filter(applicable_streams=stream_obj)
    else:
        reg_qs = RegulatoryRequirement.objects.filter(applicable_streams__in=bu_stream_qs).distinct()
    total_requirements = reg_qs.count()
    req_compliant = reg_qs.filter(compliance_status="compliant").count()
    req_partial = reg_qs.filter(compliance_status="partial").count()
    req_non_compliant = reg_qs.filter(compliance_status="non_compliant").count()
    req_under_review = reg_qs.filter(compliance_status="under_review").count()

    regulatory_status_data = {
        "Compliant": req_compliant,
        "Partially Compliant": req_partial,
        "Non-Compliant": req_non_compliant,
        "Under Review": req_under_review,
    }
    regulatory_status_json = json.dumps(regulatory_status_data)

    if stream_obj:
        comp_docs_qs = ComplianceDocument.objects.filter(stream=stream_obj)
    else:
        comp_docs_qs = ComplianceDocument.objects.filter(stream__in=bu_stream_qs)
    total_comp_docs = comp_docs_qs.count()
    approved_docs = comp_docs_qs.filter(status="approved").count()
    pending_review_docs = comp_docs_qs.filter(status="pending_review").count()

    if stream_obj:
        comp_alerts_qs = ComplianceAlert.objects.filter(stream=stream_obj)
    else:
        comp_alerts_qs = ComplianceAlert.objects.filter(stream__in=bu_stream_qs)
    total_comp_alerts = comp_alerts_qs.count()
    active_comp_alerts = comp_alerts_qs.filter(status="active").count()
    critical_alerts = comp_alerts_qs.filter(severity="critical", status="active").count()
    urgent_alerts = comp_alerts_qs.filter(severity="urgent", status="active").count()

    if stream_obj:
        checklists_qs = RegulatoryChecklist.objects.filter(stream=stream_obj)
    else:
        checklists_qs = RegulatoryChecklist.objects.filter(stream__in=bu_stream_qs)
    total_checklists = checklists_qs.count()
    completed_checklists = checklists_qs.filter(status="completed").count()
    in_progress_checklists = checklists_qs.filter(status="in_progress").count()

    # Reservation & Waitlist Stats
    if stream_obj:
        reservations_qs = RecurringReservation.objects.filter(stream=stream_obj)
    else:
        reservations_qs = RecurringReservation.objects.filter(stream__in=bu_stream_qs)
    total_reservations = reservations_qs.count()
    active_reservations = reservations_qs.filter(status="active").count()
    paused_reservations = reservations_qs.filter(status="paused").count()

    reservation_recurrence_data = {}
    for rec_type, rec_label in RecurringReservation.RECURRENCE_TYPES:
        cnt = reservations_qs.filter(recurrence_type=rec_type).count()
        if cnt > 0:
            reservation_recurrence_data[rec_label] = cnt
    reservation_recurrence_json = json.dumps(reservation_recurrence_data)

    if stream_obj:
        waitlist_qs = ReservationWaitlist.objects.filter(stream=stream_obj)
    else:
        waitlist_qs = ReservationWaitlist.objects.filter(stream__in=bu_stream_qs)
    total_waitlist = waitlist_qs.count()
    waiting_entries = waitlist_qs.filter(status="waiting").count()
    fulfilled_entries = waitlist_qs.filter(status="fulfilled").count()
    expired_entries = waitlist_qs.filter(status="expired").count()
    not_allocated_entries = waitlist_qs.filter(status="not_allocated").count()

    waitlist_status_data = {
        "Waiting": waiting_entries,
        "Notified": waitlist_qs.filter(status="notified").count(),
        "Fulfilled": fulfilled_entries,
        "Expired": expired_entries,
        "Not Allocated": not_allocated_entries,
    }
    waitlist_status_json = json.dumps(waitlist_status_data)

    if stream_obj:
        conflicts_qs = ReservationConflict.objects.filter(stream=stream_obj)
    else:
        conflicts_qs = ReservationConflict.objects.filter(stream__in=bu_stream_qs)
    total_conflicts = conflicts_qs.count()
    pending_conflicts = conflicts_qs.filter(resolution_status="pending").count()

    # ==========================================================================
    # ASSET LIFECYCLE MANAGEMENT
    # ==========================================================================
    if stream_obj:
        lifecycle_qs = AssetLifecycleRecord.objects.filter(product__stream=stream_obj)
    else:
        lifecycle_qs = AssetLifecycleRecord.objects.filter(product__stream__in=bu_stream_qs)
    total_lifecycle_records = lifecycle_qs.count()

    lifecycle_stage_dist = {}
    for stage in AssetLifecycleStage.objects.filter(is_active=True).order_by("order"):
        count = lifecycle_qs.filter(current_stage=stage).count()
        if count > 0:
            lifecycle_stage_dist[stage.name] = count
    lifecycle_stage_dist_json = json.dumps(lifecycle_stage_dist)

    lifecycle_condition_dist = {}
    for cond_key, cond_label in AssetLifecycleRecord.CONDITION_CHOICES:
        count = lifecycle_qs.filter(condition=cond_key).count()
        if count > 0:
            lifecycle_condition_dist[cond_label] = count
    lifecycle_condition_dist_json = json.dumps(lifecycle_condition_dist)

    warranty_active = sum(1 for r in lifecycle_qs if r.warranty_status == "active")
    warranty_expiring = sum(1 for r in lifecycle_qs if r.warranty_status == "expiring_soon")
    warranty_expired = sum(1 for r in lifecycle_qs if r.warranty_status == "expired")
    warranty_status_data = {
        "Active": warranty_active,
        "Expiring Soon": warranty_expiring,
        "Expired": warranty_expired,
    }
    warranty_status_json = json.dumps(warranty_status_data)

    recent_transitions = AssetLifecycleTransition.objects.filter(
        timestamp__gte=thirty_days_ago, lifecycle__product__stream__in=bu_stream_qs
    ).count()

    total_purchase_cost = sum(float(r.purchase_cost or 0) for r in lifecycle_qs)
    total_maintenance_cost = sum(float(r.total_maintenance_cost or 0) for r in lifecycle_qs)

    # ==========================================================================
    # INVENTORY ALERTS & THRESHOLDS
    # ==========================================================================
    if stream_obj:
        inv_alerts_qs = InventoryAlert.objects.filter(stream=stream_obj)
        inv_thresholds_qs = InventoryThreshold.objects.filter(stream=stream_obj)
    else:
        inv_alerts_qs = InventoryAlert.objects.filter(stream__in=bu_stream_qs)
        inv_thresholds_qs = InventoryThreshold.objects.filter(stream__in=bu_stream_qs)
    total_inv_alerts = inv_alerts_qs.count()
    active_inv_alerts = inv_alerts_qs.filter(status="active").count()
    critical_inv_alerts = inv_alerts_qs.filter(severity="critical", status="active").count()
    resolved_inv_alerts = inv_alerts_qs.filter(status="resolved").count()
    total_inv_thresholds = inv_thresholds_qs.filter(is_active=True).count()

    inv_alert_type_dist = {}
    for atype, alabel in InventoryThreshold.ALERT_TYPES:
        cnt = inv_alerts_qs.filter(alert_type=atype, status="active").count()
        if cnt > 0:
            inv_alert_type_dist[alabel] = cnt
    inv_alert_type_dist_json = json.dumps(inv_alert_type_dist)

    # ==========================================================================
    # MAINTENANCE CALENDAR
    # ==========================================================================
    if stream_obj:
        maint_events_qs = MaintenanceEvent.objects.filter(stream=stream_obj)
    else:
        maint_events_qs = MaintenanceEvent.objects.filter(stream__in=bu_stream_qs)
    total_maint_events = maint_events_qs.count()
    scheduled_maint = maint_events_qs.filter(status="scheduled").count()
    completed_maint = maint_events_qs.filter(status="completed").count()
    overdue_maint = maint_events_qs.filter(status="overdue").count()
    in_progress_maint = maint_events_qs.filter(status="in_progress").count()

    maint_by_type = {}
    for etype, elabel in MaintenanceEvent.EVENT_TYPES:
        cnt = maint_events_qs.filter(event_type=etype).count()
        if cnt > 0:
            maint_by_type[elabel] = cnt
    maint_by_type_json = json.dumps(maint_by_type)

    maint_status_data = {
        "Scheduled": scheduled_maint,
        "In Progress": in_progress_maint,
        "Completed": completed_maint,
        "Overdue": overdue_maint,
    }
    maint_status_json = json.dumps(maint_status_data)

    # ==========================================================================
    # AUDIT LOG STATS
    # ==========================================================================
    audit_qs = AuditLog.objects.filter(stream__in=bu_stream_qs)
    total_audit_entries = audit_qs.count()
    recent_audit_entries = audit_qs.filter(timestamp__gte=thirty_days_ago).count()

    audit_by_module = {}
    for mod_key, mod_label in AuditLog.MODULE_CHOICES:
        cnt = audit_qs.filter(module=mod_key, timestamp__gte=thirty_days_ago).count()
        if cnt > 0:
            audit_by_module[mod_label] = cnt
    audit_by_module_json = json.dumps(audit_by_module)

    audit_by_action = {}
    for act_key, act_label in AuditLog.ACTION_CATEGORIES:
        cnt = audit_qs.filter(action=act_key, timestamp__gte=thirty_days_ago).count()
        if cnt > 0:
            audit_by_action[act_label] = cnt
    audit_by_action_json = json.dumps(audit_by_action)

    # ==========================================================================
    # HOLISTIC SYSTEMS
    # ==========================================================================
    if stream_obj:
        holistic_qs = HolisticSystem.objects.filter(stream=stream_obj)
    else:
        holistic_qs = HolisticSystem.objects.filter(stream__in=bu_stream_qs)
    total_holistic_systems = holistic_qs.count()

    holistic_status_dist = {}
    for skey, slabel in HolisticSystem.STATUS_CHOICES:
        cnt = holistic_qs.filter(system_availability=skey).count()
        if cnt > 0:
            holistic_status_dist[slabel] = cnt
    holistic_status_dist_json = json.dumps(holistic_status_dist)

    # ==========================================================================
    # AI FEATURES STATS
    # ==========================================================================
    if stream_obj:
        ai_cal_reports_qs = AICalibrationReport.objects.filter(stream=stream_obj)
        ai_ocr_qs = OCRProcessingResult.objects.filter(stream=stream_obj)
        ai_nl_qs = NLQueryLog.objects.all()  # NL queries are not stream-specific
        ai_forecast_qs = InventoryForecast.objects.filter(stream=stream_obj)
        ai_scheduler_qs = SchedulerRecommendation.objects.filter(stream=stream_obj)
    else:
        ai_cal_reports_qs = AICalibrationReport.objects.filter(stream__in=bu_stream_qs)
        ai_ocr_qs = OCRProcessingResult.objects.filter(stream__in=bu_stream_qs)
        ai_nl_qs = NLQueryLog.objects.all()
        ai_forecast_qs = InventoryForecast.objects.filter(stream__in=bu_stream_qs)
        ai_scheduler_qs = SchedulerRecommendation.objects.filter(stream__in=bu_stream_qs)

    total_ai_cal_reports = ai_cal_reports_qs.count()
    total_ocr_processed = ai_ocr_qs.count()
    ocr_success = ai_ocr_qs.filter(status="completed").count()
    total_nl_queries = ai_nl_qs.count()
    nl_successful = ai_nl_qs.filter(was_successful=True).count()
    total_forecasts = ai_forecast_qs.count()
    total_scheduler_recs = ai_scheduler_qs.count()
    scheduler_accepted = ai_scheduler_qs.filter(was_accepted=True).count()
    total_model_trainings = AIModelTrainingLog.objects.count()
    successful_trainings = AIModelTrainingLog.objects.filter(was_successful=True).count()

    ai_ocr_status_dist = {}
    for skey, slabel in OCRProcessingResult.PROCESSING_STATUS:
        cnt = ai_ocr_qs.filter(status=skey).count()
        if cnt > 0:
            ai_ocr_status_dist[slabel] = cnt
    ai_ocr_status_dist_json = json.dumps(ai_ocr_status_dist)

    nl_feedback_dist = {
        "Helpful": ai_nl_qs.filter(user_feedback="helpful").count(),
        "Not Helpful": ai_nl_qs.filter(user_feedback="not_helpful").count(),
        "Wrong Result": ai_nl_qs.filter(user_feedback="wrong").count(),
        "No Feedback": ai_nl_qs.filter(user_feedback="").count(),
    }
    nl_feedback_dist_json = json.dumps(nl_feedback_dist)

    # ==========================================================================
    # OPERATING SYSTEMS & DOCUMENT VERSIONING
    # ==========================================================================
    if stream_obj:
        os_qs = OperatingSystem.objects.filter(stream=stream_obj, is_active=True)
    else:
        os_qs = OperatingSystem.objects.filter(stream__in=bu_stream_qs, is_active=True)
    total_operating_systems = os_qs.count()

    total_doc_versions = ComplianceDocumentVersion.objects.count()

    # ==========================================================================
    # USAGE TRACKING (Most Visited Pages)
    # ==========================================================================
    top_pages = (
        UsageTracking.objects.filter(timestamp__gte=thirty_days_ago)
        .values("page_name")
        .annotate(visit_count=Count("id"))
        .order_by("-visit_count")[:10]
    )
    top_pages_json = json.dumps(list(top_pages))

    total_shared_notes = SharedNote.objects.count()

    return render(
        request,
        "products/analytics_dashboard.html",
        {
            "category_usage": category_usage,
            "most_used": most_used,
            "least_used": least_used,
            "growth_trend": growth_trend,
            "recommendations": recommendations,
            "total_products": total_products,
            "streams": streams,
            "selected_stream": selected_stream,
            "category_usage_json": category_usage_json,
            "months_json": months_json,
            "counts_json": counts_json,
            "sublevel_dist_json": sublevel_dist_json,
            "sublevel_growth_months_json": sublevel_growth_months_json,
            "sublevel_growth_counts_json": sublevel_growth_counts_json,
            "status_counts": status_counts,
            "status_counts_json": status_counts_json,
            "system_health": system_health,
            "system_health_json": system_health_json,
            "total_systems": total_systems,
            "active_systems": active_systems,
            "build_server_status": build_server_status,
            "build_server_status_json": build_server_status_json,
            "total_build_servers": total_build_servers,
            "project_status": project_status,
            "project_status_json": project_status_json,
            "total_projects": total_projects,
            "location_dist_json": location_dist_json,
            "recent_products_created": recent_products_created,
            "recent_edits": recent_edits,
            "recent_creates": recent_creates,
            "total_active_users": total_active_users,
            "recent_sessions": recent_sessions,
            "top_contributors_json": top_contributors_json,
            "downtime_by_type_json": downtime_by_type_json,
            "downtime_by_status": downtime_by_status,
            "downtime_by_status_json": downtime_by_status_json,
            "total_downtime_events": total_downtime_events,
            "active_downtime": active_downtime,
            "total_notes": total_notes,
            "recent_notes": recent_notes,
            "floor_dist_json": floor_dist_json,
            "total_floors": total_floors,
            "stream_product_dist_json": stream_product_dist_json,
            "selected_range": date_range,
            "selected_start_date": start_date,
            "selected_end_date": end_date,
            "total_allocations": total_allocations,
            "active_allocations": active_allocations,
            "recent_allocations": recent_allocations,
            "total_calibrations": total_calibrations,
            "calibrations_overdue": calibrations_overdue,
            "calibrations_due": calibrations_due,
            "calibrations_scheduled": calibrations_scheduled,
            "calibrations_completed": calibrations_completed,
            "calibrations_in_progress": calibrations_in_progress,
            "calibration_by_type_json": calibration_by_type_json,
            "calibration_status_json": calibration_status_json,
            "total_cal_records": total_cal_records,
            "cal_pass_rate": cal_pass_rate,
            "cal_fail_count": cal_fail_count,
            "total_certificates": total_certificates,
            "expired_certificates": expired_certificates,
            "expiring_soon_certificates": expiring_soon_certificates,
            "total_requirements": total_requirements,
            "req_compliant": req_compliant,
            "req_partial": req_partial,
            "req_non_compliant": req_non_compliant,
            "req_under_review": req_under_review,
            "regulatory_status_json": regulatory_status_json,
            "total_comp_docs": total_comp_docs,
            "approved_docs": approved_docs,
            "pending_review_docs": pending_review_docs,
            "total_comp_alerts": total_comp_alerts,
            "active_comp_alerts": active_comp_alerts,
            "critical_alerts": critical_alerts,
            "urgent_alerts": urgent_alerts,
            "total_checklists": total_checklists,
            "completed_checklists": completed_checklists,
            "in_progress_checklists": in_progress_checklists,
            "total_reservations": total_reservations,
            "active_reservations": active_reservations,
            "paused_reservations": paused_reservations,
            "reservation_recurrence_json": reservation_recurrence_json,
            "total_waitlist": total_waitlist,
            "waiting_entries": waiting_entries,
            "fulfilled_entries": fulfilled_entries,
            "expired_entries": expired_entries,
            "not_allocated_entries": not_allocated_entries,
            "waitlist_status_json": waitlist_status_json,
            "total_conflicts": total_conflicts,
            "pending_conflicts": pending_conflicts,
            "total_lifecycle_records": total_lifecycle_records,
            "lifecycle_stage_dist_json": lifecycle_stage_dist_json,
            "lifecycle_condition_dist_json": lifecycle_condition_dist_json,
            "warranty_status_json": warranty_status_json,
            "recent_transitions": recent_transitions,
            "total_purchase_cost": total_purchase_cost,
            "total_maintenance_cost": total_maintenance_cost,
            "total_inv_alerts": total_inv_alerts,
            "active_inv_alerts": active_inv_alerts,
            "critical_inv_alerts": critical_inv_alerts,
            "resolved_inv_alerts": resolved_inv_alerts,
            "total_inv_thresholds": total_inv_thresholds,
            "inv_alert_type_dist_json": inv_alert_type_dist_json,
            "total_maint_events": total_maint_events,
            "scheduled_maint": scheduled_maint,
            "completed_maint": completed_maint,
            "overdue_maint": overdue_maint,
            "in_progress_maint": in_progress_maint,
            "maint_by_type_json": maint_by_type_json,
            "maint_status_json": maint_status_json,
            "total_audit_entries": total_audit_entries,
            "recent_audit_entries": recent_audit_entries,
            "audit_by_module_json": audit_by_module_json,
            "audit_by_action_json": audit_by_action_json,
            "total_holistic_systems": total_holistic_systems,
            "holistic_status_dist_json": holistic_status_dist_json,
            "total_ai_cal_reports": total_ai_cal_reports,
            "total_ocr_processed": total_ocr_processed,
            "ocr_success": ocr_success,
            "total_nl_queries": total_nl_queries,
            "nl_successful": nl_successful,
            "total_forecasts": total_forecasts,
            "total_scheduler_recs": total_scheduler_recs,
            "scheduler_accepted": scheduler_accepted,
            "total_model_trainings": total_model_trainings,
            "successful_trainings": successful_trainings,
            "ai_ocr_status_dist_json": ai_ocr_status_dist_json,
            "nl_feedback_dist_json": nl_feedback_dist_json,
            "total_operating_systems": total_operating_systems,
            "total_doc_versions": total_doc_versions,
            "top_pages_json": top_pages_json,
            "total_shared_notes": total_shared_notes,
        },
    )
