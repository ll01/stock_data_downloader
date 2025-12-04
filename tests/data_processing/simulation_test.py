from typing import Dict
import unittest
from stock_data_downloader.models import TickerConfig, GBMConfig
from stock_data_downloader.data_processing.simulation import GBMSimulator


class TestSimulation(unittest.TestCase):
    def test_gbm_simulator_deterministic_seed(self):
        stats: Dict[str, TickerConfig] = {
            'AAPL': TickerConfig(gbm=GBMConfig(mean=0.001, sd=0.05)),
            'GOOGL': TickerConfig(gbm=GBMConfig(mean=0.002, sd=0.01))
        }
        start_prices: Dict[str, float] = {'AAPL': 100.0, 'GOOGL': 2000.0}
        timesteps: int = 10
        interval: float = 1.0
        seed = 42
        sim1 = GBMSimulator(stats=stats, start_prices=start_prices, dt=interval, seed=seed)
        sim2 = GBMSimulator(stats=stats, start_prices=start_prices, dt=interval, seed=seed)
        res1 = [sim1.next_bars() for _ in range(timesteps)]
        res2 = [sim2.next_bars() for _ in range(timesteps)]
        # Compare closes for determinism
        closes1 = [[b.close for b in bars] for bars in res1]
        closes2 = [[b.close for b in bars] for bars in res2]
        assert closes1 == closes2

if __name__ == "__main__":
    unittest.main()
