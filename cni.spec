# -*- mode: python -*-

block_cipher = None

a = Analysis(['/usr/local/bin/kuryr-cni'],
             pathex=['/usr/local/lib/python3.5/site-packages', '/usr/local/lib/python3.5/site-packages/eventlet/support'],
             binaries=[],
             datas=[],
             hiddenimports=['backports.ssl_match_hostname', 'setuptools', 'kuryr_kubernetes.objects.vif', 'kuryr_kubernetes.os_vif_plug_noop', 'dns', 'vif_plug_ovs', 'vif_plug_linux_bridge', 'oslo_privsep'],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          name='kuryr-cni',
          debug=False,
          strip=False,
          upx=True,
          console=True )

