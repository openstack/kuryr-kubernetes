FROM centos:7
LABEL authors="Antoni Segura Puimedon<toni@kuryr.org>, Vikas Choudhary<vichoudh@redhat.com>"

COPY . /opt/kuryr-kubernetes

RUN yum install -y epel-release https://rdoproject.org/repos/rdo-release.rpm \
    && yum install -y --setopt=tsflags=nodocs python-pip iproute bridge-utils openvswitch \
    && yum install -y --setopt=tsflags=nodocs gcc python-devel git \
    && cd /opt/kuryr-kubernetes \
    && pip install --no-cache-dir . \
    && rm -fr .git \
    && yum -y history undo last

COPY kuryr-cni /kuryr-cni
COPY kuryr-cni-bin /kuryr-cni-bin
COPY cni_ds_init /usr/bin/cni_ds_init

ARG CNI_CONFIG_DIR_PATH=/etc/cni/net.d
ENV CNI_CONFIG_DIR_PATH ${CNI_CONFIG_DIR_PATH}
ARG CNI_BIN_DIR_PATH=/opt/cni/bin
ENV CNI_BIN_DIR_PATH ${CNI_BIN_DIR_PATH}
ARG CNI_DAEMON=False
ENV CNI_DAEMON ${CNI_DAEMON}

VOLUME [ "/sys/fs/cgroup" ]
ENTRYPOINT [ "cni_ds_init" ]
