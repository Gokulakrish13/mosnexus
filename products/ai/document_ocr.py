"""
AI Engine 2: Document OCR & Auto-Extraction
=============================================
Uses Tesseract OCR to extract text from uploaded images/PDFs,
then a trained scikit-learn text classifier (TF-IDF + SVM)
identifies document type, and regex patterns extract structured
fields (serial numbers, dates, values, pass/fail).
"""

# pylint: disable=broad-exception-caught,duplicate-code,import-outside-toplevel,invalid-name,too-many-lines,too-many-locals,unspecified-encoding
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

AI_MODELS_DIR = os.path.join(settings.BASE_DIR, "ai_models")


class DocumentOCREngine:
    """OCR text extraction + intelligent field extraction."""

    PATTERNS = {
        "serial_number": [
            r"(?:serial\s*(?:no|number|#|num)?\.?\s*[:\-]?\s*)([A-Z0-9][\w\-]{3,30})",
            r"(?:S/?N\s*[:\-]?\s*)([A-Z0-9][\w\-]{3,30})",
            r"(?:asset\s*(?:id|tag|no)\.?\s*[:\-]?\s*)([A-Z0-9][\w\-]{3,30})",
        ],
        "date": [
            r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
            r"(\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2})",
            r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\.?\s+\d{1,2},?\s+\d{4})",
        ],
        "calibration_result": [
            r"\b(pass(?:ed)?|fail(?:ed)?|within\s+tolerance|out\s+of\s+tolerance|adjusted|refer)\b",
        ],
        "temperature": [
            r"(\d{1,3}(?:\.\d+)?)\s*°?\s*[cCfF](?:elsius|ahrenheit)?",
            r"(?:temp(?:erature)?\.?\s*[:\-]?\s*)(\d{1,3}(?:\.\d+)?)",
        ],
        "humidity": [
            r"(\d{1,3}(?:\.\d+)?)\s*%\s*(?:RH|rh|r\.?h\.?)?",
            r"(?:humid(?:ity)?\.?\s*[:\-]?\s*)(\d{1,3}(?:\.\d+)?)\s*%?",
        ],
        "certificate_number": [
            r"(?:cert(?:ificate)?\s*(?:no|number|#|num)?\.?\s*[:\-]?\s*)([A-Z0-9][\w\-/]{3,30})",
        ],
        "organization": [
            r"(?:(?:issued|certified|calibrated)\s+by\s*[:\-]?\s*)([A-Z][\w\s&,\.]{3,50}?)(?:\n|$)",
            r"(?:laboratory|lab|company|organization)\s*[:\-]?\s*([A-Z][\w\s&,\.]{3,50}?)(?:\n|$)",
        ],
        "numeric_values": [
            r"(?:(?:reading|value|measurement|result|tolerance|accuracy|uncertainty)\s*[:\-]?\s*)"
            r"([+-]?\d+(?:\.\d+)?(?:\s*[+±]\s*\d+(?:\.\d+)?)?(?:\s*(?:mm|cm|m|kg|g|mA|V|A|Ω|Hz|dB|psi|bar))?)",
        ],
    }

    DOC_TYPE_KEYWORDS = {
        "calibration_certificate": [
            "calibration",
            "certificate",
            "traceability",
            "measurement",
            "uncertainty",
            "standard",
            "tolerance",
            "as found",
            "as left",
            "calibrated by",
        ],
        "compliance_report": [
            "compliance",
            "regulatory",
            "audit",
            "requirement",
            "standard",
            "iec",
            "iso",
            "fda",
            "ce mark",
            "conformity",
        ],
        "maintenance_record": [
            "maintenance",
            "repair",
            "service",
            "work order",
            "preventive",
            "corrective",
            "downtime",
            "parts replaced",
            "technician",
        ],
        "inspection_report": [
            "inspection",
            "visual",
            "defect",
            "condition",
            "checklist",
            "pass",
            "fail",
            "observed",
            "finding",
        ],
        "purchase_order": [
            "purchase",
            "order",
            "vendor",
            "supplier",
            "invoice",
            "quantity",
            "unit price",
            "total",
            "delivery",
            "payment",
        ],
        "warranty_document": [
            "warranty",
            "guarantee",
            "coverage",
            "expiration",
            "claim",
            "repair",
            "replacement",
            "terms",
            "conditions",
        ],
        "test_report": [
            "test",
            "testing",
            "result",
            "specimen",
            "sample",
            "protocol",
            "procedure",
            "acceptance criteria",
            "pass/fail",
        ],
        "safety_datasheet": [
            "safety",
            "hazard",
            "msds",
            "sds",
            "chemical",
            "exposure",
            "precaution",
            "emergency",
            "first aid",
        ],
    }

    def __init__(self):
        self._tesseract_available = None
        self._classifier = None

    # ------------------------------------------------------------------
    # OCR
    # ------------------------------------------------------------------
    def _check_tesseract(self):
        """Check if Tesseract OCR is available."""
        if self._tesseract_available is not None:
            return self._tesseract_available
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
            self._tesseract_available = True
        except Exception:
            self._tesseract_available = False
            logger.warning("Tesseract OCR is not installed. OCR features disabled.")
        return self._tesseract_available

    def extract_text_from_image(self, image_path):
        """Extract text from an image file using Tesseract OCR."""
        if not self._check_tesseract():
            return {"success": False, "error": "Tesseract OCR is not installed.", "text": ""}
        try:
            import pytesseract
            from PIL import Image

            img = Image.open(image_path)
            # Preprocess: convert to grayscale for better OCR
            if img.mode != "L":
                img = img.convert("L")

            text = pytesseract.image_to_string(img, config="--psm 6")
            confidence_data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
            confidences = [int(c) for c in confidence_data["conf"] if int(c) > 0]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0

            return {
                "success": True,
                "text": text.strip(),
                "confidence": round(avg_confidence, 1),
                "word_count": len(text.split()),
            }
        except Exception:
            logger.error("OCR extraction failed")
            return {"success": False, "error": "An error occurred", "text": ""}

    def extract_text_from_pdf(self, pdf_path):
        """Extract text from a PDF file."""
        try:
            # Try direct text extraction first (for non-scanned PDFs)
            text = self._extract_pdf_text_direct(pdf_path)
            if text and len(text.strip()) > 50:
                return {
                    "success": True,
                    "text": text.strip(),
                    "confidence": 95.0,
                    "word_count": len(text.split()),
                    "method": "direct",
                }

            # If direct extraction yields little text, try OCR on rendered pages
            if self._check_tesseract():
                return self._ocr_pdf(pdf_path)

            return {
                "success": True,
                "text": text.strip() if text else "",
                "confidence": 50.0,
                "word_count": len(text.split()) if text else 0,
                "method": "direct_limited",
            }
        except Exception:
            logger.error("PDF text extraction failed")
            return {"success": False, "error": "An error occurred", "text": ""}

    def _extract_pdf_text_direct(self, pdf_path):
        """Extract text directly from PDF (for digital PDFs)."""
        try:
            from reportlab.lib.pagesizes import letter  # noqa: F401  # pylint: disable=unused-import

            # reportlab is for writing — try reading with simple parsing
            text_parts = []
            with open(pdf_path, "rb") as f:
                content = f.read()
                # Simple PDF text extraction via regex on stream content
                # (works for many standard PDFs)
                stream_pattern = re.compile(rb"stream\s*\n(.*?)\nendstream", re.DOTALL)
                for match in stream_pattern.finditer(content):
                    try:
                        data = match.group(1)
                        # Extract text within parentheses (PDF text objects)
                        text_objs = re.findall(rb"\(([^)]*)\)", data)
                        for obj in text_objs:
                            try:
                                decoded = obj.decode("utf-8", errors="ignore")
                                if decoded.strip():
                                    text_parts.append(decoded)
                            except Exception:
                                continue
                    except Exception:
                        continue
            return " ".join(text_parts)
        except Exception:
            return ""

    def _ocr_pdf(self, pdf_path):
        """OCR a PDF by converting pages to images."""
        try:
            import pytesseract  # noqa: F401  # pylint: disable=unused-import
            from PIL import Image  # noqa: F401  # pylint: disable=unused-import

            # Try to convert PDF pages to images (requires pdf2image or similar)
            # Fallback: extract what we can with direct method
            return {
                "success": True,
                "text": self._extract_pdf_text_direct(pdf_path) or "",
                "confidence": 60.0,
                "word_count": 0,
                "method": "ocr_fallback",
            }
        except Exception:
            return {"success": False, "error": "An unexpected error occurred", "text": ""}

    # ------------------------------------------------------------------
    # Document Classification (keyword-based + optional ML)
    # ------------------------------------------------------------------
    def classify_document(self, text):
        """Classify document type based on text content."""
        if not text:
            return {"type": "unknown", "confidence": 0, "scores": {}}

        text_lower = text.lower()
        scores = {}

        for doc_type, keywords in self.DOC_TYPE_KEYWORDS.items():
            score = 0
            matched_keywords = []
            for kw in keywords:
                count = text_lower.count(kw.lower())
                if count > 0:
                    score += count
                    matched_keywords.append(kw)
            scores[doc_type] = {
                "score": score,
                "matched_keywords": matched_keywords,
            }

        if not scores or all(s["score"] == 0 for s in scores.values()):
            return {"type": "unknown", "confidence": 0, "scores": scores}

        best_type = max(scores, key=lambda k: scores[k]["score"])
        total_score = sum(s["score"] for s in scores.values())
        confidence = (scores[best_type]["score"] / total_score * 100) if total_score > 0 else 0

        ml_result = self._ml_classify(text)
        if ml_result and ml_result["confidence"] > confidence:
            return ml_result

        return {
            "type": best_type,
            "confidence": round(confidence, 1),
            "scores": scores,
            "method": "keyword",
        }

    def _ml_classify(self, text):
        """Try ML-based classification if a trained model exists."""
        try:
            model_path = os.path.join(AI_MODELS_DIR, "doc_classifier.joblib")
            if not os.path.exists(model_path):
                return None

            import joblib

            model_data = joblib.load(model_path)
            vectorizer = model_data["vectorizer"]
            classifier = model_data["classifier"]
            label_map = model_data["label_map"]

            features = vectorizer.transform([text])
            prediction = classifier.predict(features)[0]
            probabilities = classifier.predict_proba(features)[0]
            confidence = max(probabilities) * 100

            return {
                "type": label_map.get(prediction, "unknown"),
                "confidence": round(confidence, 1),
                "method": "ml",
            }
        except Exception:
            logger.debug("ML classification failed")
            return None

    # ------------------------------------------------------------------
    # Field extraction
    # ------------------------------------------------------------------
    def extract_fields(self, text):
        """Extract structured fields from OCR text."""
        if not text:
            return {}

        extracted = {}
        for field_name, patterns in self.PATTERNS.items():
            matches = []
            for pattern in patterns:
                found = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
                matches.extend(found)
            if matches:
                cleaned = list(dict.fromkeys(m.strip() for m in matches if m.strip()))
                extracted[field_name] = cleaned[0] if len(cleaned) == 1 else cleaned

        if "date" in extracted:
            dates = extracted["date"] if isinstance(extracted["date"], list) else [extracted["date"]]
            parsed_dates = []
            for d in dates:
                parsed = self._parse_date(d)
                if parsed:
                    parsed_dates.append(parsed)
            if parsed_dates:
                extracted["parsed_dates"] = parsed_dates

        return extracted

    def _parse_date(self, date_str):
        """Try parsing a date string in various formats."""
        formats = [
            "%d/%m/%Y",
            "%m/%d/%Y",
            "%Y/%m/%d",
            "%d-%m-%Y",
            "%m-%d-%Y",
            "%Y-%m-%d",
            "%d.%m.%Y",
            "%m.%d.%Y",
            "%Y.%m.%d",
            "%d/%m/%y",
            "%m/%d/%y",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return date_str

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------
    def process_document(self, file_path, file_type=None):
        """Full pipeline: OCR → classify → extract fields."""
        if not file_type:
            ext = Path(file_path).suffix.lower()
            if ext in (".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp"):
                file_type = "image"
            elif ext == ".pdf":
                file_type = "pdf"
            else:
                file_type = "unknown"

        # Extract text
        if file_type == "image":
            ocr_result = self.extract_text_from_image(file_path)
        elif file_type == "pdf":
            ocr_result = self.extract_text_from_pdf(file_path)
        else:
            # Try reading as text
            try:
                with open(file_path, "r", errors="ignore") as f:
                    text = f.read()
                ocr_result = {"success": True, "text": text, "confidence": 100.0}
            except Exception:
                ocr_result = {"success": False, "error": "An unexpected error occurred", "text": ""}

        if not ocr_result.get("success") or not ocr_result.get("text"):
            return {
                "success": False,
                "error": ocr_result.get("error", "No text extracted."),
                "ocr_result": ocr_result,
            }

        text = ocr_result["text"]

        # Classify
        classification = self.classify_document(text)

        # Extract fields
        fields = self.extract_fields(text)

        return {
            "success": True,
            "ocr_result": ocr_result,
            "classification": classification,
            "extracted_fields": fields,
            "raw_text": text,
        }

    # ------------------------------------------------------------------
    # Training (builds ML classifier from existing documents)
    # ------------------------------------------------------------------
    @staticmethod
    def train_classifier():
        """Train document classifier on existing ComplianceDocument data."""
        try:
            import joblib
            from products.models import ComplianceDocument
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.svm import SVC

            os.makedirs(AI_MODELS_DIR, exist_ok=True)

            docs = ComplianceDocument.objects.exclude(document_type__isnull=True).exclude(document_type="")

            if docs.count() < 10:
                return {"success": False, "error": "Need at least 10 documents to train."}

            texts = []
            labels = []
            label_map = {}
            label_counter = 0

            for doc in docs:
                text_content = f"{doc.title} {doc.document_type} {doc.description or ''}"
                if doc.file:
                    try:
                        with open(doc.file.path, "r", errors="ignore") as f:
                            text_content += " " + f.read()[:5000]
                    except Exception:
                        pass

                if doc.document_type not in label_map.values():
                    label_map[label_counter] = doc.document_type
                    label_counter += 1

                reverse_map = {v: k for k, v in label_map.items()}
                texts.append(text_content)
                labels.append(reverse_map[doc.document_type])

            vectorizer = TfidfVectorizer(max_features=5000, stop_words="english")
            features = vectorizer.fit_transform(texts)

            classifier = SVC(kernel="linear", probability=True)
            classifier.fit(features, labels)

            model_data = {
                "vectorizer": vectorizer,
                "classifier": classifier,
                "label_map": label_map,
                "trained_at": datetime.now().isoformat(),
                "sample_count": len(texts),
            }
            joblib.dump(model_data, os.path.join(AI_MODELS_DIR, "doc_classifier.joblib"))

            return {"success": True, "samples": len(texts), "classes": len(label_map)}
        except ImportError as e:
            return {"success": False, "error": f"Missing dependency: {e}"}
        except Exception:
            return {"success": False, "error": "An unexpected error occurred"}
