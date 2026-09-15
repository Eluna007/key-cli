"""Public file commands, independent of Clavis and its installation."""

from ..files import backend


def run(args):
    if args.action == "status":
        return backend.status()
    if args.action == "search":
        return backend.search(args)
    return backend.action(args)
