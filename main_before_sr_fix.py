from risk_manager import calculate_trade_levels

from market_data import get_market_data

from indicators import (
    calculate_rsi,
    calculate_ema,
    calculate_ema200,
    calculate_macd,
    calculate_bollinger,
    calculate_adx,
    calculate_atr,
    calculate_support_resistance
)

from ai_model import generate_signal

from logger import logger
from messages import create_message
from notifications import send_telegram



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



    price = float(data["close"].iloc[-1])


    rsi = float(calculate_rsi(data).iloc[-1])

    ema = float(calculate_ema(data).iloc[-1])

    ema200 = float(calculate_ema200(data).iloc[-1])


    macd_data = calculate_macd(data)

    macd = float(macd_data["macd"].iloc[-1])

    signal = float(macd_data["signal"].iloc[-1])


    bollinger = calculate_bollinger(data)

    upper = float(bollinger["upper"].iloc[-1])

    lower = float(bollinger["lower"].iloc[-1])


    adx = float(calculate_adx(data).iloc[-1])


    atr = float(calculate_atr,
    calculate_support_resistance(data).iloc[-1])


    ai_result = generate_signal(
        rsi,
        ema,
        ema200,
        price,
        macd,
        signal,
        upper,
        lower,
        adx
    )

    decision = ai_result["decision"]

    confidence = ai_result["confidence"]

    # Confidence filter
    if confidence < 40:
        decision = "HOLD"



        trade = calculate_trade_levels(
            price,
            decision,
            atr
        )
    else:
        trade = None


    print("----------------------")
    print(f"Symbol: {symbol}")
    print(f"Price: {price:.5f}")
    print(f"RSI: {rsi:.2f}")
    print(f"EMA: {ema:.5f}")
    print(f"EMA200: {ema200:.5f}")
    print(f"MACD: {macd:.5f}")
    print(f"Signal: {signal:.5f}")
    print(f"ADX: {adx:.2f}")
    print(f"ATR: {atr:.5f}")

    print("----------------------")

    message = create_message(
        symbol,
        price,
        decision,
        ai_result["confidence"],
        ai_result["reasons"],
        trade
    )

    print(message)

    if decision in ["BUY", "SELL"]:
        send_telegram(message)












    print("----------------------")



if __name__ == "__main__":
    run_bot()

