"""
AI Engine 3: Natural Language to SQL Dashboard
================================================
A trained intent classifier (TF-IDF + Naive Bayes) maps
user natural-language queries to predefined ORM query templates.
Keyword extraction pulls parameters (stream, dates, status).
Pre-seeded with ~200 training examples.
"""

# pylint: disable=broad-exception-caught,duplicate-code,import-outside-toplevel,invalid-name,not-callable,too-complex,too-many-lines,too-many-locals,unused-argument
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

logger = logging.getLogger(__name__)

AI_MODELS_DIR = os.path.join(settings.BASE_DIR, "ai_models")


# Training data: intent → example queries
TRAINING_DATA = {
    "product_list": [
        "show all products",
        "list all products",
        "get all products",
        "display products",
        "what products do we have",
        "all items in inventory",
        "show me everything in stock",
        "product inventory",
    ],
    "product_by_stream": [
        "show products in {stream} stream",
        "list {stream} products",
        "products for {stream}",
        "get products from {stream}",
        "what products are in {stream}",
        "{stream} inventory",
    ],
    "product_by_status": [
        "show active products",
        "list inactive products",
        "scraped products",
        "show products with status {status}",
        "which products are active",
        "not active products",
        "hand-overed products",
        "all active items",
    ],
    "product_count": [
        "how many products",
        "count products",
        "total products",
        "number of products",
        "product count",
        "how many items",
    ],
    "product_count_by_stream": [
        "how many products in {stream}",
        "count products per stream",
        "products per stream",
        "product count by stream",
        "breakdown by stream",
        "stream-wise count",
    ],
    "product_expiring": [
        "products expiring soon",
        "expiring products",
        "warranty expiring",
        "products with warranty expiring",
        "items about to expire",
        "soon to expire",
        "what is expiring next month",
    ],
    "system_status": [
        "show system status",
        "system health",
        "all systems",
        "list systems",
        "system overview",
        "which systems are active",
        "system availability",
        "systems with issues",
    ],
    "system_utilization": [
        "system utilization",
        "most used systems",
        "least used systems",
        "utilization percentage",
        "system usage",
        "busy systems",
        "underutilized systems",
        "system workload",
    ],
    "calibration_due": [
        "calibrations due",
        "upcoming calibrations",
        "overdue calibrations",
        "calibration schedule",
        "what needs calibration",
        "next calibration",
        "pending calibrations",
        "calibration reminders",
    ],
    "calibration_results": [
        "calibration results",
        "calibration pass rate",
        "failed calibrations",
        "calibration history",
        "recent calibrations",
        "calibration records",
    ],
    "reservation_summary": [
        "reservation summary",
        "upcoming reservations",
        "active reservations",
        "who has reservations",
        "reservation count",
        "system reservations",
        "booking summary",
        "scheduled reservations",
    ],
    "reservation_conflicts": [
        "reservation conflicts",
        "scheduling conflicts",
        "double bookings",
        "overlapping reservations",
        "conflict list",
        "booking conflicts",
    ],
    "alert_summary": [
        "inventory alerts",
        "active alerts",
        "critical alerts",
        "unresolved alerts",
        "alert summary",
        "what alerts are active",
        "pending alerts",
        "show me warnings",
    ],
    "low_stock": [
        "low stock items",
        "items below threshold",
        "short on stock",
        "inventory shortage",
        "what is running low",
        "critical stock",
        "items to reorder",
        "low inventory",
    ],
    "build_server_status": [
        "build server status",
        "server health",
        "all build servers",
        "which servers are down",
        "server overview",
        "build servers",
        "server availability",
        "server list",
    ],
    "maintenance_upcoming": [
        "upcoming maintenance",
        "scheduled maintenance",
        "maintenance schedule",
        "next maintenance",
        "planned maintenance",
        "maintenance this week",
        "maintenance this month",
        "maintenance events",
    ],
    "lifecycle_summary": [
        "asset lifecycle",
        "lifecycle status",
        "assets by stage",
        "lifecycle summary",
        "asset stages",
        "depreciation report",
        "aging assets",
        "asset condition",
    ],
    "compliance_status": [
        "compliance status",
        "compliance overview",
        "regulatory compliance",
        "expired documents",
        "compliance documents",
        "compliance alerts",
        "overdue compliance",
        "compliance summary",
    ],
    "top_users": [
        "most active users",
        "top users",
        "user activity",
        "who uses the system most",
        "user statistics",
        "power users",
    ],
    "stream_overview": [
        "stream overview",
        "stream summary",
        "all streams",
        "stream statistics",
        "stream comparison",
        "stream details",
    ],
}


class NLQueryEngine:
    """Natural language to Django ORM query engine."""

    def __init__(self):
        self._classifier = None
        self._vectorizer = None
        self._label_map = None
        self._stream_names = None
        self._load_model()

    def _load_model(self):
        """Load trained intent classifier if available."""
        try:
            model_path = os.path.join(AI_MODELS_DIR, "nl_query_classifier.joblib")
            if os.path.exists(model_path):
                import joblib

                data = joblib.load(model_path)
                self._classifier = data["classifier"]
                self._vectorizer = data["vectorizer"]
                self._label_map = data["label_map"]
                logger.info("NL query classifier loaded.")
        except Exception:
            logger.debug("Could not load NL classifier.")

    # ------------------------------------------------------------------
    # Intent classification
    # ------------------------------------------------------------------
    def classify_intent(self, query):
        """Classify user query intent."""
        query_lower = query.lower().strip()

        # Try ML classifier first
        if self._classifier and self._vectorizer:
            try:
                features = self._vectorizer.transform([query_lower])
                prediction = self._classifier.predict(features)[0]
                probabilities = self._classifier.predict_proba(features)[0]
                confidence = max(probabilities) * 100

                if confidence > 40:
                    return {
                        "intent": self._label_map.get(prediction, prediction),
                        "confidence": round(confidence, 1),
                        "method": "ml",
                    }
            except Exception:
                pass

        # Fallback: keyword matching
        return self._keyword_classify(query_lower)

    def _keyword_classify(self, query_lower):
        """Classify intent using keyword matching."""
        scores = defaultdict(int)

        keyword_map = {
            "product_list": ["product", "item", "inventory", "stock", "everything"],
            "product_by_stream": ["product", "stream", "in"],
            "product_by_status": ["active", "inactive", "scraped", "status", "hand-over"],
            "product_count": ["count", "how many", "number", "total"],
            "product_count_by_stream": ["count", "per stream", "by stream", "breakdown"],
            "product_expiring": ["expir", "warranty", "soon"],
            "system_status": ["system", "health", "status", "active", "issue"],
            "system_utilization": ["utilization", "usage", "busy", "workload", "underutilized"],
            "calibration_due": ["calibration", "due", "overdue", "upcoming", "schedule", "pending"],
            "calibration_results": ["calibration", "result", "pass", "fail", "record", "history"],
            "reservation_summary": ["reservation", "booking", "scheduled", "upcoming"],
            "reservation_conflicts": ["conflict", "double", "overlapping"],
            "alert_summary": ["alert", "warning", "notification", "pending"],
            "low_stock": ["low", "shortage", "reorder", "below", "threshold", "critical stock"],
            "build_server_status": ["server", "build server", "hostname"],
            "maintenance_upcoming": ["maintenance", "scheduled", "planned"],
            "lifecycle_summary": ["lifecycle", "stage", "depreciation", "aging", "condition"],
            "compliance_status": ["compliance", "regulatory", "document", "expired"],
            "top_users": ["user", "active", "top", "most"],
            "stream_overview": ["stream", "overview", "summary", "comparison"],
        }

        for intent, keywords in keyword_map.items():
            for kw in keywords:
                if kw in query_lower:
                    scores[intent] += 1

        if not scores:
            return {"intent": "unknown", "confidence": 0, "method": "keyword"}

        best = max(scores, key=scores.get)
        max_score = scores[best]
        total = sum(scores.values())
        confidence = (max_score / total * 100) if total > 0 else 0

        return {
            "intent": best,
            "confidence": round(min(confidence, 95), 1),
            "method": "keyword",
        }

    # ------------------------------------------------------------------
    # Parameter extraction
    # ------------------------------------------------------------------
    def extract_parameters(self, query):
        """Extract parameters like stream names, dates, status from query."""
        params = {}
        query_lower = query.lower()

        # Extract stream name
        if self._stream_names is None:
            try:
                from products.models import Stream

                self._stream_names = list(Stream.objects.values_list("name", flat=True))
            except Exception:
                self._stream_names = []

        for sname in self._stream_names:
            if sname.lower() in query_lower:
                params["stream"] = sname
                break

        # Extract status
        status_map = {
            "active": "Active",
            "not active": "Not Active",
            "inactive": "Not Active",
            "scraped": "Scraped",
            "hand-overed": "Hand-Overed",
            "handed over": "Hand-Overed",
        }
        for keyword, value in status_map.items():
            if keyword in query_lower:
                params["status"] = value
                break

        # Extract time ranges
        if any(w in query_lower for w in ["today", "this day"]):
            params["date_from"] = timezone.now().date()
            params["date_to"] = timezone.now().date()
        elif "this week" in query_lower:
            today = timezone.now().date()
            params["date_from"] = today - timedelta(days=today.weekday())
            params["date_to"] = params["date_from"] + timedelta(days=6)
        elif "this month" in query_lower:
            today = timezone.now().date()
            params["date_from"] = today.replace(day=1)
            next_month = today.replace(day=28) + timedelta(days=4)
            params["date_to"] = next_month.replace(day=1) - timedelta(days=1)
        elif "next month" in query_lower:
            today = timezone.now().date()
            next_month = today.replace(day=28) + timedelta(days=4)
            params["date_from"] = next_month.replace(day=1)
            second_next = params["date_from"].replace(day=28) + timedelta(days=4)
            params["date_to"] = second_next.replace(day=1) - timedelta(days=1)
        elif "last month" in query_lower:
            today = timezone.now().date()
            first_this = today.replace(day=1)
            params["date_to"] = first_this - timedelta(days=1)
            params["date_from"] = params["date_to"].replace(day=1)

        # Extract limit
        limit_match = re.search(r"(?:top|first|last|limit)\s+(\d+)", query_lower)
        if limit_match:
            params["limit"] = int(limit_match.group(1))

        return params

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------
    def execute_query(self, query):
        """Full pipeline: classify intent → extract params → execute ORM query."""
        classification = self.classify_intent(query)
        params = self.extract_parameters(query)
        intent = classification["intent"]

        try:
            executor = getattr(self, f"_exec_{intent}", None)
            if executor is None:
                return {
                    "success": False,
                    "intent": intent,
                    "confidence": classification["confidence"],
                    "error": "I couldn't understand the query. Try rephrasing.",
                    "suggestions": self._get_suggestions(),
                }

            result = executor(params)
            return {
                "success": True,
                "intent": intent,
                "confidence": classification["confidence"],
                "method": classification["method"],
                "params": {k: str(v) for k, v in params.items()},
                **result,
            }
        except Exception:
            logger.error("NL query execution failed")
            return {
                "success": False,
                "intent": intent,
                "error": "An unexpected error occurred",
            }

    def _get_suggestions(self):
        return [
            "Show all products",
            "How many products per stream?",
            "System utilization",
            "Upcoming calibrations",
            "Low stock items",
            "Active alerts",
            "Upcoming maintenance",
        ]

    # ------------------------------------------------------------------
    # Query Executors (one per intent)
    # ------------------------------------------------------------------
    def _exec_product_list(self, params):
        from products.models import Product

        qs = Product.objects.select_related("stream", "category")
        if params.get("stream"):
            qs = qs.filter(stream__name=params["stream"])
        limit = params.get("limit", 50)
        products = qs[:limit]
        return {
            "title": f"Products{' in ' + params['stream'] if params.get('stream') else ''}",
            "chart_type": "table",
            "columns": ["Name", "Serial Number", "Stream", "Category", "Status"],
            "data": [
                [p.name, p.serial_number, str(p.stream), str(p.category) if p.category else "-", p.status]
                for p in products
            ],
            "total": qs.count(),
        }

    def _exec_product_by_stream(self, params):
        return self._exec_product_list(params)

    def _exec_product_by_status(self, params):
        from products.models import Product

        qs = Product.objects.select_related("stream", "category")
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("stream"):
            qs = qs.filter(stream__name=params["stream"])
        limit = params.get("limit", 50)
        products = qs[:limit]
        return {
            "title": f"Products — {params.get('status', 'All')}",
            "chart_type": "table",
            "columns": ["Name", "Serial Number", "Stream", "Status"],
            "data": [[p.name, p.serial_number, str(p.stream), p.status] for p in products],
            "total": qs.count(),
        }

    def _exec_product_count(self, params):
        from products.models import Product

        qs = Product.objects.all()
        if params.get("stream"):
            qs = qs.filter(stream__name=params["stream"])
        count = qs.count()
        by_status = dict(qs.values_list("status").annotate(c=Count("id")).values_list("status", "c"))
        return {
            "title": "Product Count",
            "chart_type": "stat_card",
            "value": count,
            "breakdown": by_status,
        }

    def _exec_product_count_by_stream(self, params):
        from products.models import Product

        data = list(Product.objects.values("stream__name").annotate(count=Count("id")).order_by("-count"))
        return {
            "title": "Products per Stream",
            "chart_type": "bar",
            "labels": [d["stream__name"] or "No Stream" for d in data],
            "values": [d["count"] for d in data],
            "data": [[d["stream__name"] or "No Stream", d["count"]] for d in data],
            "columns": ["Stream", "Count"],
        }

    def _exec_product_expiring(self, params):
        from products.models import Product

        _cutoff = timezone.now().date() + timedelta(days=90)
        # Products with handover or warranty expiry logic
        products = Product.objects.filter(status="Active").select_related("stream", "category")[:50]
        # Without explicit expiry field, show all active with lifecycle
        return {
            "title": "Active Products (review for expiration)",
            "chart_type": "table",
            "columns": ["Name", "Serial Number", "Stream", "Status"],
            "data": [[p.name, p.serial_number, str(p.stream), p.status] for p in products],
            "total": products.count() if hasattr(products, "count") else len(products),
        }

    def _exec_system_status(self, params):
        from products.models import System

        qs = System.objects.select_related("stream")
        if params.get("stream"):
            qs = qs.filter(stream__name=params["stream"])
        systems = qs[:50]
        by_status = dict(qs.values_list("status").annotate(c=Count("id")).values_list("status", "c"))
        return {
            "title": "System Status",
            "chart_type": "pie",
            "labels": list(by_status.keys()),
            "values": list(by_status.values()),
            "data": [[s.name, s.status, s.health, f"{s.utilization_percentage or 0}%", str(s.stream)] for s in systems],
            "columns": ["System", "Status", "Health", "Utilization", "Stream"],
            "total": qs.count(),
        }

    def _exec_system_utilization(self, params):
        from products.models import System

        qs = System.objects.select_related("stream").order_by("-utilization_percentage")
        if params.get("stream"):
            qs = qs.filter(stream__name=params["stream"])
        systems = qs[:20]
        return {
            "title": "System Utilization",
            "chart_type": "bar",
            "labels": [s.name for s in systems],
            "values": [float(s.utilization_percentage or 0) for s in systems],
            "data": [[s.name, f"{s.utilization_percentage or 0}%", s.status, str(s.stream)] for s in systems],
            "columns": ["System", "Utilization", "Status", "Stream"],
        }

    def _exec_calibration_due(self, params):
        from products.models import CalibrationSchedule

        today = timezone.now().date()
        qs = (
            CalibrationSchedule.objects.filter(next_calibration_date__lte=today + timedelta(days=30))
            .select_related("stream")
            .order_by("next_calibration_date")
        )
        if params.get("stream"):
            qs = qs.filter(stream__name=params["stream"])
        items = qs[:30]
        return {
            "title": "Calibrations Due (Next 30 Days)",
            "chart_type": "table",
            "columns": ["Title", "Type", "Next Date", "Status", "Stream"],
            "data": [
                [s.title, s.calibration_type, str(s.next_calibration_date), s.status, str(s.stream)] for s in items
            ],
            "total": qs.count(),
        }

    def _exec_calibration_results(self, params):
        from products.models import CalibrationRecord

        qs = CalibrationRecord.objects.select_related("calibration_schedule")
        if params.get("stream"):
            qs = qs.filter(calibration_schedule__stream__name=params["stream"])
        by_result = dict(qs.values_list("result").annotate(c=Count("id")).values_list("result", "c"))
        total = qs.count()
        return {
            "title": "Calibration Results",
            "chart_type": "pie",
            "labels": list(by_result.keys()),
            "values": list(by_result.values()),
            "total": total,
        }

    def _exec_reservation_summary(self, params):
        from products.models import RecurringReservation

        qs = RecurringReservation.objects.select_related("system", "stream", "reserved_for")
        if params.get("stream"):
            qs = qs.filter(stream__name=params["stream"])
        active = qs.filter(status="active")
        by_status = dict(qs.values_list("status").annotate(c=Count("id")).values_list("status", "c"))
        return {
            "title": "Reservation Summary",
            "chart_type": "pie",
            "labels": list(by_status.keys()),
            "values": list(by_status.values()),
            "total": qs.count(),
            "data": [[r.title, str(r.system), str(r.reserved_for), r.status, str(r.start_date)] for r in active[:20]],
            "columns": ["Title", "System", "Reserved For", "Status", "Start Date"],
        }

    def _exec_reservation_conflicts(self, params):
        from products.models import ReservationConflict

        qs = ReservationConflict.objects.select_related("system", "stream")
        if params.get("stream"):
            qs = qs.filter(stream__name=params["stream"])
        conflicts = qs.filter(resolution_status="unresolved")[:20]
        return {
            "title": "Unresolved Reservation Conflicts",
            "chart_type": "table",
            "columns": ["System", "Conflict Type", "Status", "Stream"],
            "data": [[str(c.system), c.conflict_type, c.resolution_status, str(c.stream)] for c in conflicts],
            "total": qs.filter(resolution_status="unresolved").count(),
        }

    def _exec_alert_summary(self, params):
        from products.models import InventoryAlert

        qs = InventoryAlert.objects.select_related("stream")
        if params.get("stream"):
            qs = qs.filter(stream__name=params["stream"])
        by_status = dict(qs.values_list("status").annotate(c=Count("id")).values_list("status", "c"))
        active = qs.exclude(status="resolved")[:20]
        return {
            "title": "Inventory Alert Summary",
            "chart_type": "pie",
            "labels": list(by_status.keys()),
            "values": list(by_status.values()),
            "data": [[a.title, a.severity, a.status, a.item_name, str(a.stream or "-")] for a in active],
            "columns": ["Title", "Severity", "Status", "Item", "Stream"],
            "total": qs.count(),
        }

    def _exec_low_stock(self, params):
        from products.models import InventoryAlert

        qs = (
            InventoryAlert.objects.filter(alert_type__in=["low_stock", "critical_stock"])
            .exclude(status="resolved")
            .select_related("stream")
        )
        if params.get("stream"):
            qs = qs.filter(stream__name=params["stream"])
        alerts = qs[:30]
        return {
            "title": "Low Stock Items",
            "chart_type": "table",
            "columns": ["Item", "Current Qty", "Threshold", "Severity", "Stream"],
            "data": [
                [a.item_name, a.current_quantity, a.threshold_value, a.severity, str(a.stream or "-")] for a in alerts
            ],
            "total": qs.count(),
        }

    def _exec_build_server_status(self, params):
        from products.models import BuildServer

        qs = BuildServer.objects.select_related("stream")
        if params.get("stream"):
            qs = qs.filter(stream__name=params["stream"])
        by_status = dict(qs.values_list("status").annotate(c=Count("id")).values_list("status", "c"))
        servers = qs[:30]
        return {
            "title": "Build Server Status",
            "chart_type": "pie",
            "labels": list(by_status.keys()),
            "values": list(by_status.values()),
            "data": [[s.hostname, s.ip_address, s.status, s.stream_type, str(s.stream)] for s in servers],
            "columns": ["Hostname", "IP", "Status", "Type", "Stream"],
            "total": qs.count(),
        }

    def _exec_maintenance_upcoming(self, params):
        from products.models import MaintenanceEvent

        now = timezone.now()
        qs = (
            MaintenanceEvent.objects.filter(start_datetime__gte=now, status__in=["scheduled", "in_progress"])
            .select_related("stream", "assigned_to")
            .order_by("start_datetime")
        )
        if params.get("stream"):
            qs = qs.filter(stream__name=params["stream"])
        events = qs[:20]
        return {
            "title": "Upcoming Maintenance",
            "chart_type": "table",
            "columns": ["Title", "Type", "Start", "Priority", "Assigned To", "Stream"],
            "data": [
                [
                    e.title,
                    e.event_type,
                    str(e.start_datetime.strftime("%Y-%m-%d %H:%M")),
                    e.priority,
                    str(e.assigned_to) if e.assigned_to else "-",
                    str(e.stream or "-"),
                ]
                for e in events
            ],
            "total": qs.count(),
        }

    def _exec_lifecycle_summary(self, params):
        from products.models import AssetLifecycleRecord

        qs = AssetLifecycleRecord.objects.select_related("current_stage", "product", "product__stream")
        if params.get("stream"):
            qs = qs.filter(product__stream__name=params["stream"])
        by_stage = dict(
            qs.values_list("current_stage__name").annotate(c=Count("id")).values_list("current_stage__name", "c")
        )
        by_condition = dict(qs.values_list("condition").annotate(c=Count("id")).values_list("condition", "c"))
        return {
            "title": "Asset Lifecycle Summary",
            "chart_type": "bar",
            "labels": list(by_stage.keys()),
            "values": list(by_stage.values()),
            "extra_charts": [
                {
                    "title": "By Condition",
                    "type": "pie",
                    "labels": list(by_condition.keys()),
                    "values": list(by_condition.values()),
                }
            ],
            "total": qs.count(),
        }

    def _exec_compliance_status(self, params):
        from products.models import ComplianceDocument

        qs = ComplianceDocument.objects.select_related("stream")
        if params.get("stream"):
            qs = qs.filter(stream__name=params["stream"])
        by_status = dict(qs.values_list("status").annotate(c=Count("id")).values_list("status", "c"))
        expired = qs.filter(expiry_date__lt=timezone.now().date()).count()
        return {
            "title": "Compliance Document Status",
            "chart_type": "pie",
            "labels": list(by_status.keys()),
            "values": list(by_status.values()),
            "total": qs.count(),
            "extra_info": {"expired_documents": expired},
        }

    def _exec_top_users(self, params):
        from products.models import AuditLog

        data = list(AuditLog.objects.values("user__username").annotate(actions=Count("id")).order_by("-actions")[:10])
        return {
            "title": "Most Active Users",
            "chart_type": "bar",
            "labels": [d["user__username"] or "System" for d in data],
            "values": [d["actions"] for d in data],
            "columns": ["User", "Actions"],
            "data": [[d["user__username"] or "System", d["actions"]] for d in data],
        }

    def _exec_stream_overview(self, params):
        from products.models import Product, Stream, System

        streams = Stream.objects.filter(is_active=True)
        data = []
        for s in streams:
            products = Product.objects.filter(stream=s).count()
            systems = System.objects.filter(stream=s).count()
            data.append([s.name, products, systems])
        return {
            "title": "Stream Overview",
            "chart_type": "table",
            "columns": ["Stream", "Products", "Systems"],
            "data": data,
        }

    def _exec_unknown(self, params):
        return {
            "title": "Couldn't understand query",
            "chart_type": "text",
            "data": [],
            "suggestions": self._get_suggestions(),
        }

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------
    @staticmethod
    def train_classifier():
        """Train the intent classifier on predefined training data."""
        try:
            import joblib
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.naive_bayes import MultinomialNB

            os.makedirs(AI_MODELS_DIR, exist_ok=True)

            texts = []
            labels = []
            label_map = {}

            for i, (intent, examples) in enumerate(TRAINING_DATA.items()):
                label_map[i] = intent
                for ex in examples:
                    # Generate variations
                    texts.append(ex)
                    labels.append(i)
                    # Also add without template markers
                    clean = re.sub(r"\{[^}]+\}", "", ex).strip()
                    if clean != ex:
                        texts.append(clean)
                        labels.append(i)

            vectorizer = TfidfVectorizer(max_features=3000, ngram_range=(1, 2), stop_words="english")
            features = vectorizer.fit_transform(texts)

            classifier = MultinomialNB(alpha=0.1)
            classifier.fit(features, labels)

            model_data = {
                "vectorizer": vectorizer,
                "classifier": classifier,
                "label_map": label_map,
                "trained_at": datetime.now().isoformat(),
                "sample_count": len(texts),
            }
            joblib.dump(model_data, os.path.join(AI_MODELS_DIR, "nl_query_classifier.joblib"))

            return {"success": True, "samples": len(texts), "intents": len(label_map)}
        except ImportError as e:
            return {"success": False, "error": f"Missing dependency: {e}"}
        except Exception:
            return {"success": False, "error": "An unexpected error occurred"}
