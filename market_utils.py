"""
market_utils.py — Ortak fonksiyonlar
Data yükleme, indiqatorlar, ensemble model, MTF trend
Optimallaşdırılmış versiya v2.1 - cache ile
"""
import yfinance as yf
import pandas as pd
import numpy as np
import json
import os
import logging
import joblib
from datetime import datetime, timezone, timedelta
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score

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

# Real ticarət qaydası ilə EYNİ barrier-lər (bot.py-dəki SL/TP ilə uyğunlaşdırılıb).
# Target labeling da, canlı SL/TP də bu 3 konstantı istifadə edir ki, model
# həqiqətən "bu qayda ilə ticarət etsəm uduram, ya uduzuram?" sualını öyrənsin.
TP_ATR_MULT = 2.5
SL_ATR_MULT = 1.5
MAX_HOLD_BARS = 48  # 15 dəq bar * 48 = 12 saat - siqnalın "gözlənilən" maksimum ömrü

TUNED_PARAMS_FILE = "tuned_params.json"
TUNE_EVERY_HOURS = 24
LAST_STATUS_FILE = "last_status.json"
MODEL_CACHE_FILE = "model_cache.pkl"
MODEL_RETRAIN_EVERY_HOURS = float(os.environ.get('MODEL_RETRAIN_EVERY_HOURS', '6'))


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
        logger.warning(f"ADX xeta: {e}")
        return pd.Series(20, index=data.index)

def compute_bollinger_width(close, period=20, nbdev=2):
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    return ((sma + nbdev*std) - (sma - nbdev*std)) / sma.replace(0, np.nan)

def load_raw_data():
    """Returns (DataFrame, is_synthetic: bool). is_synthetic=True mənası: bu data
    real bazar datası DEYİL, yalnız fallback üçün uydurulmuş random-walk-dır və
    ONUN ÜZƏRİNDƏ TİCARƏT SİQNALI GÖNDƏRİLMƏMƏLİDİR."""
    # 1. Önce yfinance dene (15m interval Yahoo-da maks. 60 günlük tarixçəyə icazə
    # verir - 90 gün istəmək HƏR DƏFƏ uğursuz olurdu və lazımsız ERROR logu yaradırdı)
    for days in [58, 45, 30]:
        try:
            data = yf.download('EURUSD=X', period=f'{days}d', interval='15m', auto_adjust=True, progress=False, threads=False)
            if data is None or data.empty or len(data) < 200:
                continue
            if data.index.tz is not None:
                data.index = data.index.tz_localize(None)
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            return data, False
        except Exception as e:
            logger.warning(f"yfinance cəhdi uğursuz ({days}d): {e}")
            continue

    # 2. Yahoo ban yediyse - Frankfurter'den son fiyatı al
    logger.warning("yfinance ban yedi, Frankfurter fallback devrede - BU SİNTETİK DATADIR")
    try:
        import requests
        r = requests.get("https://api.frankfurter.app/latest?from=EUR&to=USD", timeout=10).json()
        price = float(r['rates']['USD'])
    except Exception as e:
        logger.warning(f"Frankfurter fallback da uğursuz: {e}")
        # O da olmazsa son cache'den al
        cache = _load_last_status()
        price = cache['current_price'] if cache and 'current_price' in cache else 1.08

    # Sentetik 500 bar üret (son fiyat etrafında %0.5 random walk)
    idx = pd.date_range(end=datetime.now(), periods=500, freq='15min')
    close = price + np.cumsum(np.random.randn(500)*0.0002)
    df = pd.DataFrame({
        'Open': close,
        'High': close*1.0003,
        'Low': close*0.9997,
        'Close': close,
        'Volume': 1000
    }, index=idx)
    return df, True

def get_market_session_vectorized(index):
    hours = index.hour
    conditions = [(hours >= 7) & (hours < 16), (hours >= 13) & (hours < 21), (hours >= 0) & (hours < 9)]
    choices = [1, 2, 0]
    return np.select(conditions, choices, default=3)

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
    return (float(below.max()) if not below.empty else None, float(above.min()) if not above.empty else None)

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

def resample_ohlc(data, rule):
    return data.resample(rule).agg({'Open':'first','High':'max','Low':'min','Close':'last'}).dropna()

def get_trend_label(data, rule, min_bars=55):
    try:
        tf = resample_ohlc(data, rule)
        if len(tf) < min_bars: return "Data azdır"
        ema_f = tf['Close'].ewm(span=20, adjust=False).mean()
        ema_s = tf['Close'].ewm(span=50, adjust=False).mean()
        return "Yuxari" if ema_f.iloc[-1] > ema_s.iloc[-1] else "Asagi"
    except Exception as e:
        logger.warning(f"Trend label hesablanmadı ({rule}): {e}")
        return "N/A"

def get_multi_timeframe_trends(data):
    tfs = {"15 deq":"15min","30 deq":"30min","1 saat":"1h","4 saat":"4h","1 gun":"1D"}
    return {k: get_trend_label(data, v) for k, v in tfs.items()}

def compute_triple_barrier_target(df, tp_mult=TP_ATR_MULT, sl_mult=SL_ATR_MULT, max_hold=MAX_HOLD_BARS):
    """Hər bar üçün: əgər bu anda LONG açılsaydı (SL = sl_mult*ATR aşağı,
    TP = tp_mult*ATR yuxarı), qiymət max_hold bar ərzində əvvəlcə TP-yə,
    yoxsa SL-ə toxunardı? Bu, bot.py-dəki real SL/TP qaydasının EYNİSİDİR
    (əvvəlki versiyada target sadəcə "növbəti 1 saatda kiçik pip hərəkəti"
    idi, real ticarət nəticəsi ilə demək olar əlaqəsi yox idi).

    Qaytarır: (target array, valid mask). Nə TP, nə də SL max_hold bar
    ərzində toxunulmayan barlar 'qeyri-müəyyən' sayılır və valid=False olur —
    bunlar təlimə daxil edilmir (nə uduzur, nə udur, sadəcə bağlanmır).

    MƏHDUDİYYƏT: bu label yalnız LONG mövqe üçün dəqiqdir. SELL siqnalları
    üçün botda "ehtimal aşağıdırsa qısa aç" məntiqi işlədilir - bu, SL/TP
    məsafələri asimmetrik olduğuna görə (1.5x vs 2.5x ATR) LONG-un tam əksi
    deyil, təxmini (approksimasiya) əlaqədir. Symmetric olmayan barrier üçün
    tam dəqiq SHORT label-i ayrıca hesablamaq mümkündür, amma mürəkkəbliyi
    artırdığından hazırkı versiyada bu sadələşdirmə saxlanılıb.
    """
    high, low, atr = df['High'].values, df['Low'].values, df['ATR'].values
    entry = df['Close'].values
    n = len(df)
    target = np.zeros(n)
    valid = np.zeros(n, dtype=bool)

    for i in range(n - 1):
        a = atr[i]
        if np.isnan(a) or a <= 0:
            continue
        tp_level = entry[i] + tp_mult * a
        sl_level = entry[i] - sl_mult * a
        end = min(i + 1 + max_hold, n)
        w_high, w_low = high[i+1:end], low[i+1:end]
        if len(w_high) == 0:
            continue
        tp_hits = np.where(w_high >= tp_level)[0]
        sl_hits = np.where(w_low <= sl_level)[0]
        first_tp = tp_hits[0] if len(tp_hits) else np.inf
        first_sl = sl_hits[0] if len(sl_hits) else np.inf
        if first_tp == np.inf and first_sl == np.inf:
            continue  # max_hold ərzində heç biri toxunulmayıb - qeyri-müəyyən, atılır
        target[i] = 1.0 if first_tp < first_sl else 0.0
        valid[i] = True

    return target, valid

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
    # Köhnə target (0.5 pip-lik 1 saatlıq mikro-hərəkət) real SL/TP qaydası ilə
    # uyğun gəlmirdi (bax: compute_triple_barrier_target docstring-i). İndi target
    # birbaşa "bu barda LONG açsaydım, TP-yə SL-dən əvvəl çatardımmı?" sualıdır.
    df.dropna(inplace=True)
    tb_target, tb_valid = compute_triple_barrier_target(df)
    df['Target'] = tb_target.astype(int)
    df = df.loc[tb_valid].copy()
    return df

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
    except Exception as e:
        logger.warning(f"Tuned params oxunmadı: {e}")
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

def _load_model_cache():
    if not os.path.isfile(MODEL_CACHE_FILE):
        return None
    try:
        cached = joblib.load(MODEL_CACHE_FILE)
        ts = datetime.fromisoformat(cached.get('timestamp', '2000-01-01T00:00:00+00:00'))
        if datetime.now(timezone.utc) - ts < timedelta(hours=MODEL_RETRAIN_EVERY_HOURS):
            return cached['models']
    except Exception as e:
        logger.warning(f"Model cache oxunmadı: {e}")
    return None

def _save_model_cache(models):
    try:
        joblib.dump({'timestamp': datetime.now(timezone.utc).isoformat(), 'models': models}, MODEL_CACHE_FILE)
    except Exception as e:
        logger.warning(f"Model cache yazılmadı: {e}")

def get_or_train_ensemble(hist):
    """Modeli hər run-da sıfırdan öyrətmək əvəzinə MODEL_RETRAIN_EVERY_HOURS ərzində
    öncəki öyrədilmiş modeli təkrar istifadə edir - həm hesablama xərcini, həm də
    run-lar arası nəticə qeyri-sabitliyini azaldır."""
    cached = _load_model_cache()
    if cached is not None:
        return cached
    models = train_calibrated_ensemble(hist)
    _save_model_cache(models)
    return models

def predict_ensemble(models, live_row):
    rf_raw = models['rf'].predict_proba(live_row)[0][1]
    gb_raw = models['gb'].predict_proba(live_row)[0][1]
    rf_cal = float(models['calibrator_rf'].predict_proba([[rf_raw]])[0][1])
    gb_cal = float(models['calibrator_gb'].predict_proba([[gb_raw]])[0][1])
    return {'prob':(rf_cal+gb_cal)/2, 'rf_prob':rf_cal, 'gb_prob':gb_cal, 'model_agreement': 1.0 if (rf_cal>0.5)==(gb_cal>0.5) else 0.0}

def _save_last_status(st):
    try:
        slim = {
            'current_price': st.get('current_price'),
            'prob': st.get('prob'),
            'rf_prob': st.get('rf_prob'),
            'gb_prob': st.get('gb_prob'),
            'trend_up': st.get('trend_up'),
            'test_acc': st.get('test_acc'),
            'is_synthetic': st.get('is_synthetic', False),
            'time': datetime.now(timezone.utc).isoformat()
        }
        with open(LAST_STATUS_FILE,"w") as f:
            json.dump(slim,f)
    except Exception as e:
        logger.warning(f"last_status.json yazılmadı: {e}")

def _load_last_status():
    if os.path.isfile(LAST_STATUS_FILE):
        try:
            with open(LAST_STATUS_FILE,"r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"last_status.json oxunmadı: {e}")
            return None
    return None

def _get_live_status():
    raw, is_synthetic = load_raw_data()
    if raw is None or len(raw) < 200:
        return None
    data = build_features(raw)
    if len(data) < 200:
        return None
    live_row = data[FEATURES].iloc[[-1]]
    hist = data.iloc[:-1]
    models = get_or_train_ensemble(hist)
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
        'is_synthetic': is_synthetic,
    }

def get_current_status():
    try:
        st = _get_live_status()
        if st is not None:
            _save_last_status(st)
            return st
    except Exception as e:
        logger.warning(f"get_current_status xetasi: {e}")
    return _load_last_status()
