FROM centos:7
LABEL authors="Antoni Segura Puimedon<toni@kuryr.org>, Vikas Choudhary<vichoudh@redhat.com>"

COPY . /opt/kuryr-kubernetes

COPY kuryr-cni /kuryr-cni
COPY kuryr-cni-bin /kuryr-cni-bin
COPY cni_ds_init /usr/bin/cni_ds_init

ENV CNI_CONFIG_DIR_PATH /etc/cni/net.d
ENV CNI_BIN_DIR_PATH /opt/cni/bin
VOLUME [ "/sys/fs/cgroup" ]
ENTRYPOINT [ "cni_ds_init" ]
