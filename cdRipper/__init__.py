import logging
log = logging.getLogger(__name__)
log.setLevel( logging.DEBUG )
log.addHandler( logging.StreamHandler() )
log.handlers[0].setLevel( logging.DEBUG )
