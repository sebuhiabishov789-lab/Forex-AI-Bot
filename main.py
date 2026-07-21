from market_data import get_market_data
from indicators import (
    calculate_rsi,
    calculate_ema,
    calculate_macd,
    calculate_bollinger
)
from ai_model import generate_signal
from logger import logger


def run_bot():

    symbol = "EURUSD=X"


    data = get_market_data(
        symbol,
        period="1mo",
        interval="1h"
    )


    if data is None:
        logger.error("No market data")
        return


    price = data["close"].iloc[-1]


    rsi = calculate_rsi(data).iloc[-1]

    ema = calculate_ema(data).iloc[-1]


    macd_data = calculate_macd(data)

    macd = macd_data["macd"].iloc[-1]

    signal = macd_data["signal"].iloc[-1]


    bollinger = calculate_bollinger(data)

    upper = bollinger["upper"].iloc[-1]

    lower = bollinger["lower"].iloc[-1]


    decision = generate_signal(
        rsi,
        ema,
        price,
        macd,
        signal,
        upper,
        lower
    )


    print("----------------------")
    print(f"Symbol: {symbol}")
    print(f"Price: {price:.5f}")
    print(f"RSI: {rsi:.2f}")
    print(f"EMA: {ema:.5f}")
    print(f"MACD: {macd:.5f}")
    print(f"Signal: {signal:.5f}")
    print(f"AI Decision: {decision}")
    print("----------------------")


if __name__ == "__main__":
    run_bot()
