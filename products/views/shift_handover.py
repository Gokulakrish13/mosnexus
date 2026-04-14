"""
Shift Handover Log views — dashboard, CRUD, acknowledge, comments, API.
"""

from ._helpers import (
    AuditLog,
    JsonResponse,
    Q,
    Stream,
    get_bu_streams,
    get_current_bu,
    is_admin,
    is_lab_incharge,
    is_super_admin,
    json,
    logger,
    login_required,
    redirect,
    render,
    timezone,
    IntegrityError,
)
from ..models import (
    ShiftHandoverAuditLog,
    ShiftHandoverComment,
    ShiftHandoverLog,
    ShiftType,
)

__all__ = [
    "shift_handover_hub",
    "shift_handover_stream",
    "shift_handover_create",
    "shift_handover_detail_api",
    "shift_handover_update",
    "shift_handover_delete",
    "shift_handover_submit",
    "shift_handover_acknowledge",
    "shift_handover_comment",
    "shift_handover_stats_api",
    "shift_type_api",
    "shift_type_delete",
]


def _can_access_handover(user):
    """Lab Incharge, Admin, Super Admin, and App Admin can access handovers."""
    if getattr(user, '_fac_granted', False):
        return True
    if user.is_superuser:
        return True
    try:
        cp = user.custom_profile
        return cp.user_roles.filter(
            role__in=["lab_incharge", "admin", "super_admin", "app_admin"]
        ).exists()
    except Exception:
        return False


def _can_manage_handover(user):
    """Lab Incharge + Admin + Super Admin can create/edit/delete."""
    if getattr(user, '_fac_granted', False):
        return True
    if user.is_superuser:
        return True
    try:
        cp = user.custom_profile
        return cp.user_roles.filter(
            role__in=["lab_incharge", "admin", "super_admin", "app_admin"]
        ).exists()
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
#  HUB / DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════


@login_required
def shift_handover_hub(request):
    """Hub page showing handover stats per stream (like waste_hub)."""
    bu = get_current_bu(request)
    if not bu:
        return redirect("select_bu")
    if not _can_access_handover(request.user):
        return redirect("dashboard")

    streams = get_bu_streams(request)
    sa = is_super_admin(request.user)

    # Per-stream stats
    for s in streams:
        qs = ShiftHandoverLog.objects.filter(business_unit=bu, stream=s)
        s.h_total = qs.count()
        s.h_submitted = qs.filter(status="submitted").count()
        s.h_acknowledged = qs.filter(status="acknowledged").count()
        s.h_pending = qs.filter(status__in=["draft", "submitted"]).count()

    # Global stats (super admin)
    all_qs = ShiftHandoverLog.objects.filter(business_unit=bu)
    total_all = all_qs.count()
    submitted_all = all_qs.filter(status="submitted").count()
    acknowledged_all = all_qs.filter(status="acknowledged").count()
    pending_all = all_qs.filter(status__in=["draft", "submitted"]).count()

    return render(request, "products/shift_handover_hub.html", {
        "streams": streams,
        "is_super_admin": sa,
        "total_all": total_all,
        "submitted_all": submitted_all,
        "acknowledged_all": acknowledged_all,
        "pending_all": pending_all,
    })


# ═══════════════════════════════════════════════════════════════════════════
#  STREAM DETAIL
# ═══════════════════════════════════════════════════════════════════════════


@login_required
def shift_handover_stream(request, stream):
    """Stream-level handover list with filter/search."""
    bu = get_current_bu(request)
    if not bu:
        return redirect("select_bu")
    if not _can_access_handover(request.user):
        return redirect("dashboard")

    sa = is_super_admin(request.user)

    if stream == "all" and sa:
        handovers = ShiftHandoverLog.objects.filter(business_unit=bu)
        stream_obj = None
        stream_name = "All Streams"
    else:
        try:
            stream_obj = Stream.objects.get(name=stream, business_unit=bu)
        except Stream.DoesNotExist:
            return redirect("shift_handover_hub")
        handovers = ShiftHandoverLog.objects.filter(business_unit=bu, stream=stream_obj)
        stream_name = stream_obj.name

    # Filters
    status_filter = request.GET.get("status", "")
    if status_filter:
        handovers = handovers.filter(status=status_filter)
    search_q = request.GET.get("q", "")
    if search_q:
        handovers = handovers.filter(
            Q(handover_number__icontains=search_q)
            | Q(systems_running__icontains=search_q)
            | Q(pending_actions__icontains=search_q)
            | Q(blockers_issues__icontains=search_q)
            | Q(safety_notes__icontains=search_q)
            | Q(general_notes__icontains=search_q)
        )

    shift_types = ShiftType.objects.filter(business_unit=bu, is_active=True)
    streams = get_bu_streams(request)

    # Stats for this view
    total = handovers.count()
    submitted = handovers.filter(status="submitted").count()
    acknowledged = handovers.filter(status="acknowledged").count()
    drafts = handovers.filter(status="draft").count()

    return render(request, "products/shift_handover_detail.html", {
        "handovers": handovers[:100],
        "stream_name": stream_name,
        "stream": stream,
        "stream_obj": stream_obj,
        "shift_types": shift_types,
        "streams": streams,
        "is_super_admin": sa,
        "can_manage": _can_manage_handover(request.user),
        "total": total,
        "submitted": submitted,
        "acknowledged": acknowledged,
        "drafts": drafts,
        "status_filter": status_filter,
        "search_q": search_q,
    })


# ═══════════════════════════════════════════════════════════════════════════
#  CRUD — CREATE / READ / UPDATE / DELETE
# ═══════════════════════════════════════════════════════════════════════════


@login_required
def shift_handover_create(request):
    """POST: Create a new handover log."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)
    if not _can_manage_handover(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    stream_name = data.get("stream")
    if not stream_name:
        return JsonResponse({"success": False, "error": "Stream is required"}, status=400)

    try:
        stream_obj = Stream.objects.get(name=stream_name, business_unit=bu)
    except Stream.DoesNotExist:
        return JsonResponse({"success": False, "error": "Stream not found"}, status=404)

    shift_date = data.get("shift_date")
    if not shift_date:
        return JsonResponse({"success": False, "error": "Shift date is required"}, status=400)

    shift_type = None
    shift_type_id = data.get("shift_type_id")
    if shift_type_id:
        try:
            shift_type = ShiftType.objects.get(id=shift_type_id, business_unit=bu)
        except ShiftType.DoesNotExist:
            return JsonResponse({"success": False, "error": "Shift type not found"}, status=404)

    # Check uniqueness
    if shift_type and ShiftHandoverLog.objects.filter(
        stream=stream_obj, shift_date=shift_date, shift_type=shift_type
    ).exists():
        return JsonResponse(
            {"success": False, "error": "A handover for this stream, date, and shift already exists"},
            status=409,
        )

    handover = ShiftHandoverLog(
        business_unit=bu,
        stream=stream_obj,
        shift_type=shift_type,
        shift_date=shift_date,
        priority=data.get("priority", "normal"),
        systems_running=data.get("systems_running", ""),
        pending_actions=data.get("pending_actions", ""),
        blockers_issues=data.get("blockers_issues", ""),
        safety_notes=data.get("safety_notes", ""),
        bookings_handoff=data.get("bookings_handoff", ""),
        general_notes=data.get("general_notes", ""),
        outgoing_lead=request.user,
        created_by=request.user,
        updated_by=request.user,
    )
    handover.save()

    # Audit
    ShiftHandoverAuditLog.objects.create(
        handover=handover,
        action="created",
        details=f"Handover {handover.handover_number} created",
        performed_by=request.user,
    )
    AuditLog.log(
        action="create",
        title=f"Created shift handover {handover.handover_number}",
        user=request.user,
        module="shift_handover",
        description=f"Created shift handover {handover.handover_number}",
        request=request,
    )

    return JsonResponse({
        "success": True,
        "handover": _serialize_handover(handover),
    })


@login_required
def shift_handover_detail_api(request, pk):
    """GET: Return handover detail JSON."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    try:
        handover = ShiftHandoverLog.objects.get(pk=pk, business_unit=bu)
    except ShiftHandoverLog.DoesNotExist:
        return JsonResponse({"success": False, "error": "Not found"}, status=404)

    data = _serialize_handover(handover)
    data["comments"] = [
        {
            "id": c.id,
            "author": str(c.author) if c.author else "Unknown",
            "content": c.content,
            "created_at": c.created_at.strftime("%Y-%m-%d %H:%M"),
        }
        for c in handover.comments.select_related("author").all()
    ]
    data["audit_logs"] = [
        {
            "action": a.get_action_display(),
            "details": a.details,
            "performed_by": str(a.performed_by) if a.performed_by else "System",
            "performed_at": a.performed_at.strftime("%Y-%m-%d %H:%M"),
        }
        for a in handover.audit_logs.select_related("performed_by").all()[:20]
    ]

    return JsonResponse({"success": True, "handover": data})


@login_required
def shift_handover_update(request, pk):
    """POST: Update an existing handover log."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)
    if not _can_manage_handover(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    try:
        handover = ShiftHandoverLog.objects.get(pk=pk, business_unit=bu)
    except ShiftHandoverLog.DoesNotExist:
        return JsonResponse({"success": False, "error": "Not found"}, status=404)

    if handover.status == "acknowledged":
        return JsonResponse(
            {"success": False, "error": "Cannot edit an already acknowledged handover"},
            status=400,
        )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    # Update fields
    for field in [
        "systems_running", "pending_actions", "blockers_issues",
        "safety_notes", "bookings_handoff", "general_notes", "priority",
    ]:
        if field in data:
            setattr(handover, field, data[field])

    if "shift_type_id" in data:
        try:
            handover.shift_type = ShiftType.objects.get(
                id=data["shift_type_id"], business_unit=bu
            )
        except ShiftType.DoesNotExist:
            pass

    handover.updated_by = request.user
    handover.save()

    ShiftHandoverAuditLog.objects.create(
        handover=handover,
        action="updated",
        details="Handover content updated",
        performed_by=request.user,
    )

    return JsonResponse({"success": True, "handover": _serialize_handover(handover)})


@login_required
def shift_handover_delete(request, pk):
    """POST: Delete a handover log."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)
    if not _can_manage_handover(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    try:
        handover = ShiftHandoverLog.objects.get(pk=pk, business_unit=bu)
    except ShiftHandoverLog.DoesNotExist:
        return JsonResponse({"success": False, "error": "Not found"}, status=404)

    number = handover.handover_number
    handover.delete()

    AuditLog.log(
        action="delete",
        title=f"Deleted shift handover {number}",
        user=request.user,
        module="shift_handover",
        description=f"Deleted shift handover {number}",
        request=request,
    )

    return JsonResponse({"success": True})


# ═══════════════════════════════════════════════════════════════════════════
#  WORKFLOW — SUBMIT & ACKNOWLEDGE
# ═══════════════════════════════════════════════════════════════════════════


@login_required
def shift_handover_submit(request, pk):
    """POST: Submit a draft handover for acknowledgement."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    try:
        handover = ShiftHandoverLog.objects.get(pk=pk, business_unit=bu)
    except ShiftHandoverLog.DoesNotExist:
        return JsonResponse({"success": False, "error": "Not found"}, status=404)

    if handover.status != "draft":
        return JsonResponse({"success": False, "error": "Only drafts can be submitted"}, status=400)

    handover.status = "submitted"
    handover.updated_by = request.user
    handover.save()

    ShiftHandoverAuditLog.objects.create(
        handover=handover,
        action="submitted",
        details=f"Handover submitted by {request.user}",
        performed_by=request.user,
    )

    return JsonResponse({"success": True, "handover": _serialize_handover(handover)})


@login_required
def shift_handover_acknowledge(request, pk):
    """POST: Incoming shift acknowledges the handover."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    try:
        handover = ShiftHandoverLog.objects.get(pk=pk, business_unit=bu)
    except ShiftHandoverLog.DoesNotExist:
        return JsonResponse({"success": False, "error": "Not found"}, status=404)

    if handover.status != "submitted":
        return JsonResponse(
            {"success": False, "error": "Only submitted handovers can be acknowledged"},
            status=400,
        )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        data = {}

    handover.status = "acknowledged"
    handover.acknowledged_by = request.user
    handover.acknowledged_at = timezone.now()
    handover.acknowledgement_notes = data.get("notes", "")
    handover.updated_by = request.user
    handover.save()

    ShiftHandoverAuditLog.objects.create(
        handover=handover,
        action="acknowledged",
        details=f"Acknowledged by {request.user}",
        performed_by=request.user,
    )
    AuditLog.log(
        action="update",
        title=f"Acknowledged handover {handover.handover_number}",
        user=request.user,
        module="shift_handover",
        description=f"Acknowledged handover {handover.handover_number}",
        request=request,
    )

    return JsonResponse({"success": True, "handover": _serialize_handover(handover)})


# ═══════════════════════════════════════════════════════════════════════════
#  COMMENTS
# ═══════════════════════════════════════════════════════════════════════════


@login_required
def shift_handover_comment(request, pk):
    """POST: Add a comment to a handover log."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    try:
        handover = ShiftHandoverLog.objects.get(pk=pk, business_unit=bu)
    except ShiftHandoverLog.DoesNotExist:
        return JsonResponse({"success": False, "error": "Not found"}, status=404)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    content = data.get("content", "").strip()
    if not content:
        return JsonResponse({"success": False, "error": "Comment cannot be empty"}, status=400)

    comment = ShiftHandoverComment.objects.create(
        handover=handover,
        author=request.user,
        content=content,
    )

    ShiftHandoverAuditLog.objects.create(
        handover=handover,
        action="comment_added",
        details=f"Comment by {request.user}",
        performed_by=request.user,
    )

    return JsonResponse({
        "success": True,
        "comment": {
            "id": comment.id,
            "author": str(comment.author),
            "content": comment.content,
            "created_at": comment.created_at.strftime("%Y-%m-%d %H:%M"),
        },
    })


# ═══════════════════════════════════════════════════════════════════════════
#  STATS API
# ═══════════════════════════════════════════════════════════════════════════


@login_required
def shift_handover_stats_api(request):
    """GET: Return stats for charts/dashboards."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    from django.db.models import Count
    from datetime import timedelta

    qs = ShiftHandoverLog.objects.filter(business_unit=bu)
    today = timezone.now().date()

    # Last 30 days trend
    thirty_ago = today - timedelta(days=30)
    daily = (
        qs.filter(shift_date__gte=thirty_ago)
        .values("shift_date")
        .annotate(count=Count("id"))
        .order_by("shift_date")
    )

    # Per-status breakdown
    status_counts = dict(qs.values_list("status").annotate(c=Count("id")).values_list("status", "c"))

    # Per-priority breakdown
    priority_counts = dict(qs.values_list("priority").annotate(c=Count("id")).values_list("priority", "c"))

    return JsonResponse({
        "success": True,
        "daily_trend": [
            {"date": str(d["shift_date"]), "count": d["count"]}
            for d in daily
        ],
        "status_counts": status_counts,
        "priority_counts": priority_counts,
        "total": qs.count(),
    })


# ═══════════════════════════════════════════════════════════════════════════
#  SHIFT TYPES MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════


@login_required
def shift_type_api(request):
    """GET: list shift types. POST: create/update a shift type."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)

    if request.method == "GET":
        types = ShiftType.objects.filter(business_unit=bu, is_active=True)
        return JsonResponse({
            "success": True,
            "shift_types": [
                {
                    "id": t.id,
                    "name": t.name,
                    "code": t.code,
                    "start_time": t.start_time.strftime("%H:%M"),
                    "end_time": t.end_time.strftime("%H:%M"),
                    "color": t.color,
                    "icon_class": t.icon_class,
                }
                for t in types
            ],
        })

    if request.method == "POST":
        if not _can_manage_handover(request.user):
            return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

        pk = data.get("id")
        if pk:
            # Update
            try:
                st = ShiftType.objects.get(id=pk, business_unit=bu)
            except ShiftType.DoesNotExist:
                return JsonResponse({"success": False, "error": "Not found"}, status=404)
            for field in ["name", "code", "start_time", "end_time", "color", "icon_class"]:
                if field in data:
                    setattr(st, field, data[field])
            st.save()
        else:
            # Create
            required = ["name", "code", "start_time", "end_time"]
            for f in required:
                if not data.get(f):
                    return JsonResponse({"success": False, "error": f"{f} is required"}, status=400)
            try:
                st = ShiftType.objects.create(
                    business_unit=bu,
                    name=data["name"],
                    code=data["code"],
                    start_time=data["start_time"],
                    end_time=data["end_time"],
                    color=data.get("color", "#0B5FFF"),
                    icon_class=data.get("icon_class", "fas fa-sun"),
                )
            except IntegrityError:
                return JsonResponse(
                    {"success": False, "error": f"A shift type with code '{data['code']}' already exists for this BU."},
                    status=409,
                )
            except Exception as e:
                logger.exception("Error creating shift type")
                return JsonResponse({"success": False, "error": str(e)}, status=500)

        # Refresh to ensure TimeField values are proper Python time objects
        st.refresh_from_db()

        return JsonResponse({
            "success": True,
            "shift_type": {
                "id": st.id,
                "name": st.name,
                "code": st.code,
                "start_time": st.start_time.strftime("%H:%M"),
                "end_time": st.end_time.strftime("%H:%M"),
                "color": st.color,
                "icon_class": st.icon_class,
            },
        })

    return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)


@login_required
def shift_type_delete(request, pk):
    """POST: Soft-delete (deactivate) a shift type."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "POST required"}, status=405)
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"success": False, "error": "No BU selected"}, status=400)
    if not _can_manage_handover(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    try:
        st = ShiftType.objects.get(id=pk, business_unit=bu)
    except ShiftType.DoesNotExist:
        return JsonResponse({"success": False, "error": "Not found"}, status=404)

    st.is_active = False
    st.save()
    return JsonResponse({"success": True})


# ═══════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def _serialize_handover(h):
    """Serialize a ShiftHandoverLog to a dict."""
    return {
        "id": h.id,
        "handover_number": h.handover_number,
        "stream": h.stream.name if h.stream else "",
        "shift_type": {
            "id": h.shift_type.id,
            "name": h.shift_type.name,
            "color": h.shift_type.color,
            "icon_class": h.shift_type.icon_class,
        } if h.shift_type else None,
        "shift_date": str(h.shift_date),
        "status": h.status,
        "status_display": h.get_status_display(),
        "priority": h.priority,
        "priority_display": h.get_priority_display(),
        "systems_running": h.systems_running,
        "pending_actions": h.pending_actions,
        "blockers_issues": h.blockers_issues,
        "safety_notes": h.safety_notes,
        "bookings_handoff": h.bookings_handoff,
        "general_notes": h.general_notes,
        "outgoing_lead": str(h.outgoing_lead) if h.outgoing_lead else "",
        "acknowledged_by": str(h.acknowledged_by) if h.acknowledged_by else "",
        "acknowledged_at": h.acknowledged_at.strftime("%Y-%m-%d %H:%M") if h.acknowledged_at else "",
        "acknowledgement_notes": h.acknowledgement_notes,
        "sections_filled": h.sections_filled,
        "has_critical_items": h.has_critical_items,
        "created_at": h.created_at.strftime("%Y-%m-%d %H:%M") if h.created_at else "",
        "created_by": str(h.created_by) if h.created_by else "",
    }
