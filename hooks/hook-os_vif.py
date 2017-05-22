from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import copy_metadata

datas = copy_metadata('os_vif')
datas += collect_data_files('os_vif')
hiddenimports = collect_submodules('os_vif.objects')
