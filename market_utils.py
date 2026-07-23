"""
market_utils.py — bot.py və status_check.py tərəfindən paylaşılan ortaq funksiyalar.
Data yükləmə, indiqator hesablamaları, kalibrasiya olunmuş ensemble model
(RandomForest + GradientBoosting), çoxlu zaman dilimi trend hesabatı, trend
xətti (trendline), support/resistance, sadə həndəsi fiqur tanıma,
yeni əlavələr: ADX, Bollinger Bant genişliyi, sessiya, xəbər qadağası,
ATR nisbəti, hiperparametr tuning (RandomizedSearchCV, gündə bir dəfə),
və təkmilləşmiş target tərifi.

"""

import yfinance as yf
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timezone, timedelta
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import RandomizedSearchCV, TimeSeriesSplit

# Yeni iqtisadi təqvim funksiyasını import edirik
import economic_calendar

# Parametrlər
FEATURES = [
    'Return', 'Range', 'RSI', 'MACD_hist', 'Trend_up',
    'Trend_slope', 'Dist_to_trendline', 'Body_ratio',
    'ADX', 'BB_width', 'Session', 'News_blackout', 'ATR_ratio'
]

TUNED_PARAMS_FILE = "tuned_params.json"
TUNE_EVERY_HOURS = 24  # hər 24 saatdan bir yenidən tuning ediləcək


# ---------------------------------------------------------------------------
# Klassik indiqatorlar (yeniləri ilə birlikdə)
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


def compute_adx(data, period=14):
    """Average Directional Index — trend gücünü ölçür."""
    high = data['High']
    low = data['Low']
    close = data['Close']
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=data.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=data.index)
    atr = compute_atr(data, period)
    plus_di = 100 * (plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    return adx.fillna(20)


def compute_bollinger_bands(close, period=20, nbdev=2):
    """Bollinger Bant genişliyi (volatillik ölçüsü)."""
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + nbdev * std
    lower = sma - nbdev * std
    bb_width = (upper - lower) / sma  # nisbi genişlik
    return bb_width.fillna(0)


def resample_ohlc(data, rule):
    agg = {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last'}
    return data.resample(rule).agg(agg).dropna()


def get_trend_label(data, rule, ema_fast=20, ema_slow=50, min_bars=55):
    tf_data = resample_ohlc(data, rule)
    if len(tf_data) < min_bars:
        return "Data kifayət deyil"
    ema_f = tf_data['Close'].ewm(span=ema_fast, adjust=False).mean()
    ema_s = tf_data['Close'].ewm(span=ema_slow, adjust=False).mean()
    is_up = ema_f.iloc[-1] > ema_s.iloc[-1]
    return "🟢 Yuxarı" if is_up else "🔴 Aşağı"


def get_multi_timeframe_trends(data):
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
    target = "🟢 Yuxarı" if direction_up else "🔴 Aşağı"
    return sum(1 for v in trends.values() if v == target)


# ---------------------------------------------------------------------------
# Texniki analiz: pivot nöqtələr, trend xətti, support/resistance, fiqurlar
# ---------------------------------------------------------------------------

def find_pivots(data, window=5):
    highs = data['High']
    lows = data['Low']
    pivot_high = (highs == highs.rolling(window * 2 + 1, center=True).max())
    pivot_low = (lows == lows.rolling(window * 2 + 1, center=True).min())
    return pivot_high.fillna(False), pivot_low.fillna(False)


def compute_trendline(data, pivot_mask, lookback=50):
    recent = data.iloc[-lookback:]
    mask = pivot_mask.iloc[-lookback:]
    pts = recent.loc[mask, 'Close']
    if len(pts) < 2:
        return 0.0, None
    x = np.arange(len(pts))
    y = pts.values
    slope, intercept = np.polyfit(x, y, 1)
    line_value_now = slope * (len(recent) - 1) + intercept
    return float(slope), float(line_value_now)


def detect_support_resistance(data, window=20):
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
# Data yükləmə (daha çox data cəhdi)
# ---------------------------------------------------------------------------

def load_raw_data():
    """EUR/USD 15 dəqiqəlik datanı yfinance-dən yükləyir. Daha çox data almağa çalışır."""
    for period_days in [90, 60, 45]:  # Ən çox 90 gün, yoxsa 60, 45
        try:
            data = yf.download('EURUSD=X', period=f'{period_days}d', interval='15m', auto_adjust=True)
            if data is not None and not data.empty and len(data) >= 200:
                if data.index.tz is not None:
                    data.index = data.index.tz_localize(None)
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = data.columns.get_level_values(0)
                print(f"{period_days} günlük data yükləndi: {len(data)} bar")
                return data
        except Exception as e:
            print(f"{period_days} gün data yükləmə alınmadı: {e}")
            continue
    return None


# ---------------------------------------------------------------------------
# Sessiya təyini
# ---------------------------------------------------------------------------

def get_market_session_utc(utc_hour):
    """UTC saatına görə əsas bazar sessiyasını rəqəmsəlləşdirir."""
    if 7 <= utc_hour < 16:
        return 1  # London
    elif 13 <= utc_hour < 21:
        return 2  # Nyu-York (Londonla kəsişmə ola bilər, amma biz əsasən London>NY üstünlüyü veririk)
    elif 0 <= utc_hour < 9:
        return 0  # Asiya
    else:
        return 3  # Qarışıq/digər


# ---------------------------------------------------------------------------
# Feature mühəndisliyi (təkmilləşmiş)
# ---------------------------------------------------------------------------

def build_features(data):
    data = data.copy()
    data['Return'] = data['Close'].pct_change()
    data['Range'] = (data['High'] - data['Low']) / data['Close']
    data['RSI'] = compute_rsi(data['Close'])
    data['MACD_hist'] = compute_macd(data['Close'])
    data['EMA_fast'] = data['Close'].ewm(span=20, adjust=False).mean()
    data['EMA_slow'] = data['Close'].ewm(span=50, adjust=False).mean()
    data['Trend_up'] = (data['EMA_fast'] > data['EMA_slow']).astype(int)
    data['ATR'] = compute_atr(data)

    # Şam gövdəsinin nisbəti
    candle_range = (data['High'] - data['Low']).replace(0, np.nan)
    data['Body_ratio'] = ((data['Close'] - data['Open']).abs() / candle_range).fillna(0)

    # Trend xətti əsaslı feature-lar
    ph, _pl = find_pivots(data, window=5)
    slope, trendline_val = compute_trendline(data, ph, lookback=50)
    data['Trend_slope'] = slope
    data['Dist_to_trendline'] = (
        (data['Close'] - trendline_val) / data['Close'] if trendline_val else 0.0
    )

    # --- Yeni əlavə olunan feature-lar ---
    # ADX (trend gücü)
    data['ADX'] = compute_adx(data)

    # Bollinger Bant genişliyi (volatillik)
    data['BB_width'] = compute_bollinger_bands(data['Close'])

    # Sessiya (0-3 arası rəqəm)
    data['Session'] = data.index.map(lambda ts: get_market_session_utc(ts.hour))

    # ATR nisbəti: cari ATR / son 50 bar ATR medianı
    atr_median = data['ATR'].rolling(50).median()
    data['ATR_ratio'] = data['ATR'] / atr_median.replace(0, np.nan)

    # Xəbər qadağası: cari bar zamanı blackout pəncərəsindədir?
    # Hər sətir üçün hesablayırıq (bir az ağır ola bilər, lakin sadədir).
    # Qeyd: economic_calendar.check_news_blackout() cari UTC vaxtına baxır.
    # Biz isə tarixi sətirlər üçün onu işlədə bilmərik. Bunun əvəzinə
    # "yaxın vaxtda yüksək təsirli xəbər var?" məlumatını sadə şəkildə verəcəyik:
    # son 1 saat ərzində yüksək xəbər oldu/qarşıdakı 1 saatda olacaq?
    # Sadəlik üçün bu feature-u hər sətirdə 0 qoyub, yalnız canlı sətirdə
    # dinamik dolduracağıq. Canlı proqnozda istifadə edəcəyik, tarixi
    # öyrənmədə 0 olaraq qalacaq (çünki tarixi xəbər datasına ehtiyac var).
    data['News_blackout'] = 0

    # Target: 1 saat sonra (4 bar) ən azı 0.5 pip (0.00005) qazanc
    horizon = 4
    data['Future_return'] = data['Close'].shift(-horizon) / data['Close'] - 1
    data['Target'] = (data['Future_return'] > 0.00005).astype(int)

    data.dropna(inplace=True)
    return data


# ---------------------------------------------------------------------------
# Kalibrasiya olunmuş ensemble model (təkmilləşmiş)
# ---------------------------------------------------------------------------

def build_rf(params=None):
    default = {
        'n_estimators': 250,
        'max_depth': 6,
        'min_samples_leaf': 10,
        'class_weight': 'balanced',
        'random_state': 42,
    }
    if params:
        default.update(params)
    return RandomForestClassifier(**default)


def build_gb(params=None):
    default = {
        'n_estimators': 150,
        'max_depth': 3,
        'learning_rate': 0.05,
        'random_state': 42,
    }
    if params:
        default.update(params)
    return GradientBoostingClassifier(**default)


def fit_platt_calibrator(raw_probs, y_true):
    lr = LogisticRegression()
    lr.fit(raw_probs.reshape(-1, 1), y_true)
    return lr


def apply_calibrator(calibrator, raw_prob):
    return float(calibrator.predict_proba(np.array([[raw_prob]]))[0][1])


def train_calibrated_ensemble(hist):
    n = len(hist)
    train_end = int(n * 0.70)
    calib_end = int(n * 0.85)
    train = hist.iloc[:train_end]
    calib = hist.iloc[train_end:calib_end]
    test = hist.iloc[calib_end:]

    # Hiperparametrləri yüklə (əgər tuning edilibsə)
    tuned_rf, tuned_gb = load_tuned_params()

    rf = build_rf(tuned_rf)
    gb = build_gb(tuned_gb)
    rf.fit(train[FEATURES], train['Target'])
    gb.fit(train[FEATURES], train['Target'])

    raw_rf_calib = rf.predict_proba(calib[FEATURES])[:, 1]
    raw_gb_calib = gb.predict_proba(calib[FEATURES])[:, 1]
    calibrator_rf = fit_platt_calibrator(raw_rf_calib, calib['Target'].values)
    calibrator_gb = fit_platt_calibrator(raw_gb_calib, calib['Target'].values)

    # Test dəqiqliyi
    raw_rf_test = rf.predict_proba(test[FEATURES])[:, 1]
    raw_gb_test = gb.predict_proba(test[FEATURES])[:, 1]
    cal_rf_test = calibrator_rf.predict_proba(raw_rf_test.reshape(-1, 1))[:, 1]
    cal_gb_test = calibrator_gb.predict_proba(raw_gb_test.reshape(-1, 1))[:, 1]
    ensemble_test = (cal_rf_test + cal_gb_test) / 2
    preds = (ensemble_test > 0.5).astype(int)
    test_acc = float(accuracy_score(test['Target'], preds))

    return {
        'rf': rf,
        'gb': gb,
        'calibrator_rf': calibrator_rf,
        'calibrator_gb': calibrator_gb,
        'test_acc': test_acc,
    }


def predict_ensemble(models, live_row):
    raw_rf = models['rf'].predict_proba(live_row)[0][1]
    raw_gb = models['gb'].predict_proba(live_row)[0][1]
    cal_rf = apply_calibrator(models['calibrator_rf'], raw_rf)
    cal_gb = apply_calibrator(models['calibrator_gb'], raw_gb)
    ensemble_prob = (cal_rf + cal_gb) / 2
    same_direction = (cal_rf > 0.5) == (cal_gb > 0.5)
    agreement = 1.0 if same_direction else 0.0
    return {
        'prob': ensemble_prob,
        'rf_prob': cal_rf,
        'gb_prob': cal_gb,
        'model_agreement': agreement,
    }


# ---------------------------------------------------------------------------
# Hiperparametr tuning (gündə bir dəfə)
# ---------------------------------------------------------------------------

def load_tuned_params():
    """Əgər son 24 saatda tuning edilmiş parametrlər varsa, onları qaytarır."""
    if not os.path.isfile(TUNED_PARAMS_FILE):
        return {}, {}
    try:
        with open(TUNED_PARAMS_FILE, 'r') as f:
            data = json.load(f)
        timestamp = datetime.fromisoformat(data.get('timestamp', '2000-01-01T00:00:00'))
        if datetime.now(timezone.utc) - timestamp < timedelta(hours=TUNE_EVERY_HOURS):
            return data.get('rf_params', {}), data.get('gb_params', {})
    except (json.JSONDecodeError, OSError):
        pass
    return {}, {}


def save_tuned_params(rf_params, gb_params):
    with open(TUNED_PARAMS_FILE, 'w') as f:
        json.dump({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'rf_params': rf_params,
            'gb_params': gb_params
        }, f)


def tune_hyperparams(data):
    """Son 20% data üzərində RandomizedSearchCV ilə hiperparametr axtarışı."""
    # Data çox böyükdürsə, son 2000 bar ilə məhdudlaşdıraq
    n = len(data)
    start = max(0, n - 2000)
    tune_data = data.iloc[start:]
    X = tune_data[FEATURES]
    y = tune_data['Target']

    tscv = TimeSeriesSplit(n_splits=3)
    # RF param grid
    rf_grid = {
        'n_estimators': [150, 250, 350],
        'max_depth': [4, 6, 8],
        'min_samples_leaf': [5, 10, 20],
    }
    gb_grid = {
        'n_estimators': [100, 150, 200],
        'max_depth': [3, 4, 5],
        'learning_rate': [0.03, 0.05, 0.1],
    }

    rf = RandomForestClassifier(class_weight='balanced', random_state=42)
    gb = GradientBoostingClassifier(random_state=42)

    rf_search = RandomizedSearchCV(rf, rf_grid, n_iter=10, cv=tscv, scoring='accuracy', random_state=42, n_jobs=-1)
    gb_search = RandomizedSearchCV(gb, gb_grid, n_iter=10, cv=tscv, scoring='accuracy', random_state=42, n_jobs=-1)

    print("Hiperparametr axtarışı başladı...")
    try:
        rf_search.fit(X, y)
        gb_search.fit(X, y)
        best_rf = rf_search.best_params_
        best_gb = gb_search.best_params_
        print(f"RF ən yaxşı: {best_rf}, dəqiqlik: {rf_search.best_score_:.4f}")
        print(f"GB ən yaxşı: {best_gb}, dəqiqlik: {gb_search.best_score_:.4f}")
        save_tuned_params(best_rf, best_gb)
    except Exception as e:
        print(f"Tuning xətası: {e}")


# ---------------------------------------------------------------------------
# Canlı status
# ---------------------------------------------------------------------------

def get_current_status():
    raw = load_raw_data()
    if raw is None:
        return None

    data = build_features(raw)
    if len(data) < 200:
        return None

    # Canlı sətirdə xəbər qadağası feature-unu düzəlt
    is_blackout, _, _ = economic_calendar.check_news_blackout()
    data.loc[data.index[-1], 'News_blackout'] = 1 if is_blackout else 0

    live_row = data[FEATURES].iloc[[-1]]
    hist = data.iloc[:-1]  # canlıdan əvvəlki bütün sətirlər

    # Hiperparametr tuning — lazım olduqda
    _, _ = load_tuned_params()  # Əgər parametrlər yoxdursa/köhnədirsə, tuning et
    # Yoxlayırıq: yalnız fayl yoxdursa və ya köhnədirsə tuning işə düşsün
    if not os.path.isfile(TUNED_PARAMS_FILE):
        tune_hyperparams(hist)
    else:
        # Fayl varsa, tarixçəni yoxla
        try:
            with open(TUNED_PARAMS_FILE, 'r') as f:
                ts_str = json.load(f).get('timestamp', '')
            if ts_str:
                last_tune = datetime.fromisoformat(ts_str)
                if datetime.now(timezone.utc) - last_tune > timedelta(hours=TUNE_EVERY_HOURS):
                    tune_hyperparams(hist)
        except:
            tune_hyperparams(hist)

    models = train_calibrated_ensemble(hist)
    prediction = predict_ensemble(models, live_row)

    prob = prediction['prob']
    test_acc = models['test_acc']

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
        'rf_prob': prediction['rf_prob'],
        'gb_prob': prediction['gb_prob'],
        'model_agreement': prediction['model_agreement'],
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
