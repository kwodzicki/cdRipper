import logging
import signal
import os
import tempfile
import time
import hashlib
from subprocess import Popen, DEVNULL, STDOUT
from datetime import datetime
from threading import Thread, Event

import pyudev

from .metadata import CDMetaData

KEY = 'DEVNAME'
CHANGE = 'DISK_MEDIA_CHANGE'
STATUS = "ID_CDROM_MEDIA_STATE"  # This appears on DVD/Blu-ray mount
EJECT = "DISK_EJECT_REQUEST"  # This appears when initial eject requested
READY = "SYSTEMD_READY"  # This appears when disc tray is out

SIZE_POLL = 10

RUNNING = Event()

signal.signal(signal.SIGINT, lambda *args: RUNNING.set())
signal.signal(signal.SIGTERM, lambda *args: RUNNING.set())


def main(outdir):
    """
    Monitor udev

    Polls udev for device changes, running MakeMKV pipelines
    when dvd/bluray found

    """

    log = logging.getLogger(__name__)

    mounted = {}
    outdir = outdir
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem='block')

    log.info('Watchdog thread started')
    while not RUNNING.is_set():
        device = monitor.poll(timeout=1.0)
        if device is None:
            continue

        # Get value for KEY. If is None, then did not exist, so continue
        dev = device.properties.get(KEY, None)
        if dev is None:
            continue

        if device.properties.get(EJECT, ''):
            log.debug("%s - Eject request", dev)
            thread = mounted.pop(dev, None)
            if thread is not None and thread.is_alive():
                log.warning("%s - Ripper thread still alive!", dev)
            continue

        if device.properties.get(READY, '') == '0':
            log.debug("%s - Drive is ejected", dev)
            thread = mounted.pop(dev, None)
            if thread is not None and thread.is_alive():
                log.warning("%s - Ripper thread still alive!", dev)
            continue

        if device.properties.get(CHANGE, '') != '1':
            log.debug("%s - Not a '%s' event, ignoring", dev, CHANGE)
            continue

        # The STATUS key does not seem to exist for CD
        if device.properties.get(STATUS, '') != '':
            log.debug(
                '%s - Caught event that was NOT insert/eject, ignoring',
                dev,
            )
            continue

        if dev in mounted:
            log.info('%s - Device in mounted list', dev)
            continue

        log.debug('%s - Finished mounting', dev)
        thread = RipDisc(outdir, dev)
        thread.start()
        mounted[dev] = thread


class RipDisc(Thread):
    """
    Rip CD, convert to FLAC, tag with MusicBrainz

    """

    def __init__(self, outdir, dev, **kwargs):
        """
        Arguments:
            outDirBase (str): Top-level directory to store FLAC files in. Files
                will be placed in directory with structure:
                    Artist/Album/Tracks.flac

        Keyword arguments:
            None.

        Returns:
            bool

        """

        super().__init__()

        self.log = logging.getLogger(__name__)
        self.outdir = outdir
        self.dev = dev
        self.kwargs = kwargs
        self.status = None
        self.meta = None

    def run(self):

        tmpdir = os.path.join(
            tempfile.gettempdir(),
            randomHash(),
        )
        os.makedirs(tmpdir, exist_ok=True)

        # Set kwargs for CDMetaData; ovveride cache with locally defined
        kwargs = {
            **self.kwargs,
            'cache': tmpdir,
        }
        self.meta = CDMetaData(self.dev, **kwargs)

        tracks = self.meta.getMetaData()
        if not tracks:
            self.status = False
            return

        outdir = os.path.join(
            self.outdir,
            tracks[0]['albumartist'],
            tracks[0]['album'],
        )

        self.status = ripcd(tmpdir, dev=self.dev)
        if self.status:
            self.status = convert2FLAC(self.dev, tmpdir, outdir, tracks)

        cleanup(tmpdir)

        self.log.debug("%s - Ejecting disc", self.dev)
        cmd = ['eject']
        if self.dev is not None:
            cmd.append(self.dev)

        proc = Popen(cmd)
        proc.wait()


def ripcd(outdir, dev=None):
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
    t0 = datetime.now()
    cmd = ['cdparanoia', '-Bw']
    if dev is not None:
        cmd.extend(['--force-cdrom-device', dev])

    log.info("%s - Running command: %s", dev, cmd)
    proc = Popen(
        cmd,
        cwd=outdir,
        stdout=DEVNULL,
        stderr=STDOUT,
    )
    log.info("%s - Waiting for CD rip to finish", dev)
    proc.wait()
    log.info("%s - Rip completed in: %s", dev, datetime.now() - t0)

    return True


def convert2FLAC(dev, srcdir, outdir, tracks):
    """
    Convert wav files ripped from CD to FLAC

    Arguments:
        srcdir (str): Top-level directory of ripped CD files.
        outdir (str): Top-level directory to store FLAC files in. Files will
            be placed in directory with structure: Artist/Album/Tracks.flac
        tracks (list): Dictionaries containing information for each track
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
    for info, inFile in zip(tracks, listdir(srcdir)):
        cmd = ['flac']  # Base command for conversion
        # If cover art info, append picture option to flac command
        if 'cover-art' in info:
            coverart = info.pop('cover-art')
            cmd.append(f'--picture={coverart}')

        # Iterate over key/value pairs in info, append tag option to command
        for key, val in info.items():
            cmd.append(f'--tag={key}={val}')

        # Set basename for flac fil,e
        outFile = '{:02d} - {}.flac'.format(
            info['tracknumber'],
            info['title'],
        )

        # If more than one disc in the release, prepend disc number
        if info['totaldiscs'] > 1:
            outFile = '{:d}-{}'.format(info['discnumber'], outFile)

        # Generate full file path
        outFile = os.path.join(outdir, outFile)

        # Append output-name option to flac command
        cmd.append(f'--output-name={outFile}')

        # Append input file to command
        cmd.append(inFile)

        proc = Popen(cmd, stdout=DEVNULL, stderr=STDOUT)
        proc.wait()

    if coverart is not None:
        log.info("%s - Moving coverart", dev)
        os.rename(
            coverart,
            os.path.join(outdir, os.path.basename(coverart)),
        )

    return True


def randomHash():
    """Generate random hash for temporary directory"""

    return hashlib.md5(
        str(time.time()).encode()
    ).hexdigest()


def listdir(directory):
    """
    Get sorted list of all files with '.wav' extension in a directory

    Arguments:
        directory (str): Top-level path of directory to search for .wav files

    Keyword arguments:
      None.

    Returns:
      list: Full file paths to all .wav files in directory

    """

    files = []
    for item in os.listdir(directory):
        path = os.path.join(directory, item)
        if os.path.isfile(path) and path.endswith('.wav'):
            files.append(path)
    return sorted(files)


def cleanup(directory: str):
    """Recursively delete directory"""

    for root, dirs, items in os.walk(directory):
        for item in items:
            path = os.path.join(root, item)
            if os.path.isfile(path):
                os.remove(path)
        os.rmdir(root)
