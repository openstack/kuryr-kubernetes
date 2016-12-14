def register_locally_defined_vifs():
    __import__('kuryr_kubernetes.objects.vif')
