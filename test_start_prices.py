#!/usr/bin/env python3
"""
Test script to validate the new start_price functionality
"""

import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from stock_data_downloader.models import TickerConfig, HestonConfig, GBMConfig
from stock_data_downloader.data_processing.simulation import generate_initial_prices, HestonSimulator, GBMSimulator

def test_generate_initial_prices():
    print("Testing generate_initial_prices function...")
    
    # Test 1: Ticker config with explicit start_price
    config_with_price = TickerConfig(heston=HestonConfig(kappa=1.0, theta=0.04, xi=0.2, rho=-0.5), start_price=150.0)
    prices1 = generate_initial_prices({'AAPL': config_with_price})
    assert prices1['AAPL'] == 150.0, f"Expected 150.0, got {prices1['AAPL']}"
    print("✓ Test 1 passed: Uses explicit start_price")
    
    # Test 2: Ticker config without start_price
    config_without_price = TickerConfig(heston=HestonConfig(kappa=1.0, theta=0.04, xi=0.2, rho=-0.5))
    prices2 = generate_initial_prices({'GOOGL': config_without_price})
    assert prices2['GOOGL'] == 100.0, f"Expected 100.0, got {prices2['GOOGL']}"
    print("✓ Test 2 passed: Uses default price when no start_price")
    
    # Test 3: Mixed configs
    mixed_configs = {
        'AAPL': TickerConfig(heston=HestonConfig(kappa=1.0, theta=0.04, xi=0.2, rho=-0.5), start_price=150.0),
        'GOOGL': TickerConfig(heston=HestonConfig(kappa=1.1, theta=0.05, xi=0.22, rho=-0.48)),
        'MSFT': TickerConfig(gbm=GBMConfig(mean=0.001, sd=0.02), start_price=250.0)
    }
    prices3 = generate_initial_prices(mixed_configs)
    assert prices3['AAPL'] == 150.0, f"Expected 150.0, got {prices3['AAPL']}"
    assert prices3['GOOGL'] == 100.0, f"Expected 100.0, got {prices3['GOOGL']}"
    assert prices3['MSFT'] == 250.0, f"Expected 250.0, got {prices3['MSFT']}"
    print("✓ Test 3 passed: Mixed configs with and without start_price")
    
    print("All generate_initial_prices tests passed!")

def test_simulator_with_start_prices():
    print("\nTesting simulators with start_prices...")
    
    # Test HestonSimulator with explicit start_prices
    configs = {
        'AAPL': TickerConfig(heston=HestonConfig(kappa=1.0, theta=0.04, xi=0.2, rho=-0.5), start_price=150.0),
        'GOOGL': TickerConfig(heston=HestonConfig(kappa=1.1, theta=0.05, xi=0.22, rho=-0.48), start_price=200.0)
    }
    
    # Initialize simulator without providing start_prices - should generate from configs
    simulator = HestonSimulator(stats=configs, dt=1.0)
    
    # Check that the initial prices match what was specified in the configs
    assert simulator.current_prices['AAPL'] == 150.0, f"Expected 150.0, got {simulator.current_prices['AAPL']}"
    assert simulator.current_prices['GOOGL'] == 200.0, f"Expected 200.0, got {simulator.current_prices['GOOGL']}"
    
    print("✓ HestonSimulator test passed: Uses start_price from config when no start_prices provided")
    
    # Test GBMSimulator with explicit start_prices
    gbm_configs = {
        'TSLA': TickerConfig(gbm=GBMConfig(mean=0.001, sd=0.02), start_price=800.0),
        'AMZN': TickerConfig(gbm=GBMConfig(mean=0.0015, sd=0.015), start_price=3200.0)
    }
    
    # Initialize simulator without providing start_prices - should generate from configs
    gbm_simulator = GBMSimulator(stats=gbm_configs, dt=1.0)
    
    assert gbm_simulator.current_prices['TSLA'] == 800.0, f"Expected 800.0, got {gbm_simulator.current_prices['TSLA']}"
    assert gbm_simulator.current_prices['AMZN'] == 3200.0, f"Expected 3200.0, got {gbm_simulator.current_prices['AMZN']}"
    
    print("✓ GBMSimulator test passed: Uses start_price from config when no start_prices provided")
    
    print("All simulator tests passed!")

if __name__ == "__main__":
    test_generate_initial_prices()
    test_simulator_with_start_prices()
    print("\n🎉 All tests passed! The start_price functionality is working correctly.")