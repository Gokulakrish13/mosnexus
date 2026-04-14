"""
AI Engine 5: Smart Reservation Scheduling
===========================================
Analyzes historical reservation patterns (which systems, when,
how long, conflicts) to recommend optimal time slots.
Uses a scoring model: availability probability, conflict risk,
utilization balance, and user preference patterns.
"""

# pylint: disable=import-outside-toplevel,invalid-name,too-complex,too-many-branches,too-many-locals,too-many-positional-arguments,too-many-statements
import logging
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)


class SmartSchedulerEngine:
    """AI-powered reservation scheduling recommendations."""

    WORK_START = time(8, 0)
    WORK_END = time(18, 0)
    SLOT_DURATION_HOURS = 1  # Default slot granularity

    def __init__(self, stream=None):
        self.stream = stream
        self._usage_patterns = None
        self._conflict_history = None

    # ------------------------------------------------------------------
    # Data analysis
    # ------------------------------------------------------------------
    def _analyze_usage_patterns(self):
        """Analyze historical reservation patterns."""
        if self._usage_patterns is not None:
            return self._usage_patterns

        from products.models import RecurringReservation, RecurringReservationInstance

        filters = {}
        if self.stream:
            filters["stream"] = self.stream

        reservations = RecurringReservation.objects.filter(**filters).select_related("system", "reserved_for")
        instances = RecurringReservationInstance.objects.filter(recurring_reservation__in=reservations).select_related(
            "recurring_reservation__system"
        )

        # Day-of-week usage frequency
        dow_counts = Counter()
        for inst in instances:
            if inst.reservation_date:
                dow = inst.reservation_date.weekday()
                dow_counts[dow] += 1

        # Hour-of-day preference
        hour_counts = Counter()
        for inst in instances:
            if inst.start_time:
                hour_counts[inst.start_time.hour] += 1

        # System popularity
        system_counts = Counter()
        for r in reservations:
            if r.system:
                system_counts[r.system.pk] += 1

        # Duration preferences
        duration_counts = Counter()
        for inst in instances:
            if inst.start_time and inst.end_time:
                start_min = inst.start_time.hour * 60 + inst.start_time.minute
                end_min = inst.end_time.hour * 60 + inst.end_time.minute
                duration_hours = max(1, (end_min - start_min) // 60)
                duration_counts[duration_hours] += 1

        # Average utilization per day-of-week
        dow_utilization = defaultdict(list)
        for inst in instances:
            if inst.reservation_date and inst.start_time and inst.end_time:
                dow = inst.reservation_date.weekday()
                start_min = inst.start_time.hour * 60 + inst.start_time.minute
                end_min = inst.end_time.hour * 60 + inst.end_time.minute
                duration = (end_min - start_min) / 60
                dow_utilization[dow].append(duration)

        avg_dow_utilization = {
            dow: sum(durations) / max(1, len(durations)) for dow, durations in dow_utilization.items()
        }

        self._usage_patterns = {
            "day_of_week": dict(dow_counts),
            "hour_of_day": dict(hour_counts),
            "system_popularity": dict(system_counts),
            "duration_preferences": dict(duration_counts),
            "avg_dow_utilization": avg_dow_utilization,
            "total_reservations": reservations.count(),
            "total_instances": instances.count(),
        }

        return self._usage_patterns

    def _analyze_conflicts(self):
        """Analyze historical conflict patterns."""
        if self._conflict_history is not None:
            return self._conflict_history

        from products.models import ReservationConflict

        filters = {}
        if self.stream:
            filters["stream"] = self.stream

        conflicts = ReservationConflict.objects.filter(**filters).select_related("system")

        # Conflict hotspots by day-of-week / time
        _conflict_dow = Counter()
        conflict_systems = Counter()

        for c in conflicts:
            if c.system:
                conflict_systems[c.system.pk] += 1

        self._conflict_history = {
            "conflict_systems": dict(conflict_systems),
            "total_conflicts": conflicts.count(),
        }

        return self._conflict_history

    # ------------------------------------------------------------------
    # Smart slot recommendation
    # ------------------------------------------------------------------
    def recommend_slots(self, system=None, user=None, desired_date=None, duration_hours=2, num_suggestions=5):
        """
        Recommend optimal reservation time slots.

        Returns scored slots ranked by:
        1. Availability (no existing reservations)
        2. Conflict risk (low historical conflict rate)
        3. Utilization balance (prefer underutilized times)
        4. User preference (match user's historical patterns)
        """
        from products.models import System

        patterns = self._analyze_usage_patterns()
        conflicts = self._analyze_conflicts()

        if desired_date:
            if isinstance(desired_date, str):
                desired_date = datetime.strptime(desired_date, "%Y-%m-%d").date()
            search_dates = [desired_date + timedelta(days=i) for i in range(7)]
        else:
            today = timezone.now().date()
            search_dates = [today + timedelta(days=i) for i in range(1, 8)]

        # Filter out weekends
        search_dates = [d for d in search_dates if d.weekday() < 5]

        if system:
            systems = [system] if not isinstance(system, int) else [System.objects.get(pk=system)]
        else:
            sys_filters = {}
            if self.stream:
                sys_filters["stream"] = self.stream
            systems = list(
                System.objects.filter(status="Active", **sys_filters).order_by("utilization_percentage")[:10]
            )

        if not systems:
            return {
                "success": False,
                "error": "No active systems available.",
                "suggestions": [],
            }

        # Generate candidate slots
        candidates = []
        for date in search_dates:
            for sys in systems:
                for hour in range(self.WORK_START.hour, self.WORK_END.hour - duration_hours + 1):
                    slot_start = time(hour, 0)
                    slot_end = time(hour + duration_hours, 0)
                    candidates.append(
                        {
                            "system": sys,
                            "date": date,
                            "start_time": slot_start,
                            "end_time": slot_end,
                            "duration": duration_hours,
                        }
                    )

        scored = []
        for candidate in candidates:
            score = self._score_slot(candidate, patterns, conflicts, user)
            candidate["score"] = score["total"]
            candidate["score_breakdown"] = score
            scored.append(candidate)

        scored.sort(key=lambda s: s["score"], reverse=True)
        top_slots = scored[:num_suggestions]

        suggestions = []
        for i, slot in enumerate(top_slots):
            suggestions.append(
                {
                    "rank": i + 1,
                    "system_id": slot["system"].pk,
                    "system_name": slot["system"].name,
                    "date": str(slot["date"]),
                    "day_name": slot["date"].strftime("%A"),
                    "start_time": slot["start_time"].strftime("%H:%M"),
                    "end_time": slot["end_time"].strftime("%H:%M"),
                    "duration_hours": slot["duration"],
                    "score": round(slot["score"], 1),
                    "score_breakdown": {
                        "availability": round(slot["score_breakdown"]["availability"], 1),
                        "conflict_risk": round(slot["score_breakdown"]["conflict_risk"], 1),
                        "utilization_balance": round(slot["score_breakdown"]["utilization_balance"], 1),
                        "user_preference": round(slot["score_breakdown"]["user_preference"], 1),
                    },
                    "reasoning": self._generate_reasoning(slot),
                }
            )

        return {
            "success": True,
            "suggestions": suggestions,
            "patterns_analyzed": {
                "total_reservations": patterns["total_reservations"],
                "total_conflicts": conflicts["total_conflicts"],
                "busiest_day": (
                    self._dow_name(max(patterns["day_of_week"], key=patterns["day_of_week"].get))
                    if patterns["day_of_week"]
                    else "N/A"
                ),
                "quietest_day": (
                    self._dow_name(min(patterns["day_of_week"], key=patterns["day_of_week"].get))
                    if patterns["day_of_week"]
                    else "N/A"
                ),
                "peak_hour": (
                    f"{max(patterns['hour_of_day'], key=patterns['hour_of_day'].get):02d}:00"
                    if patterns["hour_of_day"]
                    else "N/A"
                ),
            },
        }

    def _score_slot(self, candidate, patterns, conflicts, user=None):
        """Score a single candidate slot (0-100)."""
        from products.models import RecurringReservationInstance

        scores = {
            "availability": 0,
            "conflict_risk": 0,
            "utilization_balance": 0,
            "user_preference": 0,
        }

        sys = candidate["system"]
        date = candidate["date"]
        start = candidate["start_time"]
        end = candidate["end_time"]
        dow = date.weekday()

        # 1. Availability score (40 points max)
        existing = (
            RecurringReservationInstance.objects.filter(
                recurring_reservation__system=sys,
                reservation_date=date,
                status__in=["confirmed", "pending"],
            )
            .filter(Q(start_time__lt=end, end_time__gt=start))
            .count()
        )

        if existing == 0:
            scores["availability"] = 40
        elif existing == 1:
            scores["availability"] = 10
        else:
            scores["availability"] = 0

        # 2. Conflict risk score (25 points max)
        conflict_count = conflicts.get("conflict_systems", {}).get(sys.pk, 0)
        total_conflicts = conflicts.get("total_conflicts", 1)
        system_conflict_rate = conflict_count / max(1, total_conflicts)

        if system_conflict_rate < 0.05:
            scores["conflict_risk"] = 25
        elif system_conflict_rate < 0.15:
            scores["conflict_risk"] = 18
        elif system_conflict_rate < 0.30:
            scores["conflict_risk"] = 10
        else:
            scores["conflict_risk"] = 3

        # 3. Utilization balance (20 points max)
        # Prefer times with lower historical usage
        system_pop = patterns.get("system_popularity", {}).get(sys.pk, 0)
        total = max(1, patterns.get("total_reservations", 1))
        pop_rate = system_pop / total

        if pop_rate < 0.1:
            scores["utilization_balance"] = 20  # Underutilized system
        elif pop_rate < 0.3:
            scores["utilization_balance"] = 15
        elif pop_rate < 0.5:
            scores["utilization_balance"] = 10
        else:
            scores["utilization_balance"] = 5

        # Bonus for off-peak day
        dow_total = sum(patterns.get("day_of_week", {}).values()) or 1
        dow_rate = patterns.get("day_of_week", {}).get(dow, 0) / dow_total
        if dow_rate < 0.15:
            scores["utilization_balance"] = min(20, scores["utilization_balance"] + 5)

        # 4. User preference score (15 points max)
        if user:
            from products.models import RecurringReservation

            user_reservations = RecurringReservation.objects.filter(reserved_for=user)
            user_systems = Counter(r.system_id for r in user_reservations if r.system_id)
            user_hours = Counter()
            for r in user_reservations:
                if r.start_time:
                    user_hours[r.start_time.hour] += 1

            if sys.pk in user_systems:
                scores["user_preference"] += 5

            if start.hour in user_hours:
                scores["user_preference"] += 5

            if user_reservations.exists():
                scores["user_preference"] += 5
        else:
            scores["user_preference"] = 10  # Neutral

        scores["total"] = sum(scores.values())
        return scores

    def _generate_reasoning(self, slot):
        """Generate human-readable reasoning for a slot recommendation."""
        breakdown = slot["score_breakdown"]
        reasons = []

        if breakdown["availability"] >= 35:
            reasons.append("System is fully available at this time")
        elif breakdown["availability"] >= 15:
            reasons.append("Limited availability — one existing reservation nearby")

        if breakdown["conflict_risk"] >= 20:
            reasons.append("Low historical conflict rate for this system")
        elif breakdown["conflict_risk"] < 10:
            reasons.append("Higher conflict risk — consider alternatives")

        if breakdown["utilization_balance"] >= 15:
            reasons.append("This system/time is underutilized — good for load balancing")

        if breakdown["user_preference"] >= 10:
            reasons.append("Matches your historical reservation patterns")

        return ". ".join(reasons) + "." if reasons else "Standard recommendation."

    @staticmethod
    def _dow_name(dow):
        """Convert day-of-week number to name."""
        names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        return names[dow] if 0 <= dow <= 6 else "Unknown"

    # ------------------------------------------------------------------
    # User pattern analysis
    # ------------------------------------------------------------------
    def get_user_insights(self, user):
        """Get AI-generated insights about a user's reservation patterns."""
        from products.models import RecurringReservation, RecurringReservationInstance

        reservations = RecurringReservation.objects.filter(reserved_for=user).select_related("system", "stream")

        if not reservations.exists():
            return {
                "has_data": False,
                "message": "No reservation history found for this user.",
            }

        instances = RecurringReservationInstance.objects.filter(recurring_reservation__in=reservations)

        sys_counts = Counter(r.system.name for r in reservations if r.system)
        preferred_systems = sys_counts.most_common(3)

        hour_counts = Counter()
        for inst in instances:
            if inst.start_time:
                hour_counts[inst.start_time.hour] += 1
        preferred_hours = hour_counts.most_common(3)

        dow_counts = Counter()
        for inst in instances:
            if inst.reservation_date:
                dow_counts[inst.reservation_date.weekday()] += 1
        preferred_days = [(self._dow_name(d), c) for d, c in dow_counts.most_common(3)]

        total_instances = instances.count()
        conflict_instances = instances.filter(has_conflict=True).count()
        conflict_rate = (conflict_instances / total_instances * 100) if total_instances > 0 else 0

        return {
            "has_data": True,
            "total_reservations": reservations.count(),
            "total_instances": total_instances,
            "preferred_systems": [{"name": s, "count": c} for s, c in preferred_systems],
            "preferred_hours": [{"hour": f"{h:02d}:00", "count": c} for h, c in preferred_hours],
            "preferred_days": [{"day": d, "count": c} for d, c in preferred_days],
            "conflict_rate": round(conflict_rate, 1),
            "insights": self._generate_user_insights(preferred_systems, preferred_hours, preferred_days, conflict_rate),
        }

    def _generate_user_insights(self, systems, hours, days, conflict_rate):
        """Generate AI insights text."""
        insights = []

        if systems:
            top = systems[0]
            insights.append(f"Your most-used system is {top[0]} ({top[1]} reservations).")

        if hours:
            top_hour = hours[0]
            insights.append(f"You typically book at {top_hour[0]:02d}:00 ({top_hour[1]} times).")

        if days:
            top_day = days[0]
            insights.append(f"Your busiest reservation day is {top_day[0]} ({top_day[1]} bookings).")

        if conflict_rate > 20:
            insights.append(
                f"Your conflict rate is {conflict_rate}% — consider booking earlier or using less popular systems."
            )
        elif conflict_rate > 0:
            insights.append(f"Your conflict rate is {conflict_rate}% — within normal range.")

        return " ".join(insights)
