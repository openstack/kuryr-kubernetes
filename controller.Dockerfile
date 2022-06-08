FROM quay.io/centos/centos:stream9
LABEL authors="Antoni Segura Puimedon<toni@kuryr.org>, Michał Dulko<mdulko@redhat.com>"

ARG UPPER_CONSTRAINTS_FILE="https://releases.openstack.org/constraints/upper/master"

RUN dnf upgrade -y \
    && dnf install -y epel-release \
    && dnf install -y --setopt=tsflags=nodocs python3-pip libstdc++ \
    && dnf install -y --setopt=tsflags=nodocs gcc gcc-c++ python3-devel git

COPY . /opt/kuryr-kubernetes

ARG VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
# This is enough to activate a venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN pip3 --no-cache-dir install -U pip \
    && python3 -m pip install -c $UPPER_CONSTRAINTS_FILE --no-cache-dir /opt/kuryr-kubernetes \
    && dnf -y history undo last \
    && dnf clean all \
    && rm -rf /opt/kuryr-kubernetes \
    && groupadd -r kuryr -g 1000 \
    && useradd -u 1000 -g kuryr \
         -d /opt/kuryr-kubernetes \
         -s /sbin/nologin \
         -c "Kuryr controller user" \
         kuryr

USER kuryr
CMD ["--config-dir", "/etc/kuryr"]
ENTRYPOINT [ "kuryr-k8s-controller" ]
