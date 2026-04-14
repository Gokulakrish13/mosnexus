"""Products app - Sub-levels, Sub-level Tools, Bulk Operations, and QR Code views."""

# pylint: disable=broad-exception-caught,invalid-name,too-many-lines

from PIL import Image as PILImage

from django.utils.text import slugify

from ._helpers import (  # noqa: F811
    AuditLog,
    BytesIO,
    FileResponse,
    HttpResponse,
    ImageDraw,
    ImageFont,
    JsonResponse,
    OnboardingProgress,
    PILImage,
    Product,
    SubLevel,
    SubLevelHistory,
    SubLevelTool,
    SubLevelToolHistory,
    _parse_json_body,
    check_user_access,
    csv,
    datetime,
    get_column_letter,
    get_default_stream_name,
    get_object_or_404,
    get_stream_or_404,
    json,
    logger,
    login_required,
    logout,
    messages,
    openpyxl,
    os,
    qrcode,
    redirect,
    render,
    require_GET,
    require_POST,
    reverse,
    settings,
)

__all__ = [
    "sub_level_list",
    "delete_sub_level",
    "sub_level_tool_list",
    "delete_sub_level_tool",
    "bulk_delete_subleveltools",
    "bulk_update_subleveltools",
    "export_subleveltools",
    "bulk_delete_sublevels",
    "bulk_update_sublevels",
    "export_sublevels",
    "download_qr_with_details",
]


@login_required
def sub_level_list(request, stream=None):  # noqa: C901, CCR001
    """Sub level list."""
    # pylint: disable=too-complex,too-many-branches,too-many-locals,too-many-statements
    edit_id = request.GET.get("edit_id")
    new_name = request.GET.get("new_name")
    user = request.user if request.user.is_authenticated else None

    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        logout(request)
        messages.error(request, error_message)
        return redirect("please_login")

    stream_obj = get_stream_or_404(stream, request=request)

    if edit_id and new_name:
        sub = SubLevel.objects.filter(id=edit_id, stream=stream_obj).first()
        if sub:
            old_name = sub.name
            sub.name = new_name
            sub.save()
            SubLevelHistory.objects.create(
                sublevel=sub,
                action="Edited",
                by=user.username if user else "Unknown",
                details=f"Changed name from '{old_name}' to '{new_name}'",
            )
            return redirect(request.path)
    if request.method == "POST":
        if "delete_id" in request.POST:
            delete_id = request.POST.get("delete_id")
            if delete_id:
                AuditLog.log(
                    "delete",
                    f"Deleted sub level (ID: {delete_id})",
                    user=request.user,
                    request=request,
                    module="products",
                    severity="warning",
                )
                SubLevel.objects.filter(id=delete_id, stream=stream_obj).delete()
                return redirect(request.path)
        if "sublevel_id" in request.POST:
            sub = SubLevel.objects.filter(id=request.POST["sublevel_id"], stream=stream_obj).first()
            if sub:
                old_in_stock, old_in_use, old_scraped = sub.in_stock, sub.in_use, sub.scraped
                new_in_stock = int(request.POST.get("in_stock", 0))
                new_in_use = int(request.POST.get("in_use", 0))
                new_scraped = int(request.POST.get("scraped", 0))
                changes = []
                if old_in_stock != new_in_stock:
                    changes.append(f"Changed In Stock from {old_in_stock} to {new_in_stock}")
                if old_in_use != new_in_use:
                    changes.append(f"Changed In Use from {old_in_use} to {new_in_use}")
                if old_scraped != new_scraped:
                    changes.append(f"Changed Scraped from {old_scraped} to {new_scraped}")
                sub.in_stock = new_in_stock
                sub.in_use = new_in_use
                sub.scraped = new_scraped
                sub.save()
                if changes:
                    SubLevelHistory.objects.create(
                        sublevel=sub,
                        action="Edited",
                        by=user.username if user else "Unknown",
                        details="; ".join(changes),
                    )
        elif "subitem_name" in request.POST:
            name = request.POST.get("subitem_name")
            if name:  # Prevent duplicate sublevel name (case-insensitive, per stream)
                exists = SubLevel.objects.filter(name__iexact=name.strip(), stream=stream_obj).exists()
                if exists:
                    messages.error(request, f"Sublevel '{name}' already exists.")
                else:
                    sub = SubLevel.objects.create(name=name.strip(), stream=stream_obj)
                    SubLevelHistory.objects.create(
                        sublevel=sub,
                        action="Created",
                        by=user.username if user else "Admin",
                        details="Initial creation",
                    )
            return redirect(request.path)
    subitems = SubLevel.objects.filter(stream=stream_obj) if stream else SubLevel.objects.all()
    for sub in subitems:
        sub.history_list = list(sub.history.order_by("at").values("action", "by", "at", "details"))
    sublevel_history_dict = {str(sub.id): sub.history_list for sub in subitems}
    sublevel_history_json = json.dumps(sublevel_history_dict, default=str)
    return render(
        request,
        "products/sub_level_list.html",
        {
            "subitems": subitems,
            "selected_stream": stream,
            "sublevel_history_json": sublevel_history_json,
            "show_onboarding_tour": not OnboardingProgress.objects.filter(
                user=request.user, tour_key="sub_level_data"
            ).exists(),
        },
    )


@login_required
@require_POST
def delete_sub_level(request, stream, sublevel_id):
    """Delete sub level."""
    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    stream_obj = get_stream_or_404(stream, request=request)

    SubLevel.objects.filter(id=sublevel_id, stream=stream_obj).delete()
    return redirect("sub_level_list_stream", stream=stream)


@login_required
def sub_level_tool_list(request, stream=None):  # noqa: C901, CCR001
    """Sub level tool list."""
    # pylint: disable=too-complex,too-many-branches,too-many-locals,too-many-statements
    edit_id = request.GET.get("edit_id")
    new_name = request.GET.get("new_name")
    user = request.user if request.user.is_authenticated else None

    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    has_access, error_message, _custom_profile = check_user_access(request, stream)
    if not has_access:
        logout(request)
        messages.error(request, error_message)
        return redirect("please_login")

    stream_obj = get_stream_or_404(stream, request=request)

    if edit_id and new_name:
        tool = SubLevelTool.objects.filter(id=edit_id, stream=stream_obj).first()
        if tool:
            old_name = tool.name
            tool.name = new_name
            tool.save()
            SubLevelToolHistory.objects.create(
                subleveltool=tool,
                action="Edited",
                by=user.username if user else "Unknown",
                details=f"Changed name from '{old_name}' to '{new_name}'",
            )
            return redirect(request.path)
    if request.method == "POST":
        if "delete_id" in request.POST:
            delete_id = request.POST.get("delete_id")
            if delete_id:
                AuditLog.log(
                    "delete",
                    f"Deleted sub level tool (ID: {delete_id})",
                    user=request.user,
                    request=request,
                    module="products",
                    severity="warning",
                )
                SubLevelTool.objects.filter(id=delete_id, stream=stream_obj).delete()
                return redirect(request.path)
        if "subleveltool_id" in request.POST:
            tool = SubLevelTool.objects.filter(id=request.POST["subleveltool_id"], stream=stream_obj).first()
            if tool:
                old_in_stock, old_in_use, old_scraped = tool.in_stock, tool.in_use, tool.scraped
                new_in_stock = int(request.POST.get("in_stock", 0))
                new_in_use = int(request.POST.get("in_use", 0))
                new_scraped = int(request.POST.get("scraped", 0))
                changes = []
                if old_in_stock != new_in_stock:
                    changes.append(f"Changed In Stock from {old_in_stock} to {new_in_stock}")
                if old_in_use != new_in_use:
                    changes.append(f"Changed In Use from {old_in_use} to {new_in_use}")
                if old_scraped != new_scraped:
                    changes.append(f"Changed Scraped from {old_scraped} to {new_scraped}")
                tool.in_stock = new_in_stock
                tool.in_use = new_in_use
                tool.scraped = new_scraped
                tool.save()
                if changes:
                    SubLevelToolHistory.objects.create(
                        subleveltool=tool,
                        action="Edited",
                        by=user.username if user else "Unknown",
                        details="; ".join(changes),
                    )
        elif "subtool_name" in request.POST:
            name = request.POST.get("subtool_name")
            if name:  # Prevent duplicate subleveltool name (case-insensitive, per stream)
                exists = SubLevelTool.objects.filter(name__iexact=name.strip(), stream=stream_obj).exists()
                if exists:
                    messages.error(request, f"Subtool '{name}' already exists.")
                else:
                    tool = SubLevelTool.objects.create(name=name.strip(), stream=stream_obj)
                    SubLevelToolHistory.objects.create(
                        subleveltool=tool,
                        action="Created",
                        by=user.username if user else "Admin",
                        details="Initial creation",
                    )
            return redirect(request.path)
    subtools = SubLevelTool.objects.filter(stream=stream_obj) if stream else SubLevelTool.objects.all()
    for tool in subtools:
        tool.history_list = list(tool.history.order_by("at").values("action", "by", "at", "details"))
    subleveltool_history_dict = {str(tool.id): tool.history_list for tool in subtools}
    subleveltool_history_json = json.dumps(subleveltool_history_dict, default=str)
    # Compute totals for stat pills
    total_in_stock = sum(t.in_stock for t in subtools)
    total_in_use = sum(t.in_use for t in subtools)
    total_scraped = sum(t.scraped for t in subtools)
    return render(
        request,
        "products/sub_level_tool_list.html",
        {
            "subtools": subtools,
            "selected_stream": stream,
            "subleveltool_history_json": subleveltool_history_json,
            "total_in_stock": total_in_stock,
            "total_in_use": total_in_use,
            "total_scraped": total_scraped,
            "show_onboarding_tour": not OnboardingProgress.objects.filter(
                user=request.user, tour_key="sub_level_tools"
            ).exists(),
        },
    )


@login_required
@require_POST
def delete_sub_level_tool(request, stream, subleveltool_id):
    """Delete sub level tool."""
    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    stream_obj = get_stream_or_404(stream, request=request)

    SubLevelTool.objects.filter(id=subleveltool_id, stream=stream_obj).delete()
    return redirect("sub_level_tool_list_stream", stream=stream)


@login_required
@require_POST
def bulk_delete_subleveltools(request, stream=None):
    """Bulk delete subleveltools."""
    try:
        data = json.loads(request.body)
        ids = data.get("ids", [])

        if not stream or stream.strip() == "":
            stream = get_default_stream_name(request)

        stream_obj = get_stream_or_404(stream, request=request)

        deleted_count = SubLevelTool.objects.filter(id__in=ids, stream=stream_obj).delete()[0]
        return JsonResponse({"success": True, "deleted": deleted_count})
    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"})


@login_required
@require_POST
def bulk_update_subleveltools(request, stream=None):  # noqa: CCR001
    """Bulk update subleveltools."""
    try:
        data = json.loads(request.body)
        notes = data.get("notes", {})
        user = request.user if request.user.is_authenticated else None

        if not stream or stream.strip() == "":
            stream = get_default_stream_name(request)

        stream_obj = get_stream_or_404(stream, request=request)

        for tool_id, note_text in notes.items():
            tool = SubLevelTool.objects.filter(id=tool_id, stream=stream_obj).first()
            if tool:
                old_note = tool.note or ""
                tool.note = note_text
                tool.save()
                if old_note != note_text:
                    SubLevelToolHistory.objects.create(
                        subleveltool=tool,
                        action="Edited",
                        by=user.username if user else "Unknown",
                        details=f"Updated note from '{old_note}' to '{note_text}'",
                    )
        return JsonResponse({"success": True})
    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"})


@login_required
def export_subleveltools(request, stream=None):
    """Export subleveltools."""
    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    stream_obj = get_stream_or_404(stream, request=request)

    subtools = SubLevelTool.objects.filter(stream=stream_obj)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sub-Level Tools"

    headers = ["Tool Name", "In Stock", "In Use", "Scraped", "Stream", "Note", "Last Modified By", "Last Modified Date"]
    ws.append(headers)

    for tool in subtools:
        last_history = tool.history.order_by("-at").first()
        last_by = last_history.by if last_history else ""
        last_at = last_history.at.strftime("%Y-%m-%d %H:%M:%S") if last_history else ""
        ws.append(
            [tool.name, tool.in_stock, tool.in_use, tool.scraped, tool.stream or "", tool.note or "", last_by, last_at]
        )

    for col in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 22

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{stream}_Sub_Level_Tools.xlsx"
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response


@login_required
def bulk_delete_sublevels(request, stream=None):
    """Bulk delete sublevels."""
    if request.method == "POST":
        data, err = _parse_json_body(request)
        if err:
            return err
        ids = data.get("ids", [])
        deleted = 0

        stream_obj = get_stream_or_404(stream, request=request)

        for sub_id in ids:
            try:
                sub = SubLevel.objects.get(id=sub_id, stream=stream_obj)
                sub.delete()
                deleted += 1
            except SubLevel.DoesNotExist:
                continue
        return JsonResponse({"success": True, "deleted": deleted})
    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required
def bulk_update_sublevels(request, stream=None):
    """Bulk update sublevels."""
    if request.method == "POST":
        data, err = _parse_json_body(request)
        if err:
            return err
        notes = data.get("notes", {})
        updated = 0

        stream_obj = get_stream_or_404(stream, request=request)

        for sub_id, note in notes.items():
            try:
                sub = SubLevel.objects.get(id=sub_id, stream=stream_obj)
                sub.note = note
                sub.save()
                updated += 1
            except SubLevel.DoesNotExist:
                continue
        return JsonResponse({"success": True, "updated": updated})
    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required
@require_GET
def export_sublevels(request, stream=None):
    """Export sublevels."""
    if not stream or stream.strip() == "":
        stream = get_default_stream_name(request)

    stream_obj = get_stream_or_404(stream, request=request)

    sublevels = SubLevel.objects.filter(stream=stream_obj)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="sublevels_export.csv"'
    writer = csv.writer(response)
    writer.writerow(["Name", "In Stock", "In Use", "Scrapped", "Note"])
    for sub in sublevels:
        writer.writerow([sub.name, sub.in_stock, sub.in_use, sub.scraped, sub.note or ""])
    return response


# API endpoints for system allocation real-time features


@login_required
def download_qr_with_details(request, stream, pk):  # noqa: C901, CCR001
    """Generate a high-resolution professional QR label for asset identification.

    Output is 3x scale for crisp printing and zoom without pixelation.
    """
    # pylint: disable=too-complex,too-many-locals,too-many-statements
    # ─────────────────────────────────────────────────────────────────────────────
    # CONFIGURATION (High Resolution - 3x scale)
    # ─────────────────────────────────────────────────────────────────────────────

    scale = 3  # 3x resolution for sharp output

    color_primary = (0, 51, 102)  # Deep corporate blue
    color_secondary = (51, 51, 51)  # Dark gray for text
    color_light_gray = (128, 128, 128)  # Light gray for labels
    color_red = (180, 0, 0)  # Red for warning text
    color_white = (255, 255, 255)  # Background

    # Base dimensions (will be multiplied by scale)
    base_width = 250
    base_height = 125
    base_padding = 10
    base_qr_size = 70

    # Actual dimensions at high resolution
    label_width = base_width * scale
    label_height = base_height * scale
    padding = base_padding * scale
    qr_size = base_qr_size * scale

    # ─────────────────────────────────────────────────────────────────────────────
    # DATA RETRIEVAL
    # ─────────────────────────────────────────────────────────────────────────────

    stream_obj = get_stream_or_404(stream, request=request)
    product = get_object_or_404(Product, pk=pk, stream=stream_obj)

    product_url = request.build_absolute_uri(reverse("product_detail_stream", args=[stream, product.pk]))

    product_name = product.name or "N/A"
    serial_number = product.serial_number or "N/A"
    category_name = product.category.name if product.category else "N/A"

    # ─────────────────────────────────────────────────────────────────────────────
    # FONT LOADING (Scaled)
    # ─────────────────────────────────────────────────────────────────────────────

    def load_font(base_size, bold=False):
        """Load font at scaled size."""
        size = base_size * scale
        font_names = ["arialbd.ttf", "arial.ttf"] if bold else ["arial.ttf"]
        for font_name in font_names:
            try:
                return ImageFont.truetype(font_name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    font_header = load_font(14, bold=True)
    font_warning = load_font(8, bold=True)
    font_label = load_font(8)
    font_value = load_font(9, bold=True)
    font_category = load_font(8)

    # ─────────────────────────────────────────────────────────────────────────────
    # QR CODE GENERATION (Philips Branded Style)
    # ─────────────────────────────────────────────────────────────────────────────

    # Philips brand blue color for QR code
    philips_blue = "#0B5ED7"

    # Use HIGH error correction for logo in center
    qr = qrcode.QRCode(version=2, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=12, border=2)
    qr.add_data(product_url)
    qr.make(fit=True)

    # Generate QR with Philips blue color
    qr_img = qr.make_image(fill_color=philips_blue, back_color="white").convert("RGBA")

    # Resize QR to target size
    qr_img = qr_img.resize((qr_size, qr_size), PILImage.NEAREST)  # pylint: disable=no-member

    # Load and embed Philips logo in center of QR code
    logo_path = os.path.join(settings.BASE_DIR, "products", "static", "products", "Philips_NoBG.png")
    try:
        logo = PILImage.open(logo_path).convert("RGBA")
        # Logo size should be about 25% of QR size for good scannability
        logo_size = qr_size // 4
        logo = logo.resize((logo_size, logo_size), PILImage.LANCZOS)  # pylint: disable=no-member

        # Create white background box for logo (slightly larger)
        bg_size = logo_size + 8
        logo_bg = PILImage.new("RGBA", (bg_size, bg_size), (255, 255, 255, 255))

        # Center positions
        bg_pos = ((qr_size - bg_size) // 2, (qr_size - bg_size) // 2)
        logo_pos = ((qr_size - logo_size) // 2, (qr_size - logo_size) // 2)

        # Paste white background then logo
        qr_img.paste(logo_bg, bg_pos)
        qr_img.paste(logo, logo_pos, logo if logo.mode == "RGBA" else None)
    except Exception:
        pass  # If logo loading fails, QR code works without it

    # Convert back to RGB for final output
    qr_img = qr_img.convert("RGB")

    # ─────────────────────────────────────────────────────────────────────────────
    # LABEL CANVAS CREATION
    # ─────────────────────────────────────────────────────────────────────────────

    label = PILImage.new("RGB", (label_width, label_height), color_white)
    draw = ImageDraw.Draw(label)

    # ─────────────────────────────────────────────────────────────────────────────
    # DRAW WARNING TEXT (Top Center)
    # ─────────────────────────────────────────────────────────────────────────────

    warning_text = "PLEASE DO NOT REMOVE LABEL"
    warning_bbox = draw.textbbox((0, 0), warning_text, font=font_warning)
    warning_width = warning_bbox[2] - warning_bbox[0]
    warning_x = (label_width - warning_width) // 2
    draw.text((warning_x, 6 * scale), warning_text, fill=color_red, font=font_warning)

    # ─────────────────────────────────────────────────────────────────────────────
    # DRAW HEADER WITH GRADIENT LINE
    # ─────────────────────────────────────────────────────────────────────────────

    header_text = "NexusOps"
    draw.text((padding, 20 * scale), header_text, fill=color_primary, font=font_header)

    # Get header text width for gradient line positioning
    header_bbox = draw.textbbox((0, 0), header_text, font=font_header)
    header_width = header_bbox[2] - header_bbox[0]

    # Draw gradient line next to header
    line_start_x = padding + header_width + 10 * scale
    line_end_x = label_width - qr_size - padding - 10 * scale
    line_y = 20 * scale + (header_bbox[3] - header_bbox[1]) // 2

    # Create gradient from primary blue to light gray
    if line_end_x > line_start_x:
        line_length = line_end_x - line_start_x
        for i in range(line_length):
            # Gradient from COLOR_PRIMARY to COLOR_WHITE
            ratio = i / line_length
            r = int(color_primary[0] + (color_white[0] - color_primary[0]) * ratio)
            g = int(color_primary[1] + (color_white[1] - color_primary[1]) * ratio)
            b = int(color_primary[2] + (color_white[2] - color_primary[2]) * ratio)
            draw.line([(line_start_x + i, line_y), (line_start_x + i, line_y + 2 * scale)], fill=(r, g, b))

    # ─────────────────────────────────────────────────────────────────────────────
    # DRAW QR CODE (positioned closer to content)
    # ─────────────────────────────────────────────────────────────────────────────

    qr_x = label_width - qr_size - (padding * 2)
    qr_y = (label_height - qr_size) // 2
    label.paste(qr_img, (qr_x, qr_y))

    # ─────────────────────────────────────────────────────────────────────────────
    # DRAW PRODUCT DETAILS
    # ─────────────────────────────────────────────────────────────────────────────

    content_x = padding
    content_y = 42 * scale
    line_height = 24 * scale

    text_width = label_width - qr_size - padding * 3

    def truncate_text(text, max_width, font):
        if not text:
            return "N/A"
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return text
        while len(text) > 3:
            text = text[:-1]
            bbox = draw.textbbox((0, 0), text + "...", font=font)
            if bbox[2] - bbox[0] <= max_width:
                return text + "..."
        return text

    def draw_field(y_pos, label_text, value_text, value_font=font_value):
        draw.text((content_x, y_pos), label_text, fill=color_light_gray, font=font_label)
        truncated = truncate_text(value_text, text_width - 10, value_font)
        draw.text((content_x, y_pos + 10 * scale), truncated, fill=color_secondary, font=value_font)

    # Product Name
    draw_field(content_y, "PRODUCT NAME", product_name)

    # Serial Number
    draw_field(content_y + line_height, "SERIAL NUMBER", serial_number)

    # Category
    draw_field(content_y + line_height * 2, "CATEGORY", category_name, font_category)

    # ─────────────────────────────────────────────────────────────────────────────
    # EXPORT (High Resolution PNG)
    # ─────────────────────────────────────────────────────────────────────────────

    buffer = BytesIO()
    label.save(buffer, format="PNG", dpi=(300, 300))
    buffer.seek(0)

    filename = f"Asset_Label_{slugify(serial_number)}.png"
    return FileResponse(buffer, as_attachment=True, filename=filename, content_type="image/png")
