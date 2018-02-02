FROM centos:7
LABEL authors="Antoni Segura Puimedon<toni@kuryr.org>, Vikas Choudhary<vichoudh@redhat.com>"

RUN yum install -y epel-release https://rdoproject.org/repos/rdo-release.rpm \
    && yum install -y --setopt=tsflags=nodocs python-pip iproute bridge-utils openvswitch sudo \
    && yum install -y --setopt=tsflags=nodocs gcc python-devel git \
    && pip install virtualenv \
    && virtualenv /kuryr-kubernetes

COPY . /opt/kuryr-kubernetes

RUN cd /opt/kuryr-kubernetes \
    && /kuryr-kubernetes/bin/pip install . \
    && virtualenv --relocatable /kuryr-kubernetes \
    && rm -fr .git \
    && yum -y history undo last

COPY ./cni_ds_init /usr/bin/cni_ds_init

ARG CNI_CONFIG_DIR_PATH=/etc/cni/net.d
ENV CNI_CONFIG_DIR_PATH ${CNI_CONFIG_DIR_PATH}
ARG CNI_BIN_DIR_PATH=/opt/cni/bin
ENV CNI_BIN_DIR_PATH ${CNI_BIN_DIR_PATH}
ARG CNI_DAEMON=False
ENV CNI_DAEMON ${CNI_DAEMON}

VOLUME [ "/sys/fs/cgroup" ]
ENTRYPOINT [ "cni_ds_init" ]
