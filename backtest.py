"""
Backtest skripti — bot.py-dəki strategiyanı keçmiş data üzərində simulyasiya edir.

İşlətmək üçün:
    python backtest.py

Nə edir:
1. 60 günlük 15dəq EURUSD datasını yükləyir.
2. Datanı 80% / 20% (train / test) bölür.
3. Modeli yalnız train hissəsində öyrədir (bot.py ilə eyni feature-lar).
4. Test hissəsindəki hər bar üçün bot.py-dəki eyni threshold + trend filtrini tətbiq edir.
5. Hər "siqnal" üçün irəliyə doğru gedib SL/TP-dən hansının əvvəl toxunduğunu yoxlayır.
6. Nəticədə: neçə siqnal, neçəsi uğurlu (TP), neçəsi uğursuz (SL),
   win rate, məcmu pip nəticəsi, profit factor çap edir.

Qeyd: Bu, sadələşdirilmiş backtestdir (spread/slippage/komissiya nəzərə alınmır,
   model yalnız bir dəfə öyrədilir — real botda hər işə düşəndə yenidən öyrədilir).
   Buna baxmayaraq, strategiyanın ümumi məntiqinin nə dərəcədə işlək olduğu haqqında
   real vaxtda gözləmədən dəyərli bir ilkin fikir verir.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score


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
    return macd_line - signal_line


def compute_atr(data, period=14):
    high_low = data['High'] - data['Low']
    high_cp = (data['High'] - data['Close'].shift()).abs()
    low_cp = (data['Low'] - data['Close'].shift()).abs()
    tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def load_and_prepare():
    data = yf.download('EURUSD=X', period='60d', interval='15m', auto_adjust=True)
    if data.index.tz is not None:
        data.index = data.index.tz_localize(None)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    data['Return'] = data['Close'].pct_change()
    data['Range'] = (data['High'] - data['Low']) / data['Close']
    data['RSI'] = compute_rsi(data['Close'])
    data['MACD_hist'] = compute_macd(data['Close'])
    data['EMA_fast'] = data['Close'].ewm(span=20, adjust=False).mean()
    data['EMA_slow'] = data['Close'].ewm(span=50, adjust=False).mean()
    data['Trend_up'] = (data['EMA_fast'] > data['EMA_slow']).astype(int)
    data['ATR'] = compute_atr(data)

    horizon = 4
    data['Future_return'] = data['Close'].shift(-horizon) / data['Close'] - 1
    data['Target'] = (data['Future_return'] > 0).astype(int)

    data.dropna(inplace=True)
    return data


def simulate_trade(data, entry_idx, direction, entry_price, sl, tp, max_bars=48):
    """entry_idx-dən sonrakı barlarda SL/TP-dən hansı əvvəl toxunub yoxlayır.
    max_bars ərzində heçbiri toxunmasa 'timeout' qaytarır."""
    future = data.iloc[entry_idx + 1: entry_idx + 1 + max_bars]

    for _, row in future.iterrows():
        high = row['High']
        low = row['Low']

        if direction == 'BUY':
            hit_sl = low <= sl
            hit_tp = high >= tp
        else:  # SELL
            hit_sl = high >= sl
            hit_tp = low <= tp

        # Eyni bar içində hər ikisi toxunarsa, konservativ yanaşaraq SL prioritetləndirilir
        if hit_sl and hit_tp:
            return 'SL', sl - entry_price if direction == 'BUY' else entry_price - sl
        if hit_sl:
            return 'SL', sl - entry_price if direction == 'BUY' else entry_price - sl
        if hit_tp:
            return 'TP', tp - entry_price if direction == 'BUY' else entry_price - tp

    return 'TIMEOUT', 0.0


def run_backtest():
    print("Data yüklənir və hazırlanır...")
    data = load_and_prepare()

    features = ['Return', 'Range', 'RSI', 'MACD_hist', 'Trend_up']

    split_idx = int(len(data) * 0.8)
    train = data.iloc[:split_idx]
    test = data.iloc[split_idx:]

    print(f"Train: {len(train)} bar | Test: {len(test)} bar")

    model = RandomForestClassifier(n_estimators=200, max_depth=5, random_state=42)
    model.fit(train[features], train['Target'])

    test_acc = accuracy_score(test['Target'], model.predict(test[features]))
    print(f"Modelin test dəqiqliyi: {test_acc:.2%}\n")

    BUY_THRESHOLD = 0.62
    SELL_THRESHOLD = 0.38

    trades = []
    test_reset = test.reset_index()

    for i in range(len(test_reset) - 1):
        row = test_reset.iloc[i]
        feat_row = pd.DataFrame([row[features].values], columns=features)
        prob = model.predict_proba(feat_row)[0][1]

        trend_up = bool(row['Trend_up'])
        price = row['Close']
        atr = row['ATR']

        direction = None
        if prob > BUY_THRESHOLD and trend_up:
            direction = 'BUY'
            sl = price - 1.5 * atr
            tp = price + 3.0 * atr
        elif prob < SELL_THRESHOLD and not trend_up:
            direction = 'SELL'
            sl = price + 1.5 * atr
            tp = price - 3.0 * atr

        if direction:
            outcome, pip_result = simulate_trade(test_reset, i, direction, price, sl, tp)
            trades.append({
                'time': row['Datetime'] if 'Datetime' in row else row.get('index'),
                'direction': direction,
                'entry': price,
                'sl': sl,
                'tp': tp,
                'outcome': outcome,
                'result': pip_result,
            })

    if not trades:
        print("Test dövründə heç bir siqnal yaranmadı — thresholds çox sərtdir və ya data qısadır.")
        return

    trades_df = pd.DataFrame(trades)
    total = len(trades_df)
    wins = (trades_df['outcome'] == 'TP').sum()
    losses = (trades_df['outcome'] == 'SL').sum()
    timeouts = (trades_df['outcome'] == 'TIMEOUT').sum()

    win_rate = wins / total if total > 0 else 0
    total_result = trades_df['result'].sum()

    gross_win = trades_df.loc[trades_df['result'] > 0, 'result'].sum()
    gross_loss = -trades_df.loc[trades_df['result'] < 0, 'result'].sum()
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float('inf')

    print("===== BACKTEST NƏTİCƏLƏRİ =====")
    print(f"Ümumi siqnal sayı : {total}")
    print(f"Uğurlu (TP)        : {wins}")
    print(f"Uğursuz (SL)        : {losses}")
    print(f"Timeout (nə SL nə TP): {timeouts}")
    print(f"Win rate            : {win_rate:.1%}")
    print(f"Profit factor       : {profit_factor:.2f}")
    print(f"Məcmu nəticə (qiymət vahidi): {total_result:.5f}")
    print("================================")

    trades_df.to_csv('backtest_results.csv', index=False)
    print("\nDetallı nəticələr backtest_results.csv faylına yazıldı.")


if __name__ == "__main__":
    run_backtest()
