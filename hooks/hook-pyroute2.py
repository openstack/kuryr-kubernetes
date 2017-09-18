from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import copy_metadata

datas = copy_metadata('pyroute2')
datas += collect_data_files('pyroute2')
hiddenimports = collect_submodules('pyroute2')
