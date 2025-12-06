
import asyncio
import numpy as np
import pandas as pd
from stock_data_downloader.data_processing.simulation import HestonSimulator
from stock_data_downloader.models import TickerConfig, HestonConfig

async def main():
    # User's config parameters (approximate from what I saw)
    interval = 0.0000275573192  # 10 minutes annualized
    timesteps = 1000 # User mentioned 1000 runs? Or 1000 steps? Let's run enough to see stats.
    # Let's run 144 * 10 = 1440 steps (10 days)
    timesteps = 1440 
    
    ticker_configs = {
        "SOL": TickerConfig(
            heston=HestonConfig(
                kappa=1.5,
                theta=0.08,
                xi=0.6,
                rho=-0.75
            ),
            start_price=100.0
        )
    }
    
    print(f"Initializing HestonSimulator with interval={interval}, timesteps={timesteps}")
    
    sim = HestonSimulator(
        stats=ticker_configs,
        start_prices={"SOL": 100.0},
        dt=interval,
        seed=42
    )
    
    data = []
    for _ in range(timesteps):
        bars = sim.next_bars()
        for bar in bars:
            data.append(bar.dict())
            
    df = pd.DataFrame(data)
    df['close'] = df['close'].astype(float)
    
    # Calculate returns
    df['return'] = df['close'].pct_change()
    
    # Analyze
    print("\n--- Analysis ---")
    print(f"Start Price: {df['close'].iloc[0]}")
    print(f"End Price: {df['close'].iloc[-1]}")
    print(f"Mean Return: {df['return'].mean()}")
    print(f"Std Dev Return (per step): {df['return'].std()}")
    
    # Annualize volatility
    # steps per year = 1 / interval
    steps_per_year = 1 / interval
    annualized_vol = df['return'].std() * np.sqrt(steps_per_year)
    print(f"Annualized Volatility: {annualized_vol:.4f}")
    
    expected_vol = np.sqrt(0.08) # sqrt(theta)
    print(f"Expected Long-Run Volatility (sqrt(theta)): {expected_vol:.4f}")
    
    # Check for jumps
    max_return = df['return'].max()
    min_return = df['return'].min()
    print(f"Max Single Step Return: {max_return:.4f}")
    print(f"Min Single Step Return: {min_return:.4f}")

if __name__ == "__main__":
    asyncio.run(main())
