import logging
import os
import re
import tempfile
import time
import hashlib
from subprocess import Popen, DEVNULL, PIPE, STDOUT

TRACK_NUM = r"track(\d+)"
CURRENT = rb"outputting to " + TRACK_NUM.encode()
PROGRESS = rb"== PROGRESS == \[([^\|]*)\|"


def cdparanoia(dev, outdir):
    """
    Rip CD to a temporary directory

    Arguments:
        outdir (str): Top-level directory to rip CD files to.

    Keyword arguments:
        None.

    Returns:
        bool

    """

    log = logging.getLogger(__name__)

    log.info("%s - Starting CD rip", dev)

    cmd = [
        'cdparanoia',
        '--batch',
        '--output-wav',
        '--stderr-progress',
        '--force-progress-bar',
        '--force-cdrom-device',
        dev,
    ]

    log.info("%s - Running command: %s", dev, cmd)

    return Popen(
        cmd,
        cwd=outdir,
        stdout=PIPE,
        stderr=STDOUT,
    )


def convert2FLAC(
    dev: str,
    srcdir: str,
    outdir: str,
    tracks: dict,
    media_label: bool = False,
) -> bool:
    """
    Convert wav files ripped from CD to FLAC

    Arguments:
        srcdir (str): Top-level directory of ripped CD files.
        outdir (str): Top-level directory to store FLAC files in. Files will
            be placed in directory with structure: Artist/Album/Tracks.flac
        tracks (dict): Dictionaries containing information for each track
            of the CD

    Keyword arguments:
        None.

    Returns:
        bool

    """

    log = logging.getLogger(__name__)

    log.info(
        "%s - Converting files to FLAC and placing in: %s",
        dev,
        outdir,
    )
    os.makedirs(outdir, exist_ok=True)

    coverart = None
    # Zip the list of tracks and list of files in directory; iterate over them
    for track_num, infile in listdir(srcdir):
        info = tracks.get(track_num, None)
        if info is None:
            log.error(
                "Failed to get track info for track # %s; skipping it",
                track_num,
            )
            os.remove(infile)
            continue

        cmd = ['flac']  # Base command for conversion
        # If cover art info, append picture option to flac command
        if 'cover-art' in info:
            coverart = info.pop('cover-art')
            cmd.append(f'--picture={coverart}')

        # Iterate over key/value pairs in info, append tag option to command
        for key, val in info.items():
            if key == 'short_title':
                continue
            cmd.append(f'--tag={key}={val}')

        # Set basename for flac fil,e
        outfile = '{:02d} - {}.flac'.format(
            info['tracknumber'],
            info['short_title'],
        )

        # If more than one disc in the release, prepend disc number
        totaldiscs = info.get('totaldiscs', 1)
        if totaldiscs > 1:
            discnum = info.get('discnumber', 1)
            outfile = f"{discnum:d}-{outfile}"

        # Replace path seperator with under score
        outfile = outfile.replace(os.sep, '_')

        # Generate full file path
        outfile = os.path.join(outdir, outfile)

        # Append output-name option to flac command
        cmd.append(f'--output-name={outfile}')

        # Append input file to command
        cmd.append(infile)

        log.debug("Running 'flac' command: %s", cmd)
        proc = Popen(cmd, stdout=DEVNULL, stderr=STDOUT)
        proc.wait()

        if not os.path.isfile(outfile):
            log.error("Failed to create file: %s", outfile)

    if coverart is not None:
        fname = os.path.basename(coverart)
        if totaldiscs > 1:
            fname = f"{discnum:d}-{fname}"
        dst = os.path.join(outdir, fname)
        log.info("%s - Moving coverart: %s --> %s", dev, coverart, dst)
        os.rename(
            coverart,
            dst,
        )

    return True


def cdparanoia_progress(dev, proc, progress):
    """
    Arguments:
        dev (str): Dev device to rip from
        proc (Popen): Popen instances to read from stdout
        progress (QDialog): A progress dialog object.

    """

    prog = 0
    current = None

    while proc.poll() is None:
        line = proc.stdout.readline().strip()

        while line != b'' and proc.poll() is None:
            search = re.search(CURRENT, line)
            if search is not None:
                current = str(int(search.group(1)))
                progress.CD_CUR_TRACK.emit(dev, current)
                break

            pos_size = parse_progress_line(line)
            if pos_size is None:
                break

            pos, size = pos_size
            if pos != prog:
                prog = pos
                progress.CD_TRACK_SIZE.emit(
                    dev,
                    round(pos / size * 100)
                )

            line = proc.stdout.readline().strip()

    progress.CD_TRACK_SIZE.emit(dev, 100)
    progress.CD_REMOVE_DISC.emit(dev)


def parse_progress_line(line):

    _match = re.search(PROGRESS, line)
    if _match is None:
        return None

    _match = _match.group(1)
    prog = re.search(rb'\S', _match)
    if prog is None:
        return None

    return prog.start(), len(_match)


def gen_tmpdir(dev):
    """
    Generate temporary directory for raw output

    """

    _hash = hashlib.md5(
        f"{time.time()}{dev}".encode()
    ).hexdigest()

    tmpdir = os.path.join(
        tempfile.gettempdir(),
        _hash,
    )
    os.makedirs(tmpdir, exist_ok=True)

    return tmpdir


def listdir(directory, ext: str = '.wav') -> tuple[str]:
    """
    Get sorted list of all files with '.wav' extension in a directory

    Arguments:
        directory (str): Top-level path of directory to search for .wav files

    Keyword arguments:
      None.

    Returns:
      tuple[str]: Full file paths to all .wav files in directory

    """

    for item in os.listdir(directory):
        if not item.endswith(ext):
            continue

        obj = re.search(TRACK_NUM, item)
        if obj is None:
            continue

        track_num = str(int(obj.group(1)))
        yield track_num, os.path.join(directory, item)


def cleanup(directory: str):
    """Recursively delete directory"""

    for root, dirs, items in os.walk(directory):
        for item in items:
            path = os.path.join(root, item)
            if os.path.isfile(path):
                os.remove(path)
        os.rmdir(root)
