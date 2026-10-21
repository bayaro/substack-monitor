import argparse
from pathlib import Path
import yaml

import config
import fetch


def __collect(method):
    data_dir = Path(config.CONFIG.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    sort_key = config.CONFIG.endpoints[method].get("sort_key")
    result = fetch.do_request(method)
    if sort_key:
        result = sorted(result, key=lambda x: x.get(sort_key), reverse=True)
    output = data_dir / f"{method}.yaml"
    with output.open("w", encoding="utf-8") as f:
        yaml.safe_dump(result, f, allow_unicode=True, sort_keys=True, default_flow_style=False)
    print(f"Saved {len(result)} records to {output}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--method", required=True)
    parser.add_argument("--cache", choices=["write", "read", "auto"], default="auto",
                        help="auto: read a fresh cache, otherwise fetch and write it (default); "
                             "write: always fetch; read: never fetch")
    parser.add_argument("--force", action="store_true",
                        help="do not continue an interrupted download, start it over")
    args = parser.parse_args()

    try:
        config.load_config()
    except config.ConfigError as e:
        parser.error(str(e))

    config.CONFIG.cache = args.cache
    config.CONFIG.force = args.force

    if args.method == "all":
        for method in config.CONFIG.endpoints:
            __collect(method)
    else:
        __collect(args.method)


if __name__ == "__main__":
    main()
