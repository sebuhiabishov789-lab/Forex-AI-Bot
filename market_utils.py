"""
market_utils.py — bot.py və status_check.py tərəfindən paylaşılan ortaq funksiyalar.
Data yükləmə, indiqator hesablamaları, model öyrətmə, çoxlu zaman dilimi
trend hesabatı, trend xətti (trendline), support/resistance və sadə
həndəsi fiqur tanıma (double top/bottom, triangle) burada cəmlənib ki,
kod təkrarlanmasın.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit, cross_val_score

FEATURES = [
    'Return', 'Range', 'RSI', 'MACD_hist', 'Trend_up',
    'Trend_slope', 'Dist_to_trendline', 'Body_ratio',
]


# ---------------------------------------------------------------------------
# Klassik indiqatorlar
# ---------------------------------------------------------------------------

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


def count_aligned_timeframes(trends, direction_up):
    """Neçə zaman diliminin BUY (yuxarı) və ya SELL (aşağı) istiqaməti ilə üst-üstə düşdüyünü sayır."""
    target = "🟢 Yuxarı" if direction_up else "🔴 Aşağı"
    return sum(1 for v in trends.values() if v == target)


# ---------------------------------------------------------------------------
# Texniki analiz: pivot nöqtələr, trend xətti, support/resistance, fiqurlar
# ---------------------------------------------------------------------------

def find_pivots(data, window=5):
    """Local maksimum/minimum (pivot high/low) nöqtələrini tapır."""
    highs = data['High']
    lows = data['Low']
    pivot_high = (highs == highs.rolling(window * 2 + 1, center=True).max())
    pivot_low = (lows == lows.rolling(window * 2 + 1, center=True).min())
    return pivot_high.fillna(False), pivot_low.fillna(False)


def compute_trendline(data, pivot_mask, lookback=50):
    """
    Son `lookback` bar içindəki pivot nöqtələr üzərindən xətti reqressiya
    ilə trend xəttinin meylini (slope) və cari nöqtədəki qiymətini qaytarır.
    """
    recent = data.iloc[-lookback:]
    mask = pivot_mask.iloc[-lookback:]
    pts = recent.loc[mask, 'Close']

    if len(pts) < 2:
        return 0.0, None  # kifayət qədər pivot yoxdur

    x = np.arange(len(pts))
    y = pts.values
    slope, intercept = np.polyfit(x, y, 1)
    line_value_now = slope * (len(recent) - 1) + intercept
    return float(slope), float(line_value_now)


def detect_support_resistance(data, window=20):
    """
    Son barlarda qiymətin ən çox toxunduğu pivot nöqtələri
    support/resistance kimi qaytarır (cari qiymətə ən yaxın olanlar).
    """
    recent = data.iloc[-window * 3:]
    ph, pl = find_pivots(recent, window=3)

    levels = pd.concat([recent.loc[ph, 'High'], recent.loc[pl, 'Low']])
    if levels.empty:
        return None, None

    current_price = data['Close'].iloc[-1]
    below = levels[levels < current_price]
    above = levels[levels > current_price]

    support = float(below.max()) if not below.empty else None
    resistance = float(above.min()) if not above.empty else None
    return support, resistance


def detect_pattern(data, window=5, lookback=60, tolerance=0.002):
    """
    Sadələşdirilmiş fiqur tanıma:
    - Double Top: iki bənzər hündürlük pivotu
    - Double Bottom: iki bənzər aşağı pivot
    - Triangle (converging): pivot high-lar enir, pivot low-lar qalxır
    """
    recent = data.iloc[-lookback:]
    ph, pl = find_pivots(recent, window=window)

    highs = recent.loc[ph, 'High']
    lows = recent.loc[pl, 'Low']

    pattern = "Yoxdur"

    if len(highs) >= 2:
        last_two_highs = highs.iloc[-2:]
        if abs(last_two_highs.iloc[0] - last_two_highs.iloc[1]) / last_two_highs.iloc[0] < tolerance:
            pattern = "Double Top"

    if len(lows) >= 2:
        last_two_lows = lows.iloc[-2:]
        if abs(last_two_lows.iloc[0] - last_two_lows.iloc[1]) / last_two_lows.iloc[0] < tolerance:
            pattern = "Double Bottom" if pattern == "Yoxdur" else pattern + " / Double Bottom"

    if len(highs) >= 2 and len(lows) >= 2:
        high_slope = np.polyfit(np.arange(len(highs)), highs.values, 1)[0]
        low_slope = np.polyfit(np.arange(len(lows)), lows.values, 1)[0]
        if high_slope < 0 and low_slope > 0:
            pattern = "Triangle (converging)"

    return pattern


# ---------------------------------------------------------------------------
# Data yükləmə və feature mühəndisliyi
# ---------------------------------------------------------------------------

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

    # Şam gövdəsinin range-ə nisbəti — güclü/zəif hərəkəti ayırd edir
    candle_range = (data['High'] - data['Low']).replace(0, np.nan)
    data['Body_ratio'] = ((data['Close'] - data['Open']).abs() / candle_range).fillna(0)

    # --- Trend xətti (trendline) əsaslı feature-lar ---
    ph, _pl = find_pivots(data, window=5)
    slope, trendline_val = compute_trendline(data, ph, lookback=50)
    data['Trend_slope'] = slope
    data['Dist_to_trendline'] = (
        (data['Close'] - trendline_val) / data['Close'] if trendline_val else 0.0
    )

    horizon = 4  # ≈1 saat irəli (4 x 15dəq)
    data['Future_return'] = data['Close'].shift(-horizon) / data['Close'] - 1
    data['Target'] = (data['Future_return'] > 0).astype(int)

    data.dropna(inplace=True)
    return data


def build_model():
    """Balanslaşdırılmış, overfitting-ə qarşı tənzimlənmiş RandomForest modeli qurur."""
    return RandomForestClassifier(
        n_estimators=300,
        max_depth=6,
        min_samples_leaf=10,
        class_weight='balanced',
        random_state=42,
    )


def evaluate_model_accuracy(hist):
    """
    TimeSeriesSplit ilə modelin dəqiqliyini bir neçə ardıcıl bölmə üzərində
    qiymətləndirir (tək bir train/test bölməsinə nisbətən daha etibarlı ölçüdür).
    """
    tscv = TimeSeriesSplit(n_splits=5)
    model = build_model()
    scores = cross_val_score(model, hist[FEATURES], hist['Target'], cv=tscv, scoring='accuracy')
    return float(scores.mean())


def get_current_status():
    """
    Tam status hesablamasını edir: data yükləmə, feature-lar, model öyrətmə,
    canlı proqnoz, çoxlu zaman dilimi trendlər, support/resistance və fiqur.

    Qaytarır: dict və ya None (data kifayət deyilsə).
    """
    raw = load_raw_data()
    if raw is None:
        return None

    data = build_features(raw)
    if len(data) < 150:
        return None

    live_row = data[FEATURES].iloc[[-1]]
    hist = data.iloc[:-1]

    # Daha etibarlı dəqiqlik ölçüsü: TimeSeriesSplit üzrə orta dəqiqlik
    test_acc = evaluate_model_accuracy(hist)

    # Canlı proqnoz üçün bütün tarixi data üzərində sonuncu dəfə öyrədilir
    final_model = build_model()
    final_model.fit(hist[FEATURES], hist['Target'])
    prob = final_model.predict_proba(live_row)[0][1]

    current_price = data['Close'].iloc[-1].item()
    current_atr = data['ATR'].iloc[-1].item()
    trend_up = bool(data['Trend_up'].iloc[-1])
    trend_slope = float(data['Trend_slope'].iloc[-1])

    mtf_trends = get_multi_timeframe_trends(data)
    support, resistance = detect_support_resistance(data)
    pattern = detect_pattern(data)
    aligned_tf_up = count_aligned_timeframes(mtf_trends, direction_up=True)
    aligned_tf_down = count_aligned_timeframes(mtf_trends, direction_up=False)

    return {
        'data': data,
        'prob': prob,
        'test_acc': test_acc,
        'current_price': current_price,
        'current_atr': current_atr,
        'trend_up': trend_up,
        'trend_slope': trend_slope,
        'mtf_trends': mtf_trends,
        'aligned_tf_up': aligned_tf_up,
        'aligned_tf_down': aligned_tf_down,
        'support': support,
        'resistance': resistance,
        'pattern': pattern,
    }
