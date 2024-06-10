# cdRipper

This utility is designed to make ripping and tagging audio CDs as simple as possible. Simply insert your CD and run the `cdRipper` command. The program will identify the CD using the MusicBrainz database, rip the tracks and convert them to FLAC files, and then tag them using the metadata from MusicBrainz.

Files are organized into the following structure
    Artist/
    Artist/Album
    Artist/Album/01-Track 1.flac
    Artist/Album/02-Track 2.flac

## Installation

To install, run the following command

    pip3 install git+https://github.com/kwodzicki/cdRipper

### Required CLIs

For this program to actually work, you need to install the following dependencies. 

  - [libdiscid](https://musicbrainz.org/doc/libdiscid) : Used to generate disc ID for MusicBrainz lookup
  - [cdparanoia](https://xiph.org/paranoia/) : Used to rip audio files from CD
  - [flac](https://xiph.org/flac/) : Used to convert audio to FLAC and tag files

You can use the following command to install them on Ubuntu:

    sudo apt install libdiscid-dev cdparanoia flac



