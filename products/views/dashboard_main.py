"""Products app - Main Dashboard and Stream Deletion views."""

from ._helpers import (
    AuditLog,
    BUShowcaseProduct,
    Category,
    CustomUser,
    JsonResponse,
    Location,
    OnboardingProgress,
    Participant,
    Product,
    Q,
    Stream,
    StreamDeletionHistory,
    System,
    SystemStatus,
    UserSession,
    UserStreamAccess,
    _fac_granted,
    authenticate,
    can_delete_products,
    can_edit_products,
    can_manage_system_allocation,
    can_manage_users,
    can_view_analytics,
    get_bu_streams,
    get_current_bu,
    get_stream_or_404,
    get_user_model,
    is_admin,
    is_app_admin,
    is_lab_incharge,
    is_super_admin,
    login_required,
    messages,
    redirect,
    render,
    require_POST,
    timedelta,
    timezone,
)

__all__ = [
    "dashboard",
    "delete_stream",
]


@login_required
def dashboard(request, stream=None):  # noqa: C901, CCR001
    # pylint: disable=too-many-locals,too-many-statements,too-complex,invalid-name
    """Dashboard."""
    User = get_user_model()  # noqa: N806
    custom_profile, _created = CustomUser.objects.get_or_create(user=request.user)

    if not request.user.is_superuser and not custom_profile.user_roles.exists():
        context = {
            "total_products": 0,
            "total_categories": 0,
            "total_users": 0,
            "total_locations": 0,
            "total_participants": 0,
            "total_systems": 0,
            "online_users": 0,
            "streams": [],
            "selected_stream": "",
            "system_status": None,
            "current_time": timezone.now(),
            "user_custom_profile": custom_profile,
            "user_permissions": {},
            "access_error_message": "Access denied. You have no assigned roles. Please contact an administrator.",
        }
        return render(request, "products/dashboard.html", context)

    bu = get_current_bu(request)
    bu_streams_qs = get_bu_streams(request)
    streams = list(bu_streams_qs.values_list("name", flat=True).order_by("name"))

    def stream_sort_key(s_name):
        if s_name == "PIC":
            return (0, s_name)
        if s_name == "HIC":
            return (1, s_name)
        return (2, s_name)

    streams = sorted(set(streams), key=stream_sort_key)

    # If non-superuser has no accessible streams, show access denied on dashboard
    if not streams and not request.user.is_superuser:
        context = {
            "total_products": 0,
            "total_categories": 0,
            "total_users": 0,
            "total_locations": 0,
            "total_participants": 0,
            "total_systems": 0,
            "online_users": 0,
            "streams": [],
            "selected_stream": "",
            "system_status": None,
            "current_time": timezone.now(),
            "user_custom_profile": custom_profile,
            "user_permissions": {},
            "access_error_message": "Access denied. You do not have access to any streams.",
        }
        return render(request, "products/dashboard.html", context)

    stream_obj = None
    if streams:
        stream = stream or request.GET.get("stream", streams[0] if streams else "HIC")

        if not request.user.is_superuser and stream not in streams:
            messages.error(request, f"Access denied. You do not have permission to access the {stream} stream.")
            return redirect("dashboard_stream", stream=streams[0])

        stream_obj = get_stream_or_404(stream, request=request)
    else:
        stream = ""

    bu_stream_objs = bu_streams_qs  # QuerySet of Stream objects for this BU
    total_products = Product.objects.filter(stream__in=bu_stream_objs).count()
    total_categories = Category.objects.filter(stream=stream_obj).count() if stream_obj else 0
    bu_user_ids = (
        UserStreamAccess.objects.filter(stream__in=bu_stream_objs)
        .values_list("custom_user__user_id", flat=True)
        .distinct()
    )
    total_users = User.objects.filter(Q(is_active=True) & (Q(id__in=bu_user_ids) | Q(is_superuser=True))).count()
    total_locations = Location.objects.filter(stream=stream_obj).count() if stream_obj else 0
    total_participants = Participant.objects.filter(Q(business_unit=bu) if bu else Q()).count()
    total_systems = System.objects.filter(stream=stream_obj).count() if stream_obj else 0

    # ── Product trend (this month vs last month) ──
    now = timezone.now()
    start_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_of_last_month = (start_of_this_month - timedelta(days=1)).replace(day=1)
    products_this_month = Product.objects.filter(stream__in=bu_stream_objs, created_at__gte=start_of_this_month).count()
    products_last_month = Product.objects.filter(
        stream__in=bu_stream_objs, created_at__gte=start_of_last_month, created_at__lt=start_of_this_month
    ).count()
    if products_last_month > 0:
        pct = round(abs(products_this_month - products_last_month) / products_last_month * 100, 1)
        direction = "up" if products_this_month >= products_last_month else "down"
        product_trend = {"percentage": pct, "direction": direction}
    elif products_this_month > 0:
        product_trend = {"percentage": 100, "direction": "up"}
    else:
        product_trend = None

    cutoff_time = timezone.now() - timedelta(minutes=15)

    UserSession.objects.filter(last_activity__lt=cutoff_time, is_active=True).update(is_active=False)
    online_users = UserSession.objects.filter(last_activity__gte=cutoff_time, is_active=True).count()

    # Get system status
    system_status = SystemStatus.objects.first()
    if not system_status:
        system_status = SystemStatus.objects.create(status="online", description="System operational")
    # Get current time for weather widget
    current_time = timezone.now()

    # Get or create user custom profile
    custom_profile, _created = CustomUser.objects.get_or_create(user=request.user)

    # Get user permissions for dashboard display
    user_permissions = {
        "can_manage_users": can_manage_users(request.user),
        "can_manage_system_allocation": can_manage_system_allocation(request.user),
        "can_edit_products": can_edit_products(request.user),
        "can_delete_products": can_delete_products(request.user),
        "can_view_analytics": can_view_analytics(request.user),
        "is_admin": is_admin(request.user),
        "is_super_admin": is_super_admin(request.user),
        "is_app_admin": is_app_admin(request.user),
        "is_lab_incharge": is_lab_incharge(request.user),
    }

    # ---------- BU Showcase Products for gallery section ----------
    showcase_products = []
    if bu:
        showcase_products = list(BUShowcaseProduct.objects.filter(business_unit=bu, is_active=True))

    # ---------- Onboarding tour check ----------
    show_onboarding_tour = not OnboardingProgress.objects.filter(user=request.user, tour_key="dashboard_main").exists()

    context = {
        "total_products": total_products,
        "total_categories": total_categories,
        "total_users": total_users,
        "total_locations": total_locations,
        "total_participants": total_participants,
        "total_systems": total_systems,
        "online_users": online_users,
        "streams": streams,
        "selected_stream": stream,
        "system_status": system_status,
        "current_time": current_time,
        "user_custom_profile": custom_profile,
        "user_permissions": user_permissions,
        "showcase_products": showcase_products,
        "product_trend": product_trend,
        "show_onboarding_tour": show_onboarding_tour,
        "notifications": list(request.user.notifications.select_related().order_by("-created_at")[:50]),
        "unread_count": request.user.notifications.filter(is_read=False).count(),
    }

    return render(request, "products/dashboard.html", context)


@login_required
@require_POST
def delete_stream(request):
    """Delete stream."""
    if not _fac_granted(request.user) and not request.user.is_superuser:
        return JsonResponse({"success": False, "error": "Permission denied."}, status=403)
    stream_name = request.POST.get("stream_name", "").strip()
    password = request.POST.get("password", "").strip()
    if not stream_name or not password:
        return JsonResponse({"success": False, "error": "Missing stream name or password."}, status=400)
    if stream_name in ["HIC", "PIC"]:
        return JsonResponse({"success": False, "error": "Cannot delete default streams."}, status=400)
    user = authenticate(username=request.user.username, password=password)
    if not user:
        return JsonResponse({"success": False, "error": "Incorrect password."}, status=403)
    try:
        stream_obj = Stream.objects.get(name=stream_name)
        AuditLog.log(
            "delete",
            f"Deleted stream: {stream_obj.name}",
            user=request.user,
            request=request,
            module="streams",
            severity="critical",
        )
        stream_obj.delete()
        # Log deletion
        StreamDeletionHistory.objects.create(stream_name=stream_name, deleted_by=request.user)
        return JsonResponse({"success": True})
    except Stream.DoesNotExist:
        return JsonResponse({"success": False, "error": "Stream not found."}, status=404)
