import argparse
from cdripper import ripcd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'outdir',
        type=str,
        help='Top-level directory to store files',
    )

    args = parser.parse_args()

    ripcd.main(args.outdir)
