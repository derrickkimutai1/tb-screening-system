"""
Model loading and prediction.

The model is loaded once, on the first prediction, and reused afterwards. It is
deliberately not loaded when Django starts: the file is 26 MB and loading it at
start-up would slow every management command, and the development autoreloader
would load it twice.

Thresholds and class order are read from the metadata file saved beside the
model, never hard-coded here. That is what lets a stored result be traced back
to the exact model and thresholds that produced it.
"""

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from .image_processing import ImageProcessor
from .triage import TriageJustifier

MODEL_DIR = Path(settings.ML_DIR) / "models"
MODEL_VERSION = "tb_mobilenetv2_v1"


class ModelUnavailable(RuntimeError):
    """Raised when no trained model is present."""


@dataclass(frozen=True)
class Prediction:
    probability: float
    label: str  # LIKELY_TB or UNLIKELY_TB
    triage_level: str
    triage_justification: str
    decision_threshold: float
    triage_low_medium: float
    triage_medium_high: float
    model_version: str
    inference_ms: int


class PredictionEngine:
    """Loads the trained model once and returns predictions for radiographs."""

    _model = None
    _metadata = None
    _lock = threading.Lock()

    def __init__(self):
        self.processor = ImageProcessor()
        self.triage = TriageJustifier()

    @classmethod
    def metadata(cls):
        if cls._metadata is None:
            path = MODEL_DIR / "metadata.json"
            if not path.exists():
                raise ModelUnavailable(f"No model metadata at {path}")
            cls._metadata = json.loads(path.read_text(encoding="utf-8"))
        return cls._metadata

    @classmethod
    def model(cls):
        """Load the model on first use, then reuse it for the process lifetime."""
        if cls._model is None:
            with cls._lock:
                if cls._model is None:
                    path = MODEL_DIR / f"{MODEL_VERSION}.keras"
                    if not path.exists():
                        raise ModelUnavailable(f"No trained model at {path}")
                    import keras

                    cls._model = keras.models.load_model(path)
        return cls._model

    @classmethod
    def is_available(cls):
        return (MODEL_DIR / f"{MODEL_VERSION}.keras").exists()

    def predict(self, source):
        """Score one radiograph and derive its label and triage level."""
        metadata = self.metadata()
        thresholds = metadata["thresholds"]
        decision = float(thresholds["decision"])
        low_medium = float(thresholds["triage_low_medium"])
        medium_high = float(thresholds["triage_medium_high"])

        model = self.model()
        batch = self.processor.as_model_input(source)

        started = time.perf_counter()
        probability = float(model.predict(batch, verbose=0).ravel()[0])
        elapsed_ms = int(round((time.perf_counter() - started) * 1000))

        # The positive class is 1, recorded in the metadata, so the sigmoid
        # output is the probability of TB rather than of its absence.
        label = "LIKELY_TB" if probability >= decision else "UNLIKELY_TB"
        decision_made = self.triage.decide(probability, low_medium, medium_high)

        return Prediction(
            probability=round(probability, 4),
            label=label,
            triage_level=decision_made.level,
            triage_justification=decision_made.justification,
            decision_threshold=decision,
            triage_low_medium=low_medium,
            triage_medium_high=medium_high,
            model_version=metadata.get("model_version", MODEL_VERSION),
            inference_ms=elapsed_ms,
        )
