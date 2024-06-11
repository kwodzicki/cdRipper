import logging
from importlib.metadata import metadata

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
log.addHandler(logging.StreamHandler())
log.handlers[0].setLevel(logging.DEBUG)

meta = metadata(__name__)
__version__ = meta.json['version']
__url__ = meta.json['project_url'][0].split(',')[1].strip()

del meta
