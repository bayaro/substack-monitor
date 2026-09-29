
import argparse
import inspect
import json

import api


def get_api_methods():
    return {
        name: func
        for name, func in inspect.getmembers(api, inspect.isfunction)
        if not name.startswith("_")
    }


def main():
    methods = get_api_methods()

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "method",
        choices=methods.keys(),
    )

    args, method_args = parser.parse_known_args()

    method = methods[args.method]
    signature = inspect.signature(method)

    required = [
        param
        for param in signature.parameters.values()
        if param.default is inspect.Parameter.empty
        and param.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]

    if len(method_args) != len(required):
        parser.error(
            f"{args.method}() expects "
            f"{len(required)} argument(s): "
            + ", ".join(param.name for param in required)
        )

    result = method(*method_args)

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
