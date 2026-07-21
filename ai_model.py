from logger import logger


def generate_signal(rsi, ema, price, macd, signal, upper=None, lower=None):

    try:
        score = 0


        # RSI analiz
        if rsi < 30:
            score += 2

        elif rsi > 70:
            score -= 2


        # Trend EMA
        if price > ema:
            score += 1

        elif price < ema:
            score -= 1


        # MACD trend
        if macd > signal:
            score += 2

        elif macd < signal:
            score -= 2


        # Bollinger
        if upper is not None and lower is not None:

            if price <= lower:
                score += 1

            elif price >= upper:
                score -= 1


        if score >= 3:
            result = "BUY"

        elif score <= -3:
            result = "SELL"

        else:
            result = "HOLD"


        logger.info(
            f"AI Signal: {result} | Score: {score}"
        )

        return result


    except Exception as e:
        logger.error(f"AI model error: {e}")
        return "HOLD"
