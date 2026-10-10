"""
Unit tests for Phase 5: Weather ML Pipeline input schema and inference.

Ensures target leakage fields (flight_condition, flight_risk_score,
prediction_confidence) are strictly rejected and that valid inputs yield
the correct response format.
"""

import sys
import pytest
from pathlib import Path
from pydantic import ValidationError

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ml.predict import predict_flight_condition, WeatherInputSchema


@pytest.fixture
def valid_weather_input():
    return {
        "temperature_c": 24.5,
        "humidity_pct": 65.0,
        "precipitation_mm": 0.0,
        "wind_speed_kmh": 12.0,
        "wind_gust_kmh": 15.0,
        "wind_direction_deg": 180.0,
        "visibility_km": 10.0,
        "pressure_hpa": 1013.0,
        "cloud_cover_pct": 20.0,
        "dew_point_c": 16.5,
        "uv_index": 5.0,
        "weather_condition": "Clear",
        "rain_event": 0
    }


# ── Target Leakage Guardrail Tests ──────────────────────────────────────────


class TestWeatherMLLeakageGuardrail:
    def test_schema_excludes_leakage_fields(self):
        """Assert that leakage fields are not defined in the input schema."""
        disallowed = {"flight_condition", "flight_risk_score", "prediction_confidence"}
        fields = set(WeatherInputSchema.model_fields.keys())
        
        # None of the disallowed fields must be in the schema
        intersection = disallowed.intersection(fields)
        assert not intersection, f"Target leakage fields found in Pydantic schema: {intersection}"

    def test_predict_rejects_leakage_in_dict_keys(self, valid_weather_input):
        """Assert that passing leakage fields in weather_data dict raises ValueError."""
        leakage_fields = ["flight_condition", "flight_risk_score", "prediction_confidence"]
        
        for field in leakage_fields:
            bad_input = valid_weather_input.copy()
            bad_input[field] = "LEAKED_VAL"
            
            with pytest.raises(ValueError) as excinfo:
                predict_flight_condition(bad_input)
            
            assert "Target leakage detected" in str(excinfo.value)
            assert field in str(excinfo.value)


# ── Schema Validation Tests ──────────────────────────────────────────────────


class TestWeatherMLValidation:
    def test_predict_success_schema(self, valid_weather_input, monkeypatch):
        """
        Verify that a valid input dict returns the correct result format.
        We mock the load_pipeline call to return a mock classifier so we don't
        depend on a trained joblib model to exist on disk during unit testing.
        """
        import numpy as np
        
        # Mock pipeline steps
        mock_pipeline = type("MockPipeline", (object,), {
            "predict": lambda self, df: np.array([0]),
            "predict_proba": lambda self, df: np.array([[0.95, 0.03, 0.02]])
        })()
        
        # Patch load_pipeline to return our mock pipeline
        import ml.predict
        monkeypatch.setattr(ml.predict, "load_pipeline", lambda: mock_pipeline)
        
        res = predict_flight_condition(valid_weather_input)
        
        assert "flight_condition" in res
        assert "probability" in res
        assert res["flight_condition"] == "SAFE"
        assert res["probability"] == 0.95

    def test_schema_rejects_missing_fields(self, valid_weather_input):
        """Assert that missing required fields raises ValidationError."""
        bad_input = valid_weather_input.copy()
        del bad_input["wind_speed_kmh"]
        
        with pytest.raises(ValidationError):
            predict_flight_condition(bad_input)

    def test_schema_rejects_out_of_bounds_values(self, valid_weather_input):
        """Assert that out of bounds numerical values raise ValidationError."""
        # humidity_pct must be <= 100
        bad_input = valid_weather_input.copy()
        bad_input["humidity_pct"] = 120.0
        
        with pytest.raises(ValidationError):
            predict_flight_condition(bad_input)
