"""
Management command to train / retrain local AI models.

Usage:
    python manage.py train_ai_models                    # train all
    python manage.py train_ai_models --model nl_query   # train specific
    python manage.py train_ai_models --model doc_classifier
"""

# pylint: disable=broad-exception-caught,import-outside-toplevel,missing-class-docstring
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Train or retrain local AI models (NL Query classifier, Document classifier)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--model",
            type=str,
            default="all",
            choices=["all", "nl_query", "doc_classifier"],
            help="Specify which model to train (default: all)",
        )

    def handle(self, *args, **options):
        model_type = options["model"]
        results = {}

        if model_type in ("all", "nl_query"):
            self.stdout.write(self.style.NOTICE("Training NL Query classifier..."))
            results["nl_query"] = self._train_nl_query()

        if model_type in ("all", "doc_classifier"):
            self.stdout.write(self.style.NOTICE("Training Document classifier..."))
            results["doc_classifier"] = self._train_doc_classifier()

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Training Summary"))
        for name, result in results.items():
            if result.get("success"):
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  ✓ {name}: {result.get("samples", 0)} samples, ' f'accuracy={result.get("accuracy", 0):.2%}'
                    )
                )
            else:
                self.stdout.write(self.style.ERROR(f'  ✗ {name}: {result.get("error", "Unknown error")}'))

    def _train_nl_query(self):
        try:
            from products.ai.nl_query import NLQueryEngine

            result = NLQueryEngine.train_classifier()
            self._log_training("nl_query", result)
            return result
        except Exception:
            self.stderr.write(self.style.ERROR("  Error: An unexpected error occurred"))
            return {"success": False, "error": "An unexpected error occurred"}

    def _train_doc_classifier(self):
        try:
            from products.ai.document_ocr import DocumentOCREngine

            result = DocumentOCREngine.train_classifier()
            self._log_training("doc_classifier", result)
            return result
        except Exception:
            self.stderr.write(self.style.ERROR("Error: An unexpected error occurred"))
            return {"success": False, "error": "An unexpected error occurred"}

    def _log_training(self, model_type, result):
        """Log training result to the database."""
        try:
            import os

            from products.models import AIModelTrainingLog

            AIModelTrainingLog.objects.create(
                model_type=model_type,
                trained_by=None,  # CLI — no user context
                training_samples=result.get("samples", 0),
                training_result=result,
                was_successful=result.get("success", False),
                error_message=result.get("error", ""),
                model_file_path=os.path.join("ai_models", f"{model_type}.joblib"),
            )
        except Exception:
            pass  # Non-critical — don't fail training over a log write
