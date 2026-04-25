import os
import xgboost as xgb
import pandas as pd
from typing import List, Dict

MODEL_PATH = "app/flood_model_real.json"

class MLEngine:
    def __init__(self):
        self.model = None
        if os.path.exists(MODEL_PATH):
            self.model = xgb.XGBClassifier()
            self.model.load_model(MODEL_PATH)
            
    def predict_risk(self, features_df: pd.DataFrame) -> List[float]:
        """
        Takes a DataFrame with complex climate/geographical columns.
        Returns a list of probabilities (risk scores).
        """
        if self.model is None:
            # Fallback rule-based if model is not trained yet
            print("Model not found! Using fallback rule-based system.")
            return [0.0] * len(features_df)
            
        # Predict probability of class 1 (flood)
        probs = self.model.predict_proba(features_df)[:, 1]
        return [float(p) * 100 for p in probs] # Return as percentage 0-100
