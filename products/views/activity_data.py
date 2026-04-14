"""Products app - Daily Usage, Page Views, Hourly Activity, Client IP, Dashboard API, Onboarding views."""

import json as _json

from django.utils import timezone as dj_timezone

from ._helpers import (
    Category,
    Count,
    JsonResponse,
    OnboardingProgress,
    Product,
    Q,
    SystemStatus,
    UsageTracking,
    UserSession,
    get_bu_streams,
    get_default_stream_name,
    get_stream_or_404,
    login_required,
    require_GET,
    require_POST,
    timedelta,
    timezone,
)

__all__ = [
    "generate_daily_usage_data",
    "generate_page_views_data",
    "generate_hourly_activity_data",
    "get_client_ip",
    "dashboard_api_data",
    "update_user_activity",
    "onboarding_status_api",
    "onboarding_complete_api",
    "onboarding_reset_api",
]


def generate_daily_usage_data(start_date, end_date, usage_qs=None):
    # pylint: disable=too-many-locals
    """Generate daily usage data for the specified time range."""
    if usage_qs is None:
        usage_qs = UsageTracking.objects.all()
    # Ensure start/end are timezone-aware and work in current (local) timezone for display
    local_tz = dj_timezone.get_current_timezone()
    # Normalize to local midnight for start and end (end is exclusive)
    local_start = dj_timezone.localtime(start_date, local_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = dj_timezone.localtime(end_date, local_tz).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) + timedelta(days=1)

    date_range = (local_end - local_start).days
    dates = []
    views_counts = []
    users_counts = []

    # For each date in the range (using local dates for labels)
    for i in range(date_range):
        current_local = local_start + timedelta(days=i)
        next_local = current_local + timedelta(days=1)

        # Format the date for display using local date (this fixes off-by-one day labels)
        display_date = current_local.strftime("%Y-%m-%d")
        dates.append(display_date)

        # Convert local day boundaries back to UTC for querying the DB (timestamps are stored in UTC)
        try:
            current_utc = current_local.astimezone(  # pylint: disable=no-member
                dj_timezone.utc,  # type: ignore[attr-defined]
            )
            next_utc = next_local.astimezone(  # pylint: disable=no-member
                dj_timezone.utc,  # type: ignore[attr-defined]
            )
        except (TypeError, AttributeError, ValueError):
            # Fallback: if astimezone fails, use the naive datetimes as-is (best-effort)
            current_utc = current_local
            next_utc = next_local

        day_views = usage_qs.filter(timestamp__gte=current_utc, timestamp__lt=next_utc).count()
        views_counts.append(day_views)

        day_users = (
            usage_qs.filter(timestamp__gte=current_utc, timestamp__lt=next_utc).values("user").distinct().count()
        )
        users_counts.append(day_users)

    return {"dates": dates, "views": views_counts, "users": users_counts}


def generate_page_views_data(start_date, end_date, usage_qs=None):
    """Generate data for most visited pages, excluding the usage tracking page.

    and user-related pages (login, register, profile, etc.)
    """
    if usage_qs is None:
        usage_qs = UsageTracking.objects.all()

    # Create a combined Q object for all excluded terms (more precise, avoid over-filtering)
    exclude_terms = (
        Q(page_name__iexact="/usage-tracking/")
        | Q(page_name__iexact="/usage_tracking/")
        | Q(page_name__iexact="/favicon.ico")
        | Q(page_name__iexact="/accounts/login/")
        | Q(page_name__iexact="/accounts/logout/")
        | Q(page_name__iexact="/accounts/register/")
        | Q(page_name__iexact="/accounts/profile/")
        | Q(page_name__icontains=".well-known")
        | Q(page_name__icontains="appspecific")
    )

    page_counts = (
        usage_qs.filter(timestamp__gte=start_date, timestamp__lte=end_date)
        .exclude(exclude_terms)
        .values("page_name")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )

    pages = []
    counts = []

    for item in page_counts:
        page_name = item["page_name"]
        pages.append(page_name[:25] + "..." if len(page_name) > 25 else page_name)
        counts.append(item["count"])

    return {"pages": pages, "counts": counts}


def generate_hourly_activity_data(start_date, end_date, usage_qs=None):
    """Generate data for hourly user activity."""
    if usage_qs is None:
        usage_qs = UsageTracking.objects.all()
    hours = list(range(24))
    counts = [0] * 24

    records = usage_qs.filter(timestamp__gte=start_date, timestamp__lte=end_date)

    for record in records:
        hour = record.timestamp.hour
        counts[hour] += 1

    # Format hours for display (e.g., "12 AM", "1 PM", etc.)
    hour_labels = []
    for hour_val in hours:
        if hour_val == 0:
            hour_labels.append("12 AM")
        elif hour_val < 12:
            hour_labels.append(f"{hour_val} AM")
        elif hour_val == 12:
            hour_labels.append("12 PM")
        else:
            hour_labels.append(f"{hour_val-12} PM")

    return {"hours": hour_labels, "counts": counts}


def get_client_ip(request):
    """Get client IP address from request."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip


# API endpoints for dashboard real-time data


@login_required
@require_GET
def dashboard_api_data(request):
    """API endpoint for real-time dashboard data."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=401)
    stream = request.GET.get("stream") or get_default_stream_name(request)

    if not stream or stream.strip() == "":
        stream = "PIC"

    stream_obj = get_stream_or_404(stream, default="PIC")

    bu_streams_qs = get_bu_streams(request)
    total_products = Product.objects.filter(stream__in=bu_streams_qs).count()
    total_categories = Category.objects.filter(stream=stream_obj).count()

    cutoff_time = timezone.now() - timedelta(minutes=15)

    UserSession.objects.filter(last_activity__lt=cutoff_time, is_active=True).update(is_active=False)

    online_users = UserSession.objects.filter(last_activity__gte=cutoff_time, is_active=True).count()

    system_status = SystemStatus.objects.first()
    if not system_status:
        system_status = SystemStatus.objects.create(status="online", description="System operational")
    data = {
        "total_products": total_products,
        "total_categories": total_categories,
        "online_users": online_users,
        "system_status": {
            "status": system_status.get_status_display(),
            "description": system_status.description,
            "uptime": system_status.uptime_percentage,
        },
        "timestamp": timezone.now().isoformat(),
    }

    return JsonResponse(data)


@login_required
@require_POST
def update_user_activity(request):
    """Update user activity for session tracking."""
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required"}, status=401)

    session_key = request.session.session_key
    if session_key:
        session_obj, created = UserSession.objects.get_or_create(
            session_key=session_key,
            defaults={
                "user": request.user,
                "ip_address": get_client_ip(request),
                "user_agent": request.META.get("HTTP_USER_AGENT", ""),
            },
        )
        if not created:
            session_obj.last_activity = timezone.now()
            session_obj.save()

    return JsonResponse({"status": "success"})


# ════════════════════════════════════════════════════════════════
# Onboarding / Guided Tour API
# ════════════════════════════════════════════════════════════════


@login_required
def onboarding_status_api(request):
    """Return which tours the current user has completed."""
    completed = list(OnboardingProgress.objects.filter(user=request.user).values_list("tour_key", flat=True))
    return JsonResponse({"completed_tours": completed})


@login_required
@require_POST
def onboarding_complete_api(request):
    """Mark a specific tour as completed for the current user."""
    try:
        body = _json.loads(request.body.decode("utf-8") or "{}")
    except ValueError:
        body = {}
    tour_key = body.get("tour_key", "") or request.POST.get("tour_key", "")
    valid_keys = [k for k, _label in OnboardingProgress.TOUR_KEY_CHOICES]
    if tour_key not in valid_keys:
        return JsonResponse({"success": False, "error": f"Invalid tour_key: {tour_key}"}, status=400)
    _obj, created = OnboardingProgress.objects.get_or_create(user=request.user, tour_key=tour_key)
    return JsonResponse({"success": True, "created": created, "tour_key": tour_key})


@login_required
@require_POST
def onboarding_reset_api(request):
    """Reset tours for the current user. If tour_key is provided, reset only that tour; otherwise reset all."""
    try:
        body = _json.loads(request.body.decode("utf-8") or "{}")
    except ValueError:
        body = {}
    tour_key = body.get("tour_key", "") or request.POST.get("tour_key", "")
    qs = OnboardingProgress.objects.filter(user=request.user)
    if tour_key:
        qs = qs.filter(tour_key=tour_key)
    deleted_count, _ = qs.delete()
    return JsonResponse({"success": True, "tours_reset": deleted_count})
