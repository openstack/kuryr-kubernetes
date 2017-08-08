Watching Kubernetes api-server over HTTPS
=========================================

Add absolute path of client side cert file and key file for Kubernetes server
in ``kuryr.conf``::

    [kubernetes]
    api_root = https://your_server_address:server_ssl_port
    ssl_client_crt_file = <absolute file path eg. /etc/kubernetes/admin.crt>
    ssl_client_key_file = <absolute file path eg. /etc/kubernetes/admin.key>

If server ssl certification verification is also to be enabled, add absolute
path to the ca cert::

    [kubernetes]
    ssl_ca_crt_file = <absolute file path eg. /etc/kubernetes/ca.crt>
    ssl_verify_server_crt = True

If want to query HTTPS Kubernetes api server with ``--insecure`` mode::

    [kubernetes]
    ssl_verify_server_crt = False

