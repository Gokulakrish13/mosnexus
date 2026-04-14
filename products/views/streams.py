"""Products app — Streams views."""

# pylint: disable=invalid-name,too-many-lines

from django.db.models import Prefetch

from ._helpers import (
    AuditLog,
    BUDeletionRequest,
    BusinessUnit,
    Count,
    HttpResponse,
    JsonResponse,
    Q,
    Stream,
    StreamDeletionHistory,
    UserBUAccess,
    csv,
    datetime,
    get_current_bu,
    is_app_admin,
    is_super_admin,
    login_required,
    messages,
    redirect,
    render,
    require_POST,
    timezone,
)

__all__ = [
    "manage_streams",
    "export_streams_csv",
    "clone_stream",
    "manage_business_units",
    "bu_deletion_review",
    "bu_deletion_cancel",
]


@login_required
def manage_streams(request):  # noqa: C901, CCR001
    """Manage dynamic streams."""
    # pylint: disable=too-complex,too-many-branches,too-many-locals,too-many-nested-blocks,too-many-statements
    if not is_super_admin(request.user):
        messages.error(request, "Only Super Admins can manage streams.")
        return redirect("dashboard")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create":
            name = request.POST.get("name")
            description = request.POST.get("description", "")
            allow_public_registration = request.POST.get("allow_public_registration") == "on"
            requires_approval = request.POST.get("requires_approval") == "on"

            # Auto-assign to current BU; fall back to form value
            current_bu = get_current_bu(request)
            if current_bu:
                bu_obj = current_bu
            else:
                bu_id = request.POST.get("business_unit") or None
                bu_obj = None
                if bu_id:
                    try:
                        bu_obj = BusinessUnit.objects.get(id=bu_id)
                    except BusinessUnit.DoesNotExist:
                        pass

            if Stream.objects.filter(name=name).exists():
                messages.error(request, f'Stream "{name}" already exists.')
            else:
                Stream.objects.create(
                    name=name,
                    description=description,
                    allow_public_registration=allow_public_registration,
                    requires_approval=requires_approval,
                    business_unit=bu_obj,
                    created_by=request.user,
                )
                AuditLog.log(
                    "create",
                    f"Created stream: {name}",
                    user=request.user,
                    request=request,
                    module="streams",
                    severity="info",
                )
                messages.success(request, f'Stream "{name}" created successfully.')

        elif action == "update":
            stream_id = request.POST.get("stream_id")
            try:
                stream = Stream.objects.get(id=stream_id)
                stream.name = request.POST.get("name")
                stream.description = request.POST.get("description", "")
                stream.allow_public_registration = request.POST.get("allow_public_registration") == "on"
                stream.requires_approval = request.POST.get("requires_approval") == "on"
                stream.is_active = request.POST.get("is_active") == "on"
                # Keep BU locked to current BU; only allow change if no BU context
                current_bu = get_current_bu(request)
                if current_bu:
                    stream.business_unit = current_bu
                else:
                    bu_id = request.POST.get("business_unit") or None
                    if bu_id:
                        try:
                            stream.business_unit = BusinessUnit.objects.get(id=bu_id)
                        except BusinessUnit.DoesNotExist:
                            stream.business_unit = None
                    else:
                        stream.business_unit = None
                stream.save()
                AuditLog.log(
                    "update",
                    f"Updated stream: {stream.name}",
                    user=request.user,
                    request=request,
                    obj=stream,
                    module="streams",
                    severity="info",
                )
                messages.success(request, f'Stream "{stream.name}" updated successfully.')
            except Stream.DoesNotExist:
                messages.error(request, "Stream not found.")

        elif action == "delete":
            stream_id = request.POST.get("stream_id")
            try:
                stream = Stream.objects.get(id=stream_id)
                stream_name = stream.name

                # Record deletion in history
                StreamDeletionHistory.objects.create(stream_name=stream_name, deleted_by=request.user)

                AuditLog.log(
                    "delete",
                    f"Deleted stream: {stream.name}",
                    user=request.user,
                    request=request,
                    module="streams",
                    severity="warning",
                )
                stream.delete()
                messages.success(request, f'Stream "{stream_name}" deleted successfully.')
            except Stream.DoesNotExist:
                messages.error(request, "Stream not found.")

        return redirect("manage_streams")

    bu = get_current_bu(request)
    if bu:
        streams = Stream.objects.select_related("business_unit").filter(business_unit=bu).order_by("name")
    else:
        streams = Stream.objects.select_related("business_unit").all().order_by("name")

    # Annotate each stream with resource counts
    streams = streams.annotate(
        product_count=Count("products", distinct=True),
        category_count=Count("categories", distinct=True),
        system_count=Count("systems", distinct=True),
        build_server_count=Count("build_servers", distinct=True),
    )

    # Compute accurate stats
    total_streams = streams.count()
    active_streams = streams.filter(is_active=True).count()
    inactive_streams = total_streams - active_streams

    business_units = BusinessUnit.objects.filter(is_active=True).order_by("name")
    return render(
        request,
        "products/manage_streams.html",
        {
            "streams": streams,
            "business_units": business_units,
            "current_bu": bu,
            "selected_stream": "management",
            "total_streams": total_streams,
            "active_streams": active_streams,
            "inactive_streams": inactive_streams,
        },
    )


@login_required
def export_streams_csv(request):  # noqa: CCR001
    """Export the streams list as CSV."""
    if not is_super_admin(request.user):
        return HttpResponse("Unauthorized", status=401)
    bu = get_current_bu(request)
    if bu:
        streams = Stream.objects.select_related("business_unit").filter(business_unit=bu).order_by("name")
    else:
        streams = Stream.objects.select_related("business_unit").all().order_by("name")
    streams = streams.annotate(
        product_count=Count("products", distinct=True),
        category_count=Count("categories", distinct=True),
        system_count=Count("systems", distinct=True),
        build_server_count=Count("build_servers", distinct=True),
    )
    response = HttpResponse(content_type="text/csv")
    _bu_slug = request.session.get("selected_bu_code", "all")
    response["Content-Disposition"] = (
        f'attachment; filename="streams_{_bu_slug}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(
        [
            "Stream Name",
            "Description",
            "Business Unit",
            "Status",
            "Users",
            "Products",
            "Categories",
            "Systems",
            "Build Servers",
            "Public Registration",
            "Requires Approval",
            "Created At",
            "Created By",
        ]
    )
    for s in streams:
        writer.writerow(
            [
                s.name,
                s.description or "",
                f"{s.business_unit.bu_name}-{s.business_unit.division}" if s.business_unit else "Unassigned",
                "Active" if s.is_active else "Inactive",
                s.get_active_users_count(),
                s.product_count,
                s.category_count,
                s.system_count,
                s.build_server_count,
                "Yes" if s.allow_public_registration else "No",
                "Yes" if s.requires_approval else "No",
                s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else "",
                s.created_by.username if s.created_by else "",
            ]
        )
    AuditLog.log(
        "export", "Exported streams list to CSV", user=request.user, request=request, module="streams", severity="info"
    )
    return response


@login_required
@require_POST
def clone_stream(request):
    """Clone/duplicate an existing stream (settings only, not data)."""
    if not is_super_admin(request.user):
        return JsonResponse({"error": "Unauthorized"}, status=401)

    source_id = request.POST.get("stream_id")
    new_name = request.POST.get("new_name", "").strip()
    if not source_id or not new_name:
        messages.error(request, "Source stream and new name are required.")
        return redirect("manage_streams")

    try:
        source = Stream.objects.get(id=source_id)
    except Stream.DoesNotExist:
        messages.error(request, "Source stream not found.")
        return redirect("manage_streams")

    if Stream.objects.filter(name=new_name).exists():
        messages.error(request, f'Stream "{new_name}" already exists.')
        return redirect("manage_streams")

    Stream.objects.create(
        name=new_name,
        description=source.description,
        business_unit=source.business_unit,
        allow_public_registration=source.allow_public_registration,
        requires_approval=source.requires_approval,
        is_active=True,
        created_by=request.user,
    )
    AuditLog.log(
        "create",
        f'Cloned stream "{source.name}" as "{new_name}"',
        user=request.user,
        request=request,
        module="streams",
        severity="info",
    )
    messages.success(request, f'Stream "{new_name}" cloned from "{source.name}".')
    return redirect("manage_streams")


@login_required
def manage_business_units(request):  # noqa: C901, CCR001
    """Manage Business Units (CRUD) — Application Admin only."""
    # pylint: disable=too-complex,too-many-branches,too-many-locals,too-many-statements
    if not is_app_admin(request.user):
        messages.error(request, "Only Application Admins can manage Business Units.")
        return redirect("dashboard")

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create":
            bu_name = request.POST.get("bu_name", "").strip()
            division = request.POST.get("division", "").strip()
            name = request.POST.get("name", "").strip()
            description = request.POST.get("description", "")

            if not bu_name or not division:
                messages.error(request, "BU Name and Division are required.")
            elif BusinessUnit.objects.filter(bu_name=bu_name, division=division).exists():
                messages.error(request, f'Business Unit "{bu_name}-{division}" already exists.')
            else:
                BusinessUnit.objects.create(
                    bu_name=bu_name, division=division, name=name, description=description, created_by=request.user
                )
                AuditLog.log(
                    "create",
                    f"Created business unit: {bu_name}",
                    user=request.user,
                    request=request,
                    module="settings",
                    severity="info",
                )
                messages.success(request, f'Business Unit "{bu_name}-{division}" created.')

        elif action == "update":
            bu_id = request.POST.get("bu_id")
            try:
                bu = BusinessUnit.objects.get(id=bu_id)
                bu.bu_name = request.POST.get("bu_name", "").strip()
                bu.division = request.POST.get("division", "").strip()
                bu.name = request.POST.get("name", "").strip()
                bu.description = request.POST.get("description", "")
                bu.is_active = request.POST.get("is_active") == "on"
                bu.save()
                AuditLog.log(
                    "update",
                    f"Updated business unit: {bu.bu_name}",
                    user=request.user,
                    request=request,
                    module="settings",
                    severity="info",
                )
                messages.success(request, f'Business Unit "{bu.slug}" updated.')
            except BusinessUnit.DoesNotExist:
                messages.error(request, "Business Unit not found.")

        elif action == "delete":
            bu_id = request.POST.get("bu_id")
            password = request.POST.get("password", "")
            reason = request.POST.get("reason", "").strip()
            try:
                bu = BusinessUnit.objects.get(id=bu_id)
                # ── Password verification ──
                if not request.user.check_password(password):
                    messages.error(request, "Incorrect password. Deletion request was not created.")
                    return redirect("manage_business_units")

                # ── Check for existing pending request ──
                if BUDeletionRequest.objects.filter(business_unit=bu, status="pending").exists():
                    messages.warning(request, f'A deletion request for "{bu.slug}" is already pending approval.')
                    return redirect("manage_business_units")

                # ── Build snapshot for audit ──
                stream_count = bu.streams.count()
                user_count = bu.user_access.values("custom_user").distinct().count()
                snapshot = {
                    "id": bu.id,
                    "bu_name": bu.bu_name,
                    "division": bu.division,
                    "slug": bu.slug,
                    "name": bu.name,
                    "description": bu.description,
                    "stream_count": stream_count,
                    "user_count": user_count,
                    "streams": list(bu.streams.values_list("name", flat=True)),
                }

                BUDeletionRequest.objects.create(
                    business_unit=bu,
                    bu_snapshot=snapshot,
                    requested_by=request.user,
                    request_reason=reason,
                )
                AuditLog.log(
                    "delete",
                    f"Requested deletion of BU: {bu.bu_name}",
                    user=request.user,
                    request=request,
                    module="settings",
                    severity="warning",
                )
                messages.success(
                    request,
                    f'Deletion request for "{bu.slug}" submitted. '
                    f"A System Admin must approve it before the BU is permanently deleted.",
                )
            except BusinessUnit.DoesNotExist:
                messages.error(request, "Business Unit not found.")

        elif action == "toggle_active":
            bu_id = request.POST.get("bu_id")
            try:
                bu = BusinessUnit.objects.get(id=bu_id)
                bu.is_active = not bu.is_active
                bu.save()
                AuditLog.log(
                    "status_change",
                    f"Toggled BU active status: {bu.bu_name}",
                    user=request.user,
                    request=request,
                    module="settings",
                    severity="info",
                )
                status_word = "activated" if bu.is_active else "deactivated"
                messages.success(request, f'Business Unit "{bu.slug}" {status_word}.')
            except BusinessUnit.DoesNotExist:
                messages.error(request, "Business Unit not found.")

        return redirect("manage_business_units")

    # Build annotated queryset with stats
    bus = (
        BusinessUnit.objects.all()
        .annotate(
            stream_count=Count("streams", distinct=True),
            active_stream_count=Count("streams", filter=Q(streams__is_active=True), distinct=True),
            user_count=Count("user_access__custom_user", distinct=True),
        )
        .prefetch_related(
            Prefetch("streams", queryset=Stream.objects.order_by("name")),
        )
        .select_related("created_by")
        .order_by("bu_name", "division")
    )

    # Summary stats
    total_bus = bus.count()
    active_bus = bus.filter(is_active=True).count()
    inactive_bus = total_bus - active_bus
    total_streams_all = Stream.objects.count()
    total_users_all = UserBUAccess.objects.values("custom_user").distinct().count()

    # Pending deletion requests
    pending_deletions = (
        BUDeletionRequest.objects.filter(status="pending")
        .select_related("business_unit", "requested_by")
        .order_by("-requested_at")
    )
    all_deletion_requests = BUDeletionRequest.objects.select_related(
        "business_unit", "requested_by", "reviewed_by"
    ).order_by("-requested_at")[:25]
    # BU ids with pending deletion (for badge in UI)
    pending_bu_ids = set(
        pending_deletions.filter(business_unit__isnull=False).values_list("business_unit_id", flat=True)
    )

    return render(
        request,
        "products/manage_bus.html",
        {
            "business_units": bus,
            "selected_stream": "management",
            "total_bus": total_bus,
            "active_bus": active_bus,
            "inactive_bus": inactive_bus,
            "total_streams_all": total_streams_all,
            "total_users_all": total_users_all,
            "pending_deletions": pending_deletions,
            "all_deletion_requests": all_deletion_requests,
            "pending_bu_ids": pending_bu_ids,
            "pending_count": pending_deletions.count(),
        },
    )


@login_required
@require_POST
def bu_deletion_review(request, pk):
    """Approve or Reject a BU deletion request.

    Accessible by super_admin, app_admin, or superuser.
    The reviewer must NOT be the same person who requested deletion.
    Password verification is required.
    """
    if not (is_super_admin(request.user) or is_app_admin(request.user)):
        messages.error(request, "Only Super Admins or Application Admins can review deletion requests.")
        return redirect("user_list")

    try:
        dr = BUDeletionRequest.objects.select_related("business_unit", "requested_by").get(pk=pk, status="pending")
    except BUDeletionRequest.DoesNotExist:
        messages.error(request, "Deletion request not found or already processed.")
        return redirect("user_list")

    action = request.POST.get("review_action")  # 'approve' or 'reject'
    password = request.POST.get("admin_password", "")
    comment = request.POST.get("review_comment", "").strip()

    # ── Password verification ──
    if not request.user.check_password(password):
        messages.error(request, "Incorrect password. Review action was not processed.")
        return redirect("user_list")

    # ── Prevent self-approval ──
    if action == "approve" and dr.requested_by == request.user:
        messages.error(request, "You cannot approve your own deletion request. Another admin must approve it.")
        return redirect("user_list")

    dr.reviewed_by = request.user
    dr.reviewed_at = timezone.now()
    dr.review_comment = comment

    if action == "approve":
        bu = dr.business_unit
        if bu:
            bu_label = bu.slug
            bu.delete()
            AuditLog.log(
                "delete",
                f"Approved and deleted BU: {bu_label}",
                user=request.user,
                request=request,
                module="settings",
                severity="critical",
            )
            dr.business_unit = None  # FK was SET_NULL on delete
            dr.status = "approved"
            dr.save()
            messages.success(request, f'Deletion approved. Business Unit "{bu_label}" has been permanently deleted.')
        else:
            dr.status = "approved"
            dr.save()
            messages.warning(request, "The Business Unit was already removed.")
    elif action == "reject":
        dr.status = "rejected"
        dr.save()
        AuditLog.log(
            "reject",
            f"Rejected BU deletion request for: {dr.business_unit.bu_name}",
            user=request.user,
            request=request,
            module="settings",
            severity="info",
        )
        bu_label = dr.bu_snapshot.get("slug", "(unknown)")
        messages.info(request, f'Deletion request for "{bu_label}" has been rejected.')
    else:
        messages.error(request, "Invalid review action.")

    return redirect("user_list")


@login_required
@require_POST
def bu_deletion_cancel(request, pk):
    """Cancel a pending BU deletion request (only the requester can cancel)."""
    try:
        dr = BUDeletionRequest.objects.get(pk=pk, status="pending", requested_by=request.user)
    except BUDeletionRequest.DoesNotExist:
        messages.error(request, "Deletion request not found or you are not the requester.")
        return redirect("user_list")

    dr.status = "cancelled"
    dr.save()
    bu_label = dr.bu_snapshot.get("slug", "(unknown)")
    messages.info(request, f'Deletion request for "{bu_label}" has been cancelled.')
    return redirect("user_list")


# ========== System Tags and Allocation Tree Views ==========
