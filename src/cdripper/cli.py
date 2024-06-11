import argparse
from cdripper.ripcd import Watchdog


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'outdir',
        type=str,
        help='Top-level directory to store files',
    )

    args = parser.parse_args()

    inst = Watchdog(args.outdir)
    inst.start()
