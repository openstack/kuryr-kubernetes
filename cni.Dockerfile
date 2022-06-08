FROM quay.io/kuryr/golang:1.16 as builder

WORKDIR /go/src/opendev.com/kuryr-kubernetes
COPY . .

RUN GO111MODULE=auto go build -o /go/bin/kuryr-cni ./kuryr_cni/pkg/*

FROM quay.io/centos/centos:stream9
LABEL authors="Antoni Segura Puimedon<toni@kuryr.org>, Michał Dulko<mdulko@redhat.com>"

ARG UPPER_CONSTRAINTS_FILE="https://releases.openstack.org/constraints/upper/master"
ARG OSLO_LOCK_PATH=/var/kuryr-lock
ARG RDO_REPO=https://repos.fedorapeople.org/repos/openstack/openstack-yoga/rdo-release-yoga-1.el9s.noarch.rpm

RUN dnf upgrade -y && dnf install -y epel-release $RDO_REPO \
    && dnf install -y --setopt=tsflags=nodocs python3-pip openvswitch sudo iproute pciutils kmod-libs \
    && dnf install -y --setopt=tsflags=nodocs gcc gcc-c++ python3-devel git

COPY . /opt/kuryr-kubernetes

ARG VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
# This is enough to activate a venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN pip3 --no-cache-dir install -U pip \
    && python3 -m pip --no-cache-dir install -c $UPPER_CONSTRAINTS_FILE /opt/kuryr-kubernetes \
    && cp /opt/kuryr-kubernetes/cni_ds_init /usr/bin/cni_ds_init \
    && mkdir -p /etc/kuryr-cni \
    && cp /opt/kuryr-kubernetes/etc/cni/net.d/* /etc/kuryr-cni \
    && dnf -y history undo last \
    && dnf clean all \
    && rm -rf /opt/kuryr-kubernetes \
    && mkdir ${OSLO_LOCK_PATH}

COPY --from=builder /go/bin/kuryr-cni /kuryr-cni

ARG CNI_DAEMON=True
ENV CNI_DAEMON ${CNI_DAEMON}
ENV OSLO_LOCK_PATH=${OSLO_LOCK_PATH}

ENTRYPOINT [ "cni_ds_init" ]
