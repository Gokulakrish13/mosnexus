"""
AI Usage Pattern Analytics Engine for NexusOps.

Discovers peak hours, underutilized systems, user booking patterns,
and suggests optimal lab schedules and resource reallocation.
"""

# pylint: disable=broad-exception-caught,duplicate-code,import-outside-toplevel,invalid-name,too-many-locals
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from django.db.models import Count
from django.db.models.functions import TruncWeek
from django.utils import timezone

logger = logging.getLogger(__name__)


class UsageAnalyticsEngine:
    """Analyses usage patterns across systems, reservations, and page activity."""

    def __init__(self, stream=None, days_back=90):
        self.stream = stream
        self.days_back = days_back
        self.cutoff = timezone.now() - timedelta(days=days_back)

    # ── public entry point ───────────────────────────────────────────────
    def full_analysis(self):
        """Run all analyses and return a unified report dict."""
        try:
            peak = self._peak_hours_analysis()
            utilization = self._system_utilization_analysis()
            booking = self._booking_pattern_analysis()
            user_activity = self._user_activity_analysis()
            recommendations = self._generate_recommendations(peak, utilization, booking, user_activity)

            return {
                "success": True,
                "peak_hours": peak,
                "system_utilization": utilization,
                "booking_patterns": booking,
                "user_activity": user_activity,
                "recommendations": recommendations,
                "analysis_period_days": self.days_back,
                "generated_at": timezone.now().isoformat(),
            }
        except Exception:
            logger.exception("Usage analytics failed")
            return {"success": False, "error": "An unexpected error occurred"}

    # ── peak hours ───────────────────────────────────────────────────────
    def _peak_hours_analysis(self):
        """Identify peak usage hours from reservations and system allocations."""
        from products.models import RecurringReservationInstance, SystemAllocation

        hourly = defaultdict(int)
        daily = defaultdict(int)  # 1=Sunday .. 7=Saturday (Django ExtractWeekDay)

        # Reservation instances
        instances = RecurringReservationInstance.objects.filter(
            recurring_reservation__stream=self.stream,
            reservation_date__gte=self.cutoff.date(),
            status="confirmed",
        ).values_list("start_time", "end_time", "reservation_date")

        for start, _end, dt in instances:
            if start:
                hourly[start.hour] += 1
            if dt:
                daily[dt.weekday()] += 1  # 0=Mon

        # System allocations
        allocs = SystemAllocation.objects.filter(
            stream=self.stream,
            start_date__gte=self.cutoff,
        ).values_list("start_date", flat=True)

        for dt in allocs:
            if dt:
                daily[dt.weekday()] += 1

        # Build sorted results
        hour_labels = {h: f"{h:02d}:00" for h in range(24)}
        day_labels = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday", 5: "Saturday", 6: "Sunday"}

        peak_hours = sorted(hourly.items(), key=lambda x: x[1], reverse=True)
        peak_days = sorted(daily.items(), key=lambda x: x[1], reverse=True)

        top_hour = peak_hours[0] if peak_hours else None
        off_peak_hours = [h for h in range(8, 18) if hourly.get(h, 0) == 0] if hourly else list(range(8, 18))

        return {
            "hourly_distribution": {hour_labels.get(h, str(h)): c for h, c in sorted(hourly.items())},
            "daily_distribution": {day_labels.get(d, str(d)): c for d, c in sorted(daily.items())},
            "peak_hour": hour_labels.get(top_hour[0], "—") if top_hour else "—",
            "peak_hour_count": top_hour[1] if top_hour else 0,
            "peak_day": day_labels.get(peak_days[0][0], "—") if peak_days else "—",
            "off_peak_hours": [hour_labels[h] for h in off_peak_hours[:5]],
            "total_bookings_analysed": sum(hourly.values()),
        }

    # ── system utilization ───────────────────────────────────────────────
    def _system_utilization_analysis(self):
        """Calculate utilization per system and identify underutilized ones."""
        from products.models import RecurringReservationInstance, System, SystemAllocation

        systems = System.objects.filter(stream=self.stream).order_by("name")
        results = []
        total_hours_available = self.days_back * 10  # assume 10 work-hours per day

        for sys in systems:
            # Count reservation hours
            res_count = RecurringReservationInstance.objects.filter(
                recurring_reservation__stream=self.stream,
                system_allocation__system_type=sys.name,
                reservation_date__gte=self.cutoff.date(),
                status="confirmed",
            ).count()

            # Count allocation events
            alloc_count = SystemAllocation.objects.filter(
                stream=self.stream,
                system_type=sys.name,
                start_date__gte=self.cutoff,
            ).count()

            total_events = res_count + alloc_count
            # Estimate hours (avg 2h per event)
            estimated_hours = total_events * 2
            utilization_pct = min(100.0, round((estimated_hours / max(total_hours_available, 1)) * 100, 1))

            results.append(
                {
                    "system_name": sys.name,
                    "system_id": sys.pk,
                    "status": sys.status,
                    "total_events": total_events,
                    "estimated_hours": estimated_hours,
                    "utilization_pct": utilization_pct,
                    "category": (
                        "overutilized"
                        if utilization_pct > 85
                        else ("optimal" if utilization_pct > 40 else "underutilized")
                    ),
                }
            )

        results.sort(key=lambda x: x["utilization_pct"])

        underutilized = [r for r in results if r["category"] == "underutilized"]
        overutilized = [r for r in results if r["category"] == "overutilized"]
        avg_utilization = round(sum(r["utilization_pct"] for r in results) / max(len(results), 1), 1)

        return {
            "systems": results,
            "total_systems": len(results),
            "underutilized_count": len(underutilized),
            "overutilized_count": len(overutilized),
            "avg_utilization": avg_utilization,
            "underutilized_names": [r["system_name"] for r in underutilized[:5]],
            "overutilized_names": [r["system_name"] for r in overutilized[:5]],
        }

    # ── booking patterns ─────────────────────────────────────────────────
    def _booking_pattern_analysis(self):
        """Analyse reservation duration, conflict, and cancellation patterns."""
        from products.models import RecurringReservationInstance, ReservationConflict

        instances = RecurringReservationInstance.objects.filter(
            recurring_reservation__stream=self.stream,
            reservation_date__gte=self.cutoff.date(),
        )

        total = instances.count()
        confirmed = instances.filter(status="confirmed").count()
        cancelled = instances.filter(status="cancelled").count()
        pending = instances.filter(status="pending").count()

        # Duration distribution
        durations = []
        for inst in instances.filter(start_time__isnull=False, end_time__isnull=False):
            try:
                start_dt = datetime.combine(inst.reservation_date, inst.start_time)
                end_dt = datetime.combine(inst.reservation_date, inst.end_time)
                hrs = (end_dt - start_dt).total_seconds() / 3600
                if 0 < hrs < 24:
                    durations.append(round(hrs, 1))
            except Exception:
                pass

        avg_duration = round(sum(durations) / max(len(durations), 1), 1) if durations else 0
        duration_dist = Counter()
        for d in durations:
            if d <= 1:
                duration_dist["≤1h"] += 1
            elif d <= 2:
                duration_dist["1-2h"] += 1
            elif d <= 4:
                duration_dist["2-4h"] += 1
            else:
                duration_dist["4h+"] += 1

        # Conflicts
        conflicts = ReservationConflict.objects.filter(
            stream=self.stream,
            detected_at__gte=self.cutoff,
        ).count()
        conflict_rate = round((conflicts / max(total, 1)) * 100, 1)

        # Weekly trend
        weekly_trend = list(
            instances.annotate(week=TruncWeek("reservation_date"))
            .values("week")
            .annotate(count=Count("id"))
            .order_by("week")
        )

        return {
            "total_bookings": total,
            "confirmed": confirmed,
            "cancelled": cancelled,
            "pending": pending,
            "cancellation_rate": round((cancelled / max(total, 1)) * 100, 1),
            "avg_duration_hours": avg_duration,
            "duration_distribution": dict(duration_dist),
            "conflict_count": conflicts,
            "conflict_rate": conflict_rate,
            "weekly_trend": [
                {"week": wt["week"].strftime("%Y-%m-%d") if wt["week"] else "", "count": wt["count"]}
                for wt in weekly_trend[-12:]
            ],
        }

    # ── user activity ────────────────────────────────────────────────────
    def _user_activity_analysis(self):
        """Analyse which users are most/least active."""
        from products.models import RecurringReservationInstance, UsageTracking

        from django.contrib.auth import get_user_model  # pylint: disable=unused-import

        # Page views per user
        page_views = (
            UsageTracking.objects.filter(timestamp__gte=self.cutoff)
            .values("user__username")
            .annotate(views=Count("id"))
            .order_by("-views")[:15]
        )

        # Reservations per user
        res_per_user = (
            RecurringReservationInstance.objects.filter(
                recurring_reservation__stream=self.stream,
                reservation_date__gte=self.cutoff.date(),
                status="confirmed",
            )
            .values("recurring_reservation__created_by__username")
            .annotate(count=Count("id"))
            .order_by("-count")[:10]
        )

        # Most visited pages
        top_pages = (
            UsageTracking.objects.filter(timestamp__gte=self.cutoff)
            .values("page_name")
            .annotate(views=Count("id"))
            .order_by("-views")[:10]
        )

        return {
            "top_users_by_views": [{"username": u["user__username"], "views": u["views"]} for u in page_views],
            "top_users_by_bookings": [
                {"username": u["recurring_reservation__created_by__username"], "count": u["count"]}
                for u in res_per_user
            ],
            "top_pages": [{"page": p["page_name"], "views": p["views"]} for p in top_pages],
            "total_page_views": UsageTracking.objects.filter(timestamp__gte=self.cutoff).count(),
            "unique_active_users": UsageTracking.objects.filter(timestamp__gte=self.cutoff)
            .values("user")
            .distinct()
            .count(),
        }

    # ── recommendations ──────────────────────────────────────────────────
    def _generate_recommendations(self, peak, utilization, booking, user_activity):
        """Generate AI-driven actionable recommendations."""
        recs = []

        # Peak hour recommendations
        if peak.get("off_peak_hours"):
            recs.append(
                {
                    "type": "schedule_optimization",
                    "priority": "medium",
                    "icon": "fa-clock",
                    "title": "Encourage Off-Peak Bookings",
                    "detail": f"Hours {', '.join(peak['off_peak_hours'][:3])} are consistently underused. "
                    f"Consider incentivizing bookings during these times to balance lab load.",
                }
            )

        if peak.get("peak_hour") and peak.get("peak_hour_count", 0) > 10:
            recs.append(
                {
                    "type": "capacity",
                    "priority": "high",
                    "icon": "fa-exclamation-triangle",
                    "title": f"Peak Congestion at {peak['peak_hour']}",
                    "detail": f"This hour had {peak['peak_hour_count']} bookings in the analysis period. "
                    f"Consider staggering start times or adding capacity.",
                }
            )

        # Utilization recommendations
        if utilization.get("underutilized_count", 0) > 0:
            names = ", ".join(utilization["underutilized_names"][:3])
            recs.append(
                {
                    "type": "resource_reallocation",
                    "priority": "medium",
                    "icon": "fa-chart-bar",
                    "title": f"{utilization['underutilized_count']} Underutilized System(s)",
                    "detail": f"Systems: {names} have < 40% utilization. "
                    f"Consider consolidating workloads or repurposing these assets.",
                }
            )

        if utilization.get("overutilized_count", 0) > 0:
            names = ", ".join(utilization["overutilized_names"][:3])
            recs.append(
                {
                    "type": "capacity",
                    "priority": "high",
                    "icon": "fa-fire",
                    "title": f"{utilization['overutilized_count']} Overutilized System(s)",
                    "detail": f"Systems: {names} exceed 85% utilization. "
                    f"Risk of user contention and accelerated wear. Consider load balancing.",
                }
            )

        # Booking pattern recommendations
        if booking.get("conflict_rate", 0) > 15:
            recs.append(
                {
                    "type": "conflict_reduction",
                    "priority": "high",
                    "icon": "fa-bolt",
                    "title": "High Conflict Rate",
                    "detail": f"Conflict rate is {booking['conflict_rate']}%. "
                    f"Enable the AI Smart Scheduler to auto-suggest non-conflicting slots.",
                }
            )

        if booking.get("cancellation_rate", 0) > 20:
            recs.append(
                {
                    "type": "process",
                    "priority": "medium",
                    "icon": "fa-ban",
                    "title": "High Cancellation Rate",
                    "detail": f"Cancellation rate is {booking['cancellation_rate']}%. "
                    f"Consider implementing a booking confirmation step or shorter booking windows.",
                }
            )

        if booking.get("avg_duration_hours", 0) > 0 and booking["avg_duration_hours"] < 1.5:
            recs.append(
                {
                    "type": "efficiency",
                    "priority": "low",
                    "icon": "fa-stopwatch",
                    "title": "Short Average Booking Duration",
                    "detail": f"Average booking is only {booking['avg_duration_hours']}h. "
                    f"Consider minimum booking slots to reduce scheduling overhead.",
                }
            )

        # User activity recommendations
        if user_activity.get("unique_active_users", 0) < 3:
            recs.append(
                {
                    "type": "adoption",
                    "priority": "medium",
                    "icon": "fa-users",
                    "title": "Low Platform Adoption",
                    "detail": f"Only {user_activity['unique_active_users']} unique users active in the analysis period. "
                    f"Consider training sessions or onboarding reminders.",
                }
            )

        if not recs:
            recs.append(
                {
                    "type": "positive",
                    "priority": "low",
                    "icon": "fa-check-circle",
                    "title": "Operations Running Smoothly",
                    "detail": "No significant issues detected. Usage patterns are well-balanced.",
                }
            )

        return recs
