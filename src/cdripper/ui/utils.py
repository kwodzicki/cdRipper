import logging
import os
import sys
import json

if sys.platform.startswith('win'):
    import wmi
    import pythoncom

from .. import HOMEDIR, SETTINGS_FILE


def load_settings() -> dict:
    """
    Load dict from data JSON file

    Returns:
        dict: Settings data loaded from JSON file

    """

    if not os.path.isfile(SETTINGS_FILE):
        settings = {
            'outdir': os.path.join(HOMEDIR, 'Music'),
        }
        save_settings(settings)
        return settings

    logging.getLogger(__name__).debug(
        'Loading settings from %s', SETTINGS_FILE,
    )
    with open(SETTINGS_FILE, 'r') as fid:
        return json.load(fid)


def save_settings(settings: dict) -> None:
    """
    Save dict to JSON file

    Arguments:
        settings (dict): Settings to save to JSON file

    """

    logging.getLogger(__name__).debug(
        'Saving settings to %s', SETTINGS_FILE,
    )
    with open(SETTINGS_FILE, 'w') as fid:
        json.dump(settings, fid)


def get_vendor_model(path: str) -> tuple[str]:

    vendor = model = ''
    if sys.platform.startswith('linux'):
        vendor, model = linux_vendor_model(path)
    elif sys.platform.startswith('win'):
        pythoncom.CoInitialize()
        try:
            vendor, model = windows_vendor_model(path)
        except Exception:
            pass
        finally:
            pythoncom.CoUninitialize()
    return vendor, model


def linux_vendor_model(path: str) -> tuple[str]:
    """
    Get the vendor and model of drive

    """

    path = os.path.join(
        '/sys/class/block/',
        os.path.basename(path),
        'device',
    )

    vendor = os.path.join(path, 'vendor')
    if os.path.isfile(vendor):
        with open(vendor, mode='r') as iid:
            vendor = iid.read()
    else:
        vendor = ''

    model = os.path.join(path, 'model')
    if os.path.isfile(model):
        with open(model, mode='r') as iid:
            model = iid.read()
    else:
        model = ''

    return vendor.strip(), model.strip()


def windows_vendor_model(path: str) -> tuple[str]:

    c = wmi.WMI()
    for cd in c.Win32_CDROMDrive():
        if cd.Drive != path:
            continue
        return cd.Name, ''

    return '', ''
