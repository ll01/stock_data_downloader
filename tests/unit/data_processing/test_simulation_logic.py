import pytest
from stock_data_downloader.data_processing.simulation import GBMSimulator, HestonSimulator
from stock_data_downloader.models import TickerConfig, GBMConfig, HestonConfig

def test_gbm_simulator_generates_timesteps():
    stats = {
        "AAPL": TickerConfig(gbm=GBMConfig(mean=0.01, sd=0.1)),
        "MSFT": TickerConfig(gbm=GBMConfig(mean=0.02, sd=0.15)),
    }
    start_prices = {"AAPL": 100.0, "MSFT": 200.0}
    dt = 1/252
    sim = GBMSimulator(stats=stats, start_prices=start_prices, dt=dt, seed=42)

    bars1 = sim.next_bars()
    assert isinstance(bars1, list)
    assert len(bars1) == 2
    for b in bars1:
        assert hasattr(b, "ticker")
        assert b.ticker in start_prices
        assert b.close >= 0

    bars2 = sim.next_bars()
    # successive steps should change at least one ticker price
    assert any(a.close != b.close for a, b in zip(bars1, bars2))

    sim.reset()
    assert sim.step_idx == 0
    assert sim.current_prices == sim.start_prices

def test_heston_simulator_variance_matches_expected():
    heston_cfg = HestonConfig(kappa=2.0, theta=0.05, xi=0.3, rho=-0.5)
    stats = {"BTC": TickerConfig(heston=heston_cfg)}
    start_prices = {"BTC": 1000.0}
    sim = HestonSimulator(stats=stats, start_prices=start_prices, dt=1/252, seed=123)

    variances = []
    for _ in range(50):
        _ = sim.next_bars()
        variances.append(sim.current_variances["BTC"])

    assert all(v >= 0 for v in variances)
    mean_variance = sum(variances) / len(variances)
    assert mean_variance > 0

    sim.reset()
    assert sim.step_idx == 0
    assert sim.current_prices == sim.start_prices