import requests
from config import OANDA_API_KEY, OANDA_ACCOUNT_ID, OANDA_BASE_URL
from logger import logger


class OandaAPI:
    def __init__(self):
        self.api_key = OANDA_API_KEY
        self.account_id = OANDA_ACCOUNT_ID
        self.base_url = OANDA_BASE_URL

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def get_account_summary(self):
        url = f"{self.base_url}/v3/accounts/{self.account_id}/summary"

        try:
            response = requests.get(
                url,
                headers=self.headers
            )

            response.raise_for_status()

            logger.info("Account summary received")
            return response.json()

        except Exception as e:
            logger.error(f"Account summary error: {e}")
            return None
