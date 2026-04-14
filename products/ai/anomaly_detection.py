"""
AI Duplicate & Anomaly Detection Engine for NexusOps.

Detects duplicate assets, suspicious data entries, anomalous inventory
movements, and acts as a data-quality guardian.
"""

# pylint: disable=broad-exception-caught,import-outside-toplevel,invalid-name,too-many-lines,too-many-locals,too-many-positional-arguments
import logging
import re
from datetime import timedelta
from difflib import SequenceMatcher

from django.db.models import Count, Q
from django.db.models.functions import ExtractHour
from django.utils import timezone

logger = logging.getLogger(__name__)


class AnomalyDetectionEngine:
    """Scans assets, products, and audit logs for duplicates and anomalies."""

    SIMILARITY_THRESHOLD = 0.82  # Jaro-like threshold for "likely duplicate"

    def __init__(self, stream=None, days_back=90):
        self.stream = stream
        self.days_back = days_back
        self.cutoff = timezone.now() - timedelta(days=days_back)

    # ── public entry point ───────────────────────────────────────────────
    def full_scan(self):
        """Run all detection passes and return a unified report."""
        try:
            duplicates = self._detect_duplicate_products()
            serial_anomalies = self._detect_serial_number_anomalies()
            inventory_anomalies = self._detect_inventory_anomalies()
            audit_anomalies = self._detect_audit_log_anomalies()
            data_quality = self._check_data_quality()
            risk_score = self._compute_risk_score(
                duplicates, serial_anomalies, inventory_anomalies, audit_anomalies, data_quality
            )

            return {
                "success": True,
                "duplicate_products": duplicates,
                "serial_anomalies": serial_anomalies,
                "inventory_anomalies": inventory_anomalies,
                "audit_anomalies": audit_anomalies,
                "data_quality": data_quality,
                "risk_score": risk_score,
                "scan_period_days": self.days_back,
                "scanned_at": timezone.now().isoformat(),
            }
        except Exception:
            logger.exception("Anomaly detection scan failed")
            return {"success": False, "error": "An error occurred"}

    # ── duplicate detection ──────────────────────────────────────────────
    def _detect_duplicate_products(self):
        """Identify likely duplicate products by name + serial + 12NC similarity."""
        from products.models import Product

        qs = (
            Product.objects.filter(stream=self.stream)
            .values("id", "name", "serial_number", "twelve_nc", "status")
            .order_by("name")
        )
        items = list(qs)

        groups = []
        seen = set()

        for i, a in enumerate(items):
            if a["id"] in seen:
                continue
            cluster = [a]
            for j in range(i + 1, len(items)):
                b = items[j]
                if b["id"] in seen:
                    continue
                sim = self._product_similarity(a, b)
                if sim >= self.SIMILARITY_THRESHOLD:
                    cluster.append({**b, "similarity": round(sim * 100, 1)})
                    seen.add(b["id"])
            if len(cluster) > 1:
                seen.add(a["id"])
                groups.append(
                    {
                        "anchor": {
                            "id": a["id"],
                            "name": a["name"] or "",
                            "serial_number": a["serial_number"] or "",
                            "twelve_nc": a["twelve_nc"] or "",
                            "status": a["status"] or "",
                        },
                        "matches": [
                            {
                                "id": m["id"],
                                "name": m["name"] or "",
                                "serial_number": m["serial_number"] or "",
                                "twelve_nc": m["twelve_nc"] or "",
                                "status": m["status"] or "",
                                "similarity": m.get("similarity", 100),
                            }
                            for m in cluster[1:]
                        ],
                        "count": len(cluster),
                    }
                )

        return {
            "groups": groups[:20],  # cap at 20 groups
            "total_duplicate_groups": len(groups),
            "total_duplicates_found": sum(g["count"] for g in groups),
        }

    def _product_similarity(self, a, b):
        """Compute weighted similarity score between two products."""
        scores = []
        weights = []

        # Name similarity (weight 0.4)
        name_a = (a.get("name") or "").strip().lower()
        name_b = (b.get("name") or "").strip().lower()
        if name_a and name_b:
            scores.append(SequenceMatcher(None, name_a, name_b).ratio())
            weights.append(0.4)

        # Serial number exact match (weight 0.35)
        sn_a = (a.get("serial_number") or "").strip().upper()
        sn_b = (b.get("serial_number") or "").strip().upper()
        if sn_a and sn_b:
            scores.append(1.0 if sn_a == sn_b else SequenceMatcher(None, sn_a, sn_b).ratio())
            weights.append(0.35)

        # 12NC exact match (weight 0.25)
        nc_a = (a.get("twelve_nc") or "").strip()
        nc_b = (b.get("twelve_nc") or "").strip()
        if nc_a and nc_b:
            scores.append(1.0 if nc_a == nc_b else SequenceMatcher(None, nc_a, nc_b).ratio())
            weights.append(0.25)

        if not weights:
            return 0.0
        return sum(s * w for s, w in zip(scores, weights)) / sum(weights)

    # ── serial number anomalies ──────────────────────────────────────────
    def _detect_serial_number_anomalies(self):
        """Find products with suspicious or missing serial numbers."""
        from products.models import Product

        products = Product.objects.filter(stream=self.stream)
        issues = []

        # Missing serial numbers
        missing_sn = products.filter(Q(serial_number__isnull=True) | Q(serial_number="")).values("id", "name", "status")
        for p in missing_sn[:20]:
            issues.append(
                {
                    "product_id": p["id"],
                    "product_name": p["name"] or "(unnamed)",
                    "issue_type": "missing_serial",
                    "severity": "warning",
                    "detail": "Product has no serial number assigned.",
                }
            )

        # Duplicate serial numbers
        dup_sns = (
            products.exclude(serial_number__isnull=True)
            .exclude(serial_number="")
            .values("serial_number")
            .annotate(count=Count("id"))
            .filter(count__gt=1)
        )
        for d in dup_sns[:10]:
            prods = products.filter(serial_number=d["serial_number"]).values("id", "name")
            issues.append(
                {
                    "serial_number": d["serial_number"],
                    "issue_type": "duplicate_serial",
                    "severity": "critical",
                    "count": d["count"],
                    "products": list(prods),
                    "detail": f"Serial number '{d['serial_number']}' is shared by {d['count']} products.",
                }
            )

        # Suspicious patterns (e.g., all zeros, test values)
        suspicious_patterns = [
            r"^0+$",  # all zeros
            r"^test",  # test values
            r"^xxx",  # placeholder
            r"^n/?a$",  # N/A
            r"^tbd$",  # TBD
            r"^dummy",  # dummy
            r"^sample",  # sample
            r"^1234",  # sequential test
        ]
        for p in (
            products.exclude(serial_number__isnull=True).exclude(serial_number="").values("id", "name", "serial_number")
        ):
            sn = (p["serial_number"] or "").strip().lower()
            for pat in suspicious_patterns:
                if re.match(pat, sn):
                    issues.append(
                        {
                            "product_id": p["id"],
                            "product_name": p["name"] or "(unnamed)",
                            "serial_number": p["serial_number"],
                            "issue_type": "suspicious_serial",
                            "severity": "warning",
                            "detail": f"Serial number '{p['serial_number']}' looks like a placeholder.",
                        }
                    )
                    break

        return {
            "issues": issues[:30],
            "total_issues": len(issues),
            "critical_count": sum(1 for i in issues if i["severity"] == "critical"),
            "warning_count": sum(1 for i in issues if i["severity"] == "warning"),
        }

    # ── inventory anomalies ──────────────────────────────────────────────
    def _detect_inventory_anomalies(self):
        """Detect unusual inventory movements and patterns."""
        from products.models import AuditLog, Product, ProductHistory

        anomalies = []

        # 1. Rapid status changes (same product changed status 3+ times in 7 days)
        week_ago = timezone.now() - timedelta(days=7)
        rapid_changes = (
            ProductHistory.objects.filter(
                product__stream=self.stream,
                timestamp__gte=week_ago,
            )
            .values("product__id", "product__name")
            .annotate(change_count=Count("id"))
            .filter(change_count__gte=3)
        )
        for rc in rapid_changes[:10]:
            anomalies.append(
                {
                    "product_id": rc["product__id"],
                    "product_name": rc["product__name"] or "(unnamed)",
                    "anomaly_type": "rapid_status_change",
                    "severity": "warning",
                    "detail": f"Product changed {rc['change_count']} times in the last 7 days. "
                    f"May indicate data entry errors or unresolved issues.",
                }
            )

        # 2. Products stuck in transitional states for too long
        stale_threshold = timezone.now() - timedelta(days=30)
        transitional_statuses = ["In Repair", "Pending", "Under Review", "In Transit"]
        stale_products = Product.objects.filter(
            stream=self.stream,
            status__in=transitional_statuses,
            updated_at__lt=stale_threshold,
        ).values("id", "name", "status", "updated_at")

        for p in stale_products[:10]:
            days_stale = (timezone.now() - p["updated_at"]).days if p["updated_at"] else 0
            anomalies.append(
                {
                    "product_id": p["id"],
                    "product_name": p["name"] or "(unnamed)",
                    "anomaly_type": "stale_transitional",
                    "severity": "warning",
                    "detail": f"Product has been in '{p['status']}' for {days_stale} days without update.",
                }
            )

        # 3. Bulk operations anomaly (many deletions in a short window)
        bulk_deletes = (
            AuditLog.objects.filter(
                module="products",
                action="delete",
                timestamp__gte=week_ago,
                stream=self.stream,
            )
            .values("user__username")
            .annotate(count=Count("id"))
            .filter(count__gte=5)
        )
        for bd in bulk_deletes[:5]:
            anomalies.append(
                {
                    "username": bd["user__username"],
                    "anomaly_type": "bulk_deletion",
                    "severity": "critical",
                    "detail": f"User '{bd['user__username']}' deleted {bd['count']} products in the last 7 days.",
                }
            )

        # 4. Categories with zero products (potential cleanup needed)
        from products.models import Category

        empty_cats = (
            Category.objects.filter(
                stream=self.stream,
            )
            .annotate(product_count=Count("products"))
            .filter(product_count=0)
        )

        if empty_cats.exists():
            anomalies.append(
                {
                    "anomaly_type": "empty_categories",
                    "severity": "info",
                    "count": empty_cats.count(),
                    "names": list(empty_cats.values_list("name", flat=True)[:5]),
                    "detail": f"{empty_cats.count()} categories have zero products. Consider cleaning up.",
                }
            )

        return {
            "anomalies": anomalies[:25],
            "total_anomalies": len(anomalies),
            "critical_count": sum(1 for a in anomalies if a["severity"] == "critical"),
            "warning_count": sum(1 for a in anomalies if a["severity"] == "warning"),
            "info_count": sum(1 for a in anomalies if a["severity"] == "info"),
        }

    # ── audit log anomalies ──────────────────────────────────────────────
    def _detect_audit_log_anomalies(self):
        """Detect suspicious patterns in the audit log."""
        from products.models import AuditLog

        anomalies = []

        # 1. Unusual hours activity (outside 6:00 - 22:00)
        off_hours = (
            AuditLog.objects.filter(
                stream=self.stream,
                timestamp__gte=self.cutoff,
            )
            .annotate(hour=ExtractHour("timestamp"))
            .filter(Q(hour__lt=6) | Q(hour__gte=22))
            .values("user__username")
            .annotate(count=Count("id"))
            .filter(count__gte=3)
        )

        for oh in off_hours[:5]:
            anomalies.append(
                {
                    "anomaly_type": "off_hours_activity",
                    "severity": "info",
                    "username": oh["user__username"],
                    "count": oh["count"],
                    "detail": f"User '{oh['user__username']}' performed {oh['count']} actions outside normal hours (22:00–06:00).",
                }
            )

        # 2. High-frequency operations by single user
        high_freq = (
            AuditLog.objects.filter(
                stream=self.stream,
                timestamp__gte=timezone.now() - timedelta(days=1),
            )
            .values("user__username")
            .annotate(count=Count("id"))
            .filter(count__gte=50)
        )
        for hf in high_freq[:5]:
            anomalies.append(
                {
                    "anomaly_type": "high_frequency",
                    "severity": "warning",
                    "username": hf["user__username"],
                    "count": hf["count"],
                    "detail": f"User '{hf['user__username']}' performed {hf['count']} actions in the last 24 hours.",
                }
            )

        # 3. Failed/error operations spike
        errors = AuditLog.objects.filter(
            stream=self.stream,
            timestamp__gte=timezone.now() - timedelta(days=7),
            severity="critical",
        ).count()
        if errors > 10:
            anomalies.append(
                {
                    "anomaly_type": "error_spike",
                    "severity": "critical",
                    "count": errors,
                    "detail": f"{errors} critical-severity audit events in the last 7 days.",
                }
            )

        return {
            "anomalies": anomalies[:15],
            "total_anomalies": len(anomalies),
        }

    # ── data quality ─────────────────────────────────────────────────────
    def _check_data_quality(self):
        """Run data quality checks across the stream's data."""
        from products.models import CalibrationSchedule, Product, System

        checks = []
        score = 100  # Start at 100, deduct for issues

        # Products with missing names
        unnamed = Product.objects.filter(stream=self.stream).filter(Q(name__isnull=True) | Q(name="")).count()
        if unnamed > 0:
            score -= min(15, unnamed * 3)
            checks.append(
                {
                    "check": "product_names",
                    "status": "fail",
                    "count": unnamed,
                    "detail": f"{unnamed} products have no name.",
                }
            )
        else:
            checks.append({"check": "product_names", "status": "pass", "detail": "All products have names."})

        # Products with missing location
        no_location = Product.objects.filter(
            stream=self.stream,
            location__isnull=True,
        ).count()
        total_products = Product.objects.filter(stream=self.stream).count()
        if no_location > 0 and total_products > 0:
            pct = round(no_location / total_products * 100, 1)
            score -= min(10, int(pct / 5))
            checks.append(
                {
                    "check": "product_locations",
                    "status": "warning" if pct < 30 else "fail",
                    "count": no_location,
                    "detail": f"{no_location} products ({pct}%) have no location assigned.",
                }
            )
        else:
            checks.append({"check": "product_locations", "status": "pass", "detail": "All products have locations."})

        # Systems with missing status
        systems_no_status = (
            System.objects.filter(stream=self.stream).filter(Q(status__isnull=True) | Q(status="")).count()
        )
        if systems_no_status > 0:
            score -= min(10, systems_no_status * 5)
            checks.append(
                {
                    "check": "system_status",
                    "status": "fail",
                    "count": systems_no_status,
                    "detail": f"{systems_no_status} systems have no status.",
                }
            )
        else:
            checks.append({"check": "system_status", "status": "pass", "detail": "All systems have a status."})

        # Overdue calibrations
        overdue = CalibrationSchedule.objects.filter(
            stream=self.stream,
            next_calibration_date__lt=timezone.now().date(),
            status="active",
        ).count()
        if overdue > 0:
            score -= min(20, overdue * 5)
            checks.append(
                {
                    "check": "calibration_overdue",
                    "status": "fail",
                    "count": overdue,
                    "detail": f"{overdue} calibration schedules are overdue.",
                }
            )
        else:
            checks.append({"check": "calibration_overdue", "status": "pass", "detail": "No overdue calibrations."})

        # Expired compliance documents
        from products.models import ComplianceDocument

        expired_docs = ComplianceDocument.objects.filter(
            stream=self.stream,
            expiry_date__lt=timezone.now().date(),
            status="active",
        ).count()
        if expired_docs > 0:
            score -= min(15, expired_docs * 5)
            checks.append(
                {
                    "check": "compliance_expired",
                    "status": "fail",
                    "count": expired_docs,
                    "detail": f"{expired_docs} compliance documents are expired.",
                }
            )
        else:
            checks.append(
                {"check": "compliance_expired", "status": "pass", "detail": "No expired compliance documents."}
            )

        return {
            "checks": checks,
            "score": max(0, score),
            "total_checks": len(checks),
            "passed": sum(1 for c in checks if c["status"] == "pass"),
            "failed": sum(1 for c in checks if c["status"] == "fail"),
            "warnings": sum(1 for c in checks if c["status"] == "warning"),
        }

    # ── risk score ───────────────────────────────────────────────────────
    def _compute_risk_score(self, duplicates, serial_anomalies, inventory_anomalies, audit_anomalies, data_quality):
        """Compute an overall data-health risk score (0=terrible, 100=perfect)."""
        score = 100

        # Deduct for duplicates
        dup_count = duplicates.get("total_duplicate_groups", 0)
        score -= min(20, dup_count * 5)

        # Deduct for serial anomalies
        score -= min(15, serial_anomalies.get("critical_count", 0) * 5)
        score -= min(10, serial_anomalies.get("warning_count", 0) * 2)

        # Deduct for inventory anomalies
        score -= min(15, inventory_anomalies.get("critical_count", 0) * 5)
        score -= min(10, inventory_anomalies.get("warning_count", 0) * 2)

        # Deduct for audit anomalies
        score -= min(10, audit_anomalies.get("total_anomalies", 0) * 3)

        # Factor in data quality
        dq_score = data_quality.get("score", 100)
        score = int((score * 0.6) + (dq_score * 0.4))

        return {
            "overall": max(0, min(100, score)),
            "grade": (
                "A"
                if score >= 90
                else ("B" if score >= 75 else ("C" if score >= 60 else ("D" if score >= 40 else "F")))
            ),
            "label": (
                "Excellent"
                if score >= 90
                else ("Good" if score >= 75 else ("Fair" if score >= 60 else ("Poor" if score >= 40 else "Critical")))
            ),
        }
