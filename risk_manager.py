from logger import logger


def calculate_trade_levels(
    price,
    signal,
    atr,
    risk_multiplier=1.5,
    tp1_multiplier=2,
    tp2_multiplier=3
):

    try:

        if atr <= 0:
            return None

        risk = atr * risk_multiplier

        if signal == "BUY":

            entry = price
            stop_loss = entry - risk

            tp1 = entry + atr * tp1_multiplier
            tp2 = entry + atr * tp2_multiplier

        elif signal == "SELL":

            entry = price
            stop_loss = entry + risk

            tp1 = entry - atr * tp1_multiplier
            tp2 = entry - atr * tp2_multiplier

        else:

            return None

        reward = abs(tp2 - entry)
        risk_size = abs(entry - stop_loss)

        rr = round(reward / risk_size, 2)

        result = {
            "signal": signal,
            "entry": round(entry, 5),
            "stop_loss": round(stop_loss, 5),
            "take_profit_1": round(tp1, 5),
            "take_profit_2": round(tp2, 5),
            "risk_reward": f"1:{rr}",
            "atr": round(atr, 5)
        }

        logger.info(f"Trade plan created: {result}")

        return result

    except Exception as e:

        logger.exception(e)

        return None
