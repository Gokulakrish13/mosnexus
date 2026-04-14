"""Products app — Communication views."""

# pylint: disable=broad-exception-caught,no-else-return,no-member


from ._helpers import (
    Communication,
    CommunicationAttachment,
    FileResponse,
    JsonResponse,
    datetime,
    json,
    logger,
    login_required,
    timedelta,
    timezone,
)

__all__ = [
    "communication_api",
    "upload_communication_attachment",
    "serve_communication_attachment",
    "execute_robocopy",
]


@login_required
def communication_api(request):  # noqa: C901, CCR001
    # pylint: disable=too-many-return-statements,too-many-branches,too-complex
    """Communication api."""
    user = request.user
    # Auto-delete comments older than 30 days
    Communication.objects.filter(
        page="build_os_info",
        created_at__lt=timezone.now() - timedelta(days=30),
    ).delete()
    if request.method == "GET":
        comms = Communication.objects.filter(page="build_os_info").order_by("-created_at")[:50]
        return JsonResponse(
            {
                "comments": [
                    {
                        "id": c.id,
                        "user": c.user.username,
                        "message": c.message,
                        "deleted": c.deleted,
                        "created_at": c.created_at.astimezone(timezone.utc).isoformat(),  # type: ignore[attr-defined]
                        "updated_at": (
                            c.updated_at.astimezone(timezone.utc).isoformat()  # type: ignore[attr-defined]
                            if c.updated_at
                            else c.created_at.astimezone(timezone.utc).isoformat()  # type: ignore[attr-defined]
                        ),
                        "attachments": [
                            {
                                "id": att.id,
                                "filename": att.original_filename,
                                "file_size": att.file_size_formatted,
                                "content_type": att.content_type,
                                "is_image": att.is_image,
                                "url": f"/api/communication/attachment/{att.id}/",
                            }
                            for att in c.attachments.all()
                        ],
                    }
                    for c in comms
                ]
            }
        )
    if request.method == "POST":
        data = json.loads(request.body.decode("utf-8"))
        msg = data.get("message", "").strip()
        attachment_ids = data.get("attachment_ids", [])

        if not msg:
            return JsonResponse({"success": False, "error": "Message required."}, status=400)

        comm = Communication.objects.create(user=user, message=msg, page="build_os_info")

        # Link any pending attachments to this comment
        if attachment_ids:
            attachments_to_update = CommunicationAttachment.objects.filter(
                id__in=attachment_ids, uploaded_by=user, communication__isnull=True
            )
            for attachment in attachments_to_update:
                attachment.communication = comm
                attachment.save()

        return JsonResponse(
            {
                "success": True,
                "id": comm.id,
                "message": comm.message,
                "user": user.username,
                "created_at": comm.created_at.astimezone(timezone.utc).isoformat(),  # type: ignore[attr-defined]
                "attachments": [
                    {
                        "id": att.id,
                        "filename": att.original_filename,
                        "file_size": att.file_size_formatted,
                        "content_type": att.content_type,
                        "is_image": att.is_image,
                        "url": f"/api/communication/attachment/{att.id}/",
                    }
                    for att in comm.attachments.all()
                ],
            }
        )
    if request.method == "PUT":
        data = json.loads(request.body.decode("utf-8"))
        cid = data.get("id")
        msg = data.get("message", "").strip()
        if not cid or not msg:
            return JsonResponse({"success": False, "error": "ID and message required."}, status=400)
        try:
            comm = Communication.objects.get(id=cid, user=user, page="build_os_info")
        except Communication.DoesNotExist:
            return JsonResponse({"success": False, "error": "Comment not found."}, status=404)
        # Only allow edit for 15 minutes after posting
        now = datetime.now(timezone.utc)  # type: ignore[attr-defined]
        if comm.deleted:
            return JsonResponse({"success": False, "error": "Comment deleted."}, status=403)
        if (now - comm.created_at) > timedelta(minutes=15):
            return JsonResponse({"success": False, "error": "Edit window expired."}, status=403)
        comm.message = msg
        comm.save()
        return JsonResponse({"success": True})
    if request.method == "DELETE":
        data = json.loads(request.body.decode("utf-8"))
        cid = data.get("id")
        if not cid:
            return JsonResponse({"success": False, "error": "ID required."}, status=400)
        try:
            comm = Communication.objects.get(id=cid, user=user, page="build_os_info")
            now = datetime.now(timezone.utc)  # type: ignore[attr-defined]
        except Communication.DoesNotExist:
            return JsonResponse({"success": False, "error": "Comment not found."}, status=404)
        now = datetime.now(timezone.utc)  # type: ignore[attr-defined]
        if comm.deleted:
            return JsonResponse({"success": False, "error": "Already deleted."}, status=403)
        time_diff_hours = (now - comm.created_at).total_seconds() / 3600
        if time_diff_hours > 12:
            return JsonResponse({"success": False, "error": "Delete window expired."}, status=403)
        comm.deleted = True
        comm.save()
        return JsonResponse({"success": True})
    else:
        return JsonResponse({"success": False, "error": "Invalid method."}, status=405)


@login_required
def upload_communication_attachment(request):
    """Upload communication attachment."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Invalid method"}, status=405)

    if "file" not in request.FILES:
        return JsonResponse({"success": False, "error": "No file provided"}, status=400)

    uploaded_file = request.FILES["file"]

    if uploaded_file.size > 5 * 1024 * 1024:
        return JsonResponse({"success": False, "error": "File size must be less than 5MB"}, status=400)

    allowed_types = [
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/bmp",
        "image/webp",
        "application/pdf",
        "text/plain",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ]

    if uploaded_file.content_type not in allowed_types:
        return JsonResponse({"success": False, "error": "File type not allowed"}, status=400)

    try:
        # Create a temporary attachment without a communication (will be linked when comment is posted)
        attachment = CommunicationAttachment.objects.create(
            communication=None,  # Will be set when comment is created
            file=uploaded_file,
            original_filename=uploaded_file.name,
            file_size=uploaded_file.size,
            content_type=uploaded_file.content_type,
            uploaded_by=request.user,
        )

        return JsonResponse(
            {
                "success": True,
                "attachment_id": attachment.id,
                "filename": attachment.original_filename,
                "file_size": attachment.file_size_formatted,
                "content_type": attachment.content_type,
                "is_image": attachment.is_image,
            }
        )

    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"}, status=500)


@login_required
def serve_communication_attachment(request, attachment_id):
    """Serve communication attachment."""
    try:
        attachment = CommunicationAttachment.objects.get(id=attachment_id)

        # Authorization: verify user owns the communication or uploaded the attachment
        comm = attachment.communication
        if not request.user.is_superuser:
            user_is_owner = comm and comm.user == request.user
            user_is_uploader = attachment.uploaded_by == request.user
            if not (user_is_owner or user_is_uploader):
                return JsonResponse({"error": "Access denied"}, status=403)

        if not attachment.file:
            return JsonResponse({"error": "File not found"}, status=404)

        response = FileResponse(
            attachment.file.open("rb"), content_type=attachment.content_type, filename=attachment.original_filename
        )
        response["Content-Length"] = attachment.file_size
        return response

    except CommunicationAttachment.DoesNotExist:
        return JsonResponse({"error": "Attachment not found"}, status=404)
    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"error": "An unexpected error occurred"}, status=500)


@login_required
def execute_robocopy(request):
    """Disabled — this endpoint has been removed for security reasons (command injection risk)."""
    return JsonResponse(
        {"success": False, "error": "This endpoint has been disabled for security reasons."}, status=403
    )
