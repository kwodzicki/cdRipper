"""
Utilities for ripping titles

"""

import logging
import os
from PyQt5 import QtCore

from . import utils
from . import metadata
from .ui import dialogs


class DiscHandler(QtCore.QObject):
    """
    Handle new disc event

    """

    FINISHED = QtCore.pyqtSignal()
    EJECT_DISC = QtCore.pyqtSignal()

    DISC_LOOKUP = QtCore.pyqtSignal(str)
    SELECT_RELEASE = QtCore.pyqtSignal(str)
    SUBMIT_DISCID = QtCore.pyqtSignal(str, bool)

    def __init__(self, dev: str, progress, outdir: str | None = None):
        super().__init__()
        self.log = logging.getLogger(__name__)
        self.DISC_LOOKUP.connect(self.disc_lookup)
        self.SELECT_RELEASE.connect(self.select_release)
        self.SUBMIT_DISCID.connect(self.submit_discid)

        self.dev = dev
        self.outdir = outdir
        self.progress = progress
        self.progress.CANCEL.connect(self.cancel)

        self.metadata = None
        self.selector = None
        self.submitter = None
        self.ripper = None

        self.DISC_LOOKUP.emit(self.dev)

    def isRunning(self):
        """
        Check if is Running:

        """

        # If ripper not yet defined, still going through motions
        # i.e., running
        if self.ripper is None:
            return True

        # Else, return status of the ripper
        return self.ripper.isRunning()

    @QtCore.pyqtSlot(str)
    def cancel(self, dev: str) -> None:
        """
        Kill/close all objects

        """

        if dev != self.dev:
            return

        if self.metadata is not None:
            self.metadata = None
        if self.selector is not None:
            self.selector.close()
            self.selector = None
        if self.submitter is not None:
            self.submitter.close()
            self.submitter = None
        if self.ripper is not None:
            self.ripper.CANCEL.emit(self.dev)

    @QtCore.pyqtSlot(str, bool)
    def submit_discid(self, dev: str, force: bool = False):
        """
        Submit a discid to musicbrainz

        The disc_lookup() method is connected to the dialog so that when
        closes, method is called.

        Arguments:
            dev (str): Dev device discid was run on

        """

        if dev != self.dev:
            return

        if self.metadata is None:
            self.log.info("%s - Metadata not yet defined", dev)
            return

        self.submitter = dialogs.SubmitDisc(dev, self.metadata.submission_url)
        self.submitter.FINISHED.connect(self.disc_lookup)
        # If force, then trigger submit method
        if force:
            self.submitter.submit()

    @QtCore.pyqtSlot(str)
    def select_release(self, dev: str) -> None:
        """
        Dialog to select release for disc

        If releases found, then open a dialog that contains a table of all
        releases with matching disc ID so that user can select which one is
        correct.

        The rip_disc() method is connected to the dialog so that when closes,
        method is called.

        Arguments:
            dev (str): Device dics is mount in

        """

        if dev != self.dev:
            return

        if self.metadata is None:
            self.log.info("%s - Metadata not yet defined", dev)
            return

        self.selector = dialogs.SelectDisc(
            dev,
            self.metadata.result,
        )
        self.selector.FINISHED.connect(self.rip_disc)

    @QtCore.pyqtSlot(str)
    def disc_lookup(self, dev: str):
        """
        Used to compute and search disc ID

        Launch a QThread that will scan dev device to compute the disc ID.
        Then, use this disc ID to search for matching releases in the
        MusicBrainz database.

        We connect the process_search() to the thread so that is called when
        thread completes.

        """

        # If empty dev device name, then we are ignorning
        if dev == '':
            self.FINISHED.emit()
            return

        if dev != self.dev:
            return

        self.metadata = metadata.CDMetaThread(dev)
        self.metadata.FINISHED.connect(self.process_search)
        self.metadata.start()

    @QtCore.pyqtSlot(str)
    def process_search(self, dev: str) -> None:
        """
        Process result of disc ID search

        This method is meant to be called after a CDMetaThread thread finishes
        scanning and search MusicBrainz. The results of that search are
        processed here, calling the necessary function to either submit the
        disc ID to MusicBrainz or to attempt a rip.

        Arguments:
            dev (str): The dev device that was used to compute disc ID.

        """

        # Check for errors in search
        error = ''
        if dev.startswith('ERROR'):
            error, dev = dev.split('-')

        # If dev does not match dev of class; dump out
        if dev != self.dev:
            self.FINISHED.emit()
            return

        # If there was an error; eject the drive
        if error:
            self.EJECT_DISC.emit()
            self.FINISHED.emit()
            return

        self.log.info("%s - Running select release", dev)
        if self.metadata is None:
            self.FINISHED.emit()
            return

        if self.metadata.result is None:
            self.log.info("%s - No metadata found for disc", dev)
            self.FINISHED.emit()
            return

        if isinstance(self.metadata.result, str):
            self.SUBMIT_DISCID.emit(dev, False)
            return

        self.SELECT_RELEASE.emit(dev)

    @QtCore.pyqtSlot(str, int, bool, dict)
    def rip_disc(
        self,
        dev: str,
        result: int,
        media_label: bool,
        release: dict,
    ) -> None:
        """
        Attempt disc rip

        Given the /dev path to a disc, load information from database if
        it exists or open GUI for user to input information

        Arguments:
            dev (str) : Device to rip from

        """

        if dev != self.dev:
            return

        if result == dialogs.IGNORE:
            return

        if result == dialogs.SUBMIT:
            self.SUBMIT_DISCID.emit(dev, self.metadata.result)
            return

        if self.metadata is None:
            return

        self.ripper = Ripper(
            dev,
            self.metadata,
            release,
            self.outdir,
            self.progress,
            media_label=media_label,
        )
        self.ripper.FINISHED.connect(self.FINISHED.emit)
        self.ripper.EJECT_DISC.connect(self.EJECT_DISC.emit)
        self.ripper.start()


class Ripper(QtCore.QThread):

    CANCEL = QtCore.pyqtSignal(str)
    FINISHED = QtCore.pyqtSignal()
    EJECT_DISC = QtCore.pyqtSignal()

    def __init__(
        self,
        dev: str,
        metadata: metadata.CDMetaThread,
        release: dict,
        outdir: str,
        progress,
        media_label: bool = False,
    ):
        """
        Arguments:
            dev (str): Dev device to rip from
            tracks (list[dict]): List of dictionaries containing informaiton
                about each track
            tmpdir (str): Temporary directory to rip files to
            outdir (str): Directory to put tagged FLAC files in

        Keyword Arguments:
            media_label (bool): If set, use the media label over the title
                of the album. Can be useful for multidisc collections
        """

        super().__init__()
        self.log = logging.getLogger(__name__)

        self._dead = False
        self.proc = None
        self.dev = dev
        self.metadata = metadata
        self.release = release
        self.tmpdir = metadata.tmpdir
        self.outdir = outdir
        self.media_label = media_label
        self.progress = progress

        self.progress.CANCEL.connect(self.cancel)

    def run(self):
        """
        Process run in separate thread

        """

        self.progress.CD_ADD_DISC.emit(self.dev)
        self.progress.CD_GET_METADATA.emit(self.dev)

        tracks = self.metadata.parseRelease(self.release)
        self.progress.CD_SET_TRACKS_INFO.emit(self.dev, tracks)

        # Replace path seperator with under score
        album_artist = tracks['album_info'].get('albumartist', 'Unknown')
        album_title = tracks['album_info'].get('album', 'Unknown')
        if self.media_label:
            album_title = tracks['album_info'].get('album_medium', album_title)

        outdir = os.path.join(
            self.outdir,
            album_artist.replace(os.sep, '_'),
            album_title.replace(os.sep, '_'),
        )

        self.proc = utils.cdparanoia(self.dev, self.tmpdir)
        utils.cdparanoia_progress(self.dev, self.proc, self.progress)
        _ = self.proc.communicate()

        self.EJECT_DISC.emit()

        if self.proc.returncode == 0:
            self.status = utils.convert2FLAC(
                self.dev,
                self.tmpdir,
                outdir,
                tracks,
                media_label=self.media_label,
            )

        utils.cleanup(self.tmpdir)

        self.log.info("%s - Ripper thread finished", self.dev)
        self.FINISHED.emit()

    @QtCore.pyqtSlot(str)
    def cancel(self, dev: str):
        if dev != self.dev:
            return

        self._dead = True
        if self.proc is None:
            return
        self.proc.kill()
