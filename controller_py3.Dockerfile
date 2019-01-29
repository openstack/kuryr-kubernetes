FROM fedora:29
LABEL authors="Antoni Segura Puimedon<toni@kuryr.org>, Michał Dulko<mdulko@redhat.com>"

ARG UPPER_CONSTRAINTS_FILE="https://git.openstack.org/cgit/openstack/requirements/plain/upper-constraints.txt"

RUN dnf update -y \
    && dnf install -y --setopt=tsflags=nodocs python36 \
    && dnf install -y --setopt=tsflags=nodocs gcc git

COPY . /opt/kuryr-kubernetes

RUN python3.6 -m ensurepip \
    && python3.6 -m pip install -c $UPPER_CONSTRAINTS_FILE --no-cache-dir /opt/kuryr-kubernetes \
    && dnf -y history undo last \
    && rm -rf /opt/kuryr-kubernetes \
    && groupadd -r kuryr -g 711 \
    && useradd -u 711 -g kuryr \
         -d /opt/kuryr-kubernetes \
         -s /sbin/nologin \
         -c "Kuryr controller user" \
         kuryr

USER kuryr
CMD ["--config-dir", "/etc/kuryr"]
ENTRYPOINT [ "/usr/local/bin/kuryr-k8s-controller" ]
