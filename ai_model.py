from logger import logger


def generate_signal(rsi, ema, macd, signal):
    try:
        score = 0

        if rsi < 30:
            score += 1

        if rsi > 70:
            score -= 1

        if macd > signal:
            score += 1

        if macd < signal:
            score -= 1

        if score >= 2:
            result = "BUY"

        elif score <= -2:
            result = "SELL"

        else:
            result = "HOLD"

        logger.info(f"AI Signal: {result}")

        return result

    except Exception as e:
        logger.error(f"AI model error: {e}")
        return "HOLD"
