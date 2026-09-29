import requests

def users(account_name):
    url = (
        f"https://{account_name}.substack.com"
        "/api/v1/publication/users/ranked"
    )

    response = requests.get(
        url,
        params={"public": "true"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    response.raise_for_status()

    return response.json()
