"""Walk-forward backtest engine for WeatherEdge."""

import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

from weatheredge.db import get_connection, utc_now_iso
from weatheredge.models.tmax_model import TmaxModel
from weatheredge.models.calibration import CalibrationEngine
from weatheredge.trading.paper_trading import PaperTradingEngine, PaperTradeConfig


class WalkForwardBacktester:
    """
    Chronological walk-forward backtester.
    
    At each historical time T, ONLY uses information available at or before T.
    No future leakage. Simulates the full pipeline:
    1. Reconstruct available weather information
    2. Reconstruct available forecast
    3. Generate model probability
    4. Reconstruct executable Polymarket price
    5. Calculate edge
    6. Determine whether trade would occur
    7. Simulate execution
    8. Settle based on official outcome
    9. Calculate PnL
    """
    
    def __init__(self, config: PaperTradeConfig = None):
        self.config = config or PaperTradeConfig()
        self.tmax_model = TmaxModel()
        self.calibration = CalibrationEngine()
        self.trader = PaperTradingEngine(self.config)
    
    def get_historical_dates(self, con, start_date: str, end_date: str) -> List[str]:
        """Get list of market dates with both market data and outcomes."""
        rows = con.execute("""
            SELECT DISTINCT mp.market_date
            FROM market_price mp
            JOIN outcome o ON o.market_date = mp.market_date
            WHERE mp.market_date >= ? AND mp.market_date <= ?
            ORDER BY mp.market_date ASC
        """, (start_date, end_date)).fetchall()
        
        return [r["market_date"] for r in rows]
    
    def get_market_snapshots(self, con, market_date: str, as_of: datetime) -> List[Dict]:
        """Get market prices as of a specific timestamp."""
        as_of_str = as_of.strftime("%Y-%m-%dT%H:%M:%SZ")
        
        rows = con.execute("""
            SELECT bucket_label, yes_price_cents, no_price_cents, volume_usd, raw_payload
            FROM market_price
            WHERE market_date = ? AND fetched_at <= ?
            ORDER BY fetched_at DESC
            LIMIT 10
        """, (market_date, as_of_str)).fetchall()
        
        # Group by bucket and get latest per bucket
        buckets = {}
        for r in rows:
            if r["bucket_label"] not in buckets:
                buckets[r["bucket_label"]] = {
                    "bucket_label": r["bucket_label"],
                    "yes_ask": r["yes_price_cents"],
                    "no_ask": r["no_price_cents"],
                    "volume": r["volume_usd"],
                    "raw": r["raw_payload"]
                }
        
        return list(buckets.values())
    
    def simulate_day(self, con, market_date: str) -> Dict:
        """Simulate trading for a single day using only information available that day."""
        # Get prediction time (morning of market date, SAST = UTC+2)
        try:
            date_obj = datetime.strptime(market_date, "%Y-%m-%d")
            # Predict at 10:00 SAST = 08:00 UTC
            prediction_time = datetime(date_obj.year, date_obj.month, date_obj.day, 8, 0, 0, tzinfo=timezone.utc)
        except ValueError:
            return {"status": "error", "reason": "invalid_date"}
        
        # Get model prediction
        prediction = self.tmax_model.predict(con, market_date, prediction_time)
        
        # Get calibration mapping from historical data
        cal_result = self.calibration.run_calibration(con, market_date)
        cal_points = cal_result.get("calibration_points", []) if cal_result.get("status") == "ok" else []
        
        # Apply calibration to probabilities
        calibrated_probs = {}
        for bucket, prob in prediction["probabilities"].items():
            calibrated_prob = self.calibration.calibrate_probability(cal_points, prob)
            calibrated_probs[bucket] = round(calibrated_prob, 4)
        
        # Get market snapshots
        market_snapshots = self.get_market_snapshots(con, market_date, prediction_time)
        
        # Find trades with edge
        trades_taken = []
        for bucket_data in market_snapshots:
            bucket = bucket_data["bucket_label"]
            yes_ask = bucket_data["yes_ask"]
            
            if bucket not in calibrated_probs:
                continue
            
            model_prob = calibrated_probs[bucket]
            edge = self.trader.calculate_edge(model_prob, yes_ask)
            
            # Check if trade meets criteria
            spread = 0.05  # Simplified - would calculate from orderbook
            liquidity = bucket_data.get("volume", 0)
            
            if self.trader.should_trade(edge, spread, liquidity):
                # Execute trade
                shares = min(self.config.max_position_size, int(self.config.starting_capital * 0.1 * 100 / yes_ask))
                
                side = "YES" if edge > 0 else "NO"
                price = yes_ask if side == "YES" else bucket_data["no_ask"]
                
                trade = self.trader.execute_buy(
                    market_date=market_date,
                    bucket_label=bucket,
                    side=side,
                    shares=shares,
                    price_cents=price,
                    reason=f"edge={edge:.3f}, model_prob={model_prob:.3f}"
                )
                
                if trade:
                    trades_taken.append({
                        "bucket": bucket,
                        "side": side,
                        "shares": shares,
                        "price": price,
                        "edge": edge,
                        "model_prob": model_prob
                    })
        
        # Store prediction
        for bucket, prob in prediction["probabilities"].items():
            cal_prob = calibrated_probs.get(bucket, prob)
            con.execute("""
                INSERT OR IGNORE INTO model_prediction
                (prediction_time, market_date, bucket_label, model_probability,
                 calibrated_probability, model_version, features_used, raw_payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                prediction_time.isoformat(),
                market_date,
                bucket,
                round(prob, 4),
                round(cal_prob, 4),
                "tmax_v1",
                json.dumps({"forecast_tmax": prediction["forecast_tmax"]}),
                json.dumps(prediction)
            ))
        
        con.commit()
        
        return {
            "status": "ok",
            "market_date": market_date,
            "prediction_time": prediction_time.isoformat(),
            "forecast_tmax": prediction["forecast_tmax"],
            "probabilities": prediction["probabilities"],
            "calibrated_probs": calibrated_probs,
            "trades_taken": trades_taken
        }
    
    def run_backtest(self, start_date: str, end_date: str) -> Dict:
        """Run full walk-forward backtest over date range."""
        con = get_connection()
        
        dates = self.get_historical_dates(con, start_date, end_date)
        
        if not dates:
            return {"status": "error", "reason": "no_data_in_range"}
        
        results = []
        for market_date in dates:
            day_result = self.simulate_day(con, market_date)
            results.append(day_result)
            
            # Settle any positions for this date
            outcome_row = con.execute("""
                SELECT actual_max_c FROM outcome WHERE market_date = ?
            """, (market_date,)).fetchone()
            
            if outcome_row:
                actual_max = outcome_row["actual_max_c"]
                # Determine winning bucket (simplified)
                winning_bucket = f"{round(actual_max)}°C"
                self.trader.settle_market(market_date, actual_max, winning_bucket)
        
        # Get final metrics
        metrics = self.trader.get_performance_metrics()
        
        # Save backtest result
        backtest_time = utc_now_iso()
        con.execute("""
            INSERT INTO backtest_result
            (backtest_time, start_date, end_date, starting_capital, ending_capital,
             total_pnl, roi, num_trades, win_rate, profit_factor, max_drawdown,
             sharpe_ratio, config_snapshot, trade_log)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            backtest_time,
            start_date,
            end_date,
            self.config.starting_capital,
            metrics.get("current_capital", self.config.starting_capital),
            metrics.get("total_pnl_usd", 0),
            metrics.get("roi", 0),
            metrics.get("num_trades", 0),
            metrics.get("win_rate"),
            metrics.get("profit_factor"),
            metrics.get("max_drawdown_cents", 0),
            metrics.get("sharpe_ratio"),
            json.dumps({
                "starting_capital": self.config.starting_capital,
                "max_position_size": self.config.max_position_size,
                "min_edge_threshold": self.config.min_edge_threshold,
                "max_spread_threshold": self.config.max_spread_threshold,
                "min_liquidity_usd": self.config.min_liquidity_usd
            }),
            json.dumps(self.trader.trade_log)
        ))
        con.commit()
        con.close()
        
        return {
            "status": "ok",
            "start_date": start_date,
            "end_date": end_date,
            "dates_simulated": len(dates),
            "daily_results": results,
            "metrics": metrics,
            "backtest_time": backtest_time
        }
