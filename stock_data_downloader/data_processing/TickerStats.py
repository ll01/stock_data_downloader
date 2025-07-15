from dataclasses import dataclass
from typing import Optional


@dataclass
class TickerStats:
    mean: float
    sd: float
    # Heston Model parameters
    kappa: Optional[float] = None
    theta: Optional[float] = None
    xi: Optional[float] = None
    rho: Optional[float] = None
    # GARCH Model parameters
    omega: Optional[float] = None
    alpha: Optional[float] = None
    beta: Optional[float] = None
    initial_variance: Optional[float] = None
    # For t-distribution (fat tails)
    degrees_of_freedom: Optional[float] = None