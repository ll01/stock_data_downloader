import logging
import os
import zipfile
from typing import List, Union

import pandas as pd

logger = logging.getLogger(__name__)

def save_data_to_csv(price_data: pd.DataFrame, csv_file: str):
    """Combine all data into a single DataFrame and save it to a CSV file."""
    price_data.to_csv(csv_file, index=True, encoding="utf-8")
    logger.info(f"Data saved to {csv_file}")


def zip_csv_file(csv_files: List[str], zip_file: str):
    """Zip the CSV file."""
    with zipfile.ZipFile(zip_file, "a", compression=zipfile.ZIP_DEFLATED) as zipf:
        for csv_file in csv_files:
            zipf.write(csv_file, os.path.basename(csv_file))
    logger.info(f"CSV {len(csv_files)} files zipped to {zip_file}💾")


def cleanup_csv_files(csv_files: Union[List[str], str]):
    """Remove the CSV file after zipping."""
    if isinstance(csv_files, str):
        csv_files = [csv_files]
    for csv_file in csv_files:
        if os.path.exists(csv_file):
            os.remove(csv_file)
            logger.info(f"Removed {csv_file}")