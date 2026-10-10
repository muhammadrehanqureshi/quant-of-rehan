"""The ONE AI signal component: a trained daily probability, and nothing more.

Rebuild 2026-10-10. "AI-driven signals" in this repository means exactly one
concrete thing, and this module is its whole definition:

    a logistic regression, trained offline on the frozen KMIALL event study
    (data/event_study/events.parquet), that answers one question with one
    number:

        P(price touches +2.00% before it touches -0.50%, within 10 sessions)

    from the CAUSAL daily features known at the decision bar. The trained
    artifact is models/kmiall_signal_v1.json; scripts/train_signal_model.py is
    the only thing that writes it.

Why this and not something larger: every input here already exists in the
repository's own frozen research table, so the live feature vector and the
research feature vector are the SAME columns computed the SAME way. There is no
hidden model, no opaque score, and no second definition of a feature anywhere.
The coefficient vector is a plain list of numbers that can be read, audited and
re-derived by the owner.

Honesty rules, enforced here rather than documented:

  * the model NEVER decides the trade. It is a confirmation gate on the rule
    scanner's winner, and it can only ever refuse a candidate, never invent one;
  * the model is INACTIVE unless a trained artifact exists, parses, matches
    this module's feature list and label, and reports itself eligible (its
    holdout AUC beat 0.50 on data it was not trained on). A missing, corrupt,
    mismatched or ineligible artifact disables the gate and the reason is
    reported; the rule scanner then behaves exactly as it did before;
  * a feature vector with too many missing inputs yields NO probability, never
    an imputed guess that looks like an answer;
  * the artifact records its own provenance (train window, holdout metrics,
    dataset hash). A probability without provenance is not served.

Calling convention:

    model = ai_model.load()                    # Model | None, never raises
    ai_model.status()                          # honest availability report
    probs = ai_model.live_probabilities()      # {symbol: p} for the next
                                               # session, or None when the
                                               # model or the history is unusable
    probs = ai_model.probabilities_for(panel)  # {symbol: p} from a panel
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

try:  # pandas/numpy are already required by the research pipeline
    import numpy as np
    import pandas as pd
except Exception:  # pragma: no cover - import guard, reported by status()
    np = None  # type: ignore[assignment]
    pd = None  # type: ignore[assignment]

from src import config
from src.data.sessions import now_karachi

ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "models" / "kmiall_signal_v1.json"
PANEL_PATH = ROOT / "data" / "eod_history_kmi.csv.gz"
EVENTS_PATH = ROOT / "data" / "event_study" / "events.parquet"

def live_feature_cache() -> Path:
    """Where the per-session probability cache is written.

    Derived from ``trade_state.ROOT`` at CALL time, exactly like every other
    forward-state path in this repository, and never frozen at import. That is
    what lets a test redirect the entire forward surface with one patch, and it
    is what stops an offline run from writing into the owner's real
    data/forward directory.
    """
    from src.signals import trade_state

    return trade_state.ROOT / "data" / "forward" / "daily_features.json"


# The one label. Same column the research pipeline reports.
TRUTH_LABEL = "t0.02_first_vs_a05"

# The one feature list, in the one order. Names match the columns of the frozen
# event study with the f_ prefix stripped, so a feature can always be traced
# back to the exact expression that produced it in scripts/event_study.py.
FEATURES: tuple[str, ...] = (
    "ret1", "ret5", "ret10", "ret20",
    "gap1", "gap_ret5",
    "range20", "atr20", "vol20",
    "hi20", "hi60", "lo20",
    "above_ma20", "near_hi20", "near_hi60",
    "relvol", "turnover",
    "mkt_ret", "mkt_adv",
)

# A live row may tolerate at most this many missing inputs. Beyond it there is
# not enough context to state a probability, so none is stated.
MAX_IMPUTED_FEATURES = 2

# Panel feature windows, oldest first, in sessions.
_MIN_PERIODS = {"ma20": 20, "hi20": 20, "hi60": 60, "lo20": 20, "vol20": 20,
                "atr20": 20}


# ------------------------------------------------------------------ featurizer

def market_features(panel: "pd.DataFrame") -> "pd.DataFrame":
    """Cross-sectional breadth at each date.

    Byte-for-byte the definition used by the frozen event study
    (scripts/event_study.py: market_features): equal-weight mean of ret1 over
    the whole panel, and the share of names with a positive ret1.
    """
    frame = panel.dropna(subset=["ret1"]).copy()
    frame["adv"] = (frame["ret1"] > 0).astype(float)
    out = (frame.groupby("date")[["ret1", "adv"]]
           .mean()
           .rename(columns={"ret1": "mkt_ret"})
           .reset_index())
    return out


def panel_features(panel: "pd.DataFrame") -> "pd.DataFrame":
    """Causal daily features at each bar, per symbol. Windows END at the bar.

    Deliberately the same expressions as scripts/event_study.py
    (add_daily_features + market_features), because the trained model's inputs
    must be produced by the same definition in research and live. Any change
    here invalidates the artifact, and tests/test_ai_model.py fails on drift.
    """
    if pd is None or np is None:  # pragma: no cover - guarded by status()
        raise RuntimeError("pandas/numpy unavailable")

    frame = panel.sort_values(["symbol", "date"]).reset_index(drop=True).copy()
    grouped = frame.groupby("symbol", sort=False)
    frame["ret1"] = grouped["close"].pct_change()
    frame["ret5"] = grouped["close"].pct_change(5)
    frame["ret10"] = grouped["close"].pct_change(10)
    frame["ret20"] = grouped["close"].pct_change(20)
    frame["ma20"] = grouped["close"].transform(
        lambda s: s.rolling(20, min_periods=20).mean())
    frame["hi20"] = grouped["close"].transform(
        lambda s: s.rolling(20, min_periods=20).max())
    frame["hi60"] = grouped["close"].transform(
        lambda s: s.rolling(60, min_periods=60).max())
    frame["lo20"] = grouped["close"].transform(
        lambda s: s.rolling(20, min_periods=20).min())
    frame["vol20"] = grouped["volume"].transform(
        lambda s: s.rolling(20, min_periods=20).mean())
    frame["range20"] = (frame["hi20"] - frame["lo20"]) / frame["lo20"]
    frame["atr20"] = grouped.apply(
        lambda x: (
            pd.concat([x["high"] - x["low"],
                       (x["high"] - x["close"].shift()).abs(),
                       (x["low"] - x["close"].shift()).abs()], axis=1)
            .max(axis=1)
            .rolling(20, min_periods=20)
            .mean()
        )
    ).reset_index(level=0, drop=True)
    frame["gap1"] = grouped.apply(
        lambda x: x["open"] / x["close"].shift() - 1.0
    ).reset_index(level=0, drop=True)
    frame["gap_ret5"] = grouped.apply(
        lambda x: x["open"] / x["close"].shift(5) - 1.0
    ).reset_index(level=0, drop=True)

    # The research table names this feature f_mkt_adv while the breadth builder
    # calls the column adv; one name is used here so the artifact's feature
    # order always resolves.
    frame = frame.merge(market_features(frame), on="date", how="left")
    frame = frame.rename(columns={"adv": "mkt_adv"})

    # The tri-state features of the research table: True/False/None.
    def ratio(numerator: "pd.Series", denominator: "pd.Series"):
        den = denominator.where(denominator > 0)
        return numerator / den

    frame["near_hi20"] = ratio(frame["close"], frame["hi20"])
    frame["near_hi60"] = ratio(frame["close"], frame["hi60"])
    frame["relvol"] = ratio(frame["volume"], frame["vol20"])
    frame["turnover"] = frame["close"] * frame["volume"]
    frame["above_ma20"] = np.where(frame["ma20"].isna(), np.nan,
                                   (frame["close"] > frame["ma20"]).astype(float))
    return frame


def feature_dict(row) -> dict[str, float | None]:
    """Pull the model's inputs out of one feature row, in FEATURES order."""
    out: dict[str, float | None] = {}
    for name in FEATURES:
        value = row.get(name) if hasattr(row, "get") else None
        if value is None:
            out[name] = None
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            out[name] = None
            continue
        out[name] = number if math.isfinite(number) else None
    return out


def latest_feature_rows(panel: "pd.DataFrame") -> dict[str, dict]:
    """One feature row per symbol: the LAST bar in the panel.

    The last completed session is the decision bar for the next session, so
    these are the inputs a scan at the next open is allowed to use. Nothing
    from the future exists in this frame by construction.
    """
    frame = panel_features(panel)
    last = frame.sort_values(["symbol", "date"]).groupby("symbol", sort=False).tail(1)
    return {str(row["symbol"]).strip().upper(): feature_dict(row)
            for _, row in last.iterrows()}


# ----------------------------------------------------------------------- model

@dataclass
class Model:
    """A plain, auditable logistic regression."""

    features: tuple[str, ...]
    label: str
    mean: list[float]
    scale: list[float]
    coefficients: list[float]
    intercept: float
    metadata: dict = field(default_factory=dict)

    # ---- serialization ----------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "artifact": "quant-of-rehan-ai-signal",
            "artifact_version": 1,
            "label": self.label,
            "label_meaning": ("price touched +2.00% before -0.50%, within 10 "
                              "sessions, measured from the next open"),
            "truth_column": TRUTH_LABEL,
            "features": list(self.features),
            "standardization": {"mean": self.mean, "scale": self.scale,
                                "impute_missing_with": "train_mean",
                                "max_imputed_features": MAX_IMPUTED_FEATURES},
            "coefficients": self.coefficients,
            "intercept": self.intercept,
            "model_type": "logistic_regression_l2",
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "Model":
        return cls(
            features=tuple(payload["features"]),
            label=str(payload["label"]),
            mean=[float(v) for v in payload["standardization"]["mean"]],
            scale=[float(v) for v in payload["standardization"]["scale"]],
            coefficients=[float(v) for v in payload["coefficients"]],
            intercept=float(payload["intercept"]),
            metadata=dict(payload.get("metadata") or {}),
        )

    # ---- inference --------------------------------------------------------
    def standardize(self, values: list[float]) -> list[float]:
        return [(value - mu) / sigma
                for value, mu, sigma in zip(values, self.mean, self.scale)]

    def predict_proba(self, features: dict[str, float | None]) -> float:
        values: list[float] = []
        imputed = 0
        for name, mu in zip(self.features, self.mean):
            value = features.get(name)
            if value is None:
                used = mu
                imputed += 1
            else:
                used = float(value)
            values.append(used)
        if imputed > self.max_imputed:
            raise ValueError(f"{imputed} inputs missing; refusing to guess")
        z = self.intercept
        for weight, value in zip(self.coefficients, self.standardize(values)):
            z += weight * value
        return 1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, z))))

    @property
    def max_imputed(self) -> int:
        return int(self.metadata.get("max_imputed_features",
                                     MAX_IMPUTED_FEATURES))

    @property
    def eligible(self) -> bool:
        """Did the trainer's own holdout beat a coin flip on unseen data?"""
        return bool(self.metadata.get("eligible"))

    @property
    def holdout_auc(self):
        return self.metadata.get("holdout", {}).get("auc")


def _artifact_reason(path: Path) -> str | None:
    """Why this artifact cannot be used, or None when it can."""
    if pd is None or np is None:
        return "numpy/pandas unavailable in this interpreter"
    if not path.is_file():
        return (f"no trained artifact at {path.relative_to(ROOT)}; run "
                f"python scripts/train_signal_model.py")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"artifact unreadable ({type(exc).__name__})"
    if payload.get("artifact") != "quant-of-rehan-ai-signal":
        return "artifact is not a quant-of-rehan-ai-signal file"
    if tuple(payload.get("features") or ()) != FEATURES:
        return ("artifact feature list does not match this module; retrain "
                "(the feature definition changed)")
    if payload.get("truth_column") != TRUTH_LABEL:
        return f"artifact label is not {TRUTH_LABEL}; retrain"
    std = payload.get("standardization") or {}
    for key in ("mean", "scale"):
        values = std.get(key)
        if not isinstance(values, list) or len(values) != len(FEATURES):
            return f"artifact standardization.{key} is malformed"
    if len(payload.get("coefficients") or []) != len(FEATURES):
        return "artifact coefficient vector does not match its feature list"
    return None


def load(path: Path | None = None) -> Model | None:
    """The trained model, or None. Never raises."""
    target = Path(path or MODEL_PATH)
    if _artifact_reason(target):
        return None
    try:
        return Model.from_dict(json.loads(target.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def status(path: Path | None = None) -> dict:
    """Honest report of whether the AI component can speak, and why not."""
    target = Path(path or MODEL_PATH)
    reason = _artifact_reason(target)
    report = {
        "enabled": bool(config.AI_SIGNAL_ENABLED),
        "gate_enabled": bool(config.AI_GATE_ENABLED),
        "artifact": str(target.relative_to(ROOT)),
        "artifact_exists": target.is_file(),
        "features": list(FEATURES),
        "label": TRUTH_LABEL,
        "tie_break_enabled": bool(config.AI_TIE_BREAK_ENABLED),
        "tie_band": config.AI_TIE_BAND,
        "veto_enabled": bool(config.AI_GATE_ENABLED),
        "reject_percentile": config.AI_REJECT_PERCENTILE,
        "active": False,
        "reason": reason,
    }
    if reason:
        return report
    model = load(target)
    if model is None:
        report["reason"] = "artifact failed to parse"
        return report
    report["eligible"] = model.eligible
    report["holdout_auc"] = model.holdout_auc
    report["trained_at"] = model.metadata.get("trained_at")
    report["train_rows"] = model.metadata.get("train_rows")
    report["holdout_rows"] = model.metadata.get("holdout", {}).get("rows")
    if not config.AI_SIGNAL_ENABLED:
        report["reason"] = "AI signal disabled by configuration"
        return report
    if not model.eligible:
        report["reason"] = ("artifact did not beat a coin flip on its holdout; "
                            "advisory only, the veto stays inactive")
        return report
    if model.holdout_auc is None or not (model.holdout_auc > 0.5):
        report["reason"] = "artifact holds no measurable holdout edge; advisory only"
        return report
    report["active"] = True
    report["reason"] = ("trained, feature-matched, holdout AUC above 0.50; "
                       "routing as a bounded prior")
    return report


# ----------------------------------------------------------------------- live

def load_panel(path: Path | None = None) -> "pd.DataFrame":
    """The KMIALL daily panel the features are computed from."""
    target = Path(path or PANEL_PATH)
    if not target.is_file():
        raise FileNotFoundError(f"daily panel missing: {target}")
    frame = pd.read_csv(target, parse_dates=["date"])
    return frame.sort_values(["symbol", "date"]).reset_index(drop=True)


def panel_as_of(panel: "pd.DataFrame") -> str | None:
    if panel is None or panel.empty or "date" not in panel:
        return None
    return str(pd.to_datetime(panel["date"]).max().date().isoformat())


def probabilities_for(panel: "pd.DataFrame", model: Model | None = None) -> dict[str, float]:
    """{symbol: P(+2% before -0.5%)} for the next session, from a panel.

    Symbols whose feature row is too incomplete to state a probability are
    simply absent from the result. Absence is the honest answer; a fabricated
    number is not.
    """
    active = model if model is not None else load()
    if active is None:
        return {}
    rows = latest_feature_rows(panel)
    out: dict[str, float] = {}
    for symbol, features in rows.items():
        try:
            out[symbol] = round(active.predict_proba(features), 6)
        except ValueError:
            continue
    return out


def panel_signature(path: Path | None = None) -> str | None:
    """Identity of the daily panel file: size and mtime.

    The panel only changes once a day, after the close. Keying the cached
    probabilities on this lets a 5-minute scheduler reuse one computation per
    session instead of refitting the whole panel every tick, and it can never
    serve probabilities built from a different panel file.
    """
    target = Path(path or PANEL_PATH)
    try:
        stat = target.stat()
    except OSError:
        return None
    return f"{stat.st_size}:{int(stat.st_mtime)}"


def _cached_probabilities(signature: str | None) -> dict[str, float] | None:
    cache = live_feature_cache()
    if not signature or not cache.is_file():
        return None
    try:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if payload.get("panel_signature") != signature:
        return None
    if tuple(payload.get("features") or ()) != FEATURES:
        return None
    probabilities = payload.get("probabilities")
    return probabilities if isinstance(probabilities, dict) else None


def live_probabilities(write: bool = True, use_cache: bool = True,
                       panel_path: Path | None = None,
                       model_path: Path | None = None,
                       force: bool = False) -> dict[str, float] | None:
    """Probabilities for the next session from the on-disk daily panel.

    Returns None when the model is inactive or the panel cannot be read, so a
    caller can always distinguish "no AI component" from "AI said nothing".
    A read failure is reported, never silently treated as an empty opinion.
    """
    active = load(model_path)
    if active is None or not config.AI_SIGNAL_ENABLED or not active.eligible:
        return None
    signature = panel_signature(panel_path)
    if use_cache and not force:
        cached = _cached_probabilities(signature)
        if cached is not None:
            return cached
    try:
        panel = load_panel(panel_path)
        probs = probabilities_for(panel, active)
        as_of = panel_as_of(panel)
    except Exception as exc:  # noqa: BLE001 - reported, never invented
        print(f"ai model unavailable: {type(exc).__name__}: {exc}")
        return None
    if write:
        cache = live_feature_cache()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({
            "built_at": now_karachi().isoformat(timespec="seconds"),
            "panel_as_of": as_of,
            "panel": str((Path(panel_path) if panel_path else PANEL_PATH)
                         .relative_to(ROOT)),
            "panel_signature": signature,
            "model": str(MODEL_PATH.relative_to(ROOT)),
            "holdout_auc": active.holdout_auc,
            "features": list(FEATURES),
            "probabilities": probs,
        }, indent=2, sort_keys=True), encoding="utf-8")
    return probs


# -------------------------------------------------------------- distribution

def percentile_of(distribution: dict[str, float], symbol: str) -> float | None:
    """Where one symbol sits inside the model's own cross-section.

    0.0 is the weakest name the model sees today, 1.0 the strongest. A raw
    probability is only comparable to the panel it was produced with, so the
    cross-section is what the prior is expressed in everywhere downstream.
    """
    value = distribution.get(symbol)
    if value is None or not distribution:
        return None
    weaker = sum(1 for other in distribution.values() if other < value)
    return round(weaker / max(len(distribution) - 1, 1), 4)


def attach(distribution: dict[str, float] | None,
           rows: list[dict]) -> list[dict]:
    """Record the AI prior on every candidate row, in place, honestly.

    A candidate the model did not score is marked unavailable rather than given
    a default. `ai_active` states whether the prior is allowed to reorder or
    refuse anything at all.
    """
    report = status()
    for row in rows:
        symbol = row.get("symbol")
        probability = None if distribution is None else distribution.get(symbol)
        row["ai_probability"] = probability
        row["ai_percentile"] = percentile_of(distribution or {}, symbol)
        row["ai_active"] = report["active"]
    return rows


# ----------------------------------------------------------------------- gate

def gate(probability: float | None,
         percentile: float | None = None) -> tuple[bool, str]:
    """May this candidate be entered, given the AI prior?

    Returns (passed, reason). The veto is off unless the owner turns it on AND
    the model is active AND a probability exists. It refuses only the weakest
    ``AI_REJECT_PERCENTILE`` sliver of the model's own cross-section, because a
    weakly-predictive model can rank names but cannot certify a level. The word
    "veto" is exact here: the AI component can refuse a candidate and can
    never invent or upgrade one.
    """
    report = status()
    if not report["active"] or not config.AI_GATE_ENABLED:
        return True, "AI veto inactive"
    if probability is None:
        return True, "no AI probability available"
    if percentile is None:
        return True, "no AI cross-section available"
    if percentile <= config.AI_REJECT_PERCENTILE:
        return False, (f"AI prior {percentile:.0%} percentile is inside the "
                       f"rejected bottom {config.AI_REJECT_PERCENTILE:.0%}"
                       f" of today's model ranking")
    return True, (f"AI prior {percentile:.0%} percentile clears the rejected "
                  f"bottom {config.AI_REJECT_PERCENTILE:.0%}")


def tie_break_winner(rows: list[dict]) -> tuple[int, str]:
    """Reorder a near-tie at the top by the AI prior. Returns (index, reason).

    Only the top two matter. If their rule scores differ by more than
    ``AI_TIE_BAND`` the rule score decides and the prior is ignored -- a weak
    prior must never overturn a clear rule decision. Inside the band the higher
    AI percentile wins, and if the prior cannot separate them the rule order
    stands.
    """
    if len(rows) < 2 or not config.AI_TIE_BREAK_ENABLED:
        return 0, "no tie-break applied"
    first, second = rows[0], rows[1]
    gap = float(first.get("score", 0.0)) - float(second.get("score", 0.0))
    if gap < 0 or gap > config.AI_TIE_BAND:
        return 0, f"rule score gap {gap:.2f} is outside the {config.AI_TIE_BAND:g} point band"
    first_p, second_p = first.get("ai_percentile"), second.get("ai_percentile")
    if first_p is None or second_p is None or first_p == second_p:
        return 0, "AI prior cannot separate the top two"
    if second_p > first_p:
        return 1, (f"AI prior promoted {second['symbol']} over {first['symbol']} "
                   f"inside a {gap:.2f} point rule gap")
    return 0, (f"AI prior kept {first['symbol']} over {second['symbol']} "
               f"inside a {gap:.2f} point rule gap")


def dataset_fingerprint(path: Path) -> str | None:
    """sha256 of a dataset, recorded in the artifact as provenance."""
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None
