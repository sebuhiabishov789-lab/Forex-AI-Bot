from logger import logger


def generate_signal(
        rsi,
        ema,
        ema200,
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

        total_points = 8


        # RSI
        if rsi < 35:
            score += 1
            reasons.append("RSI aşağıdır - alış potensialı")

        elif rsi > 65:
            score -= 1
            reasons.append("RSI yüksəkdir - satış potensialı")


        # EMA qısa trend
        if price > ema:
            score += 1
            reasons.append("Qiymət EMA-dan yuxarıdır - qısa trend yüksəlişdir")

        elif price < ema:
            score -= 1
            reasons.append("Qiymət EMA-dan aşağıdır - qısa trend enişdir")


        # EMA200 uzun trend
        if price > ema200:
            score += 1
            reasons.append("Qiymət EMA200-dən yuxarıdır - əsas trend yüksəlişdir")

        elif price < ema200:
            score -= 1
            reasons.append("Qiymət EMA200-dən aşağıdır - əsas trend enişdir")


        # MACD
        if macd > signal:
            score += 1
            reasons.append("MACD yüksəlişi göstərir")

        elif macd < signal:
            score -= 1
            reasons.append("MACD enişi göstərir")


        # Bollinger
        if price <= lower:
            score += 1
            reasons.append("Qiymət Bollinger aşağı zonasındadır")

        elif price >= upper:
            score -= 1
            reasons.append("Qiymət Bollinger yuxarı zonasındadır")


        # ADX
        if adx > 25:
            score += 1
            reasons.append("ADX güclüdür - trend təsdiqlənir")


        confidence = abs(score) / total_points * 100


        if score >= 4:
            decision = "BUY"

        elif score <= -4:
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


        logger.info(
            f"AI Result: {result}"
        )

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
