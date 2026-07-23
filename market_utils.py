"""
market_utils.py — Ortak fonksiyonlar
Data yükleme, indiqatorlar, ensemble model, MTF trend
Optimallaşdırılmış versiya v2.1
"""
import yfinance as yf
import pandas as pd
import numpy as np
import json
import os
import logging
from datetime import datetime, timezone, timedelta
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import RandomizedSearchCV, TimeSeriesSplit

try:
    import economic_calendar
except ImportError:
    economic_calendar = None

logger = logging.getLogger(__name__)

FEATURES = [
    'Return', 'Range', 'RSI', 'MACD_hist', 'Trend_up',
    'Trend_slope', 'Dist_to_trendline', 'Body_ratio',
    'ADX', 'BB_width', 'Session', 'ATR_ratio'
]

TUNED_PARAMS_FILE = "tuned_params.json"
TUNE_EVERY_HOURS = 24

# --- Indiqatorlar ---
def compute_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)

def compute_macd(close, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    return (ema_fast - ema_slow).ewm(span=signal, adjust=False).mean() - (ema_fast - ema_slow)

def compute_atr(data, period=14):
    hl = data['High'] - data['Low']
    hc = (data['High'] - data['Close'].shift()).abs()
    lc = (data['Low'] - data['Close'].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def compute_adx(data, period=14):
    try:
        high, low = data['High'], data['Low']
        up_move, down_move = high.diff(), -low.diff()
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        atr = compute_atr(data, period).replace(0, np.nan)
        plus_di = 100 * (pd.Series(plus_dm, index=data.index).ewm(alpha=1/period, adjust=False).mean() / atr)
        minus_di = 100 * (pd.Series(minus_dm, index=data.index).ewm(alpha=1/period, adjust=False).mean() / atr)
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan) * 100).fillna(0)
        return dx.ewm(alpha=1/period, adjust=False).mean().fillna(20)
    except Exception as e:
        logger.warning(f"ADX hesablama xətası: {e}")
        return pd.Series(20, index=data.index)

def compute_bollinger_width(close, period=20, nbdev=2):
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    return ((sma + nbdev*std) - (sma - nbdev*std)) / sma.replace(0, np.nan)

# --- Data ---
def load_raw_data():
    for days in [90, 60, 45]:
        try:
            data = yf.download('EURUSD=X', period=f'{days}d', interval='15m', auto_adjust=True, progress=False)
            if data is None or data.empty or len(data) < 200:
                continue
            if data.index.tz is not None:
                data.index = data.index.tz_localize(None)
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            logger.info(f"{days}g data: {len(data)} bar")
            return data
        except Exception as e:
            logger.warning(f"{days}g yukleme xetasi: {e}")
    return None

def get_market_session_vectorized(index):
    hours = index.hour
    conditions = [
        (hours >= 7) & (hours < 16),
        (hours >= 13) & (hours < 21),
        (hours >= 0) & (hours < 9),
    ]
    choices = [1, 2, 0]
    return np.select(conditions, choices, default=3)

# --- Texniki Analiz ---
def find_pivots(data, window=5):
    highs, lows = data['High'], data['Low']
    ph = highs == highs.rolling(window*2+1, center=True).max()
    pl = lows == lows.rolling(window*2+1, center=True).min()
    return ph.fillna(False), pl.fillna(False)

def compute_trendline(data, pivot_mask, lookback=50):
    recent = data.iloc[-lookback:]
    mask = pivot_mask.iloc[-lookback:]
    pts = recent.loc[mask, 'Close']
    if len(pts) < 2:
        return 0.0, None
    x = np.arange(len(pts))
    slope, intercept = np.polyfit(x, pts.values, 1)
    return float(slope), float(slope*(len(recent)-1)+intercept)

def detect_support_resistance(data, window=20):
    recent = data.iloc[-window*3:]
    ph, pl = find_pivots(recent, window=3)
    levels = pd.concat([recent.loc[ph, 'High'], recent.loc[pl, 'Low']]).dropna()
    if levels.empty:
        return None, None
    price = data['Close'].iloc[-1]
    below, above = levels[levels < price], levels[levels > price]
    return (float(below.max()) if not below.empty else None,
            float(above.min()) if not above.empty else None)

def detect_pattern(data, window=5, lookback=60, tolerance=0.002):
    recent = data.iloc[-lookback:]
    ph, pl = find_pivots(recent, window=window)
    highs, lows = recent.loc[ph, 'High'], recent.loc[pl, 'Low']
    pattern = "Yoxdur"
    if len(highs) >= 2 and abs(highs.iloc[-2]-highs.iloc[-1])/highs.iloc[-2] < tolerance:
        pattern = "Double Top"
    if len(lows) >= 2 and abs(lows.iloc[-2]-lows.iloc[-1])/lows.iloc[-2] < tolerance:
        pattern = "Double Bottom" if pattern=="Yoxdur" else pattern+" / Double Bottom"
    return pattern

# --- MTF ---
def resample_ohlc(data, rule):
    return data.resample(rule).agg({'Open':'first','High':'max','Low':'min','Close':'last'}).dropna()

def get_trend_label(data, rule, min_bars=55):
    try:
        tf = resample_ohlc(data, rule)
        if len(tf) < min_bars: return "Data azdır"
        ema_f = tf['Close'].ewm(span=20, adjust=False).mean()
        ema_s = tf['Close'].ewm(span=50, adjust=False).mean()
        return "🟢 Yuxarı" if ema_f.iloc[-1] > ema_s.iloc[-1] else "🔴 Aşağı"
    except: return "N/A"

def get_multi_timeframe_trends(data):
    tfs = {"15 dəq":"15min","30 dəq":"30min","1 saat":"1h","4 saat":"4h","1 gün":"1D"}
    return {k: get_trend_label(data, v) for k, v in tfs.items()}

def count_aligned_timeframes(trends, direction_up):
    target = "🟢 Yuxarı" if direction_up else "🔴 Aşağı"
    return sum(1 for v in trends.values() if v == target)

# --- Features ---
def build_features(data):
    df = data.copy()
    df['Return'] = df['Close'].pct_change()
    df['Range'] = (df['High']-df['Low'])/df['Close']
    df['RSI'] = compute_rsi(df['Close'])
    df['MACD_hist'] = compute_macd(df['Close'])
    df['EMA_fast'] = df['Close'].ewm(span=20, adjust=False).mean()
    df['EMA_slow'] = df['Close'].ewm(span=50, adjust=False).mean()
    df['Trend_up'] = (df['EMA_fast'] > df['EMA_slow']).astype(int)
    df['ATR'] = compute_atr(df)
    df['Body_ratio'] = ((df['Close']-df['Open']).abs() / (df['High']-df['Low']).replace(0, np.nan)).fillna(0)

    ph, _ = find_pivots(df, 5)
    slope, tval = compute_trendline(df, ph, 50)
    df['Trend_slope'] = slope
    df['Dist_to_trendline'] = (df['Close']-tval)/df['Close'] if tval else 0.0
    df['ADX'] = compute_adx(df)
    df['BB_width'] = compute_bollinger_width(df['Close']).fillna(0)
    df['Session'] = get_market_session_vectorized(df.index)
    df['ATR_ratio'] = df['ATR'] / df['ATR'].rolling(50).median().replace(0, np.nan)

    df['Future_return'] = df['Close'].shift(-4) / df['Close'] - 1
    df['Target'] = (df['Future_return'] > 0.00005).astype(int)
    df.dropna(inplace=True)
    return df

# --- Model ---
def build_rf(params=None):
    d = dict(n_estimators=250, max_depth=6, min_samples_leaf=10, class_weight='balanced', random_state=42)
    if params: d.update(params)
    return RandomForestClassifier(**d)

def build_gb(params=None):
    d = dict(n_estimators=150, max_depth=3, learning_rate=0.05, random_state=42)
    if params: d.update(params)
    return GradientBoostingClassifier(**d)

def load_tuned_params():
    if not os.path.isfile(TUNED_PARAMS_FILE): return {}, {}
    try:
        with open(TUNED_PARAMS_FILE, 'r') as f:
            j = json.load(f)
        ts = datetime.fromisoformat(j.get('timestamp','2000-01-01T00:00:00'))
        if datetime.now(timezone.utc) - ts < timedelta(hours=TUNE_EVERY_HOURS):
            return j.get('rf_params',{}), j.get('gb_params',{})
    except: pass
    return {}, {}

def train_calibrated_ensemble(hist):
    n = len(hist)
    train_end, calib_end = int(n*0.70), int(n*0.85)
    train, calib, test = hist.iloc[:train_end], hist.iloc[train_end:calib_end], hist.iloc[calib_end:]
    rf_p, gb_p = load_tuned_params()
    rf, gb = build_rf(rf_p), build_gb(gb_p)
    rf.fit(train[FEATURES], train['Target'])
    gb.fit(train[FEATURES], train['Target'])

    cal_rf = LogisticRegression().fit(rf.predict_proba(calib[FEATURES])[:,1].reshape(-1,1), calib['Target'])
    cal_gb = LogisticRegression().fit(gb.predict_proba(calib[FEATURES])[:,1].reshape(-1,1), calib['Target'])

    rf_t = cal_rf.predict_proba(rf.predict_proba(test[FEATURES])[:,1].reshape(-1,1))[:,1]
    gb_t = cal_gb.predict_proba(gb.predict_proba(test[FEATURES])[:,1].reshape(-1,1))[:,1]
    ensemble = (rf_t + gb_t)/2
    acc = float(accuracy_score(test['Target'], (ensemble>0.5).astype(int)))

    return {'rf':rf,'gb':gb,'calibrator_rf':cal_rf,'calibrator_gb':cal_gb,'test_acc':acc}

def predict_ensemble(models, live_row):
    rf_raw = models['rf'].predict_proba(live_row)[0][1]
    gb_raw = models['gb'].predict_proba(live_row)[0][1]
    rf_cal = float(models['calibrator_rf'].predict_proba([[rf_raw]])[0][1])
    gb_cal = float(models['calibrator_gb'].predict_proba([[gb_raw]])[0][1])
    return {'prob':(rf_cal+gb_cal)/2, 'rf_prob':rf_cal, 'gb_prob':gb_cal, 'model_agreement': 1.0 if (rf_cal>0.5)==(gb_cal>0.5) else 0.0}

def get_current_status():
    raw = load_raw_data()
    if raw is None or len(raw) < 200: return None
    data = build_features(raw)
    if len(data) < 200: return None

    live_row = data[FEATURES].iloc[[-1]]
    hist = data.iloc[:-1]
    models = train_calibrated_ensemble(hist)
    pred = predict_ensemble(models, live_row)

    return {
        'data': data,
        'prob': pred['prob'],
        'rf_prob': pred['rf_prob'],
        'gb_prob': pred['gb_prob'],
        'model_agreement': pred['model_agreement'],
        'test_acc': models['test_acc'],
        'current_price': float(data['Close'].iloc[-1]),
        'current_atr': float(data['ATR'].iloc[-1]),
        'trend_up': bool(data['Trend_up'].iloc[-1]),
        'trend_slope': float(data['Trend_slope'].iloc[-1]),
        'mtf_trends': get_multi_timeframe_trends(data),
        'support': detect_support_resistance(data)[0],
        'resistance': detect_support_resistance(data)[1],
        'pattern': detect_pattern(data),
    }
