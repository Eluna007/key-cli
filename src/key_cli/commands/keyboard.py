import json

from ..keyboard.backend import responses


def run(args):
    if args.action == "status":
        return next(responses())
    exit_code = 0
    for result in responses(watch=True):
        print(json.dumps(result.json(), separators=(",", ":")), flush=True)
        exit_code = result.exit_code
    return exit_code
