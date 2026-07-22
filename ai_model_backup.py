from logger import logger

from AI.trend import analyze_trend
from AI.momentum import analyze_momentum
from AI.volatility import analyze_volatility
from AI.support_resistance import analyze_support_resistance


def generate_signal(
    rsi,
    ema50,
    ema200,
    price,
    macd,
    signal,
    upper,
    lower,
    adx,
    support,
    resistance
):

    try:

        score = 0
        reasons = []

        trend_score, trend_reasons = analyze_trend(
            price,
            ema50,
            ema200
        )

        momentum_score, momentum_reasons = analyze_momentum(
            rsi,
            macd,
            signal
        )

        volatility_score, volatility_reasons = analyze_volatility(
            price,
            upper,
            lower,
            adx
        )

        sr_score, sr_reasons = analyze_support_resistance(
            price,
            support,
            resistance
        )

        score = (
            trend_score
            + momentum_score
            + volatility_score
            + sr_score
        )

        reasons.extend(trend_reasons)
        reasons.extend(momentum_reasons)
        reasons.extend(volatility_reasons)
        reasons.extend(sr_reasons)

        max_score = 18
        confidence = abs(score) / max_score * 100

        if score >= 6:
            decision = "BUY"

        elif score <= -6:
            decision = "SELL"

        else:
            decision = "HOLD"

        result = {
            "decision": decision,
            "confidence": round(confidence, 2),
            "score": score,
            "adx": round(float(adx), 2),
            "reasons": reasons
        }

        logger.info(f"AI Result: {result}")

        return result

    except Exception as e:

        logger.exception(e)

        return {
            "decision": "HOLD",
            "confidence": 0,
            "score": 0,
            "reasons": []
        }
