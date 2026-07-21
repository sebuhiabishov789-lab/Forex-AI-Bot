from risk_manager import calculate_trade_levels
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


    price = float(data["close"].iloc[-1])

    rsi = float(
        calculate_rsi(data).iloc[-1]
    )

    ema = float(
        calculate_ema(data).iloc[-1]
    )


    macd_data = calculate_macd(data)

    macd = float(
        macd_data["macd"].iloc[-1]
    )

    signal_line = float(
        macd_data["signal"].iloc[-1]
    )


    bollinger = calculate_bollinger(data)

    upper = float(
        bollinger["upper"].iloc[-1]
    )

    lower = float(
        bollinger["lower"].iloc[-1]
    )


    ai_result = generate_signal(
        rsi,
        ema,
        price,
        macd,
        signal_line,
        upper,
        lower
    )


    decision = ai_result["decision"]

    confidence = ai_result["confidence"]


    trade = calculate_trade_levels(
        price,
        decision
    )


    print("----------------------")
    print(f"Symbol: {symbol}")
    print(f"Price: {price:.5f}")
    print(f"RSI: {rsi:.2f}")
    print(f"EMA: {ema:.5f}")
    print(f"MACD: {macd:.5f}")
    print(f"Signal: {signal_line:.5f}")
    print(f"AI Decision: {decision}")
    print(f"Confidence: {confidence}%")

    print("")
    print("Reasons:")

    for reason in ai_result["reasons"]:
        print("-", reason)


    if trade:
        print("")
        print("TRADE PLAN")
        print(f"Entry: {trade['entry']:.5f}")
        print(f"Stop Loss: {trade['stop_loss']}")
        print(f"Take Profit: {trade['take_profit']}")
        print(f"Risk Reward: {trade['risk_reward']}")


    print("----------------------")


if __name__ == "__main__":
    run_bot()
