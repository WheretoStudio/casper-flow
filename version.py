"""
The version number, in one place.

It used to be written by hand in build_installer.ps1, again in installer.iss, and
again in the website constants, which is three chances for a release to disagree
with itself about what it is. Everything now reads it from here:

  build_installer.ps1  imports this to stamp the installer and the portable zip
  installer.iss        receives it as /DAppVersion from that script
  main.py --version    prints it, which is also the frozen build's smoke test
  website              the build script prints the value to paste into constants.ts

A separate module rather than a constant in config.py so that packaging can read
it without importing the application, which would pull in numpy and pywin32.
"""

__version__ = "0.1.0"
