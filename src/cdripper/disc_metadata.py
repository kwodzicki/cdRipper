"""
Disc ID scan and MusicBrainz search

"""

import logging
import os
import tempfile
from urllib.request import urlopen

try:
    import discid
except ModuleNotFoundError:
    logging.getLogger(__name__).critical(
        "Error importing 'discid', may have to set LD_LIBRARY_PATH",
    )

import musicbrainzngs as musicbrainz
from PyQt5.QtCore import QThread, pyqtSignal

from . import __version__, __url__
from . import utils

musicbrainz.set_useragent(
    __name__,
    __version__,
    __url__,
)


class CDMetaThread(QThread):
    """
    Thread for disc ID and search

    To keep the GUI alive, the scan of disc to compute the disc ID and
    searching of MusicBrainz for the disc are placed in a separate thread.

    When the thread is finished running, a custom FINISHED signal is emitted to
    signal which dev device has finshed scanning/searching for metadata

    """

    FINISHED = pyqtSignal(str)

    def __init__(self, dev, **kwargs):
        super().__init__()

        self.log = logging.getLogger(__name__)
        self.dev = dev
        self.kwargs = kwargs

        self.metadata = None
        self.tmpdir = None
        self.result = None

    def run(self):
        """
        Run scan and search in separate thread

        """

        # Generate temporary directory
        self.tmpdir = utils.gen_tmpdir(self.dev)

        self.log.info("%s - Attempting to get metadata for disc", self.dev)
        # Set up metadata object
        self.metadata = CDMetaData(
            self.dev,
            cache=self.tmpdir,
            **self.kwargs,
        )

        # Search for releases
        self.result = self.metadata.searchMusicBrainz()
        self.log.info("%s - Search finished", self.dev)

        # Emit custom finished signal
        self.FINISHED.emit(self.dev)

    def parseRelease(self, release):
        """
        Parse release information

        Wrapper to access the CDMetaData object's parseRelease() method.

        """

        return self.metadata.parseRelease(release)


class CDMetaData(discid.Disc):
    """
    Sub-class of discid.Disc that enables searching of MusicBrainz

    """

    def __init__(
        self,
        dev: str,
        features=["mnc", "isrc"],
        cache=tempfile.gettempdir(),
        **kwargs,
    ):
        super().__init__()
        self.log = logging.getLogger(__name__)
        self.dev = dev
        self.features = features
        self.cache = cache
        self.result = None

    def getMetaData(self):
        """
        Download metadata based on discid

        Arguments:
          None.

        Keyword Arguments:
          None.

        Returns:
          dict: Meta

        """

        # Run method to search MusicBrainz using discid
        self.result = self.searchMusicBrainz()

        # If releases found based on discid
        if isinstance(self.result, list):
            # Filter the releases
            release = self.filterReleases(self.result)
            # Parse releases into internal format and return
            return self.parseRelease(release)
        return None  # If made here, no releases matched, return None

    def searchMusicBrainz(
        self,
        includes: list[str] = ['artists', 'recordings', 'isrcs'],
        discid: str | None = None,
    ):
        """
        Get discid and search MusicBrainz

        Run discid compute to get the unique ID for the disc. Then try to
        search MusicBrainz for the disc. If the search fails with a response
        error, then a None object is returned. If the search fails because the
        discid is not found on MusicBrainz, then return submission URL. Else,
        return a list of releases corresponding to the disc id

        Arguments:
          None.

        Keyword arguments:
            includes (list): Attributes a release must contain to be
                considered?
            discid (str): A discid to search for on musicbrainz. Setting this
                will bypass scan of the disc drive

        Returns:
            Depends on what happens:
                None: MusicBrainz search had error
                str: Discid not found; is submission url
                list: Releases corresponding to the discid

        """

        # Read given features from the disc
        if discid is None:
            self.read(device=self.dev, features=self.features)
            discid = self.id

        self.log.debug("%s - Discid: %s", self.dev, discid)
        self.log.debug("%s - Searching for disc on musicbrainz", self.dev)
        try:
            result = (
                musicbrainz
                .musicbrainz
                .get_releases_by_discid(
                    discid,
                    includes=includes,
                )
            )
        except musicbrainz.ResponseError:
            self.log.error("%s - Disc not found or bad response", self.dev)
            return self.submission_url
            # return None

        if 'disc' not in result:
            self.log.warning("%s - No disc information returned!", self.dev)
            return self.submission_url

        # Return list of releases with matching discid
        return result['disc'].get('release-list', [])

    def getCoverArt(self, release):
        """
        Get cover art for given release

        Arguments:
          release : A release object

        Keyword arguments:
          None.

        Returns:
          Path to cover art if download success, None otherwise

        """

        try:
            imgs = musicbrainz.get_image_list(release['id'])
        except musicbrainz.ResponseError:
            self.log.warning("%s - Failed to get images", self.dev)
            return None

        for img in imgs.get('images', []):
            if img['front']:
                return self._download(img['image'])

        self.log.warning("%s - No image information returned!", self.dev)
        return None

    def parseRelease(self, release):
        """
        Parse information from release into internal format

        Arguments:
          release : Release object

        Keyword arguments:
          None.

        Returns:
          list: List of dictionaries containing track information for tagging

        """

        cover = self.getCoverArt(release)
        # Set some info that applies to all tracks
        album_info = {
            'artist': release.get('artist-credit-phrase', ''),
            'albumartist': release.get('artist-credit-phrase', ''),
            'album': release.get('title', ''),
            'totaltracks': int(
                release.get('medium-list', {}).get('track-count', '0')
            ),
            'discnumber': int(
                release.get('medium-list', {}).get('position', '1')
            ),
            'totaldiscs': int(release.get('medium-count', '1')),
            'date': release.get('date', ''),
            'asin': release.get('asin', ''),
            'musicbrainz_albumid': release.get('id', ''),
         }

        tracks = {'album_info': album_info}
        for i, track in enumerate(release['medium-list']['track-list']):
            # Per track data; include the base_info in all
            track_num = int(track.get('number', '0'))
            if track_num in tracks:
                self.log.error(
                    "Track number already exists in track info! "
                    "Returning NO metadata"
                )
                return []

            track = {
                **album_info,
                'title': track.get('recording', {}).get('title', ''),
                'tracknumber': track_num,
                'isrc': self.tracks[i].isrc,
                'discid': self.id,
                'musicbrainz_trackid': track['recording']['id'],
                'musicbrainz_releasetrackid': track['id'],
                'musicbrainz_artistid': '',
            }

            if cover:
                track['cover-art'] = cover

            tracks[track['tracknumber']] = track

        return tracks

    def filterReleases(self, releases):

        isrcMatches = []
        for release in releases:
            medium_list = release.get('medium-list', [])
            if len(medium_list) == 0:
                continue
            elif len(medium_list) > 1:
                self.log.warning(
                    "Found %d mediums in the list",
                    len(medium_list)
                )

            medium_list = self.filterMediumByFormat(medium_list)
            if len(medium_list) == 0:
                continue

            medium = self.filterMediumByISRCs(medium_list)
            if medium is None:
                continue

            release['medium-list'] = medium
            isrcMatches.append(medium['isrc-matches'])

        if len(isrcMatches) == 0:
            self.log.warning(
                "No ISRC matches found for any release! "
                "Returning first search result",
            )
            return releases[0]

        return releases[isrcMatches.index(max(isrcMatches))]

    def filterMediumByFormat(
        self,
        medium_list: list[dict],
        fmt: str = 'CD',
    ) -> list[dict]:

        return [
            medium
            for medium in medium_list
            if fmt in medium.get('format', '')
        ]

    def filterMediumByISRCs(self, medium_list: list[dict]) -> dict:
        isrcMatches = []
        # Iterate over all medium; i.e., CD, vinyl, etc.
        for medium in medium_list:
            nMatch = 0
            medium['isrc-matches'] = nMatch
            isrcMatches.append(nMatch)
            # If track counts NOT match between CD and medium, skip
            if medium['track-count'] != self.last_track_num:
                continue

            # Iterate over each track in the album get counter for disc check
            for i, track in enumerate(medium['track-list']):
                # If ISRC from track is emtpy, continue
                if self.tracks[i].isrc == '':
                    continue

                # If 'isrc-list' is NOT in recoding information, continue
                if 'isrc-list' not in track['recording']:
                    continue

                nMatch += (
                    self.tracks[i].isrc in track['recording']['isrc-list']
                )  # Increment nMatch based on disc ISRC in medium ISRC list

            medium['isrc-matches'] = nMatch
            isrcMatches[-1] = nMatch

        # Get maximum number of track matches; get index of that value in
        # array, return release with most track matches based on ISRC
        if len(isrcMatches) == 0:
            self.log.info("No ISRC matches found for mediums in release!")
            return None

        return medium_list[isrcMatches.index(max(isrcMatches))]

    def _download(self, url: str):
        """
        Download remote file to local machine given url

        Arguments:
            url (str): Full URL of remote file to download

        Keyword arguments:
            None.

        Returns:
            str: Path to local file if success, None otherwise

        """

        ext = url.split('.')[-1]
        lcl = os.path.join(self.cache, f"coverart.{ext}")
        try:
            img = urlopen(url).read()  # Open and read remote file
        except Exception:
            self.log.warning("%s - Failed to download: %s", self.dev, url)
            return None

        with open(lcl, mode='wb') as fid:
            fid.write(img)
        self.log.info("%s - Cover art downloaded to: %s", self.dev, lcl)
        return lcl  # Return path to local file
