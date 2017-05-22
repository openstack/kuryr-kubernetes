from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import copy_metadata

datas = copy_metadata('kuryr_kubernetes')
datas += collect_data_files('kuryr_kubernetes')


hiddenimports = collect_submodules('kuryr_kubernetes.cni.binding')
