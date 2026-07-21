import pandas as pd
import ta


def calculate_rsi(data, period=14):
    rsi_indicator = ta.momentum.RSIIndicator(
        close=data["close"],
        window=period
    )

    return rsi_indicator.rsi()

def calculate_ema(data, period=50):
    ema_indicator = ta.trend.EMAIndicator(
        close=data["close"],
        window=period
    )

    return ema_indicator.ema_indicator()

def calculate_macd(data):
    macd_indicator = ta.trend.MACD(
        close=data["close"]
    )

    return {
        "macd": macd_indicator.macd(),
        "signal": macd_indicator.macd_signal(),
        "histogram": macd_indicator.macd_diff()
    }

def calculate_bollinger(data, period=20):
    bollinger = ta.volatility.BollingerBands(
        close=data["close"],
        window=period
    )

    return {
        "upper": bollinger.bollinger_hband(),
        "middle": bollinger.bollinger_mavg(),
        "lower": bollinger.bollinger_lband()
    }
