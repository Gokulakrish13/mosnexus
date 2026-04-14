"""Products app — Demo Request & Vulnerability Report views."""

import json
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_not_required, login_required, user_passes_test

from ..models import DemoRequest, VulnerabilityReport
from ._helpers import is_app_admin

logger = logging.getLogger(__name__)

__all__ = [
    "submit_demo_request",
    "submit_vulnerability_report",
    "public_requests_list",
    "demo_request_update_status",
    "vulnerability_report_update_status",
    "send_public_request_email",
]


@login_not_required
@csrf_exempt
@require_POST
def submit_demo_request(request):
    """Public endpoint — accepts demo request from the home page (no auth)."""
    try:
        data = json.loads(request.body)
        full_name = (data.get("full_name") or "").strip()
        email = (data.get("email") or "").strip()
        organization = (data.get("organization") or "").strip()
        preferred_date = (data.get("preferred_date") or "").strip()

        if not all([full_name, email, organization, preferred_date]):
            return JsonResponse({"ok": False, "error": "All fields are required."}, status=400)

        DemoRequest.objects.create(
            full_name=full_name,
            email=email,
            organization=organization,
            preferred_date=preferred_date,
        )
        return JsonResponse({"ok": True, "message": "Demo request submitted successfully."})
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid request body."}, status=400)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@login_not_required
@csrf_exempt
@require_POST
def submit_vulnerability_report(request):
    """Public endpoint — accepts vulnerability report from the home page (no auth)."""
    try:
        data = json.loads(request.body)
        reporter_name = (data.get("reporter_name") or "").strip()
        reporter_email = (data.get("reporter_email") or "").strip()
        severity = (data.get("severity") or "medium").strip()
        description = (data.get("description") or "").strip()

        if not all([reporter_name, reporter_email, description]):
            return JsonResponse({"ok": False, "error": "Name, email and description are required."}, status=400)

        valid_severities = [s[0] for s in VulnerabilityReport.SEVERITY_CHOICES]
        if severity not in valid_severities:
            severity = "medium"

        VulnerabilityReport.objects.create(
            reporter_name=reporter_name,
            reporter_email=reporter_email,
            severity=severity,
            description=description,
        )
        return JsonResponse({"ok": True, "message": "Vulnerability report submitted successfully."})
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid request body."}, status=400)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@login_required
@user_passes_test(is_app_admin)
def public_requests_list(request):
    """Admin-only page listing demo requests + vulnerability reports (tabbed)."""
    # Active tab
    tab = request.GET.get("tab", "demo")

    # Demo requests
    demo_qs = DemoRequest.objects.all()
    demo_status = request.GET.get("demo_status", "")
    demo_q = request.GET.get("demo_q", "").strip()
    if demo_status:
        demo_qs = demo_qs.filter(status=demo_status)
    if demo_q:
        from django.db.models import Q
        demo_qs = demo_qs.filter(
            Q(full_name__icontains=demo_q) |
            Q(email__icontains=demo_q) |
            Q(organization__icontains=demo_q)
        )

    # Vulnerability reports
    vuln_qs = VulnerabilityReport.objects.all()
    vuln_status = request.GET.get("vuln_status", "")
    vuln_severity = request.GET.get("vuln_severity", "")
    vuln_q = request.GET.get("vuln_q", "").strip()
    if vuln_status:
        vuln_qs = vuln_qs.filter(status=vuln_status)
    if vuln_severity:
        vuln_qs = vuln_qs.filter(severity=vuln_severity)
    if vuln_q:
        from django.db.models import Q
        vuln_qs = vuln_qs.filter(
            Q(reporter_name__icontains=vuln_q) |
            Q(reporter_email__icontains=vuln_q) |
            Q(description__icontains=vuln_q)
        )

    # Check if SMTP email is configured (has password set)
    from django.conf import settings as _s
    _backend = getattr(_s, 'EMAIL_BACKEND', '')
    _is_console = 'console' in _backend
    _has_password = bool(getattr(_s, 'EMAIL_HOST_PASSWORD', ''))
    email_configured = _has_password and not _is_console

    return render(request, "products/demo_requests.html", {
        "active_tab": tab,
        "email_configured": email_configured,
        # Demo
        "demo_requests": demo_qs,
        "demo_status_choices": DemoRequest.STATUS_CHOICES,
        "current_demo_status": demo_status,
        "demo_search_q": demo_q,
        # Vulnerability
        "vuln_reports": vuln_qs,
        "vuln_status_choices": VulnerabilityReport.STATUS_CHOICES,
        "vuln_severity_choices": VulnerabilityReport.SEVERITY_CHOICES,
        "current_vuln_status": vuln_status,
        "current_vuln_severity": vuln_severity,
        "vuln_search_q": vuln_q,
    })


@login_required
@user_passes_test(is_app_admin)
@require_POST
def demo_request_update_status(request, pk):
    """Admin-only: update demo request status and notes."""
    try:
        demo_req = DemoRequest.objects.get(pk=pk)
        data = json.loads(request.body)
        new_status = data.get("status", "").strip()
        notes = data.get("admin_notes", "").strip()

        valid_statuses = [s[0] for s in DemoRequest.STATUS_CHOICES]
        if new_status and new_status in valid_statuses:
            demo_req.status = new_status
        if notes is not None:
            demo_req.admin_notes = notes

        demo_req.reviewed_by = request.user
        demo_req.save()
        return JsonResponse({"ok": True, "status": demo_req.get_status_display()})
    except DemoRequest.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Request not found."}, status=404)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@login_required
@user_passes_test(is_app_admin)
@require_POST
def vulnerability_report_update_status(request, pk):
    """Admin-only: update vulnerability report status and notes."""
    try:
        report = VulnerabilityReport.objects.get(pk=pk)
        data = json.loads(request.body)
        new_status = data.get("status", "").strip()
        notes = data.get("admin_notes", "").strip()

        valid_statuses = [s[0] for s in VulnerabilityReport.STATUS_CHOICES]
        if new_status and new_status in valid_statuses:
            report.status = new_status
        if notes is not None:
            report.admin_notes = notes

        report.reviewed_by = request.user
        report.save()
        return JsonResponse({"ok": True, "status": report.get_status_display()})
    except VulnerabilityReport.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Report not found."}, status=404)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)


@login_required
@user_passes_test(is_app_admin)
@require_POST
def send_public_request_email(request):
    """Admin-only: send an email to a demo or vulnerability requester."""
    try:
        data = json.loads(request.body)
        req_type = data.get("type", "")        # 'demo' or 'vuln'
        pk = data.get("pk")
        subject = (data.get("subject") or "").strip()
        body = (data.get("body") or "").strip()

        if not all([req_type, pk, subject, body]):
            return JsonResponse({"ok": False, "error": "Subject and body are required."}, status=400)

        # Resolve recipient email
        if req_type == "demo":
            obj = DemoRequest.objects.get(pk=pk)
            recipient = obj.email
            recipient_name = obj.full_name
        elif req_type == "vuln":
            obj = VulnerabilityReport.objects.get(pk=pk)
            recipient = obj.reporter_email
            recipient_name = obj.reporter_name
        else:
            return JsonResponse({"ok": False, "error": "Invalid request type."}, status=400)

        from_email = settings.DEFAULT_FROM_EMAIL
        send_mail(
            subject=subject,
            message=body,
            from_email=from_email,
            recipient_list=[recipient],
            fail_silently=False,
        )

        logger.info(
            "Email sent to %s (%s) by %s — subject: %s",
            recipient_name, recipient, request.user.username, subject,
        )
        return JsonResponse({"ok": True, "message": f"Email sent to {recipient}"})
    except (DemoRequest.DoesNotExist, VulnerabilityReport.DoesNotExist):
        return JsonResponse({"ok": False, "error": "Request not found."}, status=404)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.exception("Failed to send email: %s", exc)
        return JsonResponse({"ok": False, "error": f"Failed to send email: {exc}"}, status=500)
