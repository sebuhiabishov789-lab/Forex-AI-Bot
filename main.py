from risk_manager import calculate_trade_levels

from market_data import get_market_data

from indicators import (
    calculate_rsi,
    calculate_ema,
    calculate_macd,
    calculate_bollinger,
    calculate_adx
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


    adx = calculate_adx(data).iloc[-1]


    ai_result = generate_signal(
        rsi,
        ema,
        price,
        macd,
        signal,
        upper,
        lower,
        adx
    )


    decision = ai_result["decision"]


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
    print(f"Signal: {signal:.5f}")
    print(f"ADX: {adx:.2f}")

    print("----------------------")

    print(f"AI Decision: {decision}")
    print(f"Confidence: {ai_result['confidence']}%")

    print("\nReasons:")

    for r in ai_result["reasons"]:
        print("-", r)


    if trade:

        print("\nTRADE PLAN")
        print(f"Entry: {trade['entry']:.5f}")
        print(f"Stop Loss: {trade['stop_loss']}")
        print(f"Take Profit: {trade['take_profit']}")
        print(f"Risk Reward: {trade['risk_reward']}")


    print("----------------------")



if __name__ == "__main__":
    run_bot()