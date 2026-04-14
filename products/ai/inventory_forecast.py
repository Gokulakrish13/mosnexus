"""
AI Engine 4: Predictive Inventory Forecasting
===============================================
Uses historical inventory data to train time-series models
(Exponential Smoothing + Linear Regression) per category/stream.
Projects future stock levels with confidence intervals.
Flags items predicted to go below threshold.
"""

# pylint: disable=broad-exception-caught,import-outside-toplevel,invalid-name,no-else-break,too-complex,too-many-locals,unused-argument,wrong-import-position
import logging
import os
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

AI_MODELS_DIR = os.path.join(settings.BASE_DIR, "ai_models")


class InventoryForecastEngine:
    """Predictive inventory forecasting using local ML models."""

    def __init__(self):
        self._models = {}

    # ------------------------------------------------------------------
    # Data collection
    # ------------------------------------------------------------------
    def _get_historical_data(self, stream=None, category=None):
        """Collect historical inventory data from ProductHistory and AuditLog."""
        from products.models import InventoryAlert, Product, ProductHistory

        filters = {}
        if stream:
            filters["stream__name"] = stream if isinstance(stream, str) else stream.name

        products = Product.objects.filter(**filters)
        if category:
            products = products.filter(category=category)

        # Build time series from product history
        history = ProductHistory.objects.filter(product__in=products).order_by("timestamp")

        # Group by date: count active products per day
        daily_counts = defaultdict(int)
        date_cursor = timezone.now().date() - timedelta(days=365)
        end_date = timezone.now().date()

        # Get current count
        current_count = products.filter(status="Active").count()

        # Walk through history to reconstruct daily counts
        while date_cursor <= end_date:
            daily_counts[date_cursor] = current_count  # Baseline
            date_cursor += timedelta(days=1)

        # Adjust based on historical events
        for h in history:
            action_date = h.timestamp.date() if hasattr(h.timestamp, "date") else h.timestamp
            action = h.action.lower() if h.action else ""
            if "create" in action or "add" in action:
                # Items added after this date
                for d in list(daily_counts.keys()):
                    if d < action_date:
                        daily_counts[d] = max(0, daily_counts[d] - 1)
            elif "delete" in action or "remove" in action or "scrap" in action:
                for d in list(daily_counts.keys()):
                    if d >= action_date:
                        daily_counts[d] = max(0, daily_counts[d])

        # Also incorporate inventory alerts as data points
        alerts = InventoryAlert.objects.filter(stream__in=products.values("stream")).order_by("created_at")

        alert_series = []
        for alert in alerts:
            if alert.current_quantity is not None:
                alert_date = alert.created_at.date() if hasattr(alert.created_at, "date") else alert.created_at
                alert_series.append(
                    {
                        "date": alert_date,
                        "quantity": alert.current_quantity,
                        "item": alert.item_name,
                    }
                )

        # Convert to sorted list
        sorted_dates = sorted(daily_counts.keys())
        values = [daily_counts[d] for d in sorted_dates]

        return {
            "dates": sorted_dates,
            "values": values,
            "alert_series": alert_series,
            "current_count": current_count,
            "product_count": products.count(),
        }

    # ------------------------------------------------------------------
    # Forecasting
    # ------------------------------------------------------------------
    def forecast(self, stream=None, category=None, days_ahead=90):
        """Generate inventory forecast."""
        data = self._get_historical_data(stream, category)

        if len(data["values"]) < 14:
            return self._insufficient_data_response(data, days_ahead)

        results = {}

        # Method 1: Simple Moving Average
        sma_forecast = self._simple_moving_average(data["values"], days_ahead)
        results["moving_average"] = sma_forecast

        # Method 2: Linear Regression
        lr_forecast = self._linear_regression(data["values"], days_ahead)
        results["linear_regression"] = lr_forecast

        # Method 3: Exponential Smoothing (if statsmodels available)
        es_forecast = self._exponential_smoothing(data["values"], days_ahead)
        if es_forecast:
            results["exponential_smoothing"] = es_forecast

        # Pick best model (lowest error on last 20% holdout)
        best_method = self._select_best_model(data["values"], results)

        last_date = data["dates"][-1] if data["dates"] else timezone.now().date()
        forecast_dates = [last_date + timedelta(days=i + 1) for i in range(days_ahead)]

        best_forecast = results[best_method]

        threshold_warnings = self._check_threshold_breaches(stream, best_forecast["forecast"], forecast_dates)

        trend = self._compute_trend(data["values"])

        return {
            "success": True,
            "historical": {
                "dates": [str(d) for d in data["dates"][-90:]],  # Last 90 days
                "values": data["values"][-90:],
            },
            "forecast": {
                "dates": [str(d) for d in forecast_dates],
                "values": [round(v, 1) for v in best_forecast["forecast"]],
                "upper_bound": [round(v, 1) for v in best_forecast.get("upper_bound", best_forecast["forecast"])],
                "lower_bound": [round(v, 1) for v in best_forecast.get("lower_bound", best_forecast["forecast"])],
            },
            "method": best_method,
            "all_methods": {
                k: {
                    "forecast_end": round(v["forecast"][-1], 1) if v.get("forecast") else 0,
                    "error": round(v.get("error", 0), 2),
                }
                for k, v in results.items()
            },
            "trend": trend,
            "threshold_warnings": threshold_warnings,
            "current_count": data["current_count"],
            "summary": self._generate_summary(data, best_forecast, trend, threshold_warnings),
        }

    def _simple_moving_average(self, values, days_ahead, window=14):
        """Forecast using Simple Moving Average."""
        window = min(window, len(values))

        forecast = []
        working = list(values[-window:])

        for _ in range(days_ahead):
            avg = sum(working[-window:]) / window
            forecast.append(avg)
            working.append(avg)

        # Error on holdout
        if len(values) > window + 10:
            holdout_size = min(len(values) // 5, 30)
            train = values[:-holdout_size]
            actual = values[-holdout_size:]
            pred = []
            w = list(train[-window:])
            for _ in range(holdout_size):
                avg = sum(w[-window:]) / window
                pred.append(avg)
                w.append(avg)
            error = sum((a - p) ** 2 for a, p in zip(actual, pred)) / holdout_size
        else:
            error = float("inf")

        return {
            "forecast": forecast,
            "error": error,
            "upper_bound": [f + max(1, abs(f * 0.1)) for f in forecast],
            "lower_bound": [max(0, f - max(1, abs(f * 0.1))) for f in forecast],
        }

    def _linear_regression(self, values, days_ahead):
        """Forecast using Linear Regression."""
        n = len(values)
        x = list(range(n))
        x_mean = sum(x) / n
        y_mean = sum(values) / n

        numerator = sum((x[i] - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            slope = 0
            intercept = y_mean
        else:
            slope = numerator / denominator
            intercept = y_mean - slope * x_mean

        forecast = [max(0, slope * (n + i) + intercept) for i in range(days_ahead)]

        # Prediction error (RMSE on holdout)
        holdout_size = min(n // 5, 30) if n > 20 else 0
        if holdout_size > 0:
            train_n = n - holdout_size
            actual = values[-holdout_size:]
            pred = [slope * (train_n + i) + intercept for i in range(holdout_size)]
            error = sum((a - p) ** 2 for a, p in zip(actual, pred)) / holdout_size
        else:
            error = float("inf")

        # Confidence interval (based on residuals)
        residuals = [values[i] - (slope * i + intercept) for i in range(n)]
        if len(residuals) > 1:
            import statistics as stat

            std_residual = stat.stdev(residuals)
        else:
            std_residual = 1

        return {
            "forecast": forecast,
            "error": error,
            "slope": slope,
            "intercept": intercept,
            "upper_bound": [f + 1.96 * std_residual for f in forecast],
            "lower_bound": [max(0, f - 1.96 * std_residual) for f in forecast],
        }

    def _exponential_smoothing(self, values, days_ahead):
        """Forecast using Exponential Smoothing."""
        try:
            from statsmodels.tsa.holtwinters import SimpleExpSmoothing

            model = SimpleExpSmoothing(values).fit(optimized=True)
            forecast_result = model.forecast(days_ahead)
            forecast = [max(0, float(v)) for v in forecast_result]

            # Error on holdout
            holdout_size = min(len(values) // 5, 30) if len(values) > 20 else 0
            if holdout_size > 0:
                train = values[:-holdout_size]
                actual = values[-holdout_size:]
                m = SimpleExpSmoothing(train).fit(optimized=True)
                pred = [float(v) for v in m.forecast(holdout_size)]
                error = sum((a - p) ** 2 for a, p in zip(actual, pred)) / holdout_size
            else:
                error = float("inf")

            # Confidence interval
            import statistics as stat

            residuals = [values[i] - float(model.fittedvalues[i]) for i in range(len(values))]
            std_r = stat.stdev(residuals) if len(residuals) > 1 else 1

            return {
                "forecast": forecast,
                "error": error,
                "upper_bound": [f + 1.96 * std_r for f in forecast],
                "lower_bound": [max(0, f - 1.96 * std_r) for f in forecast],
            }
        except ImportError:
            logger.debug("statsmodels not available for exponential smoothing")
            return None
        except Exception:
            logger.debug("Exponential smoothing failed")
            return None

    def _select_best_model(self, values, results):
        """Select the model with lowest holdout error."""
        best = None
        best_error = float("inf")
        for method, result in results.items():
            if result and result.get("error", float("inf")) < best_error:
                best_error = result["error"]
                best = method
        return best or "moving_average"

    def _compute_trend(self, values):
        """Compute overall trend direction and strength."""
        if len(values) < 7:
            return {"direction": "stable", "strength": 0, "change_rate": 0}

        recent = values[-7:]
        older = values[-14:-7] if len(values) >= 14 else values[:7]

        recent_avg = sum(recent) / len(recent)
        older_avg = sum(older) / len(older)

        if older_avg == 0:
            change_rate = 0
        else:
            change_rate = (recent_avg - older_avg) / older_avg * 100

        if abs(change_rate) < 2:
            direction = "stable"
            strength = "low"
        elif abs(change_rate) < 10:
            direction = "increasing" if change_rate > 0 else "decreasing"
            strength = "moderate"
        else:
            direction = "increasing" if change_rate > 0 else "decreasing"
            strength = "strong"

        return {
            "direction": direction,
            "strength": strength,
            "change_rate": round(change_rate, 1),
            "recent_avg": round(recent_avg, 1),
            "older_avg": round(older_avg, 1),
        }

    def _check_threshold_breaches(self, stream, forecast_values, forecast_dates):
        """Check if forecast predicts threshold breaches."""
        from products.models import InventoryThreshold

        if stream is None:
            return []

        thresholds = InventoryThreshold.objects.filter(
            Q(stream__name=stream) if isinstance(stream, str) else Q(stream=stream), is_active=True
        )

        warnings = []
        for threshold in thresholds:
            min_qty = threshold.minimum_quantity or 0
            critical_qty = threshold.critical_quantity or 0

            for i, val in enumerate(forecast_values):
                if val <= critical_qty and critical_qty > 0:
                    warnings.append(
                        {
                            "threshold": threshold.name,
                            "type": "critical",
                            "predicted_date": str(forecast_dates[i]),
                            "predicted_value": round(val, 1),
                            "threshold_value": critical_qty,
                            "days_until": i + 1,
                        }
                    )
                    break
                elif val <= min_qty and min_qty > 0:
                    warnings.append(
                        {
                            "threshold": threshold.name,
                            "type": "warning",
                            "predicted_date": str(forecast_dates[i]),
                            "predicted_value": round(val, 1),
                            "threshold_value": min_qty,
                            "days_until": i + 1,
                        }
                    )
                    break

        return warnings

    def _generate_summary(self, data, forecast, trend, warnings):
        """Generate human-readable forecast summary."""
        lines = []

        lines.append(f"Current inventory level: {data['current_count']} items")

        if trend["direction"] == "stable":
            lines.append("Inventory levels are stable with minimal change.")
        elif trend["direction"] == "increasing":
            lines.append(f"Inventory is trending upward ({trend['change_rate']:+.1f}% weekly change).")
        else:
            lines.append(f"Inventory is trending downward ({trend['change_rate']:+.1f}% weekly change).")

        if forecast.get("forecast"):
            end_val = round(forecast["forecast"][-1], 1)
            lines.append(f"Predicted level in {len(forecast['forecast'])} days: ~{end_val} items.")

        if warnings:
            critical_warnings = [w for w in warnings if w["type"] == "critical"]
            if critical_warnings:
                earliest = min(critical_warnings, key=lambda w: w["days_until"])
                lines.append(
                    f"⚠ CRITICAL: {earliest['threshold']} threshold breach predicted "
                    f"in {earliest['days_until']} days ({earliest['predicted_date']})."
                )

        return " ".join(lines)

    def _insufficient_data_response(self, data, days_ahead):
        return {
            "success": True,
            "historical": {"dates": [], "values": []},
            "forecast": {"dates": [], "values": [], "upper_bound": [], "lower_bound": []},
            "method": "insufficient_data",
            "all_methods": {},
            "trend": {"direction": "unknown", "strength": "none", "change_rate": 0},
            "threshold_warnings": [],
            "current_count": data["current_count"],
            "summary": f"Insufficient historical data for forecasting. "
            f"Current inventory: {data['current_count']} items. "
            f"Need at least 14 days of data.",
        }


from django.db.models import Q
