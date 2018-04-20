FROM centos:7
LABEL authors="Antoni Segura Puimedon<toni@kuryr.org>, Vikas Choudhary<vichoudh@redhat.com>"

ARG UPPER_CONSTRAINTS_FILE="https://git.openstack.org/cgit/openstack/requirements/plain/upper-constraints.txt?h=stable/queens"
ARG OSLO_LOCK_PATH=/var/kuryr-lock

RUN yum install -y epel-release https://rdoproject.org/repos/rdo-release.rpm \
    && yum install -y --setopt=tsflags=nodocs python-pip iproute bridge-utils openvswitch sudo jq \
    && yum install -y --setopt=tsflags=nodocs gcc python-devel git

COPY . /opt/kuryr-kubernetes

RUN cd /opt/kuryr-kubernetes \
    && pip install -c $UPPER_CONSTRAINTS_FILE . \
    && rm -fr .git \
    && yum -y history undo last \
    && mkdir ${OSLO_LOCK_PATH}

COPY ./cni_ds_init /usr/bin/cni_ds_init

ARG CNI_CONFIG_DIR_PATH=/etc/cni/net.d
ENV CNI_CONFIG_DIR_PATH ${CNI_CONFIG_DIR_PATH}
ARG CNI_BIN_DIR_PATH=/opt/cni/bin
ENV CNI_BIN_DIR_PATH ${CNI_BIN_DIR_PATH}
ARG CNI_DAEMON=False
ENV CNI_DAEMON ${CNI_DAEMON}
ENV OSLO_LOCK_PATH=${OSLO_LOCK_PATH}

VOLUME [ "/sys/fs/cgroup" ]
ENTRYPOINT [ "cni_ds_init" ]
