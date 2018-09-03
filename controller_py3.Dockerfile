FROM fedora:28
LABEL authors="Antoni Segura Puimedon<toni@kuryr.org>, Michał Dulko<mdulko@redhat.com>"

ARG UPPER_CONSTRAINTS_FILE="https://git.openstack.org/cgit/openstack/requirements/plain/upper-constraints.txt"

RUN dnf update -y \
    && dnf install -y --setopt=tsflags=nodocs python3-pip \
    && dnf install -y --setopt=tsflags=nodocs gcc python3-devel wget git

COPY . /opt/kuryr-kubernetes

RUN cd /opt/kuryr-kubernetes \
    && pip3 install -c $UPPER_CONSTRAINTS_FILE --no-cache-dir . \
    && rm -fr .git \
    && dnf -y history undo last \
    && groupadd -r kuryr -g 711 \
    && useradd -u 711 -g kuryr \
         -d /opt/kuryr-kubernetes \
         -s /sbin/nologin \
         -c "Kuryr controller user" \
         kuryr \
    && chown kuryr:kuryr /opt/kuryr-kubernetes

USER kuryr
CMD ["--config-dir", "/etc/kuryr"]
ENTRYPOINT [ "/usr/local/bin/kuryr-k8s-controller" ]
