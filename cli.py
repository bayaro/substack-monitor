import argparse
import json
import yaml
import requests


def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def do_request(account_name, method):
    config = load_config()
    endpoint = config[method]

    url = f"https://{account_name}.substack.com/{endpoint['url']}"
    params = endpoint.get("params", {})
    columns = endpoint.get("columns")

    if endpoint.get("pagination") == "offset":
        limit = endpoint.get("limit", 20)
        results = []
        offset = 0
        while True:
            response = requests.get(
                url,
                params={**params, "limit": limit, "offset": offset},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=30,
            )
            response.raise_for_status()
            batch = response.json()
            if not batch:
                break
            results.extend(batch)
            offset += len(batch)
            if len(batch) < limit:
                break
    else:
        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        response.raise_for_status()
        results = response.json()

    if columns:
        results = [{col: item.get(col) for col in columns} for item in results]

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-a", "--account")
    parser.add_argument("-m", "--method", required=True)
    args = parser.parse_args()

    account = args.account or load_config().get("account_name")
    if not account:
        parser.error("account required: pass -a or set account_name in config.yaml")

    result = do_request(account, args.method)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
