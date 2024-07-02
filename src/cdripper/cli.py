import logging
import argparse
from cdripper import ripcd

from . import STREAM


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'outdir',
        type=str,
        help='Top-level directory to store files',
    )
    parser.add_argument(
        '--loglevel',
        type=int,
        help='Set logging level',
        default=logging.WARNING,
    )

    args = parser.parse_args()
    STREAM.setLevel(args.loglevel)

    ripcd.main(args.outdir)
