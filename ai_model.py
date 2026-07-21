from logger import logger


def generate_signal(
        rsi,
        ema,
        price,
        macd,
        signal,
        upper,
        lower
    ):

    try:

        score = 0
        reasons = []

        total_points = 6


        if rsi < 30:
            score += 1
            reasons.append("RSI oversold BUY")

        elif rsi > 70:
            score -= 1
            reasons.append("RSI overbought SELL")


        if price > ema:
            score += 1
            reasons.append("Price above EMA BUY")

        elif price < ema:
            score -= 1
            reasons.append("Price below EMA SELL")


        if macd > signal:
            score += 1
            reasons.append("MACD bullish")

        elif macd < signal:
            score -= 1
            reasons.append("MACD bearish")


        if price <= lower:
            score += 1
            reasons.append("Near lower Bollinger BUY")

        elif price >= upper:
            score -= 1
            reasons.append("Near upper Bollinger SELL")


        confidence = abs(score) / total_points * 100


        if score >= 2:
            decision = "BUY"

        elif score <= -2:
            decision = "SELL"

        else:
            decision = "HOLD"


        result = {
            "decision": decision,
            "confidence": round(confidence, 2),
            "score": score,
            "reasons": reasons
        }


        logger.info(f"AI Result: {result}")

        return result


    except Exception as e:

        logger.error(
            f"AI model error: {e}"
        )

        return {
            "decision": "HOLD",
            "confidence": 0,
            "score": 0,
            "reasons": []
        }
