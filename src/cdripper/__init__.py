import logging
from importlib.metadata import metadata

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.DEBUG)

STREAM = logging.StreamHandler()
STREAM.setLevel(logging.WARNING)
STREAM.setFormatter(
    logging.Formatter(
        '%(asctime)s [%(levelname).4s] %(message)s'
    )
)
LOG.addHandler(STREAM)

meta = metadata(__name__)
__version__ = meta.json['version']
__url__ = meta.json['project_url'][0].split(',')[1].strip()

del meta
