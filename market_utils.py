"""
market_utils.py — bot.py və status_check.py tərəfindən paylaşılan ortaq funksiyalar.
Data yükləmə, indiqator hesablamaları, model öyrətmə və çoxlu zaman dilimi
trend hesabatı burada cəmlənib ki, kod təkrarlanmasın.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

FEATURES = ['Return', 'Range', 'RSI', 'MACD_hist', 'Trend_up']


def compute_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def compute_macd(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line - signal_line  # histogram


def compute_atr(data, period=14):
    high_low = data['High'] - data['Low']
    high_cp = (data['High'] - data['Close'].shift()).abs()
    low_cp = (data['Low'] - data['Close'].shift()).abs()
    tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def resample_ohlc(data, rule):
    agg = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'}
    return data.resample(rule).agg(agg).dropna()


def get_trend_label(data, rule, ema_fast=20, ema_slow=50, min_bars=55):
    """Verilən timeframe-ə resample edir və EMA20/EMA50 əsasında trend istiqamətini qaytarır."""
    tf_data = resample_ohlc(data, rule)
    if len(tf_data) < min_bars:
        return "Data kifayət deyil"
    ema_f = tf_data['Close'].ewm(span=ema_fast, adjust=False).mean()
    ema_s = tf_data['Close'].ewm(span=ema_slow, adjust=False).mean()
    is_up = ema_f.iloc[-1] > ema_s.iloc[-1]
    return "🟢 Yuxarı" if is_up else "🔴 Aşağı"


def get_multi_timeframe_trends(data):
    """15dəq, 30dəq, 1saat, 4saat, 1gün üçün trend istiqamətlərini qaytarır."""
    timeframes = {
        "15 dəq": "15min",
        "30 dəq": "30min",
        "1 saat": "1h",
        "4 saat": "4h",
        "1 gün": "1D",
    }
    trends = {}
    for label, rule in timeframes.items():
        try:
            trends[label] = get_trend_label(data, rule)
        except Exception as e:
            trends[label] = "N/A"
            print(f"{label} trend hesablamasında xəta: {e}")
    return trends


def format_trends_block(trends):
    lines = ["📊 Trend istiqaməti (çoxlu zaman dilimi):"]
    for label, value in trends.items():
        lines.append(f"  {label}: {value}")
    return "\n".join(lines)


def load_raw_data():
    """EUR/USD 15 dəqiqəlik datanı yfinance-dən yükləyir və təmizləyir."""
    data = yf.download('EURUSD=X', period='60d', interval='15m', auto_adjust=True)

    if data is None or data.empty or len(data) < 200:
        return None

    if data.index.tz is not None:
        data.index = data.index.tz_localize(None)

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    return data


def build_features(data):
    """Feature-ları hesablayır və Target sütununu əlavə edir (öyrətmə üçün)."""
    data = data.copy()
    data['Return'] = data['Close'].pct_change()
    data['Range'] = (data['High'] - data['Low']) / data['Close']
    data['RSI'] = compute_rsi(data['Close'])
    data['MACD_hist'] = compute_macd(data['Close'])
    data['EMA_fast'] = data['Close'].ewm(span=20, adjust=False).mean()
    data['EMA_slow'] = data['Close'].ewm(span=50, adjust=False).mean()
    data['Trend_up'] = (data['EMA_fast'] > data['EMA_slow']).astype(int)
    data['ATR'] = compute_atr(data)

    horizon = 4  # ≈1 saat irəli (4 x 15dəq)
    data['Future_return'] = data['Close'].shift(-horizon) / data['Close'] - 1
    data['Target'] = (data['Future_return'] > 0).astype(int)

    data.dropna(inplace=True)
    return data


def get_current_status():
    """
    Tam status hesablamasını edir: data yükləmə, feature-lar, model öyrətmə,
    canlı proqnoz və çoxlu zaman dilimi trendləri.

    Qaytarır: dict və ya None (data kifayət deyilsə).
    """
    raw = load_raw_data()
    if raw is None:
        return None

    data = build_features(raw)
    if len(data) < 100:
        return None

    live_row = data[FEATURES].iloc[[-1]]
    hist = data.iloc[:-1]

    X_train, X_test, y_train, y_test = train_test_split(
        hist[FEATURES], hist['Target'], test_size=0.2, shuffle=False
    )

    model = RandomForestClassifier(n_estimators=200, max_depth=5, random_state=42)
    model.fit(X_train, y_train)

    test_acc = accuracy_score(y_test, model.predict(X_test))
    prob = model.predict_proba(live_row)[0][1]

    current_price = data['Close'].iloc[-1].item()
    current_atr = data['ATR'].iloc[-1].item()
    trend_up = bool(data['Trend_up'].iloc[-1])

    mtf_trends = get_multi_timeframe_trends(data)

    return {
        'data': data,
        'prob': prob,
        'test_acc': test_acc,
        'current_price': current_price,
        'current_atr': current_atr,
        'trend_up': trend_up,
        'mtf_trends': mtf_trends,
    }
