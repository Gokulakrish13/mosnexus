"""Products app - Role Assignment, Stream Access, User Profiles, and related views."""

# pylint: disable=broad-exception-caught,protected-access,too-many-lines

from ._helpers import (
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_SIZE,
    AuditLog,
    ChatMessage,
    Count,
    CustomUser,
    HttpResponse,
    Note,
    Notification,
    Participant,
    RecurringReservation,
    Stream,
    SystemAllocation,
    UsageTracking,
    User,
    UserDataVersion,
    UserRole,
    UserStreamAccess,
    _fac_granted,
    _get_role_level,
    _is_app_admin_user,
    can_delete_products,
    can_edit_products,
    can_manage_system_allocation,
    can_manage_users,
    can_view_analytics,
    get_current_bu,
    get_default_stream_name,
    get_object_or_404,
    is_admin,
    is_app_admin,
    is_lab_incharge,
    is_super_admin,
    login_not_required,
    login_required,
    messages,
    redirect,
    render,
    require_POST,
    reverse,
    timedelta,
    timezone,
    update_session_auth_hash,
    validate_uploaded_file,
)

__all__ = [
    "assign_role",
    "remove_role",
    "grant_stream_access",
    "revoke_stream_access",
    "user_profile",
    "custom_password_change",
    "please_login",
    "faq",
    "add_participant",
    "remove_participant",
    "delete_user_backup",
]


@login_required
@require_POST
def assign_role(request, user_id):  # noqa: CCR001
    """Assign a role to a user."""
    if not is_super_admin(request.user):
        messages.error(request, "Only Super Admins can assign roles.")
        return redirect("user_list")

    user = get_object_or_404(User, id=user_id)
    role = request.POST.get("role")

    if role not in ["user", "lab_incharge", "admin", "super_admin", "app_admin"]:
        messages.error(request, "Invalid role selected.")
        return redirect("user_list")

    # ── Hierarchy enforcement (app_admin exempt) ──
    requester_level = _get_role_level(request.user)
    target_level = _get_role_level(user)
    hierarchy = CustomUser._ROLE_HIERARCHY
    role_level = hierarchy.index(role) if role in hierarchy else len(hierarchy)
    if not _is_app_admin_user(request.user):
        if requester_level >= target_level:
            messages.error(request, "You cannot modify roles for a user with equal or higher privilege than yours.")
            return redirect("user_list")
        if requester_level >= role_level:
            messages.error(request, "You cannot assign a role that is at or above your own privilege level.")
            return redirect("user_list")

    custom_user, _created = CustomUser.objects.get_or_create(user=user)

    # Check if user already has this role
    if custom_user.user_roles.filter(role=role).exists():
        messages.info(request, f"User {user.username} already has the {role} role.")
        return redirect("user_list")

    # Create the role assignment
    UserRole.objects.create(custom_user=custom_user, role=role, assigned_by=request.user)

    # Sync Django flags based on role
    flag_changed = False
    if role in ("admin", "super_admin", "app_admin") and not user.is_staff:
        user.is_staff = True
        flag_changed = True
    if role in ("super_admin", "app_admin") and not user.is_superuser:
        user.is_superuser = True
        flag_changed = True
    if flag_changed:
        user.save(update_fields=["is_staff", "is_superuser"])

    AuditLog.log(
        action="permission_change",
        title=f"Assigned role {role} to user {user.username}",
        user=request.user,
        request=request,
        obj=user,
        module="users",
        severity="warning",
    )
    messages.success(request, f"Role {role} assigned to {user.username}.")
    return redirect("user_list")


@login_required
@require_POST
def remove_role(request, user_id):  # noqa: C901, CCR001
    """Remove a role from a user."""
    # pylint: disable=too-complex
    if not is_super_admin(request.user):
        messages.error(request, "Only Super Admins can remove roles.")
        return redirect("user_list")

    user = get_object_or_404(User, id=user_id)
    role = request.POST.get("role")

    # ── Hierarchy enforcement (app_admin exempt) ──
    requester_level = _get_role_level(request.user)
    target_level = _get_role_level(user)
    hierarchy = CustomUser._ROLE_HIERARCHY
    role_level = hierarchy.index(role) if role in hierarchy else len(hierarchy)
    if not _is_app_admin_user(request.user):
        if requester_level >= target_level:
            messages.error(request, "You cannot modify roles for a user with equal or higher privilege than yours.")
            return redirect("user_list")
        if requester_level >= role_level:
            messages.error(request, "You cannot remove a role that is at or above your own privilege level.")
            return redirect("user_list")

    try:
        custom_user = user.custom_profile  # type: ignore[attr-defined]
        role_obj = custom_user.user_roles.get(role=role)
        role_obj.delete()
        # Invalidate cached roles so subsequent checks see the change
        custom_user.clear_roles_cache()

        AuditLog.log(
            action="permission_change",
            title=f"Removed role {role} from user {user.username}",
            user=request.user,
            request=request,
            obj=user,
            module="users",
            severity="warning",
        )

        # Sync Django flags based on remaining roles
        remaining = set(custom_user.user_roles.values_list("role", flat=True))
        flag_changed = False
        needs_superuser = bool(remaining & {"super_admin", "app_admin"})
        needs_staff = bool(remaining & {"admin", "super_admin", "app_admin"})
        if user.is_superuser and not needs_superuser:
            user.is_superuser = False
            flag_changed = True
        if user.is_staff and not needs_staff:
            user.is_staff = False
            flag_changed = True
        if flag_changed:
            user.save(update_fields=["is_staff", "is_superuser"])

        # Check if user has any roles left
        remaining_count = len(remaining)
        if remaining_count == 0:
            # Remove all stream access when user has no roles
            custom_user.stream_access.all().delete()
            messages.success(
                request,
                f"Role {role} removed from {user.username}. All stream access has been revoked as user has no remaining roles.",  # noqa: E501
            )
        else:
            messages.success(request, f"Role {role} removed from {user.username}.")

    except (CustomUser.DoesNotExist, UserRole.DoesNotExist):
        messages.error(request, "Role assignment not found.")

    return redirect("user_list")


@login_required
@require_POST
def grant_stream_access(request, user_id):
    """Grant stream access to a user."""
    if not is_super_admin(request.user):
        messages.error(request, "Only Super Admins can grant stream access.")
        return redirect("user_list")

    user = get_object_or_404(User, id=user_id)

    # ── Hierarchy enforcement (app_admin exempt) ──
    if not _is_app_admin_user(request.user):
        if _get_role_level(request.user) >= _get_role_level(user):
            messages.error(request, "You cannot modify stream access for a user with equal or higher privilege.")
            return redirect("user_list")

    stream_id = request.POST.get("stream_id")

    try:
        stream = Stream.objects.get(id=stream_id)
        custom_user, created = CustomUser.objects.get_or_create(user=user)

        UserStreamAccess.objects.get_or_create(
            custom_user=custom_user, stream=stream, defaults={"granted_by": request.user}
        )

        AuditLog.log(
            action="permission_change",
            title=f"Granted stream access to {user.username} for stream {stream.name}",
            user=request.user,
            request=request,
            obj=user,
            module="users",
            severity="info",
            stream=stream,
        )
        if created:
            messages.success(request, f"Stream access granted: {user.username} can now access {stream.name}.")
            Notification.notify(
                user,
                f"You have been granted access to stream '{stream.name}' by {request.user.username}.",
                "user_access",
            )
        else:
            messages.info(request, f"User {user.username} already has access to {stream.name}.")

    except Stream.DoesNotExist:
        messages.error(request, "Invalid stream selected.")

    return redirect("user_list")


@login_required
@require_POST
def revoke_stream_access(request, user_id):
    """Revoke stream access from a user."""
    if not is_super_admin(request.user):
        messages.error(request, "Only Super Admins can revoke stream access.")
        return redirect("user_list")

    user = get_object_or_404(User, id=user_id)

    # ── Hierarchy enforcement (app_admin exempt) ──
    if not _is_app_admin_user(request.user):
        if _get_role_level(request.user) >= _get_role_level(user):
            messages.error(request, "You cannot modify stream access for a user with equal or higher privilege.")
            return redirect("user_list")

    stream_id = request.POST.get("stream_id")

    try:
        stream = Stream.objects.get(id=stream_id)
        custom_user = user.custom_profile  # type: ignore[attr-defined]
        access = custom_user.stream_access.get(stream=stream)
        access.delete()
        AuditLog.log(
            action="permission_change",
            title=f"Revoked stream access from {user.username} for stream {stream.name}",
            user=request.user,
            request=request,
            obj=user,
            module="users",
            severity="warning",
            stream=stream,
        )
        messages.success(request, f"Stream access revoked: {user.username} can no longer access {stream.name}.")
        Notification.notify(
            user, f"Your access to stream '{stream.name}' has been revoked by {request.user.username}.", "user_access"
        )

    except (Stream.DoesNotExist, CustomUser.DoesNotExist, UserStreamAccess.DoesNotExist):
        messages.error(request, "Stream access not found.")

    return redirect("user_list")


def _build_dynamic_profile_menus(profile_user, request):  # noqa: CCR001
    """Build dynamic sidebar menu and quick action items based on user's usage patterns."""
    # pylint: disable=too-many-locals
    is_admin_user = is_admin(profile_user) or is_super_admin(profile_user)

    # All possible features – each will be scored by real usage data
    features_list = [
        {
            "key": "reservations",
            "url_name": "reservations_hub",
            "label": "Reservations Hub",
            "icon": "fas fa-calendar-alt",
            "color": "primary",
            "url_patterns": ["/reservations", "/booking"],
            "base_score": 10,
        },
        {
            "key": "build_servers",
            "url_name": "build_servers_dashboard",
            "label": "Build Servers",
            "icon": "fas fa-server",
            "color": "success",
            "url_patterns": ["/build-servers", "/build_servers"],
            "base_score": 8,
        },
        {
            "key": "holistic",
            "url_name": "holistic_dashboard",
            "label": "Holistic Dashboard",
            "icon": "fas fa-chart-pie",
            "color": "info",
            "url_patterns": ["/holistic"],
            "base_score": 6,
        },
        {
            "key": "notes",
            "url_name": "notes_list",
            "label": "Notes",
            "icon": "fas fa-sticky-note",
            "color": "warning",
            "url_patterns": ["/notes"],
            "base_score": 5,
        },
        {
            "key": "calibration",
            "url_name": "calibration_hub",
            "label": "Calibration",
            "icon": "fas fa-tools",
            "color": "warning",
            "url_patterns": ["/calibration"],
            "base_score": 4,
        },
        {
            "key": "compliance",
            "url_name": "compliance_hub",
            "label": "Compliance",
            "icon": "fas fa-shield-alt",
            "color": "success",
            "url_patterns": ["/compliance"],
            "base_score": 4,
        },
        {
            "key": "team_chat",
            "url_name": "team_chat",
            "label": "Team Chat",
            "icon": "fas fa-comments",
            "color": "info",
            "url_patterns": ["/team-chat", "/chat"],
            "base_score": 4,
        },
        {
            "key": "analytics",
            "url_name": "analytics_dashboard",
            "label": "Analytics",
            "icon": "fas fa-chart-bar",
            "color": "info",
            "url_patterns": ["/analytics"],
            "base_score": 4,
        },
        {
            "key": "trackboard",
            "url_name": "personal_trackboard",
            "label": "Personal Trackboard",
            "icon": "fas fa-tasks",
            "color": "primary",
            "url_patterns": ["/personal_trackboard"],
            "base_score": 3,
        },
        {
            "key": "vendors",
            "url_name": "vendor_hub",
            "label": "Vendors",
            "icon": "fas fa-handshake",
            "color": "primary",
            "url_patterns": ["/vendors"],
            "base_score": 2,
        },
        {
            "key": "waste",
            "url_name": "waste_dashboard",
            "label": "Waste Management",
            "icon": "fas fa-recycle",
            "color": "success",
            "url_patterns": ["/waste"],
            "base_score": 2,
        },
        {
            "key": "tld_badges",
            "url_name": "tld_badge_dashboard",
            "label": "TLD Badges",
            "icon": "fas fa-id-badge",
            "color": "warning",
            "url_patterns": ["/tld-badges", "/tld_badges"],
            "base_score": 2,
        },
        {
            "key": "maintenance",
            "url_name": "maintenance_calendar",
            "label": "Maintenance Calendar",
            "icon": "fas fa-wrench",
            "color": "warning",
            "url_patterns": ["/maintenance"],
            "base_score": 2,
        },
        {
            "key": "support",
            "url_name": "support_ticket_list",
            "label": "Support Tickets",
            "icon": "fas fa-headset",
            "color": "warning",
            "url_patterns": ["/support"],
            "base_score": 2,
        },
        {
            "key": "feature_hub",
            "url_name": "feature_hub",
            "label": "Feature Hub",
            "icon": "fas fa-puzzle-piece",
            "color": "primary",
            "url_patterns": ["/feature-hub"],
            "base_score": 1,
        },
        {
            "key": "faq",
            "url_name": "faq",
            "label": "FAQ",
            "icon": "fas fa-question-circle",
            "color": "info",
            "url_patterns": ["/faq"],
            "base_score": 1,
        },
        {
            "key": "build_os",
            "url_name": "build_os_info",
            "label": "Build OS Info",
            "icon": "fas fa-info-circle",
            "color": "info",
            "url_patterns": ["/build_os_info"],
            "base_score": 1,
        },
        # Admin-only features
        {
            "key": "audit_log",
            "url_name": "audit_log_list",
            "label": "Audit Logs",
            "icon": "fas fa-clipboard-list",
            "color": "secondary",
            "url_patterns": ["/audit-log"],
            "base_score": 2,
            "admin_only": True,
        },
        {
            "key": "manage_streams",
            "url_name": "manage_streams",
            "label": "Manage Streams",
            "icon": "fas fa-stream",
            "color": "primary",
            "url_patterns": ["/manage-streams"],
            "base_score": 2,
            "admin_only": True,
        },
    ]

    available_features = [f for f in features_list if not f.get("admin_only") or is_admin_user]

    # ── Gather user's page-visit counts (last 90 days) ──────────────────
    ninety_days_ago = timezone.now() - timedelta(days=90)
    usage_qs = (
        UsageTracking.objects.filter(user=profile_user, timestamp__gte=ninety_days_ago)
        .values("page_url")
        .annotate(visit_count=Count("id"))
    )
    url_visits = {(e["page_url"] or "").lower(): e["visit_count"] for e in usage_qs}

    # ── Gather model-level activity boosts ──────────────────────────────
    alloc_count = SystemAllocation.objects.filter(user=profile_user).count()
    recurring_count = RecurringReservation.objects.filter(created_by=profile_user).count()
    note_count = Note.objects.filter(created_by=profile_user).count()
    try:
        chat_count = ChatMessage.objects.filter(user=profile_user).count()
    except Exception:
        chat_count = 0

    model_boosts = {
        "reservations": min(alloc_count * 3 + recurring_count * 5, 40),
        "notes": min(note_count * 2, 20),
        "team_chat": min(chat_count, 20),
    }

    # ── Score each feature ──────────────────────────────────────────────
    scored = []
    for feat in available_features:
        score = feat["base_score"]
        # URL pattern matching
        for pat in feat["url_patterns"]:  # type: ignore[attr-defined]
            pat_l = pat.lower()
            for visited_url, cnt in url_visits.items():
                if pat_l in visited_url:
                    score += cnt
        # Model-level boost
        score += model_boosts.get(str(feat["key"]), 0)
        # Resolve URL
        try:
            url = reverse(feat["url_name"])  # type: ignore[arg-type]
        except Exception:
            continue
        scored.append(
            {
                "key": feat["key"],
                "label": feat["label"],
                "icon": feat["icon"],
                "color": feat["color"],
                "url": url,
                "score": score,
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)

    # Quick Actions: top 4 dynamic (Dashboard + Sign Out handled in template)
    quick_actions = scored[:4]
    # Sidebar: top 6 dynamic (Dashboard + Account section handled in template)
    sidebar_menu = scored[:6]
    return quick_actions, sidebar_menu


@login_required
def user_profile(request, user_id=None):  # noqa: CCR001
    """User profile."""
    if user_id:
        # Only admins can view other users' profiles
        if not can_manage_users(request.user):
            messages.error(request, "Access denied. You can only view your own profile.")
            return redirect("user_profile")

        try:
            profile_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            messages.error(request, "User not found.")
            return redirect("user_list")
    else:
        profile_user = request.user

    custom_profile, _created = CustomUser.objects.get_or_create(user=profile_user)

    if request.method == "POST" and profile_user == request.user:
        profile_image = request.FILES.get("profile_image")
        if profile_image:
            is_valid, error_msg = validate_uploaded_file(
                profile_image, ALLOWED_IMAGE_TYPES, ALLOWED_IMAGE_EXTENSIONS, MAX_IMAGE_SIZE
            )
            if not is_valid:
                messages.error(request, f"Invalid image: {error_msg}")
                return redirect("user_profile")
            custom_profile.profile_image = profile_image
            custom_profile.save()
            messages.success(request, "Profile image updated successfully!")
        else:
            messages.error(request, "No image file selected.")
        return redirect("user_profile")

    user_roles = custom_profile.user_roles.all()
    stream_access = custom_profile.stream_access.select_related("stream").all()
    accessible_streams = custom_profile.get_accessible_streams(business_unit=get_current_bu(request))

    permissions = {
        "can_manage_users": can_manage_users(profile_user),
        "can_manage_system_allocation": can_manage_system_allocation(profile_user),
        "can_edit_products": can_edit_products(profile_user),
        "can_delete_products": can_delete_products(profile_user),
        "can_view_analytics": can_view_analytics(profile_user),
        "is_admin": is_admin(profile_user),
        "is_super_admin": is_super_admin(profile_user),
        "is_lab_incharge": is_lab_incharge(profile_user),
    }

    # Super admins / app admins can deactivate other users (not themselves)
    can_deactivate = is_super_admin(request.user) and profile_user != request.user

    # Build dynamic menus based on user usage
    quick_actions, sidebar_menu = _build_dynamic_profile_menus(profile_user, request)

    return render(
        request,
        "products/user_profile.html",
        {
            "profile_user": profile_user,
            "custom_profile": custom_profile,
            "user_roles": user_roles,
            "stream_access": stream_access,
            "accessible_streams": accessible_streams,
            "permissions": permissions,
            "is_own_profile": profile_user == request.user,
            "can_edit": request.user == profile_user or can_manage_users(request.user),
            "can_deactivate": can_deactivate,
            "selected_stream": "profile",
            "quick_actions": quick_actions,
            "sidebar_menu": sidebar_menu,
        },
    )


@login_required
def custom_password_change(request):
    """Custom password change."""
    if request.method == "POST":
        old_password = request.POST.get("old_password")
        new_password1 = request.POST.get("new_password1")
        new_password2 = request.POST.get("new_password2")
        user = request.user
        errors = []
        if not user.check_password(old_password):
            errors.append("Old password is incorrect.")
        if new_password1 != new_password2:
            errors.append("New passwords do not match.")
        if len(new_password1) < 6:
            errors.append("New password must be at least 6 characters.")
        # Add more password validation as needed
        if errors:
            return render(
                request,
                "products/password_change_form.html",
                {"selected_stream": get_default_stream_name(request), "form_errors": errors},
            )
        user.set_password(new_password1)
        user.save()
        update_session_auth_hash(request, user)
        AuditLog.log(
            action="update",
            title=f"Password changed by {request.user.username}",
            user=request.user,
            request=request,
            obj=request.user,
            module="auth",
            severity="info",
        )
        return redirect("password_change_done")
    return render(request, "products/password_change_form.html", {"selected_stream": get_default_stream_name(request)})


@login_not_required
def please_login(request):
    """Please login."""
    next_url = request.GET.get("next", "")
    # Don't pass logout/login URLs as next — they cause redirect loops
    if next_url and ("/logout" in next_url or "/login" in next_url):
        next_url = ""
    return render(request, "products/please_login.html", {"next": next_url})


def faq(request, stream=None):
    """Render the FAQ/help page for users."""
    context = {
        "selected_stream": stream or "",
        "stream": stream or "",
        "is_admin": is_app_admin(request.user) if request.user.is_authenticated else False,
    }
    return render(request, "products/faq.html", context)


@login_required
@require_POST
def add_participant(request):
    """Add participant."""
    if not _fac_granted(request.user) and not request.user.is_superuser:
        return redirect("user_list")
    name = request.POST.get("name", "").strip()
    email = request.POST.get("email", "").strip()
    if not name or not email:
        messages.error(request, "Name and email are required.")
        return redirect("user_list")
    if Participant.objects.filter(email=email).exists():
        messages.error(request, "A participant with this email already exists.")
        return redirect("user_list")
    bu = get_current_bu(request)
    Participant.objects.create(name=name, email=email, business_unit=bu)
    AuditLog.log(
        "create",
        f'Added participant "{name}" ({email})',
        user=request.user,
        request=request,
        module="allocation",
        severity="info",
    )
    messages.success(request, f"Participant {name} added.")
    return redirect("user_list")


@login_required
@require_POST
def remove_participant(request, participant_id):
    """Remove participant."""
    if not _fac_granted(request.user) and not request.user.is_superuser:
        messages.error(request, "Only admins can remove participants.")
        return redirect("user_list")
    participant = get_object_or_404(Participant, id=participant_id)
    AuditLog.log(
        "delete",
        f'Removed participant "{participant.name}" ({participant.email})',
        user=request.user,
        request=request,
        module="allocation",
        severity="info",
    )
    participant.delete()
    messages.success(request, "Participant removed.")
    return redirect("user_list")


@login_required
def delete_user_backup(request, backup_id):
    """Delete user backup."""
    if not _fac_granted(request.user) and not request.user.is_superuser:
        return HttpResponse("Unauthorized", status=401)
    backup = get_object_or_404(UserDataVersion, id=backup_id)
    backup.delete()
    messages.success(request, "Backup deleted successfully.")
    return redirect("user_list")
