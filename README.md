# Forex AI Bot — EUR/USD

RandomForest + GradientBoosting ensemble ilə EUR/USD üçün siqnal istehsal edən,
Telegram-a bildiriş göndərən və nəticələri özü izləyən bir sistem. Tamamilə
GitHub Actions üzərində, server icarəsi olmadan işləyir.

> ⚠️ **Risk xəbərdarlığı:** Bu layihə maliyyə məsləhəti DEYİL. Model keçmiş
> qiymət hərəkətlərinə əsaslanır, gələcək nəticəni zəmanət etmir. Foreks
> ticarəti yüksək riskli maliyyə fəaliyyətidir, əsas kapitalınızın hamısını
> itirə bilərsiniz. Bu bot yalnız təhsil/tədqiqat məqsədi daşıyır, real pulla
> istifadə etməzdən əvvəl uzun müddət demo hesabda test edin.

## Arxitektura

Sistem 3 ayrı GitHub Actions workflow-u ilə idarə olunur, hər biri nəticələri
birbaşa `main` branch-a commit edərək "state"-i saxlayır (server/DB lazım deyil):

| Workflow | Tezlik | Skript | Nə edir |
|---|---|---|---|
| `daily_bot.yml` | 15 dəq | `bot.py` | Yeni data üzərində model işlədir, threshold-lardan keçərsə Telegram-a siqnal göndərir |
| `tracker.yml` | 30 dəq | `outcome_tracker.py` | Açıq siqnalların SL/TP-yə çatıb-çatmadığını yoxlayır, `signals_log.csv`-i yeniləyir |
| `status_check.yml` | 10 dəq | `status_check.py` | Telegram-da "a" yazan istifadəçiyə anlıq status göndərir |

Üç workflow da eyni `forex-bot-repo-write` concurrency qrupundadır ki, eyni
anda `main`-ə push edərək bir-birini bloklamasınlar.

Digər fayllar:
- `market_utils.py` — data yükləmə (yfinance, fallback: Frankfurter → sintetik), feature engineering, RF+GB ensemble təlimi/kalibrasiyası, model cache
- `economic_calendar.py` — yüksək təsirli xəbərlər ətrafında "blackout" filtri
- `backtest.py` — canlı botla EYNİ model/feature/threshold-larla tarixi simulyasiya
- `app.py` — Streamlit paneli (canlı qiymət, qrafik, son siqnallar)

## Quraşdırma

```bash
git clone <repo-url>
cd Forex-AI-Bot
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # dəyərləri doldur
```

### Mühit dəyişənləri (`.env`)

| Dəyişən | Təsvir | Default |
|---|---|---|
| `TELEGRAM_TOKEN` | BotFather-dən alınan token | — |
| `TELEGRAM_CHAT_ID` | Siqnalların göndəriləcəyi chat ID | — |
| `MIN_TEST_ACC` | Modelin minimum test dəqiqliyi (bundan aşağıdırsa siqnal yoxdur) | 0.50 |
| `MIN_CONFIDENCE` | Minimum güvən skoru | 0.52 |
| `ACCOUNT_BALANCE` | Lot ölçüsü hesablaması üçün fərz edilən balans | 1000 |
| `RISK_PERCENT` | Hər əməliyyatda riskə atılan balans faizi | 1.0 |
| `MODEL_RETRAIN_EVERY_HOURS` | Model neçə saatdan bir yenidən öyrədilsin | 6 |
| `MAX_CONSECUTIVE_LOSSES` | Bu qədər ardıcıl LOSS-dan sonra bot dayanır | 4 |
| `LOSS_STREAK_COOLDOWN_HOURS` | Ardıcıl itkidən sonra susma müddəti | 12 |

GitHub Actions-da işə salmaq üçün `TELEGRAM_TOKEN` və `TELEGRAM_CHAT_ID`-i repo
**Settings → Secrets and variables → Actions** bölməsində saxla.

## Lokal işlətmək

```bash
python bot.py              # bir dəfəlik siqnal yoxlaması
python outcome_tracker.py  # açıq siqnalları yoxla
python backtest.py         # tarixi simulyasiya
streamlit run app.py       # canlı panel
```

## Strategiyanın qısa izahı

- **Feature-lar:** RSI, MACD, ADX, Bollinger genişliyi, ATR nisbəti, çoxlu-EMA trend, trendline məsafəsi, seans (Asiya/Avropa/ABŞ) və s. — 12 feature.
- **Model:** RandomForest + GradientBoosting, hər ikisi ayrıca `LogisticRegression` ilə ehtimal kalibrasiyasından keçir, sonra ortalanır.
- **Filtrlər:** minimum model dəqiqliyi, ATR-ə görə aşağı volatillik filtri, yüksək təsirli xəbər ətrafında blackout, gündəlik siqnal limiti, ardıcıl itkidən sonra soyuma dövrü.
- **SL/TP:** ATR əsaslı (1.5×ATR SL, 2.5×ATR TP).

Ətraflı məhdudiyyətlər üçün `backtest.py`-ın başındakı qeydə bax.

## Lisenziya / Məsuliyyət

Kod "olduğu kimi" (as-is) təqdim olunur, heç bir zəmanət verilmir. İstifadəçi
öz riski ilə istifadə edir.
