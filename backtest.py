"""
Backtest skripti — bot.py-dəki CANLI strategiyanı (eyni feature-lar, eyni RF+GB
kalibrə olunmuş ensemble, eyni threshold-lar) keçmiş data üzərində simulyasiya edir.

İşlətmək üçün:
    python backtest.py

Nə edir:
1. market_utils.load_raw_data() + build_features() ilə CANLI botla EYNİ 12 feature-ı
   hesablayır (əvvəlki versiyada backtest yalnız 5 sadə feature işlədirdi - artıq belə deyil).
2. Datanı 70% / 15% / 15% (train / kalibrasiya / test) bölür — bot.py-dəki
   train_calibrated_ensemble() ilə EYNİ məntiq (RandomForest + GradientBoosting,
   hər ikisi ayrı-ayrı kalibrə olunur, sonra ortalanır).
3. Test hissəsindəki hər bar üçün bot.py-dəki Config-dən gələn EYNİ
   BUY/SELL threshold, MIN_TEST_ACC və ATR filtrini tətbiq edir.
4. Hər "siqnal" üçün irəliyə doğru gedib SL/TP-dən hansının əvvəl toxunduğunu yoxlayır,
   HƏM DƏ sabit spread xərcini nəzərə alır (real ticarətdə hər girişdə ödənilir).
5. Nəticədə: neçə siqnal, neçəsi uğurlu (TP), neçəsi uğursuz (SL), win rate,
   məcmu pip nəticəsi (spread xərci çıxılmış), profit factor çap edir.

QALAN MƏHDUDİYYƏTLƏR (hələ tam canlı botu əks etdirmir):
- Çoxlu-timeframe (MTF) trend uyğunluğu və dəstək/müqavimət əsaslı `confidence`
  filtri backtest-də hesablanmır (hər bar üçün bunu hesablamaq performansca
  bahalıdır) — yəni backtest canlıdan bir qədər DAHA ÇOX siqnal buraxa bilər.
- Model backtest boyu YALNIZ BİR DƏFƏ öyrədilir (canlı botda hər
  MODEL_RETRAIN_EVERY_HOURS-də bir yenidən öyrədilir) — uzun test dövründə bu,
  nəticələri optimistik göstərə bilər (regime dəyişikliyi nəzərə alınmır).
- Slippage və komissiya modelə salınmayıb, yalnız sabit spread çıxılır.
Bu səbəblərdən backtest nəticələrini "yuxarı hədd" (upper bound) kimi oxu, canlı
performansın bundan bir qədər zəif olması normaldır.
"""

import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score

import market_utils
from bot import config as bot_config

# EUR/USD üçün tipik spread (broker/vaxtdan asılı olaraq dəyişir - realist qonşuluq)
SPREAD_PIPS = 1.2
PIP_VALUE = 0.0001


def simulate_trade(data, entry_idx, direction, entry_price, sl, tp, max_bars=48):
    """entry_idx-dən sonrakı barlarda SL/TP-dən hansı əvvəl toxunub yoxlayır.
    max_bars ərzində heçbiri toxunmasa 'timeout' qaytarır."""
    future = data.iloc[entry_idx + 1: entry_idx + 1 + max_bars]

    for _, row in future.iterrows():
        high, low = row['High'], row['Low']
        if direction == 'BUY':
            hit_sl, hit_tp = low <= sl, high >= tp
        else:
            hit_sl, hit_tp = high >= sl, low <= tp

        # Eyni bar içində hər ikisi toxunarsa, konservativ yanaşaraq SL prioritetləndirilir
        if hit_sl:
            return 'SL', sl - entry_price if direction == 'BUY' else entry_price - sl
        if hit_tp:
            return 'TP', tp - entry_price if direction == 'BUY' else entry_price - tp

    return 'TIMEOUT', 0.0


def train_ensemble_for_backtest(train, calib):
    """market_utils.train_calibrated_ensemble ilə eyni məntiq, sadəcə hazır
    train/calib bölgüsü qəbul edir ki, test hissəsi üzərində vektorlaşdırılmış
    (sürətli) proqnoz apara bilək."""
    rf, gb = market_utils.build_rf(), market_utils.build_gb()
    rf.fit(train[market_utils.FEATURES], train['Target'])
    gb.fit(train[market_utils.FEATURES], train['Target'])
    cal_rf = LogisticRegression().fit(rf.predict_proba(calib[market_utils.FEATURES])[:, 1].reshape(-1, 1), calib['Target'])
    cal_gb = LogisticRegression().fit(gb.predict_proba(calib[market_utils.FEATURES])[:, 1].reshape(-1, 1), calib['Target'])
    return rf, gb, cal_rf, cal_gb


def run_backtest():
    print("Data yüklənir və hazırlanır (canlı botla eyni feature pipeline)...")
    raw, is_synthetic = market_utils.load_raw_data()
    if is_synthetic:
        print("XƏBƏRDARLIQ: yfinance/Frankfurter əlçatan deyil, sintetik data qayıtdı - backtest MƏNASIZDIR, sonra yenidən cəhd et.")
        return
    data = market_utils.build_features(raw)

    n = len(data)
    train_end, calib_end = int(n * 0.70), int(n * 0.85)
    train, calib, test = data.iloc[:train_end], data.iloc[train_end:calib_end], data.iloc[calib_end:]
    print(f"Train: {len(train)} bar | Kalibrasiya: {len(calib)} bar | Test: {len(test)} bar")

    rf, gb, cal_rf, cal_gb = train_ensemble_for_backtest(train, calib)

    # Vektorlaşdırılmış proqnoz - bütün test set üçün bir dəfəyə (sürətli)
    rf_raw_test = rf.predict_proba(test[market_utils.FEATURES])[:, 1]
    gb_raw_test = gb.predict_proba(test[market_utils.FEATURES])[:, 1]
    rf_cal_test = cal_rf.predict_proba(rf_raw_test.reshape(-1, 1))[:, 1]
    gb_cal_test = cal_gb.predict_proba(gb_raw_test.reshape(-1, 1))[:, 1]
    ensemble_prob = (rf_cal_test + gb_cal_test) / 2

    test_acc = float(accuracy_score(test['Target'], (ensemble_prob > 0.5).astype(int)))
    print(f"Modelin test dəqiqliyi: {test_acc:.2%}")

    if test_acc < bot_config.MIN_TEST_ACC:
        print(f"Model dəqiqliyi canlı botun MIN_TEST_ACC ({bot_config.MIN_TEST_ACC}) həddindən aşağıdır - "
              f"canlıda bu model heç siqnal göndərməyəcək.\n")

    hist_atr_median = test['ATR'].rolling(50).median()
    atr_ratio = test['ATR'] / hist_atr_median

    test_reset = test.reset_index()
    prob_arr, atr_ratio_arr = ensemble_prob, atr_ratio.values

    trades = []
    for i in range(len(test_reset) - 1):
        row = test_reset.iloc[i]
        prob = prob_arr[i]
        ratio = atr_ratio_arr[i]
        if np.isnan(ratio) or ratio < bot_config.MIN_ATR_RATIO:
            continue

        trend_up = bool(row['Trend_up'])
        price, atr = row['Close'], row['ATR']

        direction = None
        if prob >= bot_config.BUY_THRESHOLD:
            direction = 'BUY'
            sl, tp = price - atr * market_utils.SL_ATR_MULT, price + atr * market_utils.TP_ATR_MULT
        elif prob <= bot_config.SELL_THRESHOLD:
            direction = 'SELL'
            sl, tp = price + atr * market_utils.SL_ATR_MULT, price - atr * market_utils.TP_ATR_MULT

        if direction:
            outcome, pip_result_price_units = simulate_trade(test_reset, i, direction, price, sl, tp, max_bars=market_utils.MAX_HOLD_BARS)
            pip_result = pip_result_price_units / PIP_VALUE - SPREAD_PIPS  # spread xərci hər girişdə çıxılır
            trades.append({
                'time': row.get('Datetime', row.get('index')),
                'direction': direction,
                'entry': price,
                'sl': sl,
                'tp': tp,
                'prob': prob,
                'outcome': outcome,
                'pips': round(pip_result, 1),
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
    total_pips = trades_df['pips'].sum()

    gross_win = trades_df.loc[trades_df['pips'] > 0, 'pips'].sum()
    gross_loss = -trades_df.loc[trades_df['pips'] < 0, 'pips'].sum()
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float('inf')

    print("\n===== BACKTEST NƏTİCƏLƏRİ (spread daxil, ~1 dəfə öyrədilmiş model) =====")
    print(f"Ümumi siqnal sayı     : {total}")
    print(f"Uğurlu (TP)           : {wins}")
    print(f"Uğursuz (SL)          : {losses}")
    print(f"Timeout (nə SL nə TP) : {timeouts}")
    print(f"Win rate              : {win_rate:.1%}")
    print(f"Profit factor         : {profit_factor:.2f}")
    print(f"Məcmu nəticə (pip, spread çıxılmış): {total_pips:.1f}")
    print("=========================================================================")

    trades_df.to_csv('backtest_results.csv', index=False)
    print("\nDetallı nəticələr backtest_results.csv faylına yazıldı.")


if __name__ == "__main__":
    run_backtest()
