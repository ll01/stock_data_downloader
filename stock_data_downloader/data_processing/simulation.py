from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from math import exp, sqrt
import random
from typing import AsyncGenerator, Dict, List, Optional, Any, cast
import numpy as np
import asyncio
from stock_data_downloader.models import GBMConfig, HestonConfig, TickerConfig, TickerData
from typing import Protocol

def _calculate_gbm_step(
    mean: float, sd: float, rng: random.Random, last_price: float, interval: float
) -> float:
    """Simulate a single price step using geometric Brownian motion."""
    return last_price * exp(
        (mean - 0.5 * sd**2) * interval + rng.gauss(0, 1) * sd * sqrt(interval)
    )

logger = logging.getLogger(__name__)

class ISimulator(Protocol):
    @abstractmethod
    def next_bars(self) -> List[TickerData]:
        raise NotImplementedError
    @abstractmethod
    def reset(self) -> None:
        raise NotImplementedError
    
    def __aiter__(self):
        return self

    async def __anext__(self):
        # Optional: allow `async for bar in simulator: ...`
        return self.next_bars()
        

@dataclass
class StrictHestonTickerConfig:
    """TickerConfig guaranteed to have .heston"""
    heston: HestonConfig          # non-optional
    
class HestonSimulator(ISimulator):
    """
    Stateful Heston simulator that can be stepped forward one bar at a time.
    Use with `async for` or `await sim.next_bars()`.
    """
    def __init__(
        self,
        stats: Dict[str, TickerConfig],
        start_prices: Dict[str, float],
        dt: float,
        seed: Optional[int] = None,
    ):
        # per-instance RNG for determinism
        self._rng = np.random.default_rng(seed)

        self.dt = dt
        self.start_time = datetime.now(timezone.utc)
        
        strict_stats: Dict[str, StrictHestonTickerConfig] = {}
        invalid_henson_stats  = []
        for ticker, cfg in stats.items():
            if cfg.heston is None:
                invalid_henson_stats.append(ticker)
            else:
                strict_stats[ticker] = StrictHestonTickerConfig(heston=cfg.heston)
        if invalid_henson_stats:
            logger.warning(f"{len(invalid_henson_stats)} tickers dont have henson stats")
        self.start_prices = start_prices
        self.stats = strict_stats  # now .heston is never None
        self.current_prices = start_prices.copy()
        self.current_variances = {
            t: cfg.heston.theta for t, cfg in self.stats.items()
        }
        self.step_idx = 0
    def next_bars(self) -> List[TickerData]:
        """
        Return the next OHLCV bar for every ticker.
        Call this repeatedly until you’re done.
        """
        bars: List[TickerData] = []
        step_duration = self.dt * 252
        ts = self.start_time + timedelta(days=(self.step_idx * step_duration))
        
        for ticker, s in self.stats.items():
            if ticker not in self.current_prices or ticker not in self.current_variances:
                continue
            mu = 0
            kappa, theta, xi, rho = (
                s.heston.kappa or 3.0,
                s.heston.theta or 0.04,
                s.heston.xi or 0.3,
                s.heston.rho or -0.6,
            )

            corr = np.array([[1, rho], [rho, 1]])
            z = self._rng.normal(size=2) @ np.linalg.cholesky(corr).T
            price_shock, var_shock = z[0], z[1]

            last_v = max(self.current_variances[ticker], 0)
            dv = kappa * (theta - last_v) * self.dt + xi * np.sqrt(last_v * self.dt) * var_shock
            new_v = last_v + dv
            self.current_variances[ticker] = new_v

            last_p = self.current_prices[ticker]
            dp = mu * last_p * self.dt + np.sqrt(last_v * self.dt) * last_p * price_shock
            new_p = last_p + dp
            self.current_prices[ticker] = new_p

            open_p = last_p
            high_p = max(open_p, new_p) + self._rng.uniform(0, 0.01) * new_p
            low_p = min(open_p, new_p) - self._rng.uniform(0, 0.01) * new_p
            
            bars.append(
                TickerData(
                    ticker= ticker,
                    timestamp= ts.isoformat(),
                    open= open_p,
                    high= high_p,
                    low=low_p,
                    close= new_p,
                    volume= np.random.randint(10_000, 50_000),
                    
                ) 
            )

        self.step_idx += 1
        return bars
    
    def reset(self) -> None:
        self.step_idx = 0
        self.current_prices = self.start_prices.copy()


@dataclass
class StrictGBMTickerConfig:
    gbm: GBMConfig  # non-optional

class GBMSimulator(ISimulator):
    """
    Stateful GBM simulator that steps forward one bar at a time.
    Guarantees every TickerConfig has a non-None .gbm section.
    """

    def __init__(
        self,
        stats: Dict[str, TickerConfig],
        start_prices: Dict[str, float],
        dt: float,
        seed: int | None = None,
    ):
        # per-instance RNG for determinism
        self._rng = np.random.default_rng(seed)

        self.dt = dt
        self.start_time = datetime.now(timezone.utc)

        # Build narrow dict where .gbm is present
        strict_stats: Dict[str, StrictGBMTickerConfig] = {}
        invalid = []
        for ticker, cfg in stats.items():
            if cfg.gbm is None:
                invalid.append(ticker)
            else:
                strict_stats[ticker] = StrictGBMTickerConfig(gbm=cfg.gbm)

        if invalid:
            logger.warning(f"{len(invalid)} tickers missing GBM config: {invalid}")

        self.stats = strict_stats
        self.start_prices = start_prices
        self.current_prices = start_prices.copy()
        self.step_idx = 0

    def next_bars(self) -> list[TickerData]:
        bars: list[TickerData] = []
        step_days = self.dt * 252
        ts = self.start_time + timedelta(days=self.step_idx * step_days)

        for ticker, s in self.stats.items():
            if ticker not in self.current_prices:
                continue

            mu = s.gbm.mean
            sigma = s.gbm.sd
            last_price = self.current_prices[ticker]

            # GBM closed-form update
            z = self._rng.normal()
            growth = (mu - 0.5 * sigma ** 2) * self.dt + sigma * np.sqrt(self.dt) * z
            new_price = last_price * np.exp(growth)
            self.current_prices[ticker] = new_price

            # Simple OHLC
            open_p = last_price
            high_p = max(open_p, new_price) + self._rng.uniform(0, 0.01) * new_price
            low_p = min(open_p, new_price) - self._rng.uniform(0, 0.01) * new_price

            bars.append(
                TickerData(
                    ticker=ticker,
                    timestamp=ts.isoformat(),
                    open=open_p,
                    high=high_p,
                    low=low_p,
                    close=new_price,
                    volume=int(np.random.randint(10_000, 50_000)),
                )
            )

        self.step_idx += 1
        return bars

    def reset(self) -> None:
        self.step_idx = 0
        self.current_prices = self.start_prices.copy()
        
        