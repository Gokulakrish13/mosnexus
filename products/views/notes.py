"""Products app - Notes CRUD, Sharing, and Note Tags views."""

# pylint: disable=redefined-outer-name,too-many-lines

import json as _json

from ._helpers import (
    AuditLog,
    CustomUser,
    JsonResponse,
    Note,
    NoteAttachment,
    NoteTag,
    Notification,
    Q,
    SharedNote,
    Stream,
    User,
    UserStreamAccess,
    get_current_bu,
    get_default_stream_name,
    get_object_or_404,
    login_required,
    messages,
    redirect,
    render,
    require_POST,
    timezone,
)

__all__ = [
    "notes_list",
    "note_detail",
    "note_create",
    "note_edit",
    "note_delete",
    "share_note",
    "shared_notes",
    "shared_by_me",
    "remove_shared_note",
    "note_tags_api",
    "note_tag_create_api",
    "note_tag_delete_api",
    "note_tag_update_api",
]


@login_required
def notes_list(request):
    """List all notes accessible to the current user, scoped to the current BU.

    Visibility rules:
      - 'public'  → visible to all users in the same BU
      - 'private' → visible only to the creator
      - 'stream'  → visible only to users who have access to note.stream
    Legacy notes (created before the visibility field) use is_public as fallback.
    """
    bu = get_current_bu(request)
    custom_profile, _ = CustomUser.objects.get_or_create(user=request.user)

    # Determine which stream IDs the current user can access
    if bu:
        user_stream_ids = set(
            custom_profile.get_accessible_streams(business_unit=bu).filter(is_active=True).values_list("id", flat=True)
        )
    else:
        user_stream_ids = set(
            custom_profile.get_accessible_streams().filter(is_active=True).values_list("id", flat=True)
        )
    is_super = request.user.is_superuser or custom_profile.is_super_admin()

    if bu:
        bu_user_ids = set(
            UserStreamAccess.objects.filter(stream__business_unit=bu).values_list("custom_user__user_id", flat=True)
        )
        bu_user_ids |= set(User.objects.filter(is_superuser=True).values_list("id", flat=True))

        # Build the queryset scoped to BU
        base_q = Q(business_unit=bu) | Q(business_unit__isnull=True, created_by_id__in=bu_user_ids)
        notes = Note.objects.filter(
            base_q
            & (
                # Always show user's own notes from this BU
                Q(created_by=request.user)
                # Public notes from BU users
                | Q(visibility="public")
                # Stream-scoped notes where user has access to that stream
                | (Q(visibility="stream") & Q(stream_id__in=user_stream_ids))
            )
        )
        # Super admins see all BU notes
        if is_super:
            notes = Note.objects.filter(base_q)
    else:
        notes = Note.objects.filter(
            Q(created_by=request.user)
            | Q(visibility="public")
            | (Q(visibility="stream") & Q(stream_id__in=user_stream_ids))
        )
        if is_super:
            notes = Note.objects.all()

    notes = (
        notes.distinct()
        .select_related("created_by", "stream")
        .prefetch_related("attachments", "tags")
        .order_by("-created_at")
    )

    # Search
    search_query = request.GET.get("search", "").strip()
    if search_query:
        notes = notes.filter(
            Q(title__icontains=search_query)
            | Q(content__icontains=search_query)
            | Q(created_by__username__icontains=search_query)
            | Q(created_by__first_name__icontains=search_query)
            | Q(created_by__last_name__icontains=search_query)
            | Q(tags__name__icontains=search_query)
        ).distinct()

    # Tag filter via query param
    tag_filter = request.GET.get("tag", "").strip()
    if tag_filter:
        notes = notes.filter(tags__id=tag_filter)

    shared_notes_count = SharedNote.objects.filter(shared_with=request.user).count()

    # Provide user's accessible streams for the filter tabs
    accessible_streams = Stream.objects.filter(id__in=user_stream_ids).order_by("name")

    # All tags for this BU
    all_tags = NoteTag.objects.filter(business_unit=bu) if bu else NoteTag.objects.filter(business_unit__isnull=True)

    return render(
        request,
        "products/notes_list.html",
        {
            "notes": notes,
            "shared_notes_count": shared_notes_count,
            "accessible_streams": accessible_streams,
            "all_tags": all_tags,
            "active_tag_filter": tag_filter,
            "selected_stream": get_default_stream_name(request),
        },
    )


@login_required
def note_detail(request, pk):
    """View a single note with stream-aware access control."""
    note = get_object_or_404(Note, pk=pk)
    is_shared_with_user = SharedNote.objects.filter(note=note, shared_with=request.user).exists()
    custom_profile, _ = CustomUser.objects.get_or_create(user=request.user)
    is_super = request.user.is_superuser or custom_profile.is_super_admin()

    # Access check based on visibility
    can_view = False
    if note.created_by == request.user or is_shared_with_user or is_super:
        can_view = True
    elif note.visibility == "public":
        can_view = True
    elif note.visibility == "stream" and note.stream:
        # Check if user has access to this stream
        can_view = UserStreamAccess.objects.filter(custom_user=custom_profile, stream=note.stream).exists()
    elif note.visibility == "private":
        can_view = note.created_by == request.user
    # Legacy fallback for notes without visibility field set
    elif note.is_public:
        can_view = True

    if not can_view:
        messages.error(request, "You don't have permission to view this note.")
        return redirect("notes_list")

    if is_shared_with_user:
        SharedNote.objects.filter(note=note, shared_with=request.user).update(is_read=True)
    attachments = note.attachments.all()

    # Get all BU tags for display
    bu = get_current_bu(request)
    all_tags = NoteTag.objects.filter(business_unit=bu) if bu else NoteTag.objects.filter(business_unit__isnull=True)

    return render(
        request,
        "products/note_detail.html",
        {
            "note": note,
            "attachments": attachments,
            "all_tags": all_tags,
            "selected_stream": get_default_stream_name(request),
            "is_shared_note": is_shared_with_user,
        },
    )


@login_required
def note_create(request):  # noqa: C901, CCR001
    """Create a new note with visibility options: public, private, or stream-specific."""
    # pylint: disable=too-complex,too-many-locals
    bu = get_current_bu(request)
    custom_profile, _ = CustomUser.objects.get_or_create(user=request.user)
    if bu:
        user_streams = custom_profile.get_accessible_streams(business_unit=bu).filter(is_active=True)
    else:
        user_streams = custom_profile.get_accessible_streams().filter(is_active=True)
    all_tags = NoteTag.objects.filter(business_unit=bu) if bu else NoteTag.objects.filter(business_unit__isnull=True)

    if request.method == "POST":
        title = request.POST.get("title")
        content = request.POST.get("content")
        visibility = request.POST.get("visibility", "public")
        stream_id = request.POST.get("stream", "")
        is_public = visibility == "public"

        # Validate stream selection for stream visibility
        selected_stream_obj = None
        if visibility == "stream":
            if not stream_id:
                return render(
                    request,
                    "products/note_form.html",
                    {
                        "note": {"title": title, "content": content, "is_public": is_public},
                        "user_streams": user_streams,
                        "all_tags": all_tags,
                        "selected_stream": get_default_stream_name(request),
                        "form_error": "Please select a stream for stream-specific visibility.",
                    },
                )
            try:
                selected_stream_obj = user_streams.get(pk=stream_id)
            except Stream.DoesNotExist:
                return render(
                    request,
                    "products/note_form.html",
                    {
                        "note": {"title": title, "content": content, "is_public": is_public},
                        "user_streams": user_streams,
                        "all_tags": all_tags,
                        "selected_stream": get_default_stream_name(request),
                        "form_error": "Invalid stream selected.",
                    },
                )

        if not title or not content:
            return render(
                request,
                "products/note_form.html",
                {
                    "note": {"title": title, "content": content, "is_public": is_public},
                    "user_streams": user_streams,
                    "all_tags": all_tags,
                    "selected_stream": get_default_stream_name(request),
                    "form_error": "Title and content are required.",
                },
            )

        note = Note.objects.create(
            title=title,
            content=content,
            is_public=is_public,
            visibility=visibility,
            stream=selected_stream_obj,
            created_by=request.user,
            updated_by=request.user,
            business_unit=bu,
        )

        # Handle tags
        tag_ids = request.POST.getlist("tags")
        if tag_ids:
            note.tags.set(tag_ids)

        # Handle file attachments
        files = request.FILES.getlist("attachments")
        for file in files:
            if file.size > 5 * 1024 * 1024:
                messages.warning(request, f'File "{file.name}" is larger than 5MB and was not uploaded.')
                continue

            allowed_types = [
                "image/jpeg",
                "image/png",
                "image/gif",
                "image/bmp",
                "image/webp",
                "application/pdf",
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.ms-excel",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ]

            if file.content_type not in allowed_types:
                messages.warning(request, f'File "{file.name}" has an unsupported format and was not uploaded.')
                continue

            NoteAttachment.objects.create(
                note=note,
                file=file,
                original_filename=file.name,
                content_type=file.content_type,
                uploaded_by=request.user,
            )

        AuditLog.log(
            action="create",
            title=f"Created note: {note.title}",
            user=request.user,
            request=request,
            obj=note,
            module="notes",
            severity="info",
            stream=note.stream,
        )
        messages.success(request, "Note created successfully.")
        return redirect("note_detail", pk=note.pk)

    return render(
        request,
        "products/note_form.html",
        {
            "note": None,
            "user_streams": user_streams,
            "all_tags": (
                NoteTag.objects.filter(business_unit=bu) if bu else NoteTag.objects.filter(business_unit__isnull=True)
            ),
            "selected_stream": get_default_stream_name(request),
        },
    )


@login_required
def note_edit(request, pk):  # noqa: C901, CCR001
    """Edit an existing note with visibility options."""
    # pylint: disable=too-complex,too-many-branches,too-many-locals
    note = get_object_or_404(Note, pk=pk)
    bu = get_current_bu(request)
    custom_profile, _ = CustomUser.objects.get_or_create(user=request.user)
    if bu:
        user_streams = custom_profile.get_accessible_streams(business_unit=bu).filter(is_active=True)
    else:
        user_streams = custom_profile.get_accessible_streams().filter(is_active=True)
    all_tags = NoteTag.objects.filter(business_unit=bu) if bu else NoteTag.objects.filter(business_unit__isnull=True)

    # Check if user has permission to edit the note
    if note.created_by != request.user:
        messages.error(request, "You don't have permission to edit this note.")
        return redirect("notes_list")

    if request.method == "POST":
        title = request.POST.get("title")
        content = request.POST.get("content")
        visibility = request.POST.get("visibility", "public")
        stream_id = request.POST.get("stream", "")
        is_public = visibility == "public"

        # Validate stream for stream visibility
        selected_stream_obj = None
        if visibility == "stream":
            if not stream_id:
                return render(
                    request,
                    "products/note_form.html",
                    {
                        "note": note,
                        "user_streams": user_streams,
                        "all_tags": all_tags,
                        "selected_stream": get_default_stream_name(request),
                        "form_error": "Please select a stream for stream-specific visibility.",
                    },
                )
            try:
                selected_stream_obj = user_streams.get(pk=stream_id)
            except Stream.DoesNotExist:
                return render(
                    request,
                    "products/note_form.html",
                    {
                        "note": note,
                        "user_streams": user_streams,
                        "all_tags": all_tags,
                        "selected_stream": get_default_stream_name(request),
                        "form_error": "Invalid stream selected.",
                    },
                )

        if not title or not content:
            return render(
                request,
                "products/note_form.html",
                {
                    "note": note,
                    "user_streams": user_streams,
                    "all_tags": all_tags,
                    "selected_stream": get_default_stream_name(request),
                    "form_error": "Title and content are required.",
                },
            )

        note.title = title
        note.content = content
        note.is_public = is_public
        note.visibility = visibility
        note.stream = selected_stream_obj
        note.updated_by = request.user
        note.updated_at = timezone.now()
        note.save()

        # Handle tags
        tag_ids = request.POST.getlist("tags")
        note.tags.set(tag_ids)

        # Handle new file attachments
        files = request.FILES.getlist("attachments")
        for file in files:
            if file.size > 5 * 1024 * 1024:
                messages.warning(request, f'File "{file.name}" is larger than 5MB and was not uploaded.')
                continue

            allowed_types = [
                "image/jpeg",
                "image/png",
                "image/gif",
                "image/bmp",
                "image/webp",
                "application/pdf",
                "application/msword",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.ms-excel",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ]

            if file.content_type not in allowed_types:
                messages.warning(request, f'File "{file.name}" has an unsupported format and was not uploaded.')
                continue

            NoteAttachment.objects.create(
                note=note,
                file=file,
                original_filename=file.name,
                content_type=file.content_type,
                uploaded_by=request.user,
            )  # Handle attachment deletions
        attachment_ids_to_delete = request.POST.getlist("delete_attachments")
        if attachment_ids_to_delete:
            attachments_to_delete = NoteAttachment.objects.filter(id__in=attachment_ids_to_delete, note=note)
            for attachment in attachments_to_delete:
                # Delete each attachment individually to ensure file deletion
                attachment.delete()

        AuditLog.log(
            action="update",
            title=f"Updated note: {note.title}",
            user=request.user,
            request=request,
            obj=note,
            module="notes",
            severity="info",
            stream=note.stream,
        )
        messages.success(request, "Note updated successfully.")
        return redirect("note_detail", pk=note.pk)

    return render(
        request,
        "products/note_form.html",
        {
            "note": note,
            "user_streams": user_streams,
            "all_tags": (
                NoteTag.objects.filter(business_unit=bu) if bu else NoteTag.objects.filter(business_unit__isnull=True)
            ),
            "selected_stream": get_default_stream_name(request),
        },
    )


@login_required
def note_delete(request, pk):
    """Delete a note."""
    note = get_object_or_404(Note, pk=pk)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    # Check if user has permission to delete the note
    custom_profile, _ = CustomUser.objects.get_or_create(user=request.user)
    is_admin = request.user.is_superuser or custom_profile.is_super_admin()
    if note.created_by != request.user and not is_admin:
        if is_ajax:
            return JsonResponse({"success": False, "error": "Permission denied"}, status=403)
        messages.error(request, "You don't have permission to delete this note.")
        return redirect("notes_list")
    if request.method == "POST":
        # Delete the note (this will also delete attachments and files due to CASCADE and overridden delete method)
        note_title = note.title
        AuditLog.log(
            action="delete",
            title=f"Deleted note: {note_title}",
            user=request.user,
            request=request,
            obj=note,
            module="notes",
            severity="warning",
            stream=note.stream,
        )
        note.delete()
        if is_ajax:
            return JsonResponse({"success": True, "message": f'Note "{note_title}" deleted successfully.'})
        messages.success(request, "Note and all attachments deleted successfully.")
        return redirect("notes_list")

    return render(
        request,
        "products/note_confirm_delete.html",
        {"note": note, "selected_stream": get_default_stream_name(request)},
    )


@login_required
def share_note(request, pk):  # noqa: C901, CCR001
    """Share a note with other users."""
    # pylint: disable=too-complex
    note = get_object_or_404(Note, pk=pk)

    # Check if user has permission to share the note
    custom_profile, _ = CustomUser.objects.get_or_create(user=request.user)
    can_share = False
    if note.created_by == request.user:
        can_share = True
    elif note.visibility == "public":
        can_share = True
    elif note.visibility == "stream" and note.stream:
        can_share = UserStreamAccess.objects.filter(custom_user=custom_profile, stream=note.stream).exists()
    if not can_share:
        messages.error(request, "You don't have permission to share this note.")
        return redirect("notes_list")

    if request.method == "POST":
        user_ids = request.POST.getlist("users")
        message = request.POST.get("message", "")

        if not user_ids:
            users = User.objects.exclude(id=request.user.id).order_by("username")
            return render(
                request,
                "products/share_note.html",
                {
                    "note": note,
                    "users": users,
                    "selected_stream": get_default_stream_name(request),
                    "form_error": "Please select at least one user to share with.",
                },
            )

        shared_count = 0
        for user_id in user_ids:
            try:
                user = User.objects.get(id=user_id)
                _shared_note, created = SharedNote.objects.get_or_create(
                    note=note, shared_by=request.user, shared_with=user, defaults={"message": message}
                )
                if created:
                    shared_count += 1
                    Notification.notify(user, f"{request.user.username} shared a note '{note.title}' with you.", "note")
            except User.DoesNotExist:
                continue

        if shared_count > 0:
            messages.success(request, f"Note shared with {shared_count} user(s).")
        else:
            messages.info(request, "Note was already shared with selected users.")

        return redirect("note_detail", pk=pk)

    # GET request - show share form
    users = User.objects.exclude(id=request.user.id).order_by("username")
    return render(
        request,
        "products/share_note.html",
        {"note": note, "users": users, "selected_stream": get_default_stream_name(request)},
    )


@login_required
def shared_notes(request):
    """View notes shared with the current user."""
    shared_notes = (
        SharedNote.objects.filter(shared_with=request.user)
        .select_related("note", "shared_by", "note__created_by")
        .order_by("-shared_at")
    )

    shared_by_me_count = SharedNote.objects.filter(shared_by=request.user).count()
    # Mark as read when viewed
    SharedNote.objects.filter(shared_with=request.user, is_read=False).update(is_read=True)

    return render(
        request,
        "products/shared_notes.html",
        {
            "shared_notes": shared_notes,
            "shared_by_me_count": shared_by_me_count,
            "selected_stream": get_default_stream_name(request),
        },
    )


@login_required
def shared_by_me(request):
    """View notes shared by the current user to others."""
    shared_notes = (
        SharedNote.objects.filter(shared_by=request.user)
        .select_related("note", "shared_with", "note__created_by")
        .order_by("-shared_at")
    )
    shared_with_me_count = SharedNote.objects.filter(shared_with=request.user).count()
    notes_shared = {}
    for share in shared_notes:
        if share.note.pk not in notes_shared:
            notes_shared[share.note.pk] = {"note": share.note, "recipients": [], "latest_shared_at": share.shared_at}
        notes_shared[share.note.pk]["recipients"].append(
            {
                "user": share.shared_with,
                "shared_at": share.shared_at,
                "is_read": share.is_read,
                "message": share.message,
                "share_id": share.pk,
            }
        )
    notes_shared_list = list(notes_shared.values())
    return render(
        request,
        "products/shared_by_me.html",
        {
            "shared_notes": shared_notes,
            "notes_shared": notes_shared_list,
            "shared_with_me_count": shared_with_me_count,
            "selected_stream": get_default_stream_name(request),
        },
    )


@login_required
def remove_shared_note(request, pk):
    """Remove a shared note from user's shared list."""
    shared_note = get_object_or_404(SharedNote, pk=pk, shared_with=request.user)

    if request.method == "POST":
        shared_note.delete()
        messages.success(request, "Shared note removed from your list.")
        return redirect("shared_notes")

    return render(
        request,
        "products/remove_shared_note.html",
        {"shared_note": shared_note, "selected_stream": get_default_stream_name(request)},
    )


# ─── Note Tags API ───────────────────────────────────────────────


@login_required
def note_tags_api(request):
    """Return all tags for the current BU as JSON."""
    bu = get_current_bu(request)
    tags = NoteTag.objects.filter(business_unit=bu) if bu else NoteTag.objects.filter(business_unit__isnull=True)
    data = [{"id": t.id, "name": t.name, "color": t.color, "count": t.notes.count()} for t in tags]
    return JsonResponse({"tags": data})


@login_required
@require_POST
def note_tag_create_api(request):
    """Create a new tag for the current BU. Returns the created tag as JSON."""
    bu = get_current_bu(request)
    # Support both JSON body and form-encoded POST
    if request.content_type and "application/json" in request.content_type:
        try:
            body = _json.loads(request.body)
        except (ValueError, TypeError):
            body = {}
        name = body.get("name", "").strip()
        color = body.get("color", "#3b82f6").strip()
    else:
        name = request.POST.get("name", "").strip()
        color = request.POST.get("color", "#3b82f6").strip()

    if not name:
        return JsonResponse({"error": "Tag name is required."}, status=400)
    if len(name) > 50:
        return JsonResponse({"error": "Tag name must be 50 characters or less."}, status=400)

    # Check for duplicate in same BU
    existing = NoteTag.objects.filter(name__iexact=name, business_unit=bu).first()
    if existing:
        return JsonResponse({"id": existing.id, "name": existing.name, "color": existing.color, "created": False})

    tag = NoteTag.objects.create(name=name, color=color, business_unit=bu, created_by=request.user)
    return JsonResponse({"id": tag.id, "name": tag.name, "color": tag.color, "created": True}, status=201)


@login_required
@require_POST
def note_tag_delete_api(request, pk):
    """Delete a tag. Only the creator or admins can delete."""
    tag = get_object_or_404(NoteTag, pk=pk)
    custom_profile, _ = CustomUser.objects.get_or_create(user=request.user)
    if tag.created_by != request.user and not custom_profile.is_admin():
        return JsonResponse({"error": "Permission denied."}, status=403)
    tag.delete()
    return JsonResponse({"deleted": True})


@login_required
@require_POST
def note_tag_update_api(request, pk):  # noqa: CCR001
    """Rename or recolor a tag. Only the creator or admins can update."""
    tag = get_object_or_404(NoteTag, pk=pk)
    custom_profile, _ = CustomUser.objects.get_or_create(user=request.user)
    if tag.created_by != request.user and not custom_profile.is_admin():
        return JsonResponse({"error": "Permission denied."}, status=403)

    if request.content_type and "application/json" in request.content_type:
        try:
            body = _json.loads(request.body)
        except (ValueError, TypeError):
            body = {}
    else:
        body = request.POST

    name = body.get("name", "").strip()
    color = body.get("color", "").strip()

    if name:
        if len(name) > 50:
            return JsonResponse({"error": "Tag name must be 50 characters or less."}, status=400)
        # Check for duplicate in same BU
        existing = NoteTag.objects.filter(name__iexact=name, business_unit=tag.business_unit).exclude(pk=pk).first()
        if existing:
            return JsonResponse({"error": f'A tag named "{existing.name}" already exists.'}, status=400)
        tag.name = name
    if color:
        tag.color = color
    tag.save()
    return JsonResponse({"id": tag.id, "name": tag.name, "color": tag.color, "updated": True})
