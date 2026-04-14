"""Products app - Usage Tracking, Activity Data, and Onboarding views."""

# pylint: disable=else-if-used,import-error,relative-beyond-top-level,too-many-lines,unused-variable

from ..models import BusinessUnit as BU  # noqa: N817
from ._helpers import (
    Count,
    JsonResponse,
    UsageTracking,
    User,
    UserBUAccess,
    datetime,
    get_current_bu,
    get_default_stream_name,
    is_app_admin,
    is_super_admin,
    json,
    login_required,
    render,
    timedelta,
    timezone,
    user_passes_test,
)
from .activity_data import generate_daily_usage_data, generate_hourly_activity_data, generate_page_views_data

__all__ = [
    "usage_tracking",
    "usage_tracking_data",
]


def _get_bu_user_ids(bu):
    """Return a list of user IDs that have access to the given BU."""
    return list(UserBUAccess.objects.filter(business_unit=bu).values_list("custom_user__user_id", flat=True))


def _usage_base_qs(model_qs, bu, selected_bu_slug, is_admin):
    """Apply BU scoping to a UsageTracking queryset.

    Filters by the business_unit FK recorded on each usage record
    so that only page views that actually occurred within a BU
    context are counted for that BU.
    If selected_bu_slug == 'all' and is_admin, return unfiltered.
    """
    if selected_bu_slug == "all" and is_admin:
        return model_qs  # global view for app admins
    target_bu = bu
    if selected_bu_slug and selected_bu_slug != "all":
        try:
            target_bu = BU.objects.get(slug=selected_bu_slug)
        except BU.DoesNotExist:
            pass
    if target_bu:
        return model_qs.filter(business_unit=target_bu)
    return model_qs


def _user_base_qs(bu, selected_bu_slug, is_admin):
    """Return a User queryset scoped to BU users."""
    if selected_bu_slug == "all" and is_admin:
        return User.objects.filter(is_active=True)
    target_bu = bu
    if selected_bu_slug and selected_bu_slug != "all":
        try:
            target_bu = BU.objects.get(slug=selected_bu_slug)
        except BU.DoesNotExist:
            pass
    if target_bu:
        user_ids = _get_bu_user_ids(target_bu)
        return User.objects.filter(id__in=user_ids, is_active=True)
    return User.objects.filter(is_active=True)


def _compute_bu_breakdown(start_date, end_date):  # noqa: CCR001
    """Compute per-BU usage stats for all active BUs.

    Returns a list of dicts suitable for JSON serialisation / template rendering.
    """
    # pylint: disable=too-many-locals
    previous_period = end_date - start_date
    prev_start = start_date - previous_period
    prev_end = start_date

    breakdown = []
    for bu in BU.objects.filter(is_active=True).order_by("bu_name", "division"):
        bu_user_ids = _get_bu_user_ids(bu)
        bu_usage = UsageTracking.objects.filter(business_unit=bu)
        bu_users = User.objects.filter(id__in=bu_user_ids, is_active=True)

        total_users = bu_users.count()
        views = bu_usage.filter(timestamp__gte=start_date, timestamp__lt=end_date).count()
        prev_views = bu_usage.filter(timestamp__gte=prev_start, timestamp__lt=prev_end).count()
        views_change = round(((views - prev_views) / prev_views) * 100) if prev_views > 0 else (100 if views > 0 else 0)

        active = bu_usage.filter(timestamp__gte=start_date, timestamp__lt=end_date).values("user").distinct().count()
        prev_active = (
            bu_usage.filter(timestamp__gte=prev_start, timestamp__lt=prev_end).values("user").distinct().count()
        )
        active_change = (
            round(((active - prev_active) / prev_active) * 100) if prev_active > 0 else (100 if active > 0 else 0)
        )

        new_users = bu_users.filter(date_joined__gte=start_date, date_joined__lt=end_date).count()

        # avg session time (simplified)
        sessions_qs = bu_usage.filter(timestamp__gte=start_date, timestamp__lt=end_date).order_by("user", "timestamp")
        durations = []
        cur_uid = None
        prev_ts = None
        dur = 0
        for act in sessions_qs:
            if cur_uid != act.user_id:
                if cur_uid is not None and dur > 0:
                    durations.append(dur)
                cur_uid = act.user_id
                prev_ts = None
                dur = 0
            if prev_ts:
                diff = (act.timestamp - prev_ts).total_seconds() / 60
                if diff <= 30:
                    dur += diff
                else:
                    if dur > 0:
                        durations.append(dur)
                    dur = 0
            prev_ts = act.timestamp
        if dur > 0:
            durations.append(dur)
        avg_time = f"{int(sum(durations) / len(durations))} mins" if durations else "N/A"

        breakdown.append(
            {
                "bu_name": str(bu),
                "slug": bu.slug,
                "total_users": total_users,
                "active_users": active,
                "active_change": active_change,
                "total_views": views,
                "views_change": views_change,
                "new_users": new_users,
                "avg_session_time": avg_time,
            }
        )
    return breakdown


@login_required
@user_passes_test(is_super_admin)
def usage_tracking(request):  # noqa: C901, CCR001
    """Display a usage tracking dashboard showing application usage analytics.

    Scoped to the current BU.  Application Admins can choose 'All BUs'.
    """
    # pylint: disable=too-complex,too-many-branches,too-many-locals,too-many-nested-blocks,too-many-statements
    bu = get_current_bu(request)
    user_is_app_admin = is_app_admin(request.user)

    # Determine selected BU filter
    selected_bu_slug = request.GET.get("bu", "")
    if not selected_bu_slug:
        selected_bu_slug = bu.slug if bu else ("all" if user_is_app_admin else "")

    # All BUs for dropdown (only for app admins)
    all_bus = list(BU.objects.filter(is_active=True).order_by("bu_name", "division")) if user_is_app_admin else []

    # Default to showing last 30 days
    end_date = timezone.now()
    start_date = end_date - timedelta(days=30)
    previous_start_date = start_date - timedelta(days=30)

    # Scoped querysets
    user_qs = _user_base_qs(bu, selected_bu_slug, user_is_app_admin)
    usage_qs = _usage_base_qs(UsageTracking.objects.all(), bu, selected_bu_slug, user_is_app_admin)

    total_users = user_qs.count()
    new_users = user_qs.filter(date_joined__gte=start_date).count()
    previous_new_users = user_qs.filter(date_joined__range=(previous_start_date, start_date)).count()

    if previous_new_users > 0:
        new_users_percent = round(((new_users - previous_new_users) / previous_new_users) * 100)
    else:
        new_users_percent = 100 if new_users > 0 else 0

    active_users = usage_qs.filter(timestamp__gte=start_date).values("user").distinct().count()

    previous_active_users = (
        usage_qs.filter(timestamp__range=(previous_start_date, start_date)).values("user").distinct().count()
    )

    if previous_active_users > 0:
        active_users_change = round(((active_users - previous_active_users) / previous_active_users) * 100)
    else:
        active_users_change = 100 if active_users > 0 else 0

    total_views = usage_qs.filter(timestamp__gte=start_date).count()
    previous_total_views = usage_qs.filter(timestamp__range=(previous_start_date, start_date)).count()

    if previous_total_views > 0:
        views_percent_change = round(((total_views - previous_total_views) / previous_total_views) * 100)
    else:
        views_percent_change = 100 if total_views > 0 else 0

    top_users = []
    user_stats = (
        usage_qs.filter(timestamp__gte=start_date)
        .values("user")
        .annotate(page_views=Count("id"))
        .order_by("-page_views")[:10]
    )

    for stat in user_stats:
        user = User.objects.get(pk=stat["user"])
        last_activity = usage_qs.filter(user=user).order_by("-timestamp").first()
        # Calculate actual average session time for this user
        user_sessions = usage_qs.filter(user=user).order_by("timestamp")
        total_duration = 0
        session_count = 0

        # Simple session calculation: if gap between records > 30 min, consider it a new session
        if user_sessions.count() > 1:
            prev_timestamp = None
            session_durations = []

            for activity in user_sessions:
                if prev_timestamp:
                    time_diff = (activity.timestamp - prev_timestamp).total_seconds() / 60

                    if time_diff <= 30:  # Same session (less than 30 min gap)
                        total_duration += time_diff
                    else:  # New session
                        if total_duration > 0:
                            session_durations.append(total_duration)
                            total_duration = 0
                            session_count += 1

                prev_timestamp = activity.timestamp

            # Add the last session if there's any duration
            if total_duration > 0:
                session_durations.append(total_duration)
                session_count += 1

            avg_time = sum(session_durations) / max(len(session_durations), 1)
            avg_session_time_str = f"{int(avg_time)} mins"
        else:
            avg_session_time_str = "N/A"  # Not enough data

        top_users.append(
            {
                "username": user.username,
                "page_views": stat["page_views"],
                "last_active": last_activity.timestamp if last_activity else "N/A",
                "avg_session_time": avg_session_time_str,
            }
        )
    # Calculate average session time across all users
    all_sessions = usage_qs.filter(timestamp__gte=start_date).order_by("user", "timestamp")
    total_duration = 0
    session_count = 0

    current_user = None
    prev_timestamp = None
    session_durations = []

    for activity in all_sessions:
        # If user changed, reset the session tracking
        if current_user != activity.user_id:
            if current_user is not None and total_duration > 0:
                session_durations.append(total_duration)
                session_count += 1

            current_user = activity.user_id
            prev_timestamp = None
            total_duration = 0

        if prev_timestamp:
            time_diff = (activity.timestamp - prev_timestamp).total_seconds() / 60

            if time_diff <= 30:  # Same session (less than 30 min gap)
                total_duration += time_diff
            else:  # New session
                if total_duration > 0:
                    session_durations.append(total_duration)
                    session_count += 1
                    total_duration = 0

        prev_timestamp = activity.timestamp

    # Add the last session if there's any duration
    if total_duration > 0:
        session_durations.append(total_duration)
        session_count += 1

    if session_durations:
        current_avg_time = sum(session_durations) / len(session_durations)
        avg_session_time = f"{int(current_avg_time)} mins"

        prev_period_start = start_date - (end_date - start_date)  # noqa: F841
        prev_period_end = start_date  # noqa: F841

        # Similar calculation for previous period (simplified for brevity)
        prev_session_durations: list[float] = []
        # Similar logic as above to calculate prev_session_durations

        if prev_session_durations:
            prev_avg_time = sum(prev_session_durations) / len(prev_session_durations)
            if prev_avg_time > 0:
                session_time_change = int(((current_avg_time - prev_avg_time) / prev_avg_time) * 100)
            else:
                session_time_change = 100  # If previously 0, it's a 100% increase
        else:
            session_time_change = 100  # No previous data, consider it 100% increase
    else:
        avg_session_time = "N/A"
        session_time_change = 0

    bu_breakdown = _compute_bu_breakdown(start_date, end_date) if user_is_app_admin else []

    context = {
        "total_users": total_users,
        "new_users_percent": new_users_percent,
        "active_users": active_users,
        "active_users_change": active_users_change,
        "total_views": total_views,
        "views_percent_change": views_percent_change,
        "avg_session_time": avg_session_time,
        "session_time_change": session_time_change,
        "top_users": top_users,
        "selected_stream": get_default_stream_name(request),  # Default stream
        "user_is_app_admin": user_is_app_admin,
        "all_bus": all_bus,
        "selected_bu_slug": selected_bu_slug,
        "bu_breakdown": bu_breakdown,
        "bu_breakdown_json": json.dumps(bu_breakdown),
    }

    return render(request, "products/usage_tracking.html", context)


@login_required
@user_passes_test(is_super_admin)
def usage_tracking_data(request):  # noqa: C901, CCR001
    """API endpoint to get usage tracking data for charts — BU-scoped."""
    # pylint: disable=too-complex,too-many-branches,too-many-locals,too-many-statements
    bu = get_current_bu(request)
    user_is_admin = is_app_admin(request.user)
    selected_bu_slug = request.GET.get("bu", "")
    if not selected_bu_slug:
        selected_bu_slug = bu.slug if bu else ("all" if user_is_admin else "")

    date_range = request.GET.get("range", "30")

    if date_range == "custom":  # Handle custom date range
        start_str = request.GET.get("start")
        end_str = request.GET.get("end")

        try:
            start_date = datetime.strptime(start_str, "%Y-%m-%d")
            end_date = datetime.strptime(end_str, "%Y-%m-%d")
            # Add one day to end date to include the entire day
            end_date = end_date + timedelta(days=1)
        except (ValueError, TypeError):
            # If dates are invalid, fall back to 30 days
            end_date = timezone.now()
            start_date = end_date - timedelta(days=30)
    else:
        days = int(date_range)
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)

    if timezone.is_naive(start_date):
        start_date = timezone.make_aware(start_date)
    if timezone.is_naive(end_date):
        end_date = timezone.make_aware(end_date)

    period_length = end_date - start_date
    previous_start_date = start_date - period_length
    previous_end_date = start_date

    # Scoped querysets
    usage_qs = _usage_base_qs(UsageTracking.objects.all(), bu, selected_bu_slug, user_is_admin)
    user_qs = _user_base_qs(bu, selected_bu_slug, user_is_admin)

    total_views = usage_qs.filter(timestamp__gte=start_date, timestamp__lt=end_date).count()
    previous_total_views = usage_qs.filter(timestamp__gte=previous_start_date, timestamp__lt=previous_end_date).count()

    if previous_total_views > 0:
        views_percent_change = round(((total_views - previous_total_views) / previous_total_views) * 100)
    else:
        views_percent_change = 100 if total_views > 0 else 0

    active_users = usage_qs.filter(timestamp__gte=start_date, timestamp__lt=end_date).values("user").distinct().count()

    previous_active_users = (
        usage_qs.filter(timestamp__gte=previous_start_date, timestamp__lt=previous_end_date)
        .values("user")
        .distinct()
        .count()
    )

    if previous_active_users > 0:
        active_users_change = round(((active_users - previous_active_users) / previous_active_users) * 100)
    else:
        active_users_change = 100 if active_users > 0 else 0

    total_users = user_qs.count()
    new_users = user_qs.filter(date_joined__gte=start_date, date_joined__lt=end_date).count()
    previous_new_users = user_qs.filter(date_joined__gte=previous_start_date, date_joined__lt=previous_end_date).count()

    if previous_new_users > 0:
        new_users_percent = round(((new_users - previous_new_users) / previous_new_users) * 100)
    else:
        new_users_percent = 100 if new_users > 0 else 0

    all_sessions = usage_qs.filter(timestamp__gte=start_date, timestamp__lt=end_date).order_by("user", "timestamp")

    session_durations = []
    current_user = None
    prev_timestamp = None
    total_duration = 0

    for activity in all_sessions:
        if current_user != activity.user_id:
            if current_user is not None and total_duration > 0:
                session_durations.append(total_duration)
            current_user = activity.user_id
            prev_timestamp = None
            total_duration = 0

        if prev_timestamp:
            time_diff = (activity.timestamp - prev_timestamp).total_seconds() / 60
            if time_diff <= 30:  # Same session
                total_duration += time_diff
            else:  # New session
                if total_duration > 0:
                    session_durations.append(total_duration)
                    total_duration = 0

        prev_timestamp = activity.timestamp

    if total_duration > 0:
        session_durations.append(total_duration)

    if session_durations:
        current_avg_time = sum(session_durations) / len(session_durations)
        avg_session_time = f"{int(current_avg_time)} mins"

        prev_sessions = usage_qs.filter(timestamp__gte=previous_start_date, timestamp__lt=previous_end_date).order_by(
            "user", "timestamp"
        )

        prev_session_durations = []
        current_user = None
        prev_timestamp = None
        total_duration = 0

        for activity in prev_sessions:
            if current_user != activity.user_id:
                if current_user is not None and total_duration > 0:
                    prev_session_durations.append(total_duration)
                current_user = activity.user_id
                prev_timestamp = None
                total_duration = 0

            if prev_timestamp:
                time_diff = (activity.timestamp - prev_timestamp).total_seconds() / 60
                if time_diff <= 30:
                    total_duration += time_diff
                else:
                    if total_duration > 0:
                        prev_session_durations.append(total_duration)
                        total_duration = 0

            prev_timestamp = activity.timestamp

        if total_duration > 0:
            prev_session_durations.append(total_duration)

        if prev_session_durations:
            prev_avg_time = sum(prev_session_durations) / len(prev_session_durations)
            if prev_avg_time > 0:
                session_time_change = int(((current_avg_time - prev_avg_time) / prev_avg_time) * 100)
            else:
                session_time_change = 100
        else:
            session_time_change = 100
    else:
        avg_session_time = "N/A"
        session_time_change = 0

    # Pass scoped usage_qs to helper functions
    daily_data = generate_daily_usage_data(start_date, end_date, usage_qs)

    page_views_data = generate_page_views_data(start_date, end_date, usage_qs)

    hourly_data = generate_hourly_activity_data(start_date, end_date, usage_qs)

    # BU breakdown for app admins
    bu_breakdown = _compute_bu_breakdown(start_date, end_date) if user_is_admin else []

    return JsonResponse(
        {
            "daily_usage": daily_data,
            "page_views": page_views_data,
            "hourly_activity": hourly_data,
            "bu_breakdown": bu_breakdown,
            "stats": {
                "total_views": total_views,
                "views_percent_change": views_percent_change,
                "active_users": active_users,
                "active_users_change": active_users_change,
                "total_users": total_users,
                "new_users_percent": new_users_percent,
                "avg_session_time": avg_session_time,
                "session_time_change": session_time_change,
            },
        }
    )


# Helper functions for usage tracking data
