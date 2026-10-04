"""Command-line entry point for 5G Core Inspector."""
import argparse
import math
from datetime import datetime
from pathlib import Path

import uvicorn

from .app import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--docker-container')
    modes.add_argument('--stdin', action='store_true')
    modes.add_argument('--replay', type=Path)
    parser.add_argument('--year', type=int, default=datetime.now().year)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.year <= 9999 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('year must be 1–9999 and timeout must be finite and positive')
    uvicorn.run(create_app('docker' if args.docker_container else 'replay' if args.replay else 'stdin',
                          args.docker_container, args.replay, args.year, args.timeout),
                host=args.host, port=args.port)
