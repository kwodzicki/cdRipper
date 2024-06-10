import logging
import signal
import os, tempfile, time, hashlib
from subprocess import Popen, DEVNULL, STDOUT
from datetime import datetime
from threading import Thread, Event

import pyudev

from .getMetaData import CDMetaData

meta = CDMetaData()


KEY = 'DEVNAME'
CHANGE = 'DISK_MEDIA_CHANGE'
STATUS = "ID_CDROM_MEDIA_STATE"  # This appears on DVD/Blu-ray mount
DISC = "ID_CDROM"
EJECT = "DISK_EJECT_REQUEST"  # This appears when initial eject requested
READY = "SYSTEMD_READY"  # This appears when disc tray is out

SIZE_POLL = 10

RUNNING = Event()

signal.signal(signal.SIGINT, lambda *args: RUNNING.set())
signal.signal(signal.SIGTERM, lambda *args: RUNNING.set())


class Watchdog(Thread):

    def __init__(self, outdir):
        super().__init__()

        self.log = logging.getLogger(__name__)
        self._mounted = {}
        self.outdir = outdir
        self.context = pyudev.Context()
        self.monitor = pyudev.Monitor.from_netlink(self.context)
        self.monitor.filter_by(subsystem='block')

    def run(self):
        """
        Processing for thread

        Polls udev for device changes, running MakeMKV pipelines
        when dvd/bluray found

        """

        self.log.info('Watchdog thread started')
        while not RUNNING.is_set():
            device = self.monitor.poll(timeout=1.0)
            if device is None:
                continue

            # Get value for KEY. If is None, then did not exist, so continue
            dev = device.properties.get(KEY, None)
            if dev is None:
                continue

            if device.properties.get(EJECT, ''):
                self.log.debug("Eject request: %s", dev)
                thread = self._mounted.pop(dev, None)
                if thread is not None and thread.is_alive():
                    self.log.warning("Ripper thread still alive!")
                continue

            if device.properties.get(READY, '') == '0':
                self.log.debug("Drive is ejected: %s", dev)
                continue

            # If we did NOT change an insert/eject event
            if device.properties.get(CHANGE, None):
                # The STATUS key does not seem to exist for CD
                if device.properties.get(STATUS, '') != '':
                    msg = (
                        'Caught event that was NOT insert/eject, '
                        'ignoring : %s'
                    )
                    self.log.debug(msg, dev)
                    continue

                if dev in self._mounted:
                    self.log.info('Device in mounted list: %s', dev) 
                    continue

                self.log.debug('Finished mounting : %s', dev)
                thread = Thread(
                    target=main,
                    args=(self.outdir,),
                    kwargs={'dev': dev},
                )
                thread.start()
                self._mounted[dev] = thread
                continue

            # If dev is NOT in mounted, initialize to False
            if dev not in self._mounted:
                self.log.info('Odd event : %s', dev)
                continue


def main(outDirBase, dev=None):
    """
    Rip CD, convert to FLAC, and tag all files using metadata from MusicBrainz

    Arguments:
      outDirBase (str): Top-level directory to store FLAC files in. Files will be
        placed in directory with structure: Artist/Album/Tracks.flac

    Keyword arguments:
      None.

    Returns:
      bool

    """

    log = logging.getLogger(__name__)

    tmpDir = os.path.join(tempfile.gettempdir(), randomHash())
    os.makedirs(tmpDir, exist_ok=True)

    meta.cache = tmpDir
    tracks = meta.getMetaData()
    if not tracks:
        return False

    outDir = os.path.join(
        outDirBase,
        tracks[0]['albumartist'],
        tracks[0]['album'],
    ) 

    status = ripCD(tmpDir, dev=dev)
    if status:
      status = convert2FLAC(tmpDir, outDir, tracks)
    
    cleanUp(tmpDir)

    log.debug('Ejecting disc')
    cmd = ['eject']
    if dev is not None:
        cmd.append(dev)

    Popen(cmd)

    return status 


def ripCD(outDir, dev=None):
    """
    Rip CD to a temporary directory

    Arguments:
        outDir (str): Top-level directory to rip CD files to.

    Keyword arguments:
      None.

    Returns:
      bool

    """

    log = logging.getLogger(__name__)

    log.info('Starting CD rip')
    t0 = datetime.now()
    cmd = ['cdparanoia', '-Bw']
    if dev is not None:
        cmd.extend(['--force-cdrom-device', dev])

    log.info("Running command: %s", cmd)
    proc = Popen(
        cmd,
        cwd=outDir,
        # stdout=DEVNULL,
        # stderr=STDOUT,
    )
    log.info('Waiting for CD rip to finish')
    proc.wait()
    log.info('Rip completed in: %s', datetime.now() - t0)

    return True


def convert2FLAC(srcDir, outDir, tracks):
    """
    Convert wav files ripped from CD to FLAC

    Arguments:
      srcDir (str): Top-level directory of ripped CD files.
      outDir (str): Top-level directory to store FLAC files in. Files will be
        placed in directory with structure: Artist/Album/Tracks.flac
      tracks (list): Dictionaries containing information for each track of the CD

    Keyword arguments:
      None.

    Returns:
      bool

    """

    log = logging.getLogger(__name__)

    log.info('Converting files to FLAC and placing in: %s', outDir)
    os.makedirs(outDir, exist_ok=True)

    coverart = None
    # Zip the list of tracks and list of files in directory; iterate over them
    for info, inFile in zip(tracks, listDir(srcDir)):
        cmd = ['flac']                                                                          # Base command for conversion
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
        outFile = os.path.join(outDir, outFile)

        # Append output-name option to flac command
        cmd.append(f'--output-name={outFile}')

        # Append input file to command 
        cmd.append(inFile)

        proc = Popen(cmd, stdout=DEVNULL, stderr=STDOUT)
        proc.wait()

    if coverart is not None:
        log.info("Moving coverart")
        os.rename(
            coverart,
            os.path.join(outDir, os.path.basename(coverart)),
        )

    return True


def randomHash():
    """Generate random hash for temporary directory"""

    return hashlib.md5(
        str(time.time()).encode()
    ).hexdigest() 


def listDir(directory):
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
    return sorted( files )


def cleanUp(directory: str):
  """Recursively delete directory"""

  for root, dirs, items in os.walk(directory):
        for item in items:
            path = os.path.join(root, item)
            if os.path.isfile(path):
                os.remove(path)
        os.rmdir(root)

