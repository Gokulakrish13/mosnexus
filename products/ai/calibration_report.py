"""
AI Engine 1: Auto-Generate Calibration Reports
================================================
Pulls CalibrationRecord data, performs statistical analysis,
detects anomalies via Z-score, identifies drift trends, and
generates a structured professional report (HTML + PDF).
"""

# pylint: disable=invalid-name,too-complex,too-many-branches,too-many-locals
import logging
import statistics
from collections import defaultdict

from django.utils import timezone

logger = logging.getLogger(__name__)


class CalibrationReportEngine:
    """Generates AI-powered calibration reports with statistical analysis."""

    def __init__(self, schedule):
        """
        Args:
            schedule: CalibrationSchedule instance
        """
        self.schedule = schedule
        self.records = list(
            schedule.records.order_by("calibration_date").select_related("performed_by_user", "calibration_schedule")
        )

    # ------------------------------------------------------------------
    # Data extraction
    # ------------------------------------------------------------------
    def _extract_measurements(self):
        """Extract all numeric measurement values from records."""
        measurements = []
        for rec in self.records:
            if rec.measurement_data:
                data = rec.measurement_data if isinstance(rec.measurement_data, dict) else {}
                for key, val in data.items():
                    try:
                        measurements.append(
                            {
                                "record_id": rec.pk,
                                "date": rec.calibration_date,
                                "parameter": key,
                                "value": float(val),
                                "result": rec.result,
                            }
                        )
                    except (ValueError, TypeError):
                        continue
            # Also parse before/after values
            for label, field_val in [("before", rec.before_values), ("after", rec.after_values)]:
                if field_val:
                    try:
                        vals = [float(v.strip()) for v in str(field_val).split(",") if v.strip()]
                        for i, v in enumerate(vals):
                            measurements.append(
                                {
                                    "record_id": rec.pk,
                                    "date": rec.calibration_date,
                                    "parameter": f"{label}_value_{i+1}",
                                    "value": v,
                                    "result": rec.result,
                                }
                            )
                    except (ValueError, TypeError):
                        continue
        return measurements

    # ------------------------------------------------------------------
    # Statistical analysis
    # ------------------------------------------------------------------
    def compute_statistics(self):
        """Compute comprehensive statistics across all records."""
        measurements = self._extract_measurements()
        total_records = len(self.records)
        if total_records == 0:
            return self._empty_stats()

        # Result distribution
        result_counts = defaultdict(int)
        for rec in self.records:
            result_counts[rec.result] += 1

        pass_rate = (
            ((result_counts.get("pass", 0) + result_counts.get("pass_adjusted", 0)) / total_records * 100)
            if total_records
            else 0
        )

        fail_rate = result_counts.get("fail", 0) / total_records * 100 if total_records else 0

        # Per-parameter statistics
        param_stats = self._compute_parameter_stats(measurements)

        # Anomalies (Z-score > 2)
        anomalies = self._detect_anomalies(measurements, param_stats)

        # Drift analysis
        drift_analysis = self._analyze_drift(measurements, param_stats)

        # Cost analysis
        costs = [rec.actual_cost for rec in self.records if rec.actual_cost]
        total_cost = sum(costs) if costs else 0
        avg_cost = statistics.mean(costs) if costs else 0

        # Environmental analysis
        temps = [rec.temperature for rec in self.records if rec.temperature is not None]
        humids = [rec.humidity for rec in self.records if rec.humidity is not None]

        # Time between calibrations
        intervals = []
        sorted_records = sorted(self.records, key=lambda r: r.calibration_date)
        for i in range(1, len(sorted_records)):
            delta = (sorted_records[i].calibration_date - sorted_records[i - 1].calibration_date).days
            intervals.append(delta)

        return {
            "total_records": total_records,
            "result_distribution": dict(result_counts),
            "pass_rate": round(pass_rate, 1),
            "fail_rate": round(fail_rate, 1),
            "parameter_stats": param_stats,
            "anomalies": anomalies,
            "anomaly_count": len(anomalies),
            "drift_analysis": drift_analysis,
            "cost_analysis": {
                "total_cost": float(total_cost),
                "average_cost": round(float(avg_cost), 2),
                "record_count": len(costs),
            },
            "environmental": {
                "avg_temperature": round(statistics.mean(temps), 1) if temps else None,
                "avg_humidity": round(statistics.mean(humids), 1) if humids else None,
                "temp_range": (round(min(temps), 1), round(max(temps), 1)) if temps else None,
                "humidity_range": (round(min(humids), 1), round(max(humids), 1)) if humids else None,
            },
            "calibration_intervals": {
                "avg_days": round(statistics.mean(intervals)) if intervals else None,
                "min_days": min(intervals) if intervals else None,
                "max_days": max(intervals) if intervals else None,
            },
            "compliance_score": self._compute_compliance_score(pass_rate, anomalies, drift_analysis),
            "recommendations": [],  # Filled by generate_recommendations()
        }

    def _compute_parameter_stats(self, measurements):
        """Compute mean, std, min, max for each parameter."""
        grouped = defaultdict(list)
        for m in measurements:
            grouped[m["parameter"]].append(m["value"])

        stats = {}
        for param, values in grouped.items():
            if len(values) < 2:
                stats[param] = {
                    "count": len(values),
                    "mean": values[0] if values else 0,
                    "std": 0,
                    "min": values[0] if values else 0,
                    "max": values[0] if values else 0,
                    "cv": 0,
                }
            else:
                mean_val = statistics.mean(values)
                std_val = statistics.stdev(values)
                stats[param] = {
                    "count": len(values),
                    "mean": round(mean_val, 4),
                    "std": round(std_val, 4),
                    "min": round(min(values), 4),
                    "max": round(max(values), 4),
                    "cv": round((std_val / mean_val * 100), 2) if mean_val != 0 else 0,
                }
        return stats

    def _detect_anomalies(self, measurements, param_stats):
        """Detect anomalous measurements using Z-score (|z| > 2)."""
        anomalies = []
        for m in measurements:
            ps = param_stats.get(m["parameter"])
            if ps and ps["std"] > 0:
                z = abs((m["value"] - ps["mean"]) / ps["std"])
                if z > 2:
                    anomalies.append(
                        {
                            "record_id": m["record_id"],
                            "date": m["date"],
                            "parameter": m["parameter"],
                            "value": m["value"],
                            "z_score": round(z, 2),
                            "expected_range": (
                                round(ps["mean"] - 2 * ps["std"], 4),
                                round(ps["mean"] + 2 * ps["std"], 4),
                            ),
                            "severity": "critical" if z > 3 else "warning",
                        }
                    )
        return sorted(anomalies, key=lambda a: a["z_score"], reverse=True)

    def _analyze_drift(self, measurements, param_stats):
        """Analyze calibration drift (trend over time) per parameter."""
        grouped = defaultdict(list)
        for m in measurements:
            grouped[m["parameter"]].append((m["date"], m["value"]))

        drift_results = {}
        for param, data_points in grouped.items():
            if len(data_points) < 3:
                drift_results[param] = {"trend": "insufficient_data", "direction": None, "severity": "none"}
                continue

            sorted_points = sorted(data_points, key=lambda x: x[0])
            values = [p[1] for p in sorted_points]

            # Simple linear trend: compare first half vs second half
            mid = len(values) // 2
            first_half_mean = statistics.mean(values[:mid])
            second_half_mean = statistics.mean(values[mid:])
            overall_std = param_stats[param]["std"] if param_stats[param]["std"] > 0 else 1

            drift_magnitude = (second_half_mean - first_half_mean) / overall_std

            if abs(drift_magnitude) < 0.5:
                trend = "stable"
                severity = "none"
            elif abs(drift_magnitude) < 1.0:
                trend = "slight_drift"
                severity = "low"
            elif abs(drift_magnitude) < 2.0:
                trend = "moderate_drift"
                severity = "medium"
            else:
                trend = "significant_drift"
                severity = "high"

            drift_results[param] = {
                "trend": trend,
                "direction": "increasing" if drift_magnitude > 0 else "decreasing",
                "magnitude": round(abs(drift_magnitude), 2),
                "severity": severity,
                "first_half_mean": round(first_half_mean, 4),
                "second_half_mean": round(second_half_mean, 4),
            }
        return drift_results

    def _compute_compliance_score(self, pass_rate, anomalies, drift_analysis):
        """Compute an overall compliance score (0-100)."""
        score = pass_rate  # Start with pass rate

        # Deduct for anomalies
        critical_anomalies = sum(1 for a in anomalies if a["severity"] == "critical")
        warning_anomalies = sum(1 for a in anomalies if a["severity"] == "warning")
        score -= critical_anomalies * 5
        score -= warning_anomalies * 2

        # Deduct for drift
        for _param, drift in drift_analysis.items():
            if drift.get("severity") == "high":
                score -= 10
            elif drift.get("severity") == "medium":
                score -= 5
            elif drift.get("severity") == "low":
                score -= 2

        return max(0, min(100, round(score, 1)))

    def generate_recommendations(self, stats):
        """Generate AI-driven recommendations based on statistical analysis."""
        recommendations = []

        # Pass rate warnings
        if stats["pass_rate"] < 80:
            recommendations.append(
                {
                    "type": "critical",
                    "icon": "fa-exclamation-triangle",
                    "title": "Low Pass Rate Detected",
                    "detail": f"Pass rate is {stats['pass_rate']}% — below the 80% threshold. "
                    f"Review calibration procedures and equipment condition urgently.",
                }
            )
        elif stats["pass_rate"] < 95:
            recommendations.append(
                {
                    "type": "warning",
                    "icon": "fa-exclamation-circle",
                    "title": "Pass Rate Below Target",
                    "detail": f"Pass rate is {stats['pass_rate']}%. Target is ≥95%. "
                    f"Consider increasing calibration frequency.",
                }
            )

        # Anomaly recommendations
        if stats["anomaly_count"] > 0:
            critical_count = sum(1 for a in stats["anomalies"] if a["severity"] == "critical")
            if critical_count > 0:
                recommendations.append(
                    {
                        "type": "critical",
                        "icon": "fa-radiation",
                        "title": f"{critical_count} Critical Anomalies Found",
                        "detail": "Measurements with Z-score > 3 detected. "
                        "Immediate investigation of measurement equipment and procedures required.",
                    }
                )
            else:
                recommendations.append(
                    {
                        "type": "warning",
                        "icon": "fa-search",
                        "title": f'{stats["anomaly_count"]} Anomalous Measurements',
                        "detail": "Measurements outside 2σ range detected. Monitor these parameters closely.",
                    }
                )

        # Drift recommendations
        high_drift_params = [p for p, d in stats["drift_analysis"].items() if d.get("severity") in ("high", "medium")]
        if high_drift_params:
            recommendations.append(
                {
                    "type": "warning",
                    "icon": "fa-chart-line",
                    "title": "Calibration Drift Detected",
                    "detail": f"Significant drift found in: {', '.join(high_drift_params)}. "
                    f"This may indicate equipment aging or environmental changes.",
                }
            )

        # Interval recommendations
        if stats["calibration_intervals"]["avg_days"]:
            schedule = self.schedule
            if schedule.calibration_interval and schedule.interval_unit:
                expected_days = schedule.calibration_interval
                if schedule.interval_unit == "weeks":
                    expected_days *= 7
                elif schedule.interval_unit == "months":
                    expected_days *= 30
                elif schedule.interval_unit == "years":
                    expected_days *= 365

                actual_avg = stats["calibration_intervals"]["avg_days"]
                if actual_avg > expected_days * 1.2:
                    recommendations.append(
                        {
                            "type": "warning",
                            "icon": "fa-clock",
                            "title": "Calibration Intervals Exceeding Schedule",
                            "detail": f"Average interval is {actual_avg} days vs expected ~{expected_days} days. "
                            f"Tighten scheduling adherence.",
                        }
                    )

        # Environmental recommendations
        if stats["environmental"]["avg_temperature"] is not None:
            temp = stats["environmental"]["avg_temperature"]
            if temp < 18 or temp > 28:
                recommendations.append(
                    {
                        "type": "info",
                        "icon": "fa-thermometer-half",
                        "title": "Environmental Conditions Outside Optimal Range",
                        "detail": f"Average temperature is {temp}°C. Optimal range is 18-28°C.",
                    }
                )

        # Cost trend
        if stats["cost_analysis"]["record_count"] > 0:
            recommendations.append(
                {
                    "type": "info",
                    "icon": "fa-dollar-sign",
                    "title": "Cost Summary",
                    "detail": f"Total calibration cost: ${stats['cost_analysis']['total_cost']:,.2f} "
                    f"across {stats['cost_analysis']['record_count']} records "
                    f"(avg ${stats['cost_analysis']['average_cost']:,.2f}/calibration).",
                }
            )

        # Good compliance
        if stats["compliance_score"] >= 95 and not recommendations:
            recommendations.append(
                {
                    "type": "success",
                    "icon": "fa-check-circle",
                    "title": "Excellent Compliance",
                    "detail": f"Compliance score is {stats['compliance_score']}%. "
                    f"All parameters are within acceptable ranges.",
                }
            )

        stats["recommendations"] = recommendations
        return recommendations

    def generate_report(self):
        """Generate the full report data."""
        stats = self.compute_statistics()
        self.generate_recommendations(stats)

        return {
            "schedule": self.schedule,
            "records": self.records,
            "stats": stats,
            "generated_at": timezone.now(),
            "report_version": "1.0",
        }

    def _empty_stats(self):
        return {
            "total_records": 0,
            "result_distribution": {},
            "pass_rate": 0,
            "fail_rate": 0,
            "parameter_stats": {},
            "anomalies": [],
            "anomaly_count": 0,
            "drift_analysis": {},
            "cost_analysis": {"total_cost": 0, "average_cost": 0, "record_count": 0},
            "environmental": {
                "avg_temperature": None,
                "avg_humidity": None,
                "temp_range": None,
                "humidity_range": None,
            },
            "calibration_intervals": {"avg_days": None, "min_days": None, "max_days": None},
            "compliance_score": 0,
            "recommendations": [],
        }
