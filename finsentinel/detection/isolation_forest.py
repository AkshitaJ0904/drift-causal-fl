
"""Isolation Forest anomaly detector for federated-learning updates.

This detector is an UNSUPERVISED statistical component that must be fit on a
representative sample of clean update feature vectors before flagging anomalies.

IMPORTANT: This detector does NOT replace the cryptographic, replay-protection,
or schema-validation security controls in the ingestion pipeline.  It is a
supplementary layer that adds statistical anomaly detection.  It is intentionally
kept separate from the ingestion service: wiring it in requires calibrated
thresholds and training data sourced from your production FL system.

Workflow
--------
1. Collect clean update feature vectors from a production deployment.
2. Instantiate ``IsolationForestDetector`` with an ``IsolationForestConfig``.
3. Call ``detector.fit(feature_vectors)`` with a sufficient number of vectors.
4. Persist the fitted detector with ``detector.save(path)``.
5. Load in the serving process: ``detector = IsolationForestDetector.load(path)``.
6. At ingestion time: ``result = detector.detect(features)``; handle anomalies.

Security notes
--------------
- Loaded detector files are deserialised with joblib.  Only load files from
  trusted, integrity-verified sources.  Do not load user-supplied files.
- The contamination parameter is set at fit time and applies to the training
  distribution.  Production data distributions may differ from training data.
- An "inlier" result does not guarantee the update is benign; it only means the
  update's features are consistent with the training distribution.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

try:
    import joblib
    _JOBLIB_AVAILABLE = True
except ImportError:
    _JOBLIB_AVAILABLE = False

try:
    from sklearn.ensemble import IsolationForest as _SklearnIsolationForest
    _SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SKLEARN_AVAILABLE = False


class IsolationForestError(Exception):
    """Base class for IsolationForest detector errors."""


class DetectorNotFittedError(IsolationForestError):
    """Raised when detect() is called on an unfitted detector."""


class FeatureMismatchError(IsolationForestError):
    """Raised when input features do not match the fitted feature set."""


class DetectorPersistenceError(IsolationForestError):
    """Raised when saving or loading a detector fails."""


@dataclass(frozen=True)
class IsolationForestConfig:
    """Configuration for the Isolation Forest detector.

    Attributes
    ----------
    feature_names:
        Ordered tuple of feature names the detector expects.  Must be non-empty.
        These must match the keys of every feature dict passed to ``fit`` and
        ``detect``.
    n_estimators:
        Number of trees.  Higher values reduce variance at the cost of memory.
    contamination:
        Estimated fraction of anomalies in the training set, or ``"auto"`` to
        use the sklearn default.  When set to ``"auto"`` the threshold is
        determined by the training data distribution alone; a numeric value
        biases the threshold toward flagging that fraction of training samples.
    random_state:
        Seed for reproducibility.  ``None`` for non-deterministic training.
    max_samples:
        Number of samples to draw per estimator, or ``"auto"`` for sklearn's
        default of min(256, n_samples).
    """

    feature_names: tuple[str, ...] = ()
    n_estimators: int = 100
    contamination: float | str = "auto"
    random_state: int | None = 42
    max_samples: int | str = "auto"

    def __post_init__(self) -> None:
        if not self.feature_names:
            raise ValueError("feature_names must be a non-empty tuple of strings.")

        for name in self.feature_names:
            if not isinstance(name, str) or not name:
                raise ValueError(f"Each feature name must be a non-empty string; got {name!r}.")

        if len(self.feature_names) != len(set(self.feature_names)):
            raise ValueError("feature_names must not contain duplicates.")

        if isinstance(self.n_estimators, bool) or not isinstance(self.n_estimators, int):
            raise ValueError("n_estimators must be a positive integer.")
        if self.n_estimators < 1:
            raise ValueError("n_estimators must be >= 1.")

        if isinstance(self.contamination, str):
            if self.contamination != "auto":
                raise ValueError('contamination must be "auto" or a float in (0, 0.5].')
        else:
            if isinstance(self.contamination, bool) or not isinstance(self.contamination, float):
                raise ValueError('contamination must be "auto" or a float in (0, 0.5].')
            if not (0.0 < self.contamination <= 0.5):
                raise ValueError("contamination must be in (0, 0.5] when numeric.")

        if self.random_state is not None:
            if isinstance(self.random_state, bool) or not isinstance(self.random_state, int):
                raise ValueError("random_state must be a non-negative integer or None.")
            if self.random_state < 0:
                raise ValueError("random_state must be non-negative.")

        if isinstance(self.max_samples, str):
            if self.max_samples != "auto":
                raise ValueError('max_samples must be "auto" or a positive integer.')
        else:
            if isinstance(self.max_samples, bool) or not isinstance(self.max_samples, int):
                raise ValueError('max_samples must be "auto" or a positive integer.')
            if self.max_samples < 1:
                raise ValueError("max_samples must be >= 1.")


@dataclass(frozen=True)
class IsolationForestDetectionResult:
    """Anomaly assessment from the Isolation Forest detector.

    Attributes
    ----------
    anomaly_score:
        sklearn ``decision_function`` output.  Negative values indicate more
        anomalous samples; positive values indicate more normal samples.
        The threshold is at 0.0 when ``contamination`` is ``"auto"``; with a
        numeric contamination value it is set to separate the most anomalous
        training fraction.
    is_anomalous:
        ``True`` when the detector's threshold classifies this sample as an
        outlier.
    feature_names:
        Ordered feature names used for this prediction.
    n_estimators:
        Number of trees in the fitted model.
    """

    anomaly_score: float
    is_anomalous: bool
    feature_names: tuple[str, ...]
    n_estimators: int


class IsolationForestDetector:
    """Wrapper around sklearn's IsolationForest for FL update anomaly detection.

    This class is intentionally not integrated into the ingestion pipeline.
    Use it offline for detection research and threshold tuning.  Wire it into
    production only after fitting on representative clean traffic.

    Thread safety: ``fit`` and ``load`` are NOT thread-safe.  ``detect`` is safe
    to call concurrently once the detector is fitted.
    """

    def __init__(self, config: IsolationForestConfig) -> None:
        if not _SKLEARN_AVAILABLE:  # pragma: no cover
            raise IsolationForestError(
                "scikit-learn is required for IsolationForestDetector. "
                "Install it with: pip install scikit-learn"
            )

        self._config = config
        self._model: Any = None
        self._fitted = False

    @property
    def config(self) -> IsolationForestConfig:
        return self._config

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    def fit(self, feature_vectors: list[dict[str, float]]) -> None:
        """Fit the detector on a list of clean update feature dicts.

        Parameters
        ----------
        feature_vectors:
            A list of feature dictionaries.  Each must contain exactly the keys
            listed in ``config.feature_names``.  Values must be finite floats.

        Raises
        ------
        ValueError:
            When ``feature_vectors`` is empty, contains unknown feature names,
            or contains non-finite values.
        """
        if not feature_vectors:
            raise ValueError("feature_vectors must not be empty.")

        X = self._to_matrix(feature_vectors)

        self._model = _SklearnIsolationForest(
            n_estimators=self._config.n_estimators,
            contamination=self._config.contamination,
            random_state=self._config.random_state,
            max_samples=self._config.max_samples,
        )
        self._model.fit(X)
        self._fitted = True
        logger.info(
            "IsolationForestDetector fitted on %d samples with features %s.",
            len(feature_vectors),
            self._config.feature_names,
        )

    def detect(self, features: dict[str, float]) -> IsolationForestDetectionResult:
        """Classify a single update feature vector.

        Parameters
        ----------
        features:
            Feature dict with exactly the keys in ``config.feature_names``.

        Returns
        -------
        IsolationForestDetectionResult

        Raises
        ------
        DetectorNotFittedError:
            When called before ``fit()`` or ``load()``.
        FeatureMismatchError:
            When ``features`` does not contain all required feature names.
        ValueError:
            When any feature value is non-finite.
        """
        if not self._fitted:
            raise DetectorNotFittedError(
                "The detector has not been fitted.  Call fit() with clean "
                "training vectors or load a previously fitted detector."
            )

        X = self._to_matrix([features])

        # decision_function: positive = more inlier, negative = more outlier
        score: float = float(self._model.decision_function(X)[0])
        prediction: int = int(self._model.predict(X)[0])  # 1 = inlier, -1 = outlier
        is_anomalous = prediction == -1

        return IsolationForestDetectionResult(
            anomaly_score=score,
            is_anomalous=is_anomalous,
            feature_names=self._config.feature_names,
            n_estimators=self._config.n_estimators,
        )

    def save(self, path: str | Path) -> None:
        """Persist the fitted detector to disk using joblib.

        Security note: the saved file uses Python pickle internally.  Treat it
        as executable code and store it in an access-controlled location.

        Raises
        ------
        DetectorNotFittedError:
            When called before ``fit()``.
        DetectorPersistenceError:
            When serialisation fails or joblib is unavailable.
        """
        if not self._fitted:
            raise DetectorNotFittedError("Cannot save an unfitted detector.")

        if not _JOBLIB_AVAILABLE:  # pragma: no cover
            raise DetectorPersistenceError(
                "joblib is required for detector persistence. "
                "Install it with: pip install joblib"
            )

        path = Path(path)
        payload = {
            "config": self._config,
            "model": self._model,
            "version": 1,
        }
        try:
            joblib.dump(payload, path)
        except Exception as exc:
            raise DetectorPersistenceError(f"Failed to save detector to {path}: {exc}") from exc

        logger.info("IsolationForestDetector saved to %s.", path)

    @classmethod
    def load(cls, path: str | Path) -> IsolationForestDetector:
        """Load a previously saved detector from disk.

        Security note: only load files from trusted, integrity-verified sources.
        Do not load user-supplied model files.

        Raises
        ------
        DetectorPersistenceError:
            When the file cannot be loaded or its format is invalid.
        """
        if not _JOBLIB_AVAILABLE:  # pragma: no cover
            raise DetectorPersistenceError(
                "joblib is required for detector persistence. "
                "Install it with: pip install joblib"
            )

        path = Path(path)
        try:
            payload = joblib.load(path)
        except Exception as exc:
            raise DetectorPersistenceError(f"Failed to load detector from {path}: {exc}") from exc

        if not isinstance(payload, dict):
            raise DetectorPersistenceError(
                f"Unexpected payload type {type(payload).__name__}; expected dict."
            )

        version = payload.get("version")
        if version != 1:
            raise DetectorPersistenceError(
                f"Unsupported detector file version {version!r}."
            )

        config = payload.get("config")
        if not isinstance(config, IsolationForestConfig):
            raise DetectorPersistenceError(
                f"Unexpected config type {type(config).__name__}."
            )

        model = payload.get("model")
        if model is None:
            raise DetectorPersistenceError("Detector file contains no fitted model.")

        detector = cls(config)
        detector._model = model
        detector._fitted = True
        logger.info("IsolationForestDetector loaded from %s.", path)
        return detector

    def _to_matrix(self, feature_vectors: list[dict[str, float]]) -> np.ndarray:
        """Convert a list of feature dicts to an ordered 2D numpy array.

        Validates that every dict contains exactly the configured features with
        finite float values.
        """
        feature_names = self._config.feature_names
        expected = set(feature_names)

        rows: list[list[float]] = []
        for i, fv in enumerate(feature_vectors):
            if not isinstance(fv, dict):
                raise ValueError(f"feature_vectors[{i}] must be a dict; got {type(fv).__name__}.")

            provided = set(fv.keys())
            missing = expected - provided
            if missing:
                raise FeatureMismatchError(
                    f"feature_vectors[{i}] is missing required features: {sorted(missing)}."
                )

            row: list[float] = []
            for name in feature_names:
                val = fv[name]
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    raise ValueError(
                        f"feature_vectors[{i}][{name!r}] must be numeric; got {type(val).__name__}."
                    )
                fval = float(val)
                if not math.isfinite(fval):
                    raise ValueError(
                        f"feature_vectors[{i}][{name!r}] must be finite; got {fval}."
                    )
                row.append(fval)

            rows.append(row)

        return np.array(rows, dtype=np.float64)
