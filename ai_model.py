from logger import logger


def generate_signal(
        rsi,
        ema,
        price,
        macd,
        signal,
        upper,
        lower,
        adx
    ):

    try:

        score = 0
        reasons = []

        total_points = 7


        # RSI
        if rsi < 30:
            score += 1
            reasons.append("RSI oversold BUY")

        elif rsi > 70:
            score -= 1
            reasons.append("RSI overbought SELL")


        # EMA trend
        if price > ema:
            score += 1
            reasons.append("Price above EMA BUY")

        elif price < ema:
            score -= 1
            reasons.append("Price below EMA SELL")


        # MACD
        if macd > signal:
            score += 1
            reasons.append("MACD bullish")

        elif macd < signal:
            score -= 1
            reasons.append("MACD bearish")


        # Bollinger
        if price <= lower:
            score += 1
            reasons.append("Lower Bollinger BUY")

        elif price >= upper:
            score -= 1
            reasons.append("Upper Bollinger SELL")


        # ADX trend strength
        if adx > 25:
            score += 1
            reasons.append("Strong trend ADX")


        # Confidence
        confidence = abs(score) / total_points * 100


        if score >= 3:
            decision = "BUY"

        elif score <= -3:
            decision = "SELL"

        else:
            decision = "HOLD"


        result = {
            "decision": decision,
            "confidence": round(confidence,2),
            "score": score,
            "adx": round(float(adx),2),
            "reasons": reasons
        }


        logger.info(f"AI Result: {result}")

        return result


    except Exception as e:

        logger.error(
            f"AI model error: {e}"
        )

        return {
            "decision":"HOLD",
            "confidence":0,
            "score":0,
            "reasons":[]
        }