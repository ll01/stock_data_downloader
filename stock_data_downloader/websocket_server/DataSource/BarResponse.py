from stock_data_downloader.models import TickerData


from dataclasses import dataclass
from typing import List, Optional


@dataclass
class BarResponse:
    data: List[TickerData]
    error_message: Optional[str] = None