#!/usr/bin/env python3
"""Production-style local service entrypoint for the competition demo."""
import argparse
import os


def main():
    parser = argparse.ArgumentParser(description="Run the local route planner service.")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--warmup", action="store_true", help="Load core data before accepting requests.")
    parser.add_argument("--no-warmup", action="store_true", help="Disable warmup even if WARMUP_ON_START=1.")
    args = parser.parse_args()

    if args.no_warmup:
        os.environ["WARMUP_ON_START"] = "0"

    from config import SERVER_HOST, SERVER_PORT
    from data_repository import repository
    from web_app import serve

    if args.warmup:
        repository.warmup()

    serve(host=args.host or SERVER_HOST, port=args.port or SERVER_PORT)


if __name__ == "__main__":
    main()
