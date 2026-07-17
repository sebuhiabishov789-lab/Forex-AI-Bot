import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
from urllib.parse import quote
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

# GitHub Secrets-dən məlumatları alır
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')


def send_telegram(message):
    if TOKEN and CHAT_ID:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage?chat_id={CHAT_ID}&text={quote(message)}"
        try:
            requests.get(url, timeout=10)
        except requests.RequestException as e:
            print(f"Telegram xətası: {e}")
    else:
        print("TOKEN/CHAT_ID tapılmadı, mesaj göndərilmədi.")


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
    agg = {
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
    }
    resampled = data.resample(rule).agg(agg).dropna()
    return resampled


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


def run_bot():
    # --- Məlumatların yüklənməsi ---
    data = yf.download('EURUSD=X', period='60d', interval='15m', auto_adjust=True)

    if data is None or data.empty or len(data) < 200:
        print("Kifayət qədər data yoxdur, bot dayandırılır.")
        return

    if data.index.tz is not None:
        data.index = data.index.tz_localize(None)

    # yfinance bəzən MultiIndex sütun qaytarır — sadələşdiririk
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    # --- Feature-lar ---
    data['Return'] = data['Close'].pct_change()
    data['Range'] = (data['High'] - data['Low']) / data['Close']
    data['RSI'] = compute_rsi(data['Close'])
    data['MACD_hist'] = compute_macd(data['Close'])
    data['EMA_fast'] = data['Close'].ewm(span=20, adjust=False).mean()
    data['EMA_slow'] = data['Close'].ewm(span=50, adjust=False).mean()
    data['Trend_up'] = (data['EMA_fast'] > data['EMA_slow']).astype(int)

    atr_series = compute_atr(data)
    data['ATR'] = atr_series

    # --- Hədəf: 4 mum (≈1 saat) sonrakı istiqamət ---
    horizon = 4
    data['Future_return'] = data['Close'].shift(-horizon) / data['Close'] - 1
    data['Target'] = (data['Future_return'] > 0).astype(int)

    data.dropna(inplace=True)

    if len(data) < 100:
        print("Feature hesablamadan sonra kifayət qədər data qalmadı.")
        return

    features = ['Return', 'Range', 'RSI', 'MACD_hist', 'Trend_up']

    # Son sətir canlı proqnoz üçün ayrılır, qalanı train/test üçün istifadə olunur
    live_row = data[features].iloc[[-1]]
    hist = data.iloc[:-1]

    X_train, X_test, y_train, y_test = train_test_split(
        hist[features], hist['Target'], test_size=0.2, shuffle=False
    )

    model = RandomForestClassifier(n_estimators=200, max_depth=5, random_state=42)
    model.fit(X_train, y_train)

    test_acc = accuracy_score(y_test, model.predict(X_test))
    print(f"Test dəqiqliyi (son 20% data üzərində): {test_acc:.2%}")

    prob = model.predict_proba(live_row)[0][1]
    current_price = data['Close'].iloc[-1].item()
    current_atr = data['ATR'].iloc[-1].item()
    trend_up = bool(data['Trend_up'].iloc[-1])

    # --- Trend filtri ilə siqnal qərarı ---
    # Yalnız modelin trendlə üst-üstə düşən proqnozlarına etibar edilir.
    # Həm də model real test dəqiqliyi ən azı 52%-dən yüksək olmalıdır,
    # əks halda model hazırkı bazar şəraitində etibarsız sayılır və siqnal göndərilmir.
    MIN_TEST_ACC = 0.52
    BUY_THRESHOLD = 0.62
    SELL_THRESHOLD = 0.38

    if test_acc < MIN_TEST_ACC:
        print(f"Model dəqiqliyi kifayət qədər deyil ({test_acc:.2%}), siqnal göndərilmir.")
        return

    # --- Çoxlu zaman dilimi trend hesabatı ---
    mtf_trends = get_multi_timeframe_trends(data)
    trends_block = format_trends_block(mtf_trends)

    signal_sent = False

    if prob > BUY_THRESHOLD and trend_up:
        sl = current_price - 1.5 * current_atr
        tp = current_price + 3.0 * current_atr
        msg = (
            f"🚀 SİQNAL: ALIŞ (BUY)\n"
            f"Qiymət: {round(current_price, 5)}\n"
            f"SL: {round(sl, 5)}\n"
            f"TP: {round(tp, 5)}\n"
            f"Ehtimal: {prob:.0%} | Model dəqiqliyi: {test_acc:.0%}\n\n"
            f"{trends_block}"
        )
        send_telegram(msg)
        signal_sent = True

    elif prob < SELL_THRESHOLD and not trend_up:
        sl = current_price + 1.5 * current_atr
        tp = current_price - 3.0 * current_atr
        msg = (
            f"📉 SİQNAL: SATIŞ (SELL)\n"
            f"Qiymət: {round(current_price, 5)}\n"
            f"SL: {round(sl, 5)}\n"
            f"TP: {round(tp, 5)}\n"
            f"Ehtimal: {1 - prob:.0%} | Model dəqiqliyi: {test_acc:.0%}\n\n"
            f"{trends_block}"
        )
        send_telegram(msg)
        signal_sent = True

    if not signal_sent:
        print(
            f"Siqnal göndərilmədi. prob={prob:.2f}, trend_up={trend_up}, "
            f"test_acc={test_acc:.2%}"
        )


if __name__ == "__main__":
    run_bot()
