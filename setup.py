#!/usr/bin/env python
import setuptools
from distutils.util import convert_path

main_ns  = {}
ver_path = convert_path("cdRipper/version.py")
with open(ver_path) as ver_file:
  exec(ver_file.read(), main_ns)

setuptools.setup(
  name             = "cdRipper",
  description      = "Package to automatically rip and tag cds when inserted", 
  url              = main_ns['__url__'],
  author           = "Kyle R. Wodzicki",
  author_email     = "krwodzicki@gmail.com",
  version          = main_ns['__version__'],
  packages         = setuptools.find_packages(),
  install_requires = [ "discid", "musicbrainzngs"],
  scripts          = ['bin/cdRipper'],
  zip_safe         = False
)
