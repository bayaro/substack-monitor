import yaml
import requests
from pathlib import Path


def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    config = load_config()

    account_name = config["account_name"]
    data_dir = Path(config["data_dir"])
    columns = config["post_columns"]

    data_dir.mkdir(parents=True, exist_ok=True)

    url = f"https://{account_name}.substack.com/api/v1/posts"

    posts = []
    offset = 0
    limit = 20

    while True:
        response = requests.get(
            url,
            params={
                "limit": limit,
                "offset": offset,
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=30,
        )
        response.raise_for_status()

        batch = response.json()

        if not batch:
            break

        posts.extend(batch)

        print(f"Downloaded {len(posts)} posts...")

        offset += len(batch)

        if len(batch) < limit:
            break

    posts = [
        {
            column: post.get(column)
            for column in columns
        }
        for post in posts
    ]

    output_file = data_dir / "posts.yaml"

    with output_file.open("w", encoding="utf-8") as f:
        yaml.safe_dump(
            posts,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )

    print(f"Saved {len(posts)} posts to {output_file}")


if __name__ == "__main__":
    main()
