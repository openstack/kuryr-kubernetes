FROM quay.io/kuryr/golang:1.16 as builder

WORKDIR /go/src/opendev.com/kuryr-kubernetes
COPY . .

RUN GO111MODULE=auto go build -o /go/bin/kuryr-cni ./kuryr_cni/pkg/*

FROM quay.io/centos/centos:stream8
LABEL authors="Antoni Segura Puimedon<toni@kuryr.org>, Michał Dulko<mdulko@redhat.com>"

ARG UPPER_CONSTRAINTS_FILE="https://releases.openstack.org/constraints/upper/yoga"
ARG OSLO_LOCK_PATH=/var/kuryr-lock
ARG RDO_REPO=https://repos.fedorapeople.org/repos/openstack/openstack-xena/rdo-release-xena-1.el8.noarch.rpm

# NOTE(gryf): There is a sed substitution to make package manager to
# cooperate. It might be a subject to change in the future, either when
# yum/dnf starts to respect yum.conf variables, or mirror location would
# change.
RUN dnf upgrade -y && dnf install -y epel-release $RDO_REPO \
    && sed -e 's/$releasever/8-stream/' -i /etc/yum.repos.d/messaging.repo \
    && sed -e 's/$basearch/x86_64/' -i /etc/yum.repos.d/messaging.repo \
    && dnf install -y --setopt=tsflags=nodocs python3-pip openvswitch sudo iproute libstdc++ pciutils kmod-libs \
    && dnf install -y --setopt=tsflags=nodocs gcc gcc-c++ python3-devel git

COPY . /opt/kuryr-kubernetes

RUN pip3 --no-cache-dir install -U pip \
    && python3 -m pip --no-cache-dir install -c $UPPER_CONSTRAINTS_FILE /opt/kuryr-kubernetes \
    && cp /opt/kuryr-kubernetes/cni_ds_init /usr/bin/cni_ds_init \
    && mkdir -p /etc/kuryr-cni \
    && cp /opt/kuryr-kubernetes/etc/cni/net.d/* /etc/kuryr-cni \
    && dnf -y remove gcc gcc-c++ python3-devel git \
    && dnf clean all \
    && rm -rf /opt/kuryr-kubernetes \
    && mkdir ${OSLO_LOCK_PATH}

COPY --from=builder /go/bin/kuryr-cni /kuryr-cni

ARG CNI_DAEMON=True
ENV CNI_DAEMON ${CNI_DAEMON}
ENV OSLO_LOCK_PATH=${OSLO_LOCK_PATH}

ENTRYPOINT [ "cni_ds_init" ]
