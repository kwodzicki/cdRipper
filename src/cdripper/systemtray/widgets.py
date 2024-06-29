import logging
import os

from PyQt5.QtWidgets import (
    QFileDialog,
    QWidget,
    QDialog,
    QDialogButtonBox,
    QRadioButton,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
)

from .. import NAME
from .utils import load_settings, save_settings


class MissingOutdirDialog(QDialog):
    def __init__(self, outdir, name=NAME):
        super().__init__()

        self._name = name
        self.setWindowTitle(f"{self._name}: Output Directory Missing!")

        QBtn = QDialogButtonBox.Ok | QDialogButtonBox.Abort

        self.buttonBox = QDialogButtonBox(QBtn)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

        self.layout = QVBoxLayout()
        message = (
            "Could not find the requested output directory: ",
            os.linesep,
            outdir,
            os.linesep,
            "Would you like to select a new one?",
        )
        message = QLabel(
            os.linesep.join(message)
        )
        self.layout.addWidget(message)
        self.layout.addWidget(self.buttonBox)
        self.setLayout(self.layout)


class SettingsWidget(QDialog):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.outdir = PathSelector('Output Location:')

        self.set_settings()

        buttons = QDialogButtonBox.Save | QDialogButtonBox.Cancel
        button_box = QDialogButtonBox(buttons)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(self.outdir)
        layout.addWidget(button_box)
        self.setLayout(layout)

    def set_settings(self):

        settings = load_settings()
        if 'outdir' in settings:
            self.outdir.setText(settings['outdir'])

    def get_settings(self):

        settings = {
            'outdir': self.outdir.getText(),
        }
        save_settings(settings)
        return settings


class PathSelector(QWidget):

    def __init__(self, label, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.__log = logging.getLogger(__name__)
        self.path = None

        self.path_text = QLineEdit()
        self.path_button = QPushButton('Select Path')
        self.path_button.clicked.connect(self.path_select)

        layout = QHBoxLayout()
        layout.addWidget(self.path_text)
        layout.addWidget(self.path_button)
        widget = QWidget()
        widget.setLayout(layout)

        layout = QVBoxLayout()
        layout.addWidget(QLabel(label))
        layout.addWidget(widget)

        self.setLayout(layout)

    def setText(self, var):

        self.path_text.setText(var)

    def getText(self):

        return self.path_text.text()

    def path_select(self, *args, **kwargs):

        path = QFileDialog.getExistingDirectory(self, 'Select Folder')
        if path != '' and os.path.isdir(path):
            self.setText(path)
            self.__log.info(path)
