"""
ml/predict.py - Inference script for the Weather ML pipeline.

Provides a cached model loader and schema-validated prediction function.
"""

import os
import sys
import joblib
import pandas as pd
from pathlib import Path
from pydantic import BaseModel, Field, ValidationError

# Global cached model pipeline
_PIPELINE = None
MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "weather_flight_condition.joblib"

# Inverse mapping for prediction outputs
CLASS_MAP_INV = {0: "SAFE", 1: "CAUTION", 2: "UNSAFE"}


class WeatherInputSchema(BaseModel):
    """
    Pydantic schema representing the required inputs for real-time weather predictions.
    This schema intentionally EXCLUDES target leakage columns:
    flight_condition, flight_risk_score, prediction_confidence.
    """
    temperature_c: float = Field(..., description="Temperature in Celsius")
    humidity_pct: float = Field(..., ge=0.0, le=100.0, description="Humidity percentage")
    precipitation_mm: float = Field(..., ge=0.0, description="Precipitation in mm")
    wind_speed_kmh: float = Field(..., ge=0.0, description="Wind speed in km/h")
    wind_gust_kmh: float = Field(..., ge=0.0, description="Wind gust speed in km/h")
    wind_direction_deg: float = Field(..., ge=0.0, le=360.0, description="Wind direction in degrees")
    visibility_km: float = Field(..., ge=0.0, description="Visibility in km")
    pressure_hpa: float = Field(..., ge=0.0, description="Pressure in hPa")
    cloud_cover_pct: float = Field(..., ge=0.0, le=100.0, description="Cloud cover percentage")
    dew_point_c: float = Field(..., description="Dew point in Celsius")
    uv_index: float = Field(..., ge=0.0, description="UV index")
    weather_condition: str = Field(..., description="Categorical weather description (e.g. Clear, Cloudy)")
    rain_event: int = Field(..., ge=0, le=1, description="Binary indicator (0 or 1) of active rain")

    model_config = {
        "extra": "forbid"  # Reject any extra fields (including leakage columns)
    }


def load_pipeline():
    """Load and cache the scikit-learn pipeline from disk."""
    global _PIPELINE
    if _PIPELINE is None:
        if not MODEL_PATH.exists():
            raise FileNotFoundError(
                f"Trained model not found at {MODEL_PATH}. Please run ml/train.py first."
            )
        _PIPELINE = joblib.load(MODEL_PATH)
    return _PIPELINE


def predict_flight_condition(weather_data: dict) -> dict:
    """
    Predict flight condition based on weather parameters.

    Parameters:
    -----------
    weather_data : dict
        A dictionary containing the real-time weather metrics matching WeatherInputSchema.

    Returns:
    --------
    dict
        {
            "flight_condition": "SAFE" | "CAUTION" | "UNSAFE",
            "probability": float
        }
    """
    # 1. Target Leakage Guardrail: Ensure no target leakage columns are passed
    leakage_cols = {"flight_condition", "flight_risk_score", "prediction_confidence"}
    intersection = leakage_cols.intersection(weather_data.keys())
    if intersection:
        raise ValueError(
            f"Target leakage detected! Input contains disallowed fields: {list(intersection)}"
        )

    # 2. Schema Validation (raises ValidationError if invalid)
    validated = WeatherInputSchema(**weather_data)
    validated_dict = validated.model_dump()

    # 3. Load model and prepare DataFrame
    pipeline = load_pipeline()
    df = pd.DataFrame([validated_dict])

    # 4. Predict class and class probabilities
    pred_idx = pipeline.predict(df)[0]
    probabilities = pipeline.predict_proba(df)[0]
    
    # 5. Extract target class probability
    probability = float(probabilities[pred_idx])
    flight_condition = CLASS_MAP_INV[int(pred_idx)]

    return {
        "flight_condition": flight_condition,
        "probability": probability
    }
