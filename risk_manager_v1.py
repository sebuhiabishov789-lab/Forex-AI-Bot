from logger import logger


def calculate_trade_levels(
        price,
        signal,
        atr,
        risk_reward=2
    ):

    try:

        if atr <= 0:
            return None


        result = {
            "signal": signal,
            "entry": round(price, 5),
            "risk_reward": f"1:{risk_reward}"
        }


        risk = atr * 1.5


        if signal == "BUY":

            stop_loss = price - risk

            take_profit = price + (
                risk * risk_reward
            )


        elif signal == "SELL":

            stop_loss = price + risk

            take_profit = price - (
                risk * risk_reward
            )


        else:

            return None



        result["stop_loss"] = round(stop_loss, 5)

        result["take_profit"] = round(take_profit, 5)


        logger.info(
            f"Trade plan created: {result}"
        )


        return result



    except Exception as e:

        logger.error(
            f"Risk manager error: {e}"
        )

        return None
