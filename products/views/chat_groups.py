"""Products app - Chat Room Create, Group Members, Reactions, Pins, Typing views."""

from django.core.cache import cache
from django.utils import timezone as tz

from ._helpers import (
    ChatMessage,
    ChatReaction,
    ChatRoom,
    ChatRoomMember,
    JsonResponse,
    Stream,
    User,
    get_current_bu,
    get_object_or_404,
    is_app_admin,
    is_super_admin,
    json,
    login_required,
    messages,
    redirect,
)

__all__ = [
    "chat_room_create",
    "group_chat_add_member",
    "group_chat_remove_member",
    "chat_react",
    "chat_pin_message",
    "chat_typing_indicator",
]


@login_required
def chat_room_create(request):  # noqa: CCR001
    """Create a new chat room (admin-only for global/stream, anyone for group)."""
    bu = get_current_bu(request)
    if not bu:
        return redirect("select_bu")

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        room_type = request.POST.get("room_type", "global")
        stream_id = request.POST.get("stream_id")
        description = request.POST.get("description", "").strip()

        # Only admins can create global/stream rooms
        if room_type in ("global", "stream"):
            if not (is_super_admin(request.user) or is_app_admin(request.user)):
                messages.error(request, "Only admins can create channel rooms.")
                return redirect("team_chat")

        stream_obj = None
        if room_type == "stream" and stream_id:
            stream_obj = get_object_or_404(Stream, pk=stream_id)

        room = ChatRoom.objects.create(
            business_unit=bu,
            name=name,
            room_type=room_type,
            stream=stream_obj,
            description=description,
            created_by=request.user,
        )

        # If group chat, add creator as admin and selected members
        if room_type == "group":
            ChatRoomMember.objects.create(room=room, user=request.user, role="admin")
            member_ids = request.POST.getlist("members")
            for uid in member_ids:
                try:
                    member_user = User.objects.get(pk=int(uid), is_active=True)
                    ChatRoomMember.objects.get_or_create(room=room, user=member_user, defaults={"role": "member"})
                except (User.DoesNotExist, ValueError):
                    pass
            # System message
            member_names = ", ".join([m.user.username for m in room.members.select_related("user").all()])
            ChatMessage.objects.create(
                room=room,
                user=request.user,
                message=f"Group created with: {member_names}",
                message_type="system",
            )
            messages.success(request, f'Group chat "{name}" created.')
        else:
            messages.success(request, f'Chat room "{name}" created.')
    return redirect("team_chat")


@login_required
def group_chat_add_member(request, room_id):  # noqa: CCR001
    """Add member(s) to a group chat."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"error": "No BU"}, status=400)
    room = get_object_or_404(ChatRoom, pk=room_id, business_unit=bu, room_type="group", is_active=True)

    # Only group admin or super admin can add members
    if not (room.members.filter(user=request.user, role="admin").exists() or is_super_admin(request.user)):
        return JsonResponse({"error": "Only group admins can add members"}, status=403)

    if request.method == "POST":
        body = json.loads(request.body) if request.content_type == "application/json" else request.POST
        user_ids = body.getlist("user_ids") if hasattr(body, "getlist") else body.get("user_ids", [])
        share_history = body.get("share_history", True)
        # Handle string 'false' from JSON
        if isinstance(share_history, str):
            share_history = share_history.lower() not in ("false", "0", "no")
        added = []
        for uid in user_ids:
            try:
                member_user = User.objects.get(pk=int(uid), is_active=True)
                _, created = ChatRoomMember.objects.get_or_create(
                    room=room, user=member_user, defaults={"role": "member", "can_see_history": share_history}
                )
                if created:
                    added.append(member_user.username)
            except (User.DoesNotExist, ValueError):
                pass
        if added:
            history_note = " (with chat history)" if share_history else " (without chat history)"
            ChatMessage.objects.create(
                room=room,
                user=request.user,
                message=f'{request.user.username} added {", ".join(added)} to the group{history_note}',
                message_type="system",
            )
        return JsonResponse({"added": added})
    return JsonResponse({"error": "POST required"}, status=405)


@login_required
def group_chat_remove_member(request, room_id, user_id):  # noqa: CCR001
    """Remove a member from a group chat."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"error": "No BU"}, status=400)
    room = get_object_or_404(ChatRoom, pk=room_id, business_unit=bu, room_type="group", is_active=True)

    is_admin_user = room.members.filter(user=request.user, role="admin").exists() or is_super_admin(request.user)
    is_self_leaving = int(user_id) == request.user.id

    if not (is_admin_user or is_self_leaving):
        return JsonResponse({"error": "Permission denied"}, status=403)

    if request.method == "POST":
        membership = room.members.filter(user_id=user_id).first()
        if membership:
            username = membership.user.username
            membership.delete()
            ChatMessage.objects.create(
                room=room,
                user=request.user,
                message=f'{username} {"left" if is_self_leaving else "was removed from"} the group',
                message_type="system",
            )
            if is_self_leaving:
                return JsonResponse({"left": True, "redirect": True})
            return JsonResponse({"removed": True, "user": username})
        return JsonResponse({"error": "Not a member"}, status=404)
    return JsonResponse({"error": "POST required"}, status=405)


@login_required
def chat_react(request, room_id, message_id):  # noqa: CCR001
    """Toggle a reaction on a message."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"error": "No BU"}, status=400)
    room = get_object_or_404(ChatRoom, pk=room_id, business_unit=bu, is_active=True)

    # Group access check
    if room.room_type == "group" and not room.members.filter(user=request.user).exists():
        return JsonResponse({"error": "Not a member"}, status=403)

    msg = get_object_or_404(ChatMessage, pk=message_id, room=room, is_deleted=False)

    if request.method == "POST":
        body = json.loads(request.body)
        emoji = body.get("emoji", "").strip()
        if not emoji:
            return JsonResponse({"error": "No emoji"}, status=400)

        existing = ChatReaction.objects.filter(message=msg, user=request.user, emoji=emoji).first()
        if existing:
            existing.delete()
            action = "removed"
        else:
            ChatReaction.objects.create(message=msg, user=request.user, emoji=emoji)
            action = "added"

        # Return updated reactions for this message
        reactions = {}
        for reaction in msg.reactions.all():
            if reaction.emoji not in reactions:
                reactions[reaction.emoji] = {"emoji": reaction.emoji, "count": 0, "users": [], "user_reacted": False}
            reactions[reaction.emoji]["count"] += 1
            reactions[reaction.emoji]["users"].append(reaction.user.username)
            if reaction.user_id == request.user.id:
                reactions[reaction.emoji]["user_reacted"] = True

        return JsonResponse({"action": action, "reactions": list(reactions.values())})
    return JsonResponse({"error": "POST required"}, status=405)


@login_required
def chat_pin_message(request, room_id, message_id):
    """Pin or unpin a message."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"error": "No BU"}, status=400)
    room = get_object_or_404(ChatRoom, pk=room_id, business_unit=bu, is_active=True)
    msg = get_object_or_404(ChatMessage, pk=message_id, room=room, is_deleted=False)

    # Only admins or message owner can pin
    can_pin = is_super_admin(request.user) or is_app_admin(request.user) or msg.user == request.user
    if room.room_type == "group":
        can_pin = can_pin or room.members.filter(user=request.user, role="admin").exists()

    if not can_pin:
        return JsonResponse({"error": "Permission denied"}, status=403)

    if request.method == "POST":
        msg.is_pinned = not msg.is_pinned
        msg.save(update_fields=["is_pinned"])
        action = "pinned" if msg.is_pinned else "unpinned"
        ChatMessage.objects.create(
            room=room,
            user=request.user,
            message=f"{request.user.username} {action} a message",
            message_type="system",
        )
        return JsonResponse({"pinned": msg.is_pinned, "message_id": msg.id})
    return JsonResponse({"error": "POST required"}, status=405)


@login_required
def chat_typing_indicator(request, room_id):
    """Simple typing indicator API — stores in-memory via cache if available, else no-op."""
    bu = get_current_bu(request)
    if not bu:
        return JsonResponse({"error": "No BU"}, status=400)

    if request.method == "POST":
        # We use Django's cache for ephemeral typing state
        cache_key = f"chat_typing_{room_id}"
        typing_users = cache.get(cache_key, {})
        now = tz.now().timestamp()
        typing_users[request.user.username] = now
        # Clean stale (>5s old)
        typing_users = {k: v for k, v in typing_users.items() if now - v < 5}
        cache.set(cache_key, typing_users, 10)
        return JsonResponse({"ok": True})

    if request.method == "GET":
        cache_key = f"chat_typing_{room_id}"
        typing_users = cache.get(cache_key, {})
        now = tz.now().timestamp()
        active = [k for k, v in typing_users.items() if now - v < 5 and k != request.user.username]
        return JsonResponse({"typing": active})

    return JsonResponse({"error": "GET or POST"}, status=405)


# ═══════════════════════════════════════════════════════════════════════════
# AI USAGE PATTERN ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════
