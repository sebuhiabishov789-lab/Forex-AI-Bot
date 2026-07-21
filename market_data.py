import yfinance as yf
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
            close_data = data["Close"]

            if hasattr(close_data, "columns"):
                close_data = close_data.iloc[:, 0]

            data = close_data.to_frame(name="close")

        logger.info(f"Market data received for {symbol}")

        return data

    except Exception as e:
        logger.error(f"Market data error: {e}")
        return None
