from typing import Dict
import unittest
from stock_data_downloader.data_processing.TickerStats import TickerStats
from stock_data_downloader.data_processing.simulation import simulate_prices


class TestSimulation(unittest.TestCase):
    def test_simulate_prices(self):
        stats : Dict[str, TickerStats] = {
            'AAPL': TickerStats(mean=0.001, sd=5.0),
            'GOOGL': TickerStats(mean=0.002, sd=1.0)
        }
        start_prices : Dict[str, float] = {'AAPL': 100.0, 'GOOGL': 2000.0}
        timesteps : int = 1000
        interval : float = 1.0
        seed = 42
        results1 = simulate_prices(stats, start_prices, timesteps, interval, seed=seed)
        results2 = simulate_prices(stats, start_prices, timesteps, interval, seed=seed)
        assert results1 == results2, "Oops—they differ!"

if __name__ == "__main__":
    unittest.main()