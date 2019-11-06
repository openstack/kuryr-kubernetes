FROM golang:1.11 AS builder

WORKDIR /go/src/opendev.com/kuryr-kubernetes
COPY . .
RUN go build -o /go/bin/kuryr-cni ./kuryr_cni

FROM centos:7
LABEL authors="Antoni Segura Puimedon<toni@kuryr.org>, Michał Dulko<mdulko@redhat.com>"

ARG UPPER_CONSTRAINTS_FILE="https://releases.openstack.org/constraints/upper/train"
ARG OSLO_LOCK_PATH=/var/kuryr-lock

RUN yum install -y epel-release https://rdoproject.org/repos/rdo-release.rpm \
    && yum install -y --setopt=tsflags=nodocs python-pip iproute bridge-utils openvswitch sudo libstdc++ \
    && yum install -y --setopt=tsflags=nodocs gcc python-devel git

COPY . /opt/kuryr-kubernetes

RUN pip install -c $UPPER_CONSTRAINTS_FILE /opt/kuryr-kubernetes \
    && cp /opt/kuryr-kubernetes/cni_ds_init /usr/bin/cni_ds_init \
    && mkdir -p /etc/kuryr-cni \
    && cp /opt/kuryr-kubernetes/etc/cni/net.d/* /etc/kuryr-cni \
    && yum -y history undo last \
    && yum clean all \
    && rm -rf /opt/kuryr-kubernetes \
    && mkdir ${OSLO_LOCK_PATH}

COPY --from=builder /go/bin/kuryr-cni /kuryr-cni

ARG CNI_DAEMON=True
ENV CNI_DAEMON ${CNI_DAEMON}
ENV OSLO_LOCK_PATH=${OSLO_LOCK_PATH}

ENTRYPOINT [ "cni_ds_init" ]
