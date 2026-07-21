import yfinance as yf
import pandas as pd
from logger import logger


def get_market_data(symbol, period="1mo", interval="1h"):
    try:
        data = yf.download(
            symbol,
            period=period,
            interval=interval
        )

        if data.empty:
            logger.warning(f"No data received for {symbol}")
            return None

        if "Close" in data.columns:
            data.rename(
                columns={"Close": "close"},
                inplace=True
            )

        logger.info(f"Market data received for {symbol}")
        return data

    except Exception as e:
        logger.error(f"Market data error: {e}")
        return None
