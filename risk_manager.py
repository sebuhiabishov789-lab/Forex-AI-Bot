from logger import logger


def calculate_trade_levels(
        price,
        signal,
        atr,
        risk_reward=2
    ):

    try:

        result = {
            "signal": signal,
            "entry": round(price,5),
            "risk_reward": f"1:{risk_reward}"
        }


        if signal == "BUY":

            stop_loss = price - (atr * 1.5)

            take_profit = price + (
                (price - stop_loss) * risk_reward
            )


        elif signal == "SELL":

            stop_loss = price + (atr * 1.5)

            take_profit = price - (
                (stop_loss - price) * risk_reward
            )


        else:

            result["stop_loss"] = None
            result["take_profit"] = None

            return result



        result["stop_loss"] = round(stop_loss,5)

        result["take_profit"] = round(take_profit,5)


        logger.info(
            f"ATR Trade levels created: {result}"
        )


        return result


    except Exception as e:

        logger.error(
            f"Risk manager error: {e}"
        )

        return None
