"""Products app — Auth views."""

# pylint: disable=broad-exception-caught,logging-too-many-args,too-many-lines


from django.utils.http import url_has_allowed_host_and_scheme

from ._helpers import (
    AuditLog,
    BUDeletionRequest,
    BusinessUnit,
    CustomUser,
    Notification,
    Participant,
    Q,
    Stream,
    StreamDeletionHistory,
    User,
    UserBUAccess,
    UserDataVersion,
    UserRole,
    UserStreamAccess,
    _fac_granted,
    _get_role_level,
    _is_app_admin_user,
    authenticate,
    can_manage_users,
    get_bu_streams,
    get_current_bu,
    get_default_stream_name,
    get_object_or_404,
    get_user_model,
    is_app_admin,
    is_super_admin,
    logger,
    login,
    login_not_required,
    login_required,
    logout,
    messages,
    redirect,
    render,
    require_POST,
)

__all__ = [
    "user_register",
    "user_login",
    "user_logout",
    "promote_user",
    "depromote_user",
    "change_user_role",
    "manage_user_roles_and_streams",
    "user_registration_request",
    "user_list",
    "approve_user",
    "decline_user",
]


@login_not_required
def user_register(request):  # noqa: C901, CCR001
    # pylint: disable=too-many-return-statements,too-complex
    """User register."""
    available_streams = (
        Stream.objects.select_related("business_unit")
        .filter(
            is_active=True, allow_public_registration=True, business_unit__isnull=False, business_unit__is_active=True
        )
        .order_by("business_unit__bu_name", "name")
    )
    available_bus = BusinessUnit.objects.filter(is_active=True).order_by("bu_name", "division")

    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password")
        selected_streams = request.POST.getlist("streams")
        selected_bus = request.POST.getlist("business_units")

        ctx = {"available_streams": available_streams, "available_bus": available_bus}

        if not email.endswith("@philips.com"):
            ctx["form_error"] = "Email must be a @philips.com address."
            return render(request, "products/register.html", ctx)

        if User.objects.filter(username=username).exists():
            ctx["form_error"] = "Username already exists."
            return render(request, "products/register.html", ctx)

        if User.objects.filter(email=email).exists():
            ctx["form_error"] = "Email already registered."
            return render(request, "products/register.html", ctx)

        if not selected_bus:
            ctx["form_error"] = "Please select at least one Business Unit."
            return render(request, "products/register.html", ctx)

        if not selected_streams:
            ctx["form_error"] = "Please select at least one stream."
            return render(request, "products/register.html", ctx)
        try:
            user = User.objects.create_user(username=username, email=email, password=password)
            user.is_active = False
            user.save()

            custom_user = CustomUser.objects.create(user=user)
            for stream_id in selected_streams:
                try:
                    stream = Stream.objects.get(id=stream_id)
                    custom_user.requested_streams.add(stream)
                except Stream.DoesNotExist:
                    continue
            for bu_id in selected_bus:
                try:
                    bu = BusinessUnit.objects.get(id=bu_id)
                    custom_user.requested_bus.add(bu)
                except BusinessUnit.DoesNotExist:
                    continue
        except Exception:
            ctx["form_error"] = "An error occurred. Please try again."
            return render(request, "products/register.html", ctx)

        messages.success(request, "Registration successful! Please wait for admin approval.")
        return redirect("login")

    return render(
        request,
        "products/register.html",
        {
            "available_streams": available_streams,
            "available_bus": available_bus,
        },
    )


@login_not_required
def user_login(request):  # noqa: CCR001
    # pylint: disable=too-many-return-statements,too-complex
    """User login."""
    access_error = None
    # Capture 'next' from GET (initial page load) or POST (form submission)
    next_url = request.POST.get("next", request.GET.get("next", ""))
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            if not user.is_active:
                return render(
                    request,
                    "products/login.html",
                    {"next": next_url, "form_error": "Your account is pending admin approval."},
                )
            # Check access using the user object, not request.user
            custom_profile, _created = CustomUser.objects.get_or_create(user=user)
            if not user.is_superuser and not custom_profile.user_roles.exists():  # type: ignore[attr-defined]
                access_error = "Access denied. You have no assigned roles. Please contact an administrator."
                return render(request, "products/login.html", {"access_error": access_error, "next": next_url})
            login(request, user)
            # Clear BU selection so user re-confirms on every login
            request.session.pop("selected_bu_id", None)
            request.session.pop("selected_bu_name", None)
            request.session.pop("selected_bu_code", None)
            AuditLog.log(
                "login",
                f'User "{user.username}" logged in',  # type: ignore[attr-defined]
                user=user,
                request=request,
                module="authentication",
                severity="info",
                description=f'User "{user.username}" logged in',  # type: ignore[attr-defined]
            )
            if next_url and url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
            ):
                return redirect(f"/select-bu/?next={next_url}")
            return redirect("select_bu")
        # Check if user exists with valid password but is deactivated
        # (Django's default ModelBackend rejects inactive users at authenticate())
        UserModel = get_user_model()  # noqa: N806  # pylint: disable=invalid-name
        try:
            inactive_user = UserModel.objects.get(username=username)
            if not inactive_user.is_active and inactive_user.check_password(password):
                return render(
                    request,
                    "products/login.html",
                    {
                        "next": next_url,
                        "form_error": (
                            "Your account has been deactivated. "
                            "Please contact an administrator to reactivate your account."
                        ),
                    },
                )
        except UserModel.DoesNotExist:
            pass
        return render(request, "products/login.html", {"next": next_url, "form_error": "Invalid username or password."})
    return render(request, "products/login.html", {"next": next_url})


def user_logout(request):
    """User logout."""
    if "chat_history" in request.session:
        request.session.modified = True
    if request.user.is_authenticated:
        AuditLog.log(
            action="logout",
            title=f'User "{request.user.username}" logged out',
            user=request.user,
            request=request,
            module="authentication",
            severity="info",
            description=f'User "{request.user.username}" logged out',
        )
    logout(request)
    return redirect("/please_login/")


@login_required
@require_POST
def promote_user(request, user_id):
    """Promote user."""
    if not _fac_granted(request.user) and not request.user.is_superuser:
        messages.error(request, "Only admins can promote users.")
        return redirect("product_list")
    user = get_object_or_404(User, id=user_id)
    user.is_staff = True
    user.is_superuser = True
    user.save()
    AuditLog.log(
        action="permission_change",
        title=f"Promoted user {user.username} to admin",
        user=request.user,
        request=request,
        obj=user,
        module="users",
        severity="warning",
    )
    messages.success(request, f"{user.username} changed to admin.")
    Notification.notify(user, f"You have been promoted to admin by {request.user.username}.", "role_change")
    return redirect("user_list")


@login_required
@require_POST
def depromote_user(request, user_id):
    """Depromote user."""
    if not _fac_granted(request.user) and not request.user.is_superuser:
        messages.error(request, "Only super admins can depromote users.")
        return redirect("user_list")
    User = get_user_model()  # noqa: N806  # pylint: disable=invalid-name,redefined-outer-name
    user = get_object_or_404(User, id=user_id)
    if user == request.user:
        messages.error(request, "You cannot depromote yourself.")
        return redirect("user_list")
    user.is_superuser = False  # type: ignore[attr-defined]
    user.is_staff = False  # type: ignore[attr-defined]
    user.save()
    AuditLog.log(
        action="permission_change",
        title=f"Depromoted user {user.username} from admin",  # type: ignore[attr-defined]
        user=request.user,
        request=request,
        obj=user,
        module="users",
        severity="warning",
    )
    messages.success(request, f"User {user.username} has been depromoted from admin.")  # type: ignore[attr-defined]
    Notification.notify(user, f"Your admin privileges have been removed by {request.user.username}.", "role_change")
    return redirect("user_list")


@login_required
@require_POST
def change_user_role(request, user_id):
    """Change user role."""
    if not can_manage_users(request.user):
        messages.error(request, "Access denied. You need admin privileges to change user roles.")
        return redirect("user_list")

    user = get_object_or_404(User, id=user_id)
    new_role = request.POST.get("role")
    stream = request.POST.get("stream") or get_default_stream_name(request)

    if user == request.user and not is_super_admin(request.user):
        messages.error(request, "You cannot change your own role.")
        return redirect("user_list")

    if new_role == "super_admin" and not is_super_admin(request.user):
        messages.error(request, "Only Super Admins or Application Admins can assign Super Admin role.")
        return redirect("user_list")

    if new_role == "app_admin" and not is_super_admin(request.user):
        messages.error(request, "Only Super Admins or Application Admins can assign Application Admin role.")
        return redirect("user_list")

    custom_profile, _created = CustomUser.objects.get_or_create(user=user)
    old_role = custom_profile.role

    custom_profile.role = new_role
    custom_profile.stream = stream
    custom_profile.save()

    if new_role in ["admin", "super_admin", "app_admin"]:
        user.is_staff = True
        if new_role in ["super_admin", "app_admin"]:
            user.is_superuser = True
    else:
        user.is_staff = False
        user.is_superuser = False

    user.save()

    AuditLog.log(
        action="permission_change",
        title=f"Changed role for {user.username} from {old_role} to {new_role}",
        user=request.user,
        request=request,
        obj=user,
        module="users",
        severity="warning",
        old_values={"role": old_role},
        new_values={"role": new_role},
    )
    role_display = dict(UserRole.ROLE_CHOICES).get(new_role, new_role)
    messages.success(
        request,
        f"{user.username} role changed from {dict(UserRole.ROLE_CHOICES).get(old_role, old_role)} to {role_display}.",
    )
    Notification.notify(
        user, f"Your role has been changed to {role_display} by {request.user.username}.", "role_change"
    )
    return redirect("user_list")


@login_required
def manage_user_roles_and_streams(request, user_id):  # noqa: CCR001
    # pylint: disable=too-many-locals
    """View for super admins to manage user roles and stream access."""
    if not is_super_admin(request.user):
        messages.error(request, "Access denied. Only Super Admins can manage user roles and streams.")
        return redirect("user_list")

    target_user = get_object_or_404(User, id=user_id)
    custom_profile, _created = CustomUser.objects.get_or_create(user=target_user)

    if request.method == "POST":
        selected_roles = request.POST.getlist("roles")
        if target_user != request.user:  # Super admins bypass this guard
            custom_profile.roles.clear()
            for role_name in selected_roles:
                try:
                    role = UserRole.objects.get(name=role_name)
                    custom_profile.roles.add(role)
                except UserRole.DoesNotExist:
                    pass

        stream_ids = request.POST.getlist("streams")
        can_write_streams = request.POST.getlist("can_write")
        can_delete_streams = request.POST.getlist("can_delete")

        UserStreamAccess.objects.filter(user=target_user).delete()

        for stream_id in stream_ids:
            try:
                stream = Stream.objects.get(id=stream_id)
                UserStreamAccess.objects.create(
                    user=target_user,
                    stream=stream,
                    can_read=True,
                    can_write=stream_id in can_write_streams,
                    can_delete=stream_id in can_delete_streams,
                    granted_by=request.user,
                )
            except Stream.DoesNotExist:
                pass

        AuditLog.log(
            action="permission_change",
            title=f"Updated roles and stream access for {target_user.username}",
            user=request.user,
            request=request,
            obj=target_user,
            module="users",
            severity="warning",
        )
        messages.success(request, f"Updated roles and stream access for {target_user.username}")
        Notification.notify(
            target_user, f"Your roles and stream access have been updated by {request.user.username}.", "user_access"
        )
        return redirect("user_list")

    all_roles = UserRole.objects.all()
    all_streams = Stream.objects.filter(is_active=True)
    user_roles = custom_profile.roles.all()
    user_stream_access = UserStreamAccess.objects.filter(user=target_user)

    return render(
        request,
        "products/manage_user_access.html",
        {
            "target_user": target_user,
            "custom_profile": custom_profile,
            "all_roles": all_roles,
            "all_streams": all_streams,
            "user_roles": user_roles,
            "user_stream_access": user_stream_access,
        },
    )


@login_required
def user_registration_request(request):
    """Handle user registration with stream access requests."""
    if request.method == "POST":
        custom_profile, _created = CustomUser.objects.get_or_create(user=request.user)
        requested_stream_ids = request.POST.getlist("requested_streams")

        custom_profile.requested_streams.clear()
        for stream_id in requested_stream_ids:
            try:
                stream = Stream.objects.get(id=stream_id, is_active=True, allow_public_registration=True)
                custom_profile.requested_streams.add(stream)
            except Stream.DoesNotExist:
                pass

        messages.success(request, "Your stream access requests have been submitted for approval.")
        return redirect("dashboard")

    available_streams = Stream.objects.filter(is_active=True, allow_public_registration=True)
    custom_profile, _created = CustomUser.objects.get_or_create(user=request.user)

    return render(
        request,
        "products/request_stream_access.html",
        {
            "available_streams": available_streams,
            "custom_profile": custom_profile,
        },
    )


@login_required
def user_list(request):
    # pylint: disable=too-many-locals,protected-access,logging-too-many-args
    """User list."""
    if not can_manage_users(request.user):
        messages.error(request, "Access denied. You need admin privileges to view user list.")
        return redirect("dashboard")

    bu = get_current_bu(request)
    bu_streams_qs = get_bu_streams(request)
    if bu:
        bu_user_ids_stream = (
            UserStreamAccess.objects.filter(stream__in=bu_streams_qs)
            .values_list("custom_user__user_id", flat=True)
            .distinct()
        )
        bu_user_ids_role = UserRole.objects.values_list("custom_user__user_id", flat=True).distinct()
        users = User.objects.filter(
            Q(is_active=True) & (Q(id__in=bu_user_ids_stream) | Q(id__in=bu_user_ids_role) | Q(is_superuser=True))
        )
        # Pending users: inactive, with pending BU requests (new registrations)
        pending_users = User.objects.filter(is_active=False, custom_profile__requested_bus=bu)
        # Deactivated users: inactive, have assigned roles (were active before)
        deactivated_user_ids = UserRole.objects.values_list("custom_user__user_id", flat=True).distinct()
        deactivated_users = User.objects.filter(is_active=False, id__in=deactivated_user_ids).exclude(
            id__in=pending_users.values_list("id", flat=True)
        )
        streams = bu_streams_qs
    else:
        users = User.objects.filter(is_active=True)
        all_inactive = User.objects.filter(is_active=False)
        # Deactivated = inactive users that have roles assigned (were previously active)
        deactivated_user_ids = UserRole.objects.values_list("custom_user__user_id", flat=True).distinct()
        deactivated_users = all_inactive.filter(id__in=deactivated_user_ids)
        # Pending = inactive users without any roles (new registrations)
        pending_users = all_inactive.exclude(id__in=deactivated_user_ids)
        streams = Stream.objects.all()
    if bu:
        participants = Participant.objects.filter(business_unit=bu)
    else:
        participants = Participant.objects.all()
    selected_stream = request.GET.get("stream") or get_default_stream_name(request)
    user_backups = UserDataVersion.objects.order_by("-created_at")
    stream_deletion_history = StreamDeletionHistory.objects.select_related("deleted_by").order_by("-deleted_at")[:100]

    for user in list(users) + list(pending_users) + list(deactivated_users):
        custom_profile, _created = CustomUser.objects.get_or_create(user=user)

    pending_users_data = []
    for user in pending_users:
        custom_profile = CustomUser.objects.get(user=user)
        requested_streams = ", ".join([stream.name for stream in custom_profile.requested_streams.all()])
        requested_bus_display = ", ".join([str(b) for b in custom_profile.requested_bus.all()])
        pending_users_data.append(
            {
                "user": user,
                "requested_streams": requested_streams,
                "requested_bus": requested_bus_display,
            }
        )

    # ── BU Deletion Requests (visible to super_admin / app_admin) ──
    bu_deletion_requests = []
    bu_pending_deletion_count = 0
    if is_super_admin(request.user) or is_app_admin(request.user):
        bu_deletion_requests = BUDeletionRequest.objects.select_related(
            "business_unit", "requested_by", "reviewed_by"
        ).order_by("-requested_at")[:30]
        bu_pending_deletion_count = BUDeletionRequest.objects.filter(status="pending").count()

    return render(
        request,
        "products/user_list.html",
        {
            "users": users,
            "pending_users_data": pending_users_data,
            "deactivated_users": deactivated_users,
            "participants": participants,
            "streams": streams,
            "selected_stream": selected_stream,
            "stream": selected_stream,
            "user_backups": user_backups,
            "stream_deletion_history": stream_deletion_history,
            "bu_deletion_requests": bu_deletion_requests,
            "bu_pending_deletion_count": bu_pending_deletion_count,
            "assignable_roles": (
                CustomUser._ROLE_HIERARCHY
                if _is_app_admin_user(request.user)
                else [r for i, r in enumerate(CustomUser._ROLE_HIERARCHY) if i > _get_role_level(request.user)]
            ),
        },
    )


@login_required
@require_POST
def approve_user(request, user_id):
    # pylint: disable=logging-too-many-args
    """Activate a pending user account."""
    if not can_manage_users(request.user):
        messages.error(request, "Access denied. You need admin privileges to approve users.")
        return redirect("user_list")

    user = get_object_or_404(User, pk=user_id)
    if user.is_active:
        messages.warning(request, f"User {user.username} is already active.")
        return redirect("user_list")

    try:
        custom_user, _created = CustomUser.objects.get_or_create(user=user)

        requested_streams = list(custom_user.requested_streams.all())
        requested_bus = list(custom_user.requested_bus.all())

        UserRole.objects.get_or_create(custom_user=custom_user, role="user")

        for stream in requested_streams:
            UserStreamAccess.objects.get_or_create(custom_user=custom_user, stream=stream)

        for bu in requested_bus:
            UserBUAccess.objects.get_or_create(
                custom_user=custom_user, business_unit=bu, defaults={"granted_by": request.user}
            )

        custom_user.requested_streams.clear()
        custom_user.requested_bus.clear()

        user.is_active = True
        user.save()

        AuditLog.log(
            action="approve",
            title=f"Approved user registration: {user.username}",
            user=request.user,
            request=request,
            obj=user,
            module="users",
            severity="info",
        )
        messages.success(
            request,
            f'User "{user.username}" has been approved and activated with access to their requested streams and BUs.',
        )
        logger.info(
            "User approved: %s by %s with streams: %s, BUs: %s",
            user.username,
            request.user.username,
            ", ".join(s.name for s in requested_streams),
            ", ".join(str(b) for b in requested_bus),
        )
        Notification.notify(user, "Your account has been approved! Welcome to the platform.", "user_access")

    except Exception:
        logger.exception("Error approving user %s", user_id)
        messages.error(request, "An error occurred. Please try again.")

    return redirect("user_list")


@login_required
@require_POST
def decline_user(request, user_id):
    """Decline a pending user registration by removing the user record.

    Only applies to users who are not yet active.
    """
    if not can_manage_users(request.user):
        messages.error(request, "Permission denied. You do not have rights to decline users.")
        return redirect("user_list")

    user = get_object_or_404(User, pk=user_id)
    if user.is_active:
        messages.error(request, "Cannot decline an already active user.")
        return redirect("user_list")

    username = user.username
    try:
        AuditLog.log(
            action="reject",
            title=f"Declined user registration: {username}",
            user=request.user,
            request=request,
            module="users",
            severity="warning",
        )
        user.delete()
        messages.success(request, f'Pending user "{username}" has been declined and removed.')
        logger.info("User declined and deleted: %s by %s", username, request.user.username)
    except Exception:
        logger.exception("Error declining user %s", user_id)
        messages.error(request, "An error occurred while declining the user. Please try again.")

    return redirect("user_list")
