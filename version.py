"""
Single source of truth for the version number.

build_installer.ps1 reads it to stamp the installer and portable zip, and passes
it to installer.iss as /DAppVersion. Its own module, not a constant in config.py,
so packaging can read it without importing numpy and pywin32.
"""

__version__ = "0.1.0"
