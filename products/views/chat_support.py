"""Products app - Team Chat, Support Tickets, and Live Support views."""

# pylint: disable=broad-exception-caught,inconsistent-return-statements


import re as _re

from django.contrib.auth.models import User as _User  # pylint: disable=imported-auth-user
from django.utils import timezone as tz

from ._helpers import (
    ChatAttachment,
    ChatMessage,
    ChatReadReceipt,
    ChatRoom,
    ChatRoomMember,
    JsonResponse,
    Notification,
    Q,
    User,
    UserBUAccess,
    get_bu_streams,
    get_current_bu,
    get_object_or_404,
    is_super_admin,
    json,
    login_required,
    messages,
    redirect,
    render,
    require_http_methods,
    timedelta,
    validate_uploaded_file,
)

__all__ = [
    "team_chat",
    "chat_room_view",
    "chat_api",
    "chat_upload_attachment",
]


@login_required
def team_chat(request):  # noqa: CCR001
    # pylint: disable=too-many-locals
    """Team Chat main page — shows global + stream rooms for the user's BU."""
    bu = get_current_bu(request)
    if not bu:
        return redirect("select_bu")

    streams = get_bu_streams(request).order_by("name")

    # Ensure default rooms exist and keep name in sync with division
    expected_global_name = f"({bu.bu_name} - {bu.division}) General Chat"
    global_room, created = ChatRoom.objects.get_or_create(
        business_unit=bu,
        room_type="global",
        stream=None,
        defaults={"name": expected_global_name, "created_by": request.user},
    )
    if not created and global_room.name != expected_global_name:
        global_room.name = expected_global_name
        global_room.save(update_fields=["name"])
    for stream_item in streams:
        ChatRoom.objects.get_or_create(
            business_unit=bu,
            room_type="stream",
            stream=stream_item,
            defaults={"name": f"{stream_item.name} Chat", "created_by": request.user},
        )

    rooms = ChatRoom.objects.filter(business_unit=bu, is_active=True).select_related("stream")
    # For users without super_admin, limit stream rooms to accessible streams
    if not is_super_admin(request.user):
        accessible_stream_ids = list(streams.values_list("id", flat=True))
        user_group_ids = list(ChatRoomMember.objects.filter(user=request.user).values_list("room_id", flat=True))
        rooms = rooms.filter(
            Q(room_type="global")
            | Q(room_type="stream", stream_id__in=accessible_stream_ids)
            | Q(room_type="group", pk__in=user_group_ids)
        )
    else:
        # Super admin sees all groups they are a member of + any group
        pass

    # Count unread-ish: messages in last 24h per room
    cutoff = tz.now() - timedelta(hours=24)
    room_data = []
    group_data = []
    for room in rooms:
        msg_count = room.messages.filter(is_deleted=False).count()
        recent_count = room.messages.filter(is_deleted=False, created_at__gte=cutoff).count()
        last_msg = room.messages.filter(is_deleted=False).order_by("-created_at").first()

        # Unread count for group chats
        unread = 0
        if room.room_type == "group":
            membership = room.members.filter(user=request.user).first()
            if membership and membership.last_read_at:
                unread = (
                    room.messages.filter(is_deleted=False, created_at__gt=membership.last_read_at)
                    .exclude(user=request.user)
                    .count()
                )
            elif membership:
                unread = msg_count

        entry = {
            "room": room,
            "msg_count": msg_count,
            "recent_count": recent_count,
            "last_msg": last_msg,
            "unread": unread,
            "member_count": room.members.count() if room.room_type == "group" else 0,
        }
        if room.room_type == "group":
            group_data.append(entry)
        else:
            room_data.append(entry)

    # Get BU users for group creation people picker
    bu_user_ids = UserBUAccess.objects.filter(business_unit=bu).values_list("custom_user__user_id", flat=True)
    bu_users = User.objects.filter(id__in=bu_user_ids, is_active=True).order_by("username")

    context = {
        "rooms": room_data,
        "group_rooms": group_data,
        "streams": streams,
        "bu": bu,
        "bu_users": bu_users,
    }
    return render(request, "products/team_chat.html", context)


@login_required
def chat_room_view(request, room_id):  # noqa: C901, CCR001
    # pylint: disable=too-many-locals,too-complex
    """View a specific chat room with messages."""
    bu = get_current_bu(request)
    if not bu:
        return redirect("select_bu")
    room = get_object_or_404(ChatRoom, pk=room_id, business_unit=bu, is_active=True)

    # Access check — group rooms: must be a member
    if room.room_type == "group":
        if not room.members.filter(user=request.user).exists():
            messages.error(request, "You are not a member of this group chat.")
            return redirect("team_chat")
        # Update last read
        ChatRoomMember.objects.filter(room=room, user=request.user).update(last_read_at=tz.now())
        # Update read receipt
        last_msg = room.messages.filter(is_deleted=False).order_by("-created_at").first()
        if last_msg:
            ChatReadReceipt.objects.update_or_create(
                room=room, user=request.user, defaults={"last_read_message": last_msg}
            )

    # Access check — if stream room, user must have stream access
    elif room.stream and not is_super_admin(request.user):
        streams = get_bu_streams(request)
        if not streams.filter(id=room.stream_id).exists():
            messages.error(request, "You do not have access to this stream chat.")
            return redirect("team_chat")

    all_rooms = ChatRoom.objects.filter(business_unit=bu, is_active=True).select_related("stream")
    if not is_super_admin(request.user):
        accessible_ids = list(get_bu_streams(request).values_list("id", flat=True))
        user_group_ids = list(ChatRoomMember.objects.filter(user=request.user).values_list("room_id", flat=True))
        all_rooms = all_rooms.filter(
            Q(room_type="global")
            | Q(room_type="stream", stream_id__in=accessible_ids)
            | Q(room_type="group", pk__in=user_group_ids)
        )

    chat_messages = (
        room.messages.filter(is_deleted=False)
        .select_related("user", "parent", "parent__user")
        .prefetch_related("attachments", "reactions")
        .order_by("created_at")[:200]
    )

    # For group rooms, filter messages based on can_see_history
    if room.room_type == "group":
        membership = room.members.filter(user=request.user).first()
        if membership and not membership.can_see_history:
            chat_messages = (
                room.messages.filter(is_deleted=False, created_at__gte=membership.joined_at)
                .select_related("user", "parent", "parent__user")
                .prefetch_related("attachments", "reactions")
                .order_by("created_at")[:200]
            )
    group_members = []
    is_group_admin = False
    if room.room_type == "group":
        group_members = room.members.select_related("user").order_by("role", "user__username")
        is_group_admin = room.members.filter(user=request.user, role="admin").exists() or is_super_admin(request.user)

    # Pinned messages
    pinned_messages = (
        room.messages.filter(is_deleted=False, is_pinned=True).select_related("user").order_by("-created_at")[:10]
    )

    # BU users for adding to group
    bu_user_ids = UserBUAccess.objects.filter(business_unit=bu).values_list("custom_user__user_id", flat=True)
    bu_users = (
        User.objects.filter(id__in=bu_user_ids, is_active=True)
        .exclude(id__in=room.members.values_list("user_id", flat=True))
        .order_by("username")
        if room.room_type == "group"
        else User.objects.none()
    )

    context = {
        "room": room,
        "all_rooms": all_rooms,
        "chat_messages": chat_messages,
        "bu": bu,
        "group_members": group_members,
        "is_group_admin": is_group_admin,
        "pinned_messages": pinned_messages,
        "bu_users": bu_users,
    }
    return render(request, "products/chat_room.html", context)


@login_required
@require_http_methods(["GET", "POST", "PUT", "DELETE"])
def chat_api(request, room_id):  # noqa: C901, CCR001, E501
    # pylint: disable=too-many-locals,too-many-return-statements,too-many-branches
    # pylint: disable=too-many-statements,too-complex,inconsistent-return-statements
    """AJAX API for chat messages — GET list, POST create, PUT edit, DELETE soft-delete."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"error": "No BU selected"}, status=400)
    room = get_object_or_404(ChatRoom, pk=room_id, business_unit=bu, is_active=True)

    # Group access check
    if room.room_type == "group" and not room.members.filter(user=request.user).exists():
        return JsonResponse({"error": "Not a member"}, status=403)

    if request.method == "GET":
        after_id = request.GET.get("after", 0)
        msgs = (
            room.messages.filter(is_deleted=False, id__gt=int(after_id))
            .select_related("user", "parent", "parent__user")
            .prefetch_related("attachments", "reactions")
            .order_by("created_at")[:100]
        )

        # For group rooms, filter based on can_see_history
        if room.room_type == "group":
            membership = room.members.filter(user=request.user).first()
            if membership and not membership.can_see_history:
                msgs = msgs.filter(created_at__gte=membership.joined_at)
        data = []
        for msg in msgs:
            # Aggregate reactions
            reaction_map = {}
            for react in msg.reactions.all():
                if react.emoji not in reaction_map:
                    reaction_map[react.emoji] = {"emoji": react.emoji, "count": 0, "users": [], "user_reacted": False}
                reaction_map[react.emoji]["count"] += 1
                reaction_map[react.emoji]["users"].append(react.user.username)
                if react.user_id == request.user.id:
                    reaction_map[react.emoji]["user_reacted"] = True

            data.append(
                {
                    "id": msg.id,
                    "user": msg.user.username,
                    "user_id": msg.user.id,
                    "message": msg.message,
                    "message_type": msg.message_type,
                    "is_pinned": msg.is_pinned,
                    "created_at": msg.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "updated_at": msg.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "parent_id": msg.parent_id,
                    "parent_user": msg.parent.user.username if msg.parent and msg.parent.user else None,
                    "parent_text": (msg.parent.message[:120] if msg.parent else None),
                    "attachments": [
                        {
                            "id": a.id,
                            "filename": a.original_filename,
                            "size": a.file_size_formatted,
                            "is_image": a.is_image,
                            "url": a.file.url,
                        }
                        for a in msg.attachments.all()
                    ],
                    "reactions": list(reaction_map.values()),
                }
            )
        # Update read receipt on poll
        if room.room_type == "group" and data:
            ChatRoomMember.objects.filter(room=room, user=request.user).update(last_read_at=tz.now())
        return JsonResponse({"messages": data, "room_id": room.id})

    if request.method == "POST":
        body = json.loads(request.body) if request.content_type == "application/json" else request.POST
        text = body.get("message", "").strip()
        if not text:
            return JsonResponse({"error": "Message cannot be empty"}, status=400)
        parent_id = body.get("parent_id")
        msg = ChatMessage.objects.create(
            room=room,
            user=request.user,
            message=text,
            parent_id=parent_id if parent_id else None,
        )
        parent_user = None
        parent_text = None
        if msg.parent_id:
            try:
                parent_msg = ChatMessage.objects.select_related("user").get(pk=msg.parent_id)
                parent_user = parent_msg.user.username if parent_msg.user else None
                parent_text = parent_msg.message[:120]
            except ChatMessage.DoesNotExist:
                pass
        # Detect @mentions and notify
        mentions = _re.findall(r"@(\w+)", text)
        if mentions:
            mentioned_users = _User.objects.filter(username__in=mentions).exclude(id=request.user.id)
            if mentioned_users.exists():
                preview = text[:80] + ("..." if len(text) > 80 else "")
                Notification.notify(
                    mentioned_users, f"{request.user.username} mentioned you in chat: '{preview}'", "chat_mention"
                )
        return JsonResponse(
            {
                "id": msg.id,
                "user": msg.user.username,
                "user_id": msg.user.id,
                "message": msg.message,
                "created_at": msg.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "parent_id": msg.parent_id,
                "parent_user": parent_user,
                "parent_text": parent_text,
            }
        )

    if request.method == "PUT":
        body = json.loads(request.body)
        msg_id = body.get("id")
        new_text = body.get("message", "").strip()
        msg = get_object_or_404(ChatMessage, pk=msg_id, room=room)
        if msg.user != request.user:
            return JsonResponse({"error": "Cannot edit others messages"}, status=403)
        # Allow edit within 15 min
        if (tz.now() - msg.created_at).total_seconds() > 900:
            return JsonResponse({"error": "Edit window expired (15 min)"}, status=403)
        msg.message = new_text
        msg.save()
        return JsonResponse(
            {"id": msg.id, "message": msg.message, "updated_at": msg.updated_at.strftime("%Y-%m-%d %H:%M:%S")}
        )

    if request.method == "DELETE":
        body = json.loads(request.body)
        msg_id = body.get("id")
        msg = get_object_or_404(ChatMessage, pk=msg_id, room=room)
        if msg.user != request.user and not is_super_admin(request.user):
            return JsonResponse({"error": "Permission denied"}, status=403)
        msg.is_deleted = True
        msg.save()
        return JsonResponse({"deleted": True, "id": msg.id})


@login_required
def chat_upload_attachment(request, room_id):  # noqa: CCR001
    """Upload a file attachment to a chat message."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"error": "No BU"}, status=400)
    room = get_object_or_404(ChatRoom, pk=room_id, business_unit=bu, is_active=True)

    # Allowed chat attachment types and limits
    chat_allowed_types = {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "text/plain",
        "text/csv",
    }
    chat_allowed_extensions = {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".pdf",
        ".xlsx",
        ".docx",
        ".pptx",
        ".txt",
        ".csv",
    }
    chat_max_size = 25 * 1024 * 1024  # 25 MB

    if request.method == "POST" and request.FILES.get("file"):
        f = request.FILES["file"]

        # Validate the uploaded file
        is_valid, error_msg = validate_uploaded_file(f, chat_allowed_types, chat_allowed_extensions, chat_max_size)
        if not is_valid:
            return JsonResponse({"error": f"Invalid file: {error_msg}"}, status=400)

        msg_id = request.POST.get("message_id")
        parent_msg = get_object_or_404(ChatMessage, pk=msg_id, room=room) if msg_id else None

        if not parent_msg:
            # Create a message — use user-supplied text or fallback placeholder
            user_text = (request.POST.get("message") or "").strip() or f"📎 {f.name}"
            reply_parent_id = request.POST.get("parent_id") or None
            parent_msg = ChatMessage.objects.create(
                room=room,
                user=request.user,
                message=user_text,
                parent_id=reply_parent_id,
            )

        attachment = ChatAttachment.objects.create(
            message=parent_msg,
            file=f,
            original_filename=f.name,
            file_size=f.size,
            content_type=f.content_type or "application/octet-stream",
        )
        return JsonResponse(
            {
                "id": attachment.id,
                "filename": attachment.original_filename,
                "size": attachment.file_size_formatted,
                "is_image": attachment.is_image,
                "url": attachment.file.url,
                "message_id": parent_msg.id,
            }
        )
    return JsonResponse({"error": "No file"}, status=400)
