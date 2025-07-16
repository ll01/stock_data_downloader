from collections import deque
from typing import Any, Callable, Dict, List
import asyncio
import logging

class StreamProcessor:
    """Normalizes and processes market data from both real-time and backtest sources"""
    
    def __init__(self, max_rate: int = 1000):
        self.max_rate = max_rate  # Max messages per second
        self.subscribers: List[Callable] = []
        self.market_data_cache: Dict[str, Any] = {}
        self._queue = asyncio.Queue()
        self._processing_task = None
        
    async def start(self):
        """Start processing queue"""
        self._processing_task = asyncio.create_task(self._process_queue())
        
    async def stop(self):
        """Stop processing queue"""
        if self._processing_task:
            self._processing_task.cancel()
            
    def subscribe(self, callback: Callable):
        """Register callback for processed data"""
        self.subscribers.append(callback)
        
    async def ingest(self, data: Any):
        """Add raw data to processing queue"""
        await self._queue.put(data)
        
    async def _process_queue(self):
        """Process queue with rate limiting"""
        try:
            while True:
                # Implement rate limiting
                start_time = asyncio.get_event_loop().time()
                
                if not self._queue.empty():
                    data = await self._queue.get()
                    processed = self._process_data(data)
                    await self._notify_subscribers(processed)
                    
                # Maintain rate limit
                elapsed = asyncio.get_event_loop().time() - start_time
                await asyncio.sleep(max(0, 1/self.max_rate - elapsed))
        except asyncio.CancelledError:
            logging.info("Stream processing stopped")
            
    def _process_data(self, data: Any) -> List[Dict]:
        """Normalize and validate tick data structure"""
        # Basic validation
        if not isinstance(data, list):
            data = [data]
            
        # Update cache and normalize structure
        normalized = []
        for tick in data:
            if not all(k in tick for k in ['ticker', 'timestamp', 'price']):
                logging.warning(f"Invalid tick structure: {tick}")
                continue
                
            # Update cache
            self.market_data_cache[tick['ticker']] = tick
            
            # Normalized structure
            normalized.append({
                'ticker': tick['ticker'],
                'timestamp': tick['timestamp'],
                'price': float(tick['price'])
            })
            
        return normalized
        
    async def _notify_subscribers(self, data: Any):
        """Notify all subscribers with processed data"""
        for callback in self.subscribers:
            try:
                await callback(data)
            except Exception as e:
                logging.error(f"Subscriber error: {e}")