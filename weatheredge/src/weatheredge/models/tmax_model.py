"""Tmax probability model for WeatherEdge."""

import json
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict

from weatheredge.db import get_connection
from weatheredge.config import FORECAST_ERROR_WINDOW_DAYS, CALIBRATION_MIN_SAMPLES


class TmaxModel:
    """
    Probabilistic Tmax forecasting model.
    
    Produces P(Tmax in bucket) for each temperature bucket using:
    - SAWS forecast (if available)
    - Current FACT temperature and trajectory
    - Historical forecast error distribution
    - Time remaining in day
    - Atmospheric regime indicators
    """
    
    def __init__(self):
        self.error_window_days = FORECAST_ERROR_WINDOW_DAYS
        self.calibration_min_samples = CALIBRATION_MIN_SAMPLES
    
    def get_bucket_bounds(self, bucket_label: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Parse bucket label to get temperature bounds.
        e.g., "19°C" -> (18.5, 19.5), "20°C or higher" -> (19.5, None)
        """
        label = bucket_label.replace("°C", "").replace("C", "").strip()
        
        # Handle "X°C or higher" format
        if "or higher" in label.lower():
            try:
                lower = float(label.split()[0])
                return (lower - 0.5, None)
            except (ValueError, IndexError):
                return (None, None)
        
        # Handle "X°C or lower" format
        if "or lower" in label.lower():
            try:
                upper = float(label.split()[0])
                return (None, upper + 0.5)
            except (ValueError, IndexError):
                return (None, None)
        
        # Handle simple "XC" format
        try:
            temp = float(label)
            return (temp - 0.5, temp + 0.5)
        except ValueError:
            return (None, None)
    
    def buckets_overlap(self, bounds1: Tuple[Optional[float], Optional[float]], 
                        bounds2: Tuple[Optional[float], Optional[float]]) -> bool:
        """Check if two temperature buckets overlap."""
        lo1, hi1 = bounds1
        lo2, hi2 = bounds2
        
        # Unbounded on same side means they could overlap
        if hi1 is None and hi2 is None:
            return True
        if lo1 is None and lo2 is None:
            return True
        
        # Check for non-overlap
        if hi1 is not None and lo2 is not None and hi1 < lo2:
            return False
        if hi2 is not None and lo1 is not None and hi2 < lo1:
            return False
        
        return True
    
    def get_historical_max(self, con, market_date: str) -> Optional[float]:
        """Get actual daily max temperature from METAR observations."""
        row = con.execute("""
            SELECT MAX(temp_c) as max_temp FROM metar_obs
            WHERE obs_time LIKE ? AND temp_c IS NOT NULL
        """, (f"{market_date}%",)).fetchone()
        return row["max_temp"] if row else None
    
    def get_saws_forecast(self, con, target_date: str) -> Optional[float]:
        """Get latest SAWS max temperature forecast for target date."""
        row = con.execute("""
            SELECT max_temp FROM saws_forecast
            WHERE target_date = ? AND max_temp IS NOT NULL
            ORDER BY fetched_at DESC LIMIT 1
        """, (target_date,)).fetchone()
        return row["max_temp"] if row else None
    
    def get_current_fact_state(self, con, as_of: datetime = None) -> Dict[str, Any]:
        """Get current atmospheric state at FACT."""
        if as_of is None:
            as_of = datetime.now(timezone.utc)
        
        # Ensure as_of is timezone-aware
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        
        as_of_str = as_of.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        # Get latest METAR observation
        row = con.execute("""
            SELECT obs_time, temp_c, raw_metar FROM metar_obs
            WHERE obs_time <= ? AND temp_c IS NOT NULL
            ORDER BY obs_time DESC LIMIT 1
        """, (as_of_str,)).fetchone()
        
        if not row:
            return {"temp_c": None, "obs_time": None}
        
        result = {
            "temp_c": row["temp_c"],
            "obs_time": row["obs_time"],
            "dT_dt": None,
            "d2T_dt2": None,
        }
        
        # Get derivatives from parsed table
        parsed = con.execute("""
            SELECT dT_dt, d2T_dt2 FROM metar_parsed
            WHERE obs_time = ?
        """, (row["obs_time"],)).fetchone()
        
        if parsed:
            result["dT_dt"] = parsed["dT_dt"]
            result["d2T_dt2"] = parsed["d2T_dt2"]
        
        return result
    
    def get_recent_temperatures(self, con, market_date: str, limit: int = 10) -> List[float]:
        """Get recent temperature observations for trend analysis."""
        rows = con.execute("""
            SELECT temp_c FROM metar_obs
            WHERE obs_time LIKE ? AND temp_c IS NOT NULL
            ORDER BY obs_time DESC LIMIT ?
        """, (f"{market_date}%", limit)).fetchall()
        return [r["temp_c"] for r in rows if r["temp_c"] is not None]
    
    def calculate_temperature_trajectory(self, temps: List[float]) -> Dict[str, Optional[float]]:
        """Calculate temperature trajectory metrics."""
        if len(temps) < 2:
            return {"trend": None, "acceleration": None}
        
        # Simple linear trend (temp change per observation)
        n = len(temps)
        trend = (temps[-1] - temps[0]) / (n - 1) if n > 1 else None
        
        # Acceleration (change in trend)
        if len(temps) >= 3:
            trend1 = (temps[len(temps)//2] - temps[0]) / (len(temps)//2)
            trend2 = (temps[-1] - temps[len(temps)//2]) / (n - len(temps)//2)
            acceleration = trend2 - trend1
        else:
            acceleration = None
        
        return {"trend": trend, "acceleration": acceleration}
    
    def get_pws_divergence(self, con, fact_lat: float, fact_lon: float) -> Dict[str, Any]:
        """Calculate PWS temperature divergence from FACT."""
        rows = con.execute("""
            SELECT temp_c, distance_km, is_valid FROM pws_obs
            WHERE is_valid = 1 AND temp_c IS NOT NULL
            ORDER BY fetched_at DESC LIMIT 20
        """).fetchall()
        
        if not rows:
            return {"median": None, "mean": None, "divergence": None, "n": 0}
        
        temps = [r["temp_c"] for r in rows]
        distances = [r["distance_km"] for r in rows]
        
        sorted_temps = sorted(temps)
        n = len(sorted_temps)
        median = sorted_temps[n // 2] if n % 2 == 1 else (sorted_temps[n//2 - 1] + sorted_temps[n//2]) / 2
        mean = sum(temps) / n
        
        return {
            "median": median,
            "mean": mean,
            "std": math.sqrt(sum((t - mean)**2 for t in temps) / n) if n > 0 else None,
            "n": n
        }
    
    def get_forecast_error_distribution(self, con, target_date: str) -> Dict[str, Any]:
        """
        Build historical forecast error distribution.
        error = actual_max - forecast_max
        Only uses information available before prediction time.
        """
        # Get historical outcomes and forecasts
        rows = con.execute("""
            SELECT o.market_date, o.actual_max_c, f.max_temp as forecast_max
            FROM outcome o
            JOIN saws_forecast f ON f.target_date = o.market_date
            WHERE o.market_date < ? AND f.max_temp IS NOT NULL
            ORDER BY o.market_date DESC LIMIT ?
        """, (target_date, self.error_window_days)).fetchall()
        
        if not rows:
            return {"mean_error": 0.0, "std_error": 2.0, "n": 0}  # Default prior
        
        errors = [r["actual_max_c"] - r["forecast_max"] for r in rows if r["forecast_max"] is not None]
        
        if not errors:
            return {"mean_error": 0.0, "std_error": 2.0, "n": 0}
        
        n = len(errors)
        mean_error = sum(errors) / n
        variance = sum((e - mean_error)**2 for e in errors) / n if n > 1 else 4.0
        
        return {
            "mean_error": mean_error,
            "std_error": math.sqrt(variance),
            "n": n,
            "errors": errors
        }
    
    def compute_bucket_probability(self, 
                                   forecast_tmax: float,
                                   error_mean: float,
                                   error_std: float,
                                   bucket_lower: Optional[float],
                                   bucket_upper: Optional[float],
                                   current_temp: Optional[float] = None,
                                   time_remaining_hours: float = 12.0) -> float:
        """
        Compute P(Tmax in bucket) using forecast + error distribution.
        
        Uses a normal distribution centered on (forecast + error_mean) with
        std = error_std, adjusted for time remaining.
        """
        if bucket_lower is None and bucket_upper is None:
            return 0.0
        
        # Adjusted forecast center
        center = forecast_tmax + error_mean
        
        # Reduce uncertainty as day progresses (less time for surprises)
        time_factor = min(1.0, time_remaining_hours / 12.0)
        adjusted_std = error_std * (0.5 + 0.5 * time_factor)
        
        # Current temp as floor (Tmax can't be below current)
        if current_temp is not None:
            if bucket_upper is not None and bucket_upper < current_temp:
                return 0.0
            if bucket_lower is not None and bucket_lower < current_temp:
                # Bucket partially valid, adjust lower bound
                bucket_lower = max(bucket_lower, current_temp)
        
        # Normal CDF integration
        prob = self._normal_cdf_integral(bucket_lower, bucket_upper, center, adjusted_std)
        
        return max(0.0, min(1.0, prob))
    
    def _normal_cdf_integral(self, 
                             lower: Optional[float], 
                             upper: Optional[float], 
                             mu: float, 
                             sigma: float) -> float:
        """Compute probability mass between lower and upper bounds of normal distribution."""
        if sigma <= 0:
            sigma = 0.001
        
        def cdf(x):
            """Standard normal CDF approximation."""
            return 0.5 * (1 + math.erf((x - mu) / (sigma * math.sqrt(2))))
        
        if lower is None and upper is None:
            return 1.0
        elif lower is None:
            return cdf(upper)
        elif upper is None:
            return 1.0 - cdf(lower)
        else:
            return cdf(upper) - cdf(lower)
    
    def predict(self, 
                con,
                market_date: str,
                prediction_time: datetime = None,
                buckets: List[str] = None) -> Dict[str, float]:
        """
        Generate probability distribution for Tmax on market_date.
        
        Returns dict mapping bucket_label -> P(Tmax in bucket).
        """
        if prediction_time is None:
            prediction_time = datetime.now(timezone.utc)
        
        # Get forecast
        forecast_tmax = self.get_saws_forecast(con, market_date)
        if forecast_tmax is None:
            # Fallback: use current temp + typical diurnal range
            current_state = self.get_current_fact_state(con, prediction_time)
            if current_state["temp_c"] is not None:
                forecast_tmax = current_state["temp_c"] + 5.0  # Rough estimate
            else:
                forecast_tmax = 20.0  # Default prior
        
        # Get error distribution
        error_dist = self.get_forecast_error_distribution(con, market_date)
        
        # Get current conditions
        current_state = self.get_current_fact_state(con, prediction_time)
        current_temp = current_state["temp_c"]
        
        # Calculate time remaining in settlement day (local SAST = UTC+2)
        sast_time = prediction_time + timedelta(hours=2)
        # Ensure day_end_sast is timezone-aware
        day_end_sast = datetime(sast_time.year, sast_time.month, sast_time.day, 23, 59, 59, tzinfo=timezone.utc)
        time_remaining = (day_end_sast - sast_time).total_seconds() / 3600
        time_remaining = max(0, min(24, time_remaining))
        
        # Get bucket list from market if not provided
        if buckets is None:
            bucket_rows = con.execute("""
                SELECT DISTINCT bucket_label FROM market_price
                WHERE market_date = ?
            """, (market_date,)).fetchall()
            buckets = [r["bucket_label"] for r in bucket_rows]
        
        # Compute raw probabilities
        raw_probs = {}
        for bucket in buckets:
            lower, upper = self.get_bucket_bounds(bucket)
            prob = self.compute_bucket_probability(
                forecast_tmax=forecast_tmax,
                error_mean=error_dist["mean_error"],
                error_std=error_dist["std_error"],
                bucket_lower=lower,
                bucket_upper=upper,
                current_temp=current_temp,
                time_remaining_hours=time_remaining
            )
            raw_probs[bucket] = prob
        
        # Normalize to sum to 1 (handle overlapping buckets carefully)
        total = sum(raw_probs.values())
        if total > 0:
            normalized = {k: v / total for k, v in raw_probs.items()}
        else:
            # Equal prior if all zero
            n_buckets = len(buckets)
            normalized = {b: 1.0 / n_buckets for b in buckets}
        
        return {
            "probabilities": normalized,
            "forecast_tmax": forecast_tmax,
            "error_mean": error_dist["mean_error"],
            "error_std": error_dist["std_error"],
            "current_temp": current_temp,
            "time_remaining_hours": time_remaining,
            "prediction_time": prediction_time.isoformat(),
        }
