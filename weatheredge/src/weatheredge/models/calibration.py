"""Calibration module for WeatherEdge probability forecasts."""

import json
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from weatheredge.db import get_connection
from weatheredge.config import CALIBRATION_MIN_SAMPLES


class CalibrationEngine:
    """
    Walk-forward calibration for probabilistic forecasts.
    
    Implements:
    - Brier score calculation
    - Log loss calculation
    - Isotonic regression calibration
    - Reliability diagram data
    """
    
    def __init__(self):
        self.min_samples = CALIBRATION_MIN_SAMPLES
    
    def get_historical_predictions(self, con, before_date: str, limit: int = 100) -> List[Dict]:
        """Get historical predictions with outcomes for calibration training."""
        rows = con.execute("""
            SELECT 
                p.prediction_time,
                p.market_date,
                p.bucket_label,
                p.model_probability,
                o.actual_max_c
            FROM model_prediction p
            LEFT JOIN outcome o ON o.market_date = p.market_date
            WHERE p.market_date < ? AND o.actual_max_c IS NOT NULL
            ORDER BY p.prediction_time DESC
            LIMIT ?
        """, (before_date, limit)).fetchall()
        
        return [dict(r) for r in rows]
    
    def determine_outcome(self, bucket_label: str, actual_max: float) -> int:
        """Determine if a bucket won (1) or lost (0) given actual max temperature."""
        label = bucket_label.replace("°C", "").replace("C", "").strip().lower()
        
        # Handle "X°C or higher"
        if "or higher" in label:
            try:
                threshold = float(label.split()[0])
                return 1 if actual_max >= threshold - 0.5 else 0
            except (ValueError, IndexError):
                return 0
        
        # Handle "X°C or lower"
        if "or lower" in label:
            try:
                threshold = float(label.split()[0])
                return 1 if actual_max <= threshold + 0.5 else 0
            except (ValueError, IndexError):
                return 0
        
        # Handle simple "XC" format
        try:
            temp = float(label)
            return 1 if abs(actual_max - temp) <= 0.5 else 0
        except ValueError:
            return 0
    
    def calculate_brier_score(self, predictions: List[Dict], outcomes: List[int]) -> float:
        """
        Calculate Brier score: mean((p - o)^2)
        Lower is better. Perfect = 0.
        """
        if not predictions:
            return float('nan')
        
        probs = [p["model_probability"] for p in predictions]
        brier = sum((p - o) ** 2 for p, o in zip(probs, outcomes)) / len(outcomes)
        return round(brier, 4)
    
    def calculate_log_loss(self, predictions: List[Dict], outcomes: List[int]) -> float:
        """
        Calculate log loss: -mean(o*log(p) + (1-o)*log(1-p))
        Lower is better. Perfect = 0.
        """
        if not predictions:
            return float('nan')
        
        eps = 1e-15  # Prevent log(0)
        total = 0
        for p, o in zip(predictions, outcomes):
            prob = max(eps, min(1 - eps, p["model_probability"]))
            total += o * math.log(prob) + (1 - o) * math.log(1 - prob)
        
        return round(-total / len(outcomes), 4)
    
    def isotonic_calibration(self, predictions: List[Dict], outcomes: List[int]) -> List[Tuple[float, float]]:
        """
        Fit isotonic regression for calibration.
        Returns list of (raw_prob, calibrated_prob) points.
        """
        if len(predictions) < self.min_samples:
            return []
        
        # Sort by predicted probability
        paired = list(zip([p["model_probability"] for p in predictions], outcomes))
        paired.sort(key=lambda x: x[0])
        
        # Pool adjacent violators algorithm (PAVA)
        n = len(paired)
        blocks = [[i] for i in range(n)]
        block_means = [o for _, o in paired]
        
        changed = True
        while changed:
            changed = False
            for i in range(len(block_means) - 1):
                if block_means[i] > block_means[i + 1]:
                    # Merge blocks
                    merged = blocks[i] + blocks[i + 1]
                    merged_mean = sum(block_means[j] for j in [i, i + 1]) / 2
                    
                    blocks[i] = merged
                    block_means[i] = merged_mean
                    
                    del blocks[i + 1]
                    del block_means[i + 1]
                    
                    changed = True
                    break
        
        # Build calibration mapping
        calibration_points = []
        for block, mean in zip(blocks, block_means):
            raw_probs = [paired[i][0] for i in block]
            avg_raw = sum(raw_probs) / len(raw_probs)
            calibration_points.append((avg_raw, mean))
        
        return calibration_points
    
    def calibrate_probability(self, calibration_points: List[Tuple[float, float]], 
                              raw_prob: float) -> float:
        """Apply isotonic calibration to a raw probability."""
        if not calibration_points:
            return raw_prob
        
        # Find surrounding points and interpolate
        sorted_points = sorted(calibration_points, key=lambda x: x[0])
        
        if raw_prob <= sorted_points[0][0]:
            return sorted_points[0][1]
        if raw_prob >= sorted_points[-1][0]:
            return sorted_points[-1][1]
        
        # Linear interpolation
        for i in range(len(sorted_points) - 1):
            lo_raw, lo_cal = sorted_points[i]
            hi_raw, hi_cal = sorted_points[i + 1]
            
            if lo_raw <= raw_prob <= hi_raw:
                if hi_raw == lo_raw:
                    return lo_cal
                t = (raw_prob - lo_raw) / (hi_raw - lo_raw)
                return lo_cal + t * (hi_cal - lo_cal)
        
        return raw_prob
    
    def get_reliability_diagram_data(self, con, before_date: str) -> Dict:
        """
        Generate data for reliability diagram.
        Bins predictions and compares average predicted vs actual frequency.
        """
        predictions = self.get_historical_predictions(con, before_date, limit=500)
        
        if not predictions:
            return {"bins": [], "sufficient_data": False}
        
        # Group by bucket and determine outcomes
        bucket_data = defaultdict(lambda: {"predictions": [], "outcomes": []})
        
        for p in predictions:
            outcome = self.determine_outcome(p["bucket_label"], p["actual_max_c"])
            bucket_data[p["bucket_label"]]["predictions"].append(p)
            bucket_data[p["bucket_label"]]["outcomes"].append(outcome)
        
        # Create bins
        bin_edges = [0, 0.2, 0.4, 0.6, 0.8, 1.0]
        bins = {f"{lo}-{hi}": {"predicted": [], "actual": [], "count": 0} 
                for lo, hi in zip(bin_edges[:-1], bin_edges[1:])}
        
        all_predictions = []
        all_outcomes = []
        
        for bucket, data in bucket_data.items():
            for pred, outcome in zip(data["predictions"], data["outcomes"]):
                prob = pred["model_probability"]
                # Find bin
                for i in range(len(bin_edges) - 1):
                    if bin_edges[i] <= prob < bin_edges[i + 1]:
                        bin_key = f"{bin_edges[i]}-{bin_edges[i+1]}"
                        bins[bin_key]["predicted"].append(prob)
                        bins[bin_key]["actual"].append(outcome)
                        bins[bin_key]["count"] += 1
                        break
                
                all_predictions.append(pred)
                all_outcomes.append(outcome)
        
        # Aggregate
        result_bins = []
        for bin_key, data in sorted(bins.items()):
            if data["count"] > 0:
                result_bins.append({
                    "bin": bin_key,
                    "avg_predicted": round(sum(data["predicted"]) / len(data["predicted"]), 3),
                    "avg_actual": round(sum(data["actual"]) / len(data["actual"]), 3),
                    "count": data["count"]
                })
        
        brier = self.calculate_brier_score(all_predictions, all_outcomes)
        log_loss = self.calculate_log_loss(all_predictions, all_outcomes)
        
        return {
            "bins": result_bins,
            "brier_score": brier,
            "log_loss": log_loss,
            "total_samples": len(all_predictions),
            "sufficient_data": len(all_predictions) >= self.min_samples
        }
    
    def run_calibration(self, con, market_date: str) -> Dict:
        """Run full calibration analysis for predictions before market_date."""
        reliability = self.get_reliability_diagram_data(con, market_date)
        
        if not reliability["sufficient_data"]:
            return {
                "status": "insufficient_data",
                "samples": reliability["total_samples"],
                "min_required": self.min_samples
            }
        
        # Get calibration mapping
        predictions = self.get_historical_predictions(con, market_date, limit=200)
        outcomes = [self.determine_outcome(p["bucket_label"], p["actual_max_c"]) 
                    for p in predictions]
        
        calibration_points = self.isotonic_calibration(predictions, outcomes)
        
        return {
            "status": "ok",
            "calibration_points": calibration_points,
            "brier_score": reliability["brier_score"],
            "log_loss": reliability["log_loss"],
            "reliability_bins": reliability["bins"],
            "samples": reliability["total_samples"]
        }
