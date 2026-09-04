"""Paper trading simulator for WeatherEdge."""

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from weatheredge.db import get_connection, utc_now_iso
from weatheredge.config import (
    STARTING_CAPITAL, MAX_POSITION_SIZE, MIN_EDGE_THRESHOLD,
    MAX_SPREAD_THRESHOLD, MIN_LIQUIDITY_USD
)


@dataclass
class PaperTradeConfig:
    """Configuration for paper trading."""
    starting_capital: float = STARTING_CAPITAL
    max_position_size: int = MAX_POSITION_SIZE
    min_edge_threshold: float = MIN_EDGE_THRESHOLD
    max_spread_threshold: float = MAX_SPREAD_THRESHOLD
    min_liquidity_usd: float = MIN_LIQUIDITY_USD
    fee_rate: float = 0.02  # 2% fees
    slippage_rate: float = 0.01  # 1% slippage


@dataclass 
class Position:
    """Represents an open position."""
    market_date: str
    bucket_label: str
    side: str  # 'YES' or 'NO'
    shares: int
    entry_price_cents: float
    entry_time: str
    current_value_cents: float = 0.0
    unrealized_pnl_cents: float = 0.0


@dataclass
class TradeResult:
    """Result of a single trade."""
    market_date: str
    bucket_label: str
    side: str
    shares: int
    entry_price_cents: float
    exit_price_cents: Optional[float]
    pnl_cents: float
    fees_cents: float
    status: str  # 'open', 'closed', 'settled'
    entry_reason: str = ""
    notes: str = ""


class PaperTradingEngine:
    """
    Paper trading simulator for WeatherEdge.
    
    Simulates trades based on model edge without real money.
    Tracks PnL, positions, and performance metrics.
    """
    
    def __init__(self, config: PaperTradeConfig = None):
        self.config = config or PaperTradeConfig()
        self.capital = self.config.starting_capital
        self.initial_capital = self.config.starting_capital
        self.positions: Dict[str, Position] = {}  # key: market_date_bucket
        self.closed_trades: List[TradeResult] = []
        self.trade_log: List[Dict] = []
    
    def _position_key(self, market_date: str, bucket_label: str) -> str:
        return f"{market_date}_{bucket_label}"
    
    def calculate_edge(self, model_prob: float, executable_ask: float) -> float:
        """Calculate edge: model_probability - executable_yes_ask."""
        return model_prob - (executable_ask / 100.0)  # Convert cents to probability
    
    def should_trade(self, edge: float, spread: float, liquidity: float) -> bool:
        """Determine if trade meets criteria."""
        if abs(edge) < self.config.min_edge_threshold:
            return False
        if spread > self.config.max_spread_threshold:
            return False
        if liquidity < self.config.min_liquidity_usd:
            return False
        return True
    
    def execute_buy(self, 
                    market_date: str,
                    bucket_label: str,
                    side: str,
                    shares: int,
                    price_cents: float,
                    reason: str = "") -> Optional[TradeResult]:
        """Execute a buy order (paper trade)."""
        cost_cents = shares * price_cents
        fees_cents = cost_cents * self.config.fee_rate
        slippage_cents = cost_cents * self.config.slippage_rate
        total_cost_cents = cost_cents + fees_cents + slippage_cents
        
        # Check capital
        if total_cost_cents > self.capital * 100:  # Convert capital to cents
            return None
        
        # Update capital
        self.capital -= total_cost_cents / 100.0
        
        # Create or update position
        key = self._position_key(market_date, bucket_label)
        if key in self.positions:
            pos = self.positions[key]
            # Average into existing position
            total_shares = pos.shares + shares
            total_cost = pos.shares * pos.entry_price_cents + shares * price_cents
            avg_price = total_cost / total_shares
            pos.shares = total_shares
            pos.entry_price_cents = avg_price
        else:
            pos = Position(
                market_date=market_date,
                bucket_label=bucket_label,
                side=side,
                shares=shares,
                entry_price_cents=price_cents,
                entry_time=utc_now_iso()
            )
            self.positions[key] = pos
        
        # Log trade
        trade = TradeResult(
            market_date=market_date,
            bucket_label=bucket_label,
            side=side,
            shares=shares,
            entry_price_cents=price_cents,
            exit_price_cents=None,
            pnl_cents=0,
            fees_cents=fees_cents + slippage_cents,
            status='open',
            entry_reason=reason
        )
        self.trade_log.append({
            "type": "buy",
            "timestamp": utc_now_iso(),
            "market_date": market_date,
            "bucket_label": bucket_label,
            "side": side,
            "shares": shares,
            "price_cents": price_cents,
            "fees_cents": fees_cents + slippage_cents
        })
        
        return trade
    
    def execute_sell(self,
                     market_date: str,
                     bucket_label: str,
                     side: str,
                     shares: int,
                     price_cents: float,
                     reason: str = "") -> Optional[TradeResult]:
        """Execute a sell order (close position)."""
        key = self._position_key(market_date, bucket_label)
        
        if key not in self.positions:
            return None
        
        pos = self.positions[key]
        shares_to_sell = min(shares, pos.shares)
        
        if shares_to_sell <= 0:
            return None
        
        # Calculate proceeds
        proceeds_cents = shares_to_sell * price_cents
        fees_cents = proceeds_cents * self.config.fee_rate
        slippage_cents = proceeds_cents * self.config.slippage_rate
        net_proceeds_cents = proceeds_cents - fees_cents - slippage_cents
        
        # Calculate PnL
        cost_basis_cents = shares_to_sell * pos.entry_price_cents
        pnl_cents = net_proceeds_cents - cost_basis_cents
        
        # Update capital
        self.capital += net_proceeds_cents / 100.0
        
        # Update or remove position
        pos.shares -= shares_to_sell
        if pos.shares <= 0:
            del self.positions[key]
        
        # Record closed trade
        trade = TradeResult(
            market_date=market_date,
            bucket_label=bucket_label,
            side=side,
            shares=shares_to_sell,
            entry_price_cents=pos.entry_price_cents,
            exit_price_cents=price_cents,
            pnl_cents=pnl_cents,
            fees_cents=fees_cents + slippage_cents,
            status='closed',
            entry_reason=pos.entry_reason if hasattr(pos, 'entry_reason') else "",
            notes=reason
        )
        self.closed_trades.append(trade)
        self.trade_log.append({
            "type": "sell",
            "timestamp": utc_now_iso(),
            "market_date": market_date,
            "bucket_label": bucket_label,
            "side": side,
            "shares": shares_to_sell,
            "price_cents": price_cents,
            "pnl_cents": pnl_cents,
            "fees_cents": fees_cents + slippage_cents
        })
        
        return trade
    
    def settle_market(self, market_date: str, actual_max: float, winning_bucket: str) -> List[TradeResult]:
        """Settle all positions for a market date based on actual outcome."""
        settled = []
        keys_to_remove = [k for k in self.positions if k.startswith(f"{market_date}_")]
        
        for key in keys_to_remove:
            pos = self.positions[key]
            
            # Determine if position won
            won = pos.bucket_label == winning_bucket
            
            if won:
                # Winning position pays out 100 cents per share
                payout_cents = pos.shares * 100
                cost_basis_cents = pos.shares * pos.entry_price_cents
                pnl_cents = payout_cents - cost_basis_cents
                self.capital += payout_cents / 100.0
                status = 'settled'
            else:
                # Losing position worthless
                pnl_cents = -pos.shares * pos.entry_price_cents
                status = 'settled'
            
            trade = TradeResult(
                market_date=market_date,
                bucket_label=pos.bucket_label,
                side=pos.side,
                shares=pos.shares,
                entry_price_cents=pos.entry_price_cents,
                exit_price_cents=100 if won else 0,
                pnl_cents=pnl_cents,
                fees_cents=0,
                status=status,
                settlement_value=100 if won else 0
            )
            self.closed_trades.append(trade)
            settled.append(trade)
            
            del self.positions[key]
        
        return settled
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Calculate comprehensive performance metrics."""
        if not self.closed_trades:
            return {
                "total_pnl_cents": 0,
                "roi": 0,
                "num_trades": 0,
                "win_rate": None,
                "profit_factor": None,
                "max_drawdown": None,
                "avg_trade_cents": None,
                "median_trade_cents": None,
                "sharpe_ratio": None
            }
        
        # Basic metrics
        total_pnl_cents = sum(t.pnl_cents for t in self.closed_trades)
        num_trades = len(self.closed_trades)
        
        # Win rate
        wins = [t for t in self.closed_trades if t.pnl_cents > 0]
        losses = [t for t in self.closed_trades if t.pnl_cents < 0]
        win_rate = len(wins) / num_trades if num_trades > 0 else 0
        
        # Profit factor
        gross_profit = sum(t.pnl_cents for t in wins)
        gross_loss = abs(sum(t.pnl_cents for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Average and median trade
        pnls = [t.pnl_cents for t in self.closed_trades]
        avg_trade = sum(pnls) / len(pnls)
        sorted_pnls = sorted(pnls)
        median_trade = sorted_pnls[len(pnls) // 2] if len(pnls) % 2 == 1 else \
                       (sorted_pnls[len(pnls)//2 - 1] + sorted_pnls[len(pnls)//2]) / 2
        
        # ROI
        roi = (self.capital - self.initial_capital) / self.initial_capital
        
        # Max drawdown (simplified)
        cumulative = 0
        peak = 0
        max_dd = 0
        for t in self.closed_trades:
            cumulative += t.pnl_cents
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
        
        # Sharpe ratio (annualized, assuming daily returns)
        if len(pnls) > 1:
            mean_pnl = sum(pnls) / len(pnls)
            std_pnl = (sum((p - mean_pnl)**2 for p in pnls) / (len(pnls) - 1)) ** 0.5
            sharpe = (mean_pnl / std_pnl) * (252 ** 0.5) if std_pnl > 0 else 0
        else:
            sharpe = None
        
        return {
            "total_pnl_cents": round(total_pnl_cents, 2),
            "total_pnl_usd": round(total_pnl_cents / 100, 2),
            "roi": round(roi, 4),
            "num_trades": num_trades,
            "win_rate": round(win_rate, 3),
            "profit_factor": round(profit_factor, 3) if profit_factor != float('inf') else None,
            "max_drawdown_cents": round(max_dd, 2),
            "avg_trade_cents": round(avg_trade, 2),
            "median_trade_cents": round(median_trade, 2),
            "sharpe_ratio": round(sharpe, 3) if sharpe else None,
            "current_capital": round(self.capital, 2),
            "initial_capital": self.initial_capital
        }
    
    def save_to_db(self, con):
        """Save all trades to database."""
        for trade in self.closed_trades:
            con.execute("""
                INSERT OR REPLACE INTO paper_trade
                (trade_time, market_date, bucket_label, side, shares,
                 entry_price_cents, exit_price_cents, exit_time, pnl_cents,
                 status, settlement_value, fees_cents, entry_reason, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.entry_time if hasattr(trade, 'entry_time') else utc_now_iso(),
                trade.market_date,
                trade.bucket_label,
                trade.side,
                trade.shares,
                trade.entry_price_cents,
                trade.exit_price_cents,
                utc_now_iso() if trade.status != 'open' else None,
                trade.pnl_cents,
                trade.status,
                trade.settlement_value if hasattr(trade, 'settlement_value') else None,
                trade.fees_cents,
                trade.entry_reason,
                trade.notes
            ))
        con.commit()
