#!/usr/bin/env python3
"""
ml/train.py - Weather ML Pipeline training script.

Loads weather dataset, trains and compares Logistic Regression, Random Forest,
and XGBoost, handles class imbalance, selects the best model, and saves the
complete scikit-learn Pipeline as a joblib artifact.
"""

import os
import sys
import joblib
import pandas as pd
import numpy as np
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, f1_score, confusion_matrix, precision_recall_fscore_support
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBClassifier

def main():
    print("🚀 Starting Weather ML Training Pipeline...")

    # 1. Load dataset
    data_path = 'data/bengaluru_medical_drone_weather_dataset.csv'
    if not os.path.exists(data_path):
        print(f"❌ Dataset not found at {data_path}")
        sys.exit(1)
        
    df = pd.read_csv(data_path)
    print(f"Loaded {len(df)} rows.")

    # 2. Target mapping
    class_map = {'SAFE': 0, 'CAUTION': 1, 'UNSAFE': 2}
    inv_class_map = {v: k for k, v in class_map.items()}
    y = df['flight_condition'].map(class_map)
    
    # Check for NaN in target
    if y.isnull().any():
        print("❌ Found invalid/unknown flight conditions in dataset.")
        sys.exit(1)

    # 3. Feature Selection & Target Leakage Prevention
    # Define features to include (strictly available from weather APIs)
    numeric_features = [
        'temperature_c', 'humidity_pct', 'precipitation_mm', 'wind_speed_kmh',
        'wind_gust_kmh', 'wind_direction_deg', 'visibility_km', 'pressure_hpa',
        'cloud_cover_pct', 'dew_point_c', 'uv_index'
    ]
    categorical_features = ['weather_condition', 'rain_event']
    
    X = df[numeric_features + categorical_features]
    
    # 4. Stratified Split (70/15/15)
    X_train_val, X_test, y_train_val, y_test = train_test_split(
        X, y, test_size=0.15, stratify=y, random_state=42
    )
    X_train, X_val, y_train, y_val = train_test_split(
        X_train_val, y_train_val, test_size=0.1765, stratify=y_train_val, random_state=42
    ) # 0.1765 of 0.85 is ~0.15 of total
    
    print(f"Train size: {len(X_train)} | Val size: {len(X_val)} | Test size: {len(X_test)}")
    
    # 5. Preprocessing Pipeline
    preprocessor = ColumnTransformer(
        transformers=[
            ('num', StandardScaler(), numeric_features),
            ('cat', OneHotEncoder(handle_unknown='ignore', sparse_output=False), categorical_features)
        ]
    )

    # 6. Handle Class Imbalance
    sample_weight = compute_sample_weight(class_weight='balanced', y=y_train)

    # Models definition
    models = {
        'Logistic Regression': Pipeline([
            ('preprocessor', preprocessor),
            ('classifier', LogisticRegression(class_weight='balanced', max_iter=2000, random_state=42))
        ]),
        'Random Forest': Pipeline([
            ('preprocessor', preprocessor),
            ('classifier', RandomForestClassifier(class_weight='balanced', random_state=42, n_estimators=150, n_jobs=-1))
        ]),
        'XGBoost': Pipeline([
            ('preprocessor', preprocessor),
            ('classifier', XGBClassifier(random_state=42, n_jobs=-1, eval_metric='mlogloss'))
        ])
    }

    best_macro_f1 = -1.0
    best_unsafe_recall = -1.0
    best_model_name = None
    best_pipeline = None
    results = {}

    # 7. Model Training and Comparison
    for name, pipeline in models.items():
        print(f"\n--- Training {name} ---")
        if name == 'XGBoost':
            # XGBoost requires sample weight to be passed to fit explicitly
            pipeline.fit(X_train, y_train, classifier__sample_weight=sample_weight)
        else:
            pipeline.fit(X_train, y_train)

        # Evaluate on validation set
        y_val_pred = pipeline.predict(X_val)
        
        # Calculate scores
        macro_f1 = f1_score(y_val, y_val_pred, average='macro')
        
        # Get per-class recall
        recalls = precision_recall_fscore_support(y_val, y_val_pred, labels=[0, 1, 2])[1]
        unsafe_recall = recalls[2] # Index 2 is UNSAFE
        caution_recall = recalls[1]
        safe_recall = recalls[0]

        print(f"Validation Macro-F1: {macro_f1:.4f}")
        print(f"Validation UNSAFE Recall: {unsafe_recall:.4f}")
        print(f"Validation CAUTION Recall: {caution_recall:.4f}")
        print(f"Validation SAFE Recall: {safe_recall:.4f}")
        
        results[name] = {
            'macro_f1': macro_f1,
            'unsafe_recall': unsafe_recall,
            'pipeline': pipeline
        }

        # Model selection: Best Macro-F1, tie-breaker: UNSAFE Recall
        is_better = False
        if macro_f1 > best_macro_f1:
            is_better = True
        elif abs(macro_f1 - best_macro_f1) < 1e-6 and unsafe_recall > best_unsafe_recall:
            is_better = True

        if is_better:
            best_macro_f1 = macro_f1
            best_unsafe_recall = unsafe_recall
            best_model_name = name
            best_pipeline = pipeline

    print(f"\n🏆 Best Model Selected: {best_model_name}")

    # 8. Final Evaluation on Test Set
    best_pipeline_opt = results[best_model_name]['pipeline']
    y_test_pred = best_pipeline_opt.predict(X_test)
    
    print("\n=== Final Test Set Classification Report ===")
    print(classification_report(y_test, y_test_pred, target_names=['SAFE', 'CAUTION', 'UNSAFE']))
    
    print("=== Confusion Matrix ===")
    cm = confusion_matrix(y_test, y_test_pred)
    print(cm)
    
    # Save confusion matrix to a file
    os.makedirs('models', exist_ok=True)
    cm_df = pd.DataFrame(cm, index=['SAFE_actual', 'CAUTION_actual', 'UNSAFE_actual'], 
                             columns=['SAFE_pred', 'CAUTION_pred', 'UNSAFE_pred'])
    cm_df.to_csv('models/confusion_matrix.csv')
    print("Saved confusion matrix to models/confusion_matrix.csv")

    # 9. Save preprocessing + model pipeline
    joblib_path = 'models/weather_flight_condition.joblib'
    joblib.dump(best_pipeline_opt, joblib_path)
    print(f"Saved best model pipeline to {joblib_path}")

    # Confirm it loads back cleanly
    loaded = joblib.load(joblib_path)
    print("Verified: joblib model loads back cleanly.")

if __name__ == '__main__':
    main()
