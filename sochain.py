import requests

def check_payment(ltc_address, expected_amount):
    response = requests.get(f"https://sochain.com/api/v2/address/LTC/{ltc_address}")
    for tx in response.json()["data"]["txs"]:
        if abs(float(tx["value"]) - expected_amount) < 0.00000001:
            return {
                "txid": tx["txid"],
                "amount": tx["value"],
                "confirmations": tx["confirmations"]
            }
    return None
