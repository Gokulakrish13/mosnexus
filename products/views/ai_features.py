"""Products app — Ai Features views."""

# pylint: disable=too-many-lines,import-error,import-outside-toplevel,broad-exception-caught

import time as time_module

from ._helpers import (
    MAX_DOCUMENT_SIZE,
    AICalibrationReport,
    AIModelTrainingLog,
    AnomalyDetectionReport,
    AuditLog,
    CalibrationSchedule,
    HttpResponse,
    InventoryForecast,
    JsonResponse,
    NLQueryLog,
    OCRProcessingResult,
    SchedulerRecommendation,
    System,
    UsageAnalyticsReport,
    datetime,
    get_object_or_404,
    get_stream_or_404,
    is_super_admin,
    json,
    letter,
    logger,
    login_required,
    messages,
    os,
    redirect,
    render,
    require_POST,
    settings,
    user_passes_test,
    validate_uploaded_file,
)

__all__ = [
    "ai_calibration_report_hub",
    "ai_calibration_report_generate",
    "ai_calibration_report_view",
    "ai_calibration_report_pdf",
    "ai_ocr_hub",
    "ai_ocr_process",
    "ai_ocr_result",
    "ai_nl_dashboard",
    "ai_nl_query_api",
    "ai_nl_feedback_api",
    "ai_inventory_forecast",
    "ai_inventory_forecast_generate",
    "ai_inventory_forecast_view",
    "ai_smart_scheduler",
    "ai_smart_scheduler_recommend",
    "ai_model_management",
    "ai_train_model_api",
    "ai_usage_analytics",
    "ai_usage_analytics_generate",
    "ai_usage_analytics_view",
    "ai_anomaly_detection",
    "ai_anomaly_detection_scan",
    "ai_anomaly_detection_view",
]


@user_passes_test(is_super_admin)
@login_required
def ai_calibration_report_hub(request, stream=None):
    """Hub page to select a calibration schedule and generate a report."""
    stream_obj = get_stream_or_404(stream)
    schedules = (
        CalibrationSchedule.objects.filter(stream=stream_obj)
        .select_related("product", "system", "build_server")
        .order_by("title")
    )
    past_reports = AICalibrationReport.objects.filter(stream=stream_obj).order_by("-generated_at")[:20]
    context = {
        "stream": stream,
        "stream_obj": stream_obj,
        "schedules": schedules,
        "past_reports": past_reports,
    }
    return render(request, "products/ai_calibration_report_hub.html", context)


@user_passes_test(is_super_admin)
@login_required
def ai_calibration_report_generate(request, stream=None, schedule_id=None):
    """Generate an AI calibration report for a schedule."""
    stream_obj = get_stream_or_404(stream)
    schedule = get_object_or_404(CalibrationSchedule, pk=schedule_id, stream=stream_obj)

    from products.ai.calibration_report import CalibrationReportEngine

    engine = CalibrationReportEngine(schedule)
    report_data = engine.generate_report()

    stats = report_data["stats"]

    db_report = AICalibrationReport.objects.create(
        calibration_schedule=schedule,
        stream=stream_obj,
        generated_by=request.user,
        report_data=stats,
        compliance_score=stats["compliance_score"],
        anomaly_count=stats["anomaly_count"],
        pass_rate=stats["pass_rate"],
        recommendations_count=len(stats["recommendations"]),
    )

    AuditLog.log(
        "create",
        f'Generated AI calibration report for "{schedule.title}"',
        user=request.user,
        request=request,
        obj=db_report,
        module="ai",
        stream=stream_obj,
    )

    context = {
        "stream": stream,
        "stream_obj": stream_obj,
        "schedule": schedule,
        "report": report_data,
        "db_report": db_report,
    }
    return render(request, "products/ai_calibration_report.html", context)


@user_passes_test(is_super_admin)
@login_required
def ai_calibration_report_view(request, stream=None, pk=None):
    """View a previously generated AI calibration report."""
    stream_obj = get_stream_or_404(stream)
    db_report = get_object_or_404(AICalibrationReport, pk=pk, stream=stream_obj)
    schedule = db_report.calibration_schedule

    from products.ai.calibration_report import CalibrationReportEngine

    engine = CalibrationReportEngine(schedule)

    report_data = {
        "schedule": schedule,
        "records": list(schedule.records.order_by("calibration_date")),
        "stats": db_report.report_data,
        "generated_at": db_report.generated_at,
        "report_version": db_report.report_version,
    }
    # Regenerate recommendations from stored stats
    engine.generate_recommendations(report_data["stats"])

    context = {
        "stream": stream,
        "stream_obj": stream_obj,
        "schedule": schedule,
        "report": report_data,
        "db_report": db_report,
    }
    return render(request, "products/ai_calibration_report.html", context)


@user_passes_test(is_super_admin)
@login_required
def ai_calibration_report_pdf(request, stream=None, pk=None):  # pylint: disable=too-many-locals
    """Download AI calibration report as PDF."""
    stream_obj = get_stream_or_404(stream)
    db_report = get_object_or_404(AICalibrationReport, pk=pk, stream=stream_obj)
    schedule = db_report.calibration_schedule
    stats = db_report.report_data

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="calibration_report_{schedule.pk}_{db_report.pk}.pdf"'

    from reportlab.pdfgen import canvas as pdf_canvas

    pdf = pdf_canvas.Canvas(response, pagesize=letter)
    _width, height = letter

    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(50, height - 50, "AI Calibration Report")
    pdf.setFont("Helvetica", 12)
    pdf.drawString(50, height - 75, f"Schedule: {schedule.title}")
    pdf.drawString(50, height - 95, f"Stream: {stream_obj.name}")
    pdf.drawString(50, height - 115, f"Generated: {db_report.generated_at.strftime('%Y-%m-%d %H:%M')}")

    y = height - 155
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, y, "Summary")
    y -= 25
    pdf.setFont("Helvetica", 11)
    pdf.drawString(50, y, f"Compliance Score: {stats.get('compliance_score', 0)}%")
    y -= 18
    pdf.drawString(50, y, f"Pass Rate: {stats.get('pass_rate', 0)}%")
    y -= 18
    pdf.drawString(50, y, f"Total Records: {stats.get('total_records', 0)}")
    y -= 18
    pdf.drawString(50, y, f"Anomalies Found: {stats.get('anomaly_count', 0)}")

    y -= 35
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, y, "Recommendations")
    y -= 20
    pdf.setFont("Helvetica", 10)
    for rec in stats.get("recommendations", []):
        if y < 80:
            pdf.showPage()
            y = height - 50
        pdf.drawString(50, y, f"[{rec.get('type', '').upper()}] {rec.get('title', '')}")
        y -= 15
        detail = rec.get("detail", "")
        while detail and y > 60:
            line = detail[:90]
            pdf.drawString(70, y, line)
            detail = detail[90:]
            y -= 13
        y -= 8

    pdf.save()
    return response


# =============================================================================
# AI FEATURE 2: DOCUMENT OCR & AUTO-EXTRACTION
# =============================================================================


@user_passes_test(is_super_admin)
@login_required
def ai_ocr_hub(request, stream=None):
    """OCR hub page — upload documents and view past results."""
    stream_obj = get_stream_or_404(stream)
    past_results = OCRProcessingResult.objects.filter(stream=stream_obj).order_by("-processed_at")[:30]
    context = {
        "stream": stream,
        "stream_obj": stream_obj,
        "past_results": past_results,
    }
    return render(request, "products/ai_ocr_hub.html", context)


@user_passes_test(is_super_admin)
@login_required
@require_POST
def ai_ocr_process(request, stream=None):
    """Process an uploaded document with OCR."""
    stream_obj = get_stream_or_404(stream)

    uploaded_file = request.FILES.get("document")
    if not uploaded_file:
        messages.error(request, "No file uploaded.")
        return redirect("ai_ocr_hub", stream=stream)

    # OCR accepts images and PDFs
    ocr_allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf", "image/tiff"}
    ocr_allowed_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".tiff", ".tif"}
    is_valid, error_msg = validate_uploaded_file(
        uploaded_file, ocr_allowed_types, ocr_allowed_extensions, MAX_DOCUMENT_SIZE
    )
    if not is_valid:
        messages.error(request, f"File upload error: {error_msg}")
        return redirect("ai_ocr_hub", stream=stream)

    ocr_record = OCRProcessingResult.objects.create(
        uploaded_file=uploaded_file,
        original_filename=uploaded_file.name,
        file_type=uploaded_file.name.rsplit(".", 1)[-1].lower() if "." in uploaded_file.name else "",
        stream=stream_obj,
        processed_by=request.user,
        status="processing",
    )

    from products.ai.document_ocr import DocumentOCREngine

    engine = DocumentOCREngine()

    try:
        result = engine.process_document(ocr_record.uploaded_file.path)

        if result.get("success"):
            ocr_record.extracted_text = result.get("raw_text", "")
            ocr_record.ocr_confidence = result.get("ocr_result", {}).get("confidence", 0)
            ocr_record.document_type = result.get("classification", {}).get("type", "")
            ocr_record.classification_confidence = result.get("classification", {}).get("confidence", 0)
            ocr_record.extracted_fields = result.get("extracted_fields", {})
            ocr_record.status = "completed"
        else:
            ocr_record.status = "failed"
            ocr_record.processing_errors = result.get("error", "Unknown error")
    except Exception:
        ocr_record.status = "failed"
        ocr_record.processing_errors = "An error occurred during OCR processing"

    ocr_record.save()

    AuditLog.log(
        "create",
        f"Processed document via OCR: {uploaded_file.name}",
        user=request.user,
        request=request,
        obj=ocr_record,
        module="ai",
        stream=stream_obj,
    )

    return redirect("ai_ocr_result", stream=stream, pk=ocr_record.pk)


@user_passes_test(is_super_admin)
@login_required
def ai_ocr_result(request, stream=None, pk=None):
    """View OCR processing result."""
    stream_obj = get_stream_or_404(stream)
    result = get_object_or_404(OCRProcessingResult, pk=pk, stream=stream_obj)
    context = {
        "stream": stream,
        "stream_obj": stream_obj,
        "result": result,
    }
    return render(request, "products/ai_ocr_result.html", context)


# =============================================================================
# AI FEATURE 3: NATURAL LANGUAGE TO SQL DASHBOARD
# =============================================================================


@user_passes_test(is_super_admin)
@login_required
def ai_nl_dashboard(request, stream=None):
    """Natural language query dashboard."""
    stream_obj = get_stream_or_404(stream)
    recent_queries = NLQueryLog.objects.filter(user=request.user).order_by("-created_at")[:15]
    context = {
        "stream": stream,
        "stream_obj": stream_obj,
        "recent_queries": recent_queries,
        "suggestions": [
            "Show all products",
            "How many products per stream?",
            "System utilization",
            "Upcoming calibrations",
            "Low stock items",
            "Active alerts",
            "Upcoming maintenance",
            "Build server status",
            "Asset lifecycle summary",
            "Compliance status",
            "Top users",
            "Reservation conflicts",
        ],
    }
    return render(request, "products/ai_nl_dashboard.html", context)


@user_passes_test(is_super_admin)
@login_required
@require_POST
def ai_nl_query_api(request, stream=None):  # pylint: disable=unused-argument
    """API: Execute a natural language query."""
    try:
        body = json.loads(request.body)
        query_text = body.get("query", "").strip()
        if not query_text:
            return JsonResponse({"success": False, "error": "Empty query."})

        start_time = time_module.time()

        from products.ai.nl_query import NLQueryEngine

        engine = NLQueryEngine()
        result = engine.execute_query(query_text)

        elapsed_ms = int((time_module.time() - start_time) * 1000)

        NLQueryLog.objects.create(
            user=request.user,
            query_text=query_text,
            detected_intent=result.get("intent", ""),
            confidence=result.get("confidence", 0),
            classification_method=result.get("method", ""),
            parameters=result.get("params", {}),
            result_count=result.get("total", len(result.get("data", []))),
            was_successful=result.get("success", False),
            execution_time_ms=elapsed_ms,
        )

        result["execution_time_ms"] = elapsed_ms
        return JsonResponse(result)
    except Exception:
        logger.exception("Operation failed")
        logger.error("NL query API error")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"})


@user_passes_test(is_super_admin)
@login_required
@require_POST
def ai_nl_feedback_api(request, stream=None):  # pylint: disable=unused-argument
    """API: Submit feedback on a NL query result."""
    try:
        body = json.loads(request.body)
        query_id = body.get("query_id")
        feedback = body.get("feedback", "")
        if query_id and feedback:
            NLQueryLog.objects.filter(pk=query_id, user=request.user).update(user_feedback=feedback)
            return JsonResponse({"success": True})
        return JsonResponse({"success": False, "error": "Missing parameters."})
    except Exception:
        logger.exception("Operation failed")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"})


# =============================================================================
# AI FEATURE 4: PREDICTIVE INVENTORY FORECASTING
# =============================================================================


@user_passes_test(is_super_admin)
@login_required
def ai_inventory_forecast(request, stream=None):
    """Predictive inventory forecasting dashboard."""
    stream_obj = get_stream_or_404(stream)
    past_forecasts = InventoryForecast.objects.filter(stream=stream_obj).order_by("-generated_at")[:10]
    context = {
        "stream": stream,
        "stream_obj": stream_obj,
        "past_forecasts": past_forecasts,
    }
    return render(request, "products/ai_inventory_forecast.html", context)


@user_passes_test(is_super_admin)
@login_required
@require_POST
def ai_inventory_forecast_generate(request, stream=None):
    """Generate a new inventory forecast."""
    stream_obj = get_stream_or_404(stream)

    days = int(request.POST.get("forecast_days", 90))
    days = min(max(days, 7), 365)  # Clamp 7-365

    from products.ai.inventory_forecast import InventoryForecastEngine

    engine = InventoryForecastEngine()
    result = engine.forecast(stream=stream_obj, days_ahead=days)

    forecast = InventoryForecast.objects.create(
        stream=stream_obj,
        generated_by=request.user,
        forecast_days=days,
        forecast_method=result.get("method", ""),
        forecast_data=result,
        current_count=result.get("current_count", 0),
        predicted_end_count=(
            result.get("forecast", {}).get("values", [0])[-1] if result.get("forecast", {}).get("values") else 0
        ),
        trend_direction=result.get("trend", {}).get("direction", ""),
        trend_change_rate=result.get("trend", {}).get("change_rate", 0),
        threshold_warnings_count=len(result.get("threshold_warnings", [])),
        summary=result.get("summary", ""),
    )

    AuditLog.log(
        "create",
        f"Generated inventory forecast for {stream_obj.name}",
        user=request.user,
        request=request,
        obj=forecast,
        module="ai",
        stream=stream_obj,
    )

    return redirect("ai_inventory_forecast_view", stream=stream, pk=forecast.pk)


@user_passes_test(is_super_admin)
@login_required
def ai_inventory_forecast_view(request, stream=None, pk=None):
    """View a generated forecast."""
    stream_obj = get_stream_or_404(stream)
    forecast = get_object_or_404(InventoryForecast, pk=pk, stream=stream_obj)
    context = {
        "stream": stream,
        "stream_obj": stream_obj,
        "forecast": forecast,
        "forecast_data": forecast.forecast_data,
    }
    return render(request, "products/ai_inventory_forecast_view.html", context)


# =============================================================================
# AI FEATURE 5: SMART RESERVATION SCHEDULING
# =============================================================================


@user_passes_test(is_super_admin)
@login_required
def ai_smart_scheduler(request, stream=None):
    """Smart reservation scheduling page."""
    stream_obj = get_stream_or_404(stream)
    systems = System.objects.filter(stream=stream_obj, status="Active").order_by("name")
    past_recs = SchedulerRecommendation.objects.filter(stream=stream_obj, user=request.user).order_by("-requested_at")[
        :10
    ]

    from products.ai.smart_scheduler import SmartSchedulerEngine

    engine = SmartSchedulerEngine(stream=stream_obj)
    user_insights = engine.get_user_insights(request.user)

    context = {
        "stream": stream,
        "stream_obj": stream_obj,
        "systems": systems,
        "past_recommendations": past_recs,
        "user_insights": user_insights,
    }
    return render(request, "products/ai_smart_scheduler.html", context)


@user_passes_test(is_super_admin)
@login_required
@require_POST
def ai_smart_scheduler_recommend(request, stream=None):
    """API: Get smart slot recommendations."""
    stream_obj = get_stream_or_404(stream)
    try:
        body = json.loads(request.body)
        system_id = body.get("system_id")
        desired_date = body.get("desired_date")
        duration = int(body.get("duration_hours", 2))

        system = None
        if system_id:
            system = System.objects.filter(pk=system_id, stream=stream_obj).first()

        from products.ai.smart_scheduler import SmartSchedulerEngine

        engine = SmartSchedulerEngine(stream=stream_obj)
        result = engine.recommend_slots(
            system=system,
            user=request.user,
            desired_date=desired_date,
            duration_hours=duration,
            num_suggestions=6,
        )

        if result.get("success"):
            SchedulerRecommendation.objects.create(
                user=request.user,
                stream=stream_obj,
                system=system,
                desired_date=datetime.strptime(desired_date, "%Y-%m-%d").date() if desired_date else None,
                desired_duration_hours=duration,
                recommendations_data=result,
            )

        return JsonResponse(result)
    except Exception:
        logger.exception("Operation failed")
        logger.error("Smart scheduler error")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"})


# =============================================================================
# AI: MODEL TRAINING & MANAGEMENT
# =============================================================================


@user_passes_test(is_super_admin)
@login_required
def ai_model_management(request, stream=None):
    """AI model management page — train/retrain models."""
    stream_obj = get_stream_or_404(stream)
    training_logs = AIModelTrainingLog.objects.order_by("-trained_at")[:20]

    models_dir = os.path.join(settings.BASE_DIR, "ai_models")
    model_status = {
        "doc_classifier": os.path.exists(os.path.join(models_dir, "doc_classifier.joblib")),
        "nl_query": os.path.exists(os.path.join(models_dir, "nl_query_classifier.joblib")),
    }

    context = {
        "stream": stream,
        "stream_obj": stream_obj,
        "training_logs": training_logs,
        "model_status": model_status,
    }
    return render(request, "products/ai_model_management.html", context)


@user_passes_test(is_super_admin)
@login_required
@require_POST
def ai_train_model_api(request, stream=None):  # pylint: disable=unused-argument
    """API: Trigger model training."""
    try:
        body = json.loads(request.body)
        model_type = body.get("model_type", "")

        if model_type == "doc_classifier":
            from products.ai.document_ocr import DocumentOCREngine

            result = DocumentOCREngine.train_classifier()
        elif model_type == "nl_query":
            from products.ai.nl_query import NLQueryEngine

            result = NLQueryEngine.train_classifier()
        else:
            return JsonResponse({"success": False, "error": f"Unknown model type: {model_type}"})

        AIModelTrainingLog.objects.create(
            model_type=model_type,
            trained_by=request.user,
            training_samples=result.get("samples", 0),
            training_result=result,
            was_successful=result.get("success", False),
            error_message=result.get("error", ""),
            model_file_path=os.path.join("ai_models", f"{model_type}.joblib"),
        )

        AuditLog.log("update", f"Trained AI model: {model_type}", user=request.user, request=request, module="ai")

        return JsonResponse(result)
    except Exception:
        logger.exception("Operation failed")
        logger.error("Model training error")
        return JsonResponse({"success": False, "error": "An unexpected error occurred"})


# =============================================================================
# FEATURE ACCESS CONTROL — App-Admin-only UI for role-based feature gating
# =============================================================================


@user_passes_test(is_super_admin)
@login_required
def ai_usage_analytics(request, stream=None):
    """AI Usage Pattern Analytics dashboard."""
    stream_obj = get_stream_or_404(stream)
    past_reports = UsageAnalyticsReport.objects.filter(stream=stream_obj).order_by("-generated_at")[:10]
    context = {
        "stream": stream,
        "stream_obj": stream_obj,
        "past_reports": past_reports,
    }
    return render(request, "products/ai_usage_analytics.html", context)


@user_passes_test(is_super_admin)
@login_required
@require_POST
def ai_usage_analytics_generate(request, stream=None):
    """API: Generate a usage analytics report."""
    stream_obj = get_stream_or_404(stream)
    try:
        body = json.loads(request.body)
        days_back = int(body.get("days_back", 90))
    except (ValueError, KeyError):
        days_back = 90

    from products.ai.usage_analytics import UsageAnalyticsEngine

    engine = UsageAnalyticsEngine(stream=stream_obj, days_back=days_back)
    result = engine.full_analysis()

    if result.get("success"):
        peak = result.get("peak_hours", {})
        util = result.get("system_utilization", {})
        booking = result.get("booking_patterns", {})
        recs = result.get("recommendations", [])

        report = UsageAnalyticsReport.objects.create(
            stream=stream_obj,
            generated_by=request.user,
            analysis_period_days=days_back,
            report_data=result,
            peak_hour=peak.get("peak_hour", ""),
            avg_utilization=util.get("avg_utilization", 0),
            underutilized_count=util.get("underutilized_count", 0),
            overutilized_count=util.get("overutilized_count", 0),
            total_bookings=booking.get("total_bookings", 0),
            conflict_rate=booking.get("conflict_rate", 0),
            recommendation_count=len(recs),
        )
        AuditLog.log(
            "create",
            f"Generated AI usage analytics report (ID {report.pk})",
            user=request.user,
            request=request,
            obj=report,
            module="ai",
            stream=stream_obj,
        )
        result["report_id"] = report.pk

    return JsonResponse(result)


@user_passes_test(is_super_admin)
@login_required
def ai_usage_analytics_view(request, stream=None, pk=None):
    """View a previously generated usage analytics report."""
    stream_obj = get_stream_or_404(stream)
    report = get_object_or_404(UsageAnalyticsReport, pk=pk, stream=stream_obj)
    context = {
        "stream": stream,
        "stream_obj": stream_obj,
        "report": report,
        "data_json": json.dumps(report.report_data, default=str),
    }
    return render(request, "products/ai_usage_analytics_view.html", context)


# ═══════════════════════════════════════════════════════════════════════════
# AI DUPLICATE / ANOMALY DETECTION
# ═══════════════════════════════════════════════════════════════════════════


@user_passes_test(is_super_admin)
@login_required
def ai_anomaly_detection(request, stream=None):
    """AI Anomaly Detection dashboard."""
    stream_obj = get_stream_or_404(stream)
    past_scans = AnomalyDetectionReport.objects.filter(stream=stream_obj).order_by("-scanned_at")[:10]
    context = {
        "stream": stream,
        "stream_obj": stream_obj,
        "past_scans": past_scans,
    }
    return render(request, "products/ai_anomaly_detection.html", context)


@user_passes_test(is_super_admin)
@login_required
@require_POST
def ai_anomaly_detection_scan(request, stream=None):
    """API: Run an anomaly detection scan."""
    stream_obj = get_stream_or_404(stream)
    try:
        body = json.loads(request.body)
        days_back = int(body.get("days_back", 90))
    except (ValueError, KeyError):
        days_back = 90

    from products.ai.anomaly_detection import AnomalyDetectionEngine

    engine = AnomalyDetectionEngine(stream=stream_obj, days_back=days_back)
    result = engine.full_scan()

    if result.get("success"):
        risk = result.get("risk_score", {})
        dupes = result.get("duplicate_products", {})
        serials = result.get("serial_anomalies", {})
        inv = result.get("inventory_anomalies", {})
        dq = result.get("data_quality", {})

        report = AnomalyDetectionReport.objects.create(
            stream=stream_obj,
            scanned_by=request.user,
            scan_type="full",
            scan_period_days=days_back,
            report_data=result,
            risk_score=risk.get("overall", 100),
            risk_grade=risk.get("grade", ""),
            duplicate_groups=dupes.get("total_duplicate_groups", 0),
            serial_issues=serials.get("total_issues", 0),
            inventory_anomalies_count=inv.get("total_anomalies", 0),
            data_quality_score=dq.get("score", 100),
        )
        AuditLog.log(
            "create",
            f'Ran AI anomaly detection scan (ID {report.pk}, Grade: {risk.get("grade", "?")})',
            user=request.user,
            request=request,
            obj=report,
            module="ai",
            stream=stream_obj,
        )
        result["report_id"] = report.pk

    return JsonResponse(result)


@user_passes_test(is_super_admin)
@login_required
def ai_anomaly_detection_view(request, stream=None, pk=None):
    """View a previously generated anomaly detection report."""
    stream_obj = get_stream_or_404(stream)
    report = get_object_or_404(AnomalyDetectionReport, pk=pk, stream=stream_obj)
    context = {
        "stream": stream,
        "stream_obj": stream_obj,
        "report": report,
        "data_json": json.dumps(report.report_data, default=str),
        "risk_degrees": round(report.risk_score * 3.6, 1),
    }
    return render(request, "products/ai_anomaly_detection_view.html", context)


# =============================================================================
# TLD BADGE MANAGEMENT
# =============================================================================
