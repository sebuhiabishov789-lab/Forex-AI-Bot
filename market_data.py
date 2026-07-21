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
            logger.warning(
                f"No data received for {symbol}"
            )
            return None


        # yfinance yeni versiyada MultiIndex qaytara bil?r
        if hasattr(data.columns, "levels"):

            data.columns = data.columns.get_level_values(0)


        data.rename(
            columns={
                "Close": "close",
                "High": "High",
                "Low": "Low"
            },
            inplace=True
        )


        logger.info(
            f"Market data received for {symbol}"
        )


        return data


    except Exception as e:

        logger.error(
            f"Market data error: {e}"
        )

        return None
