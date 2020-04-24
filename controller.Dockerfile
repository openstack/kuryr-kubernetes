FROM centos:8
LABEL authors="Antoni Segura Puimedon<toni@kuryr.org>, Michał Dulko<mdulko@redhat.com>"

ARG UPPER_CONSTRAINTS_FILE="https://releases.openstack.org/constraints/upper/ussuri"

RUN yum upgrade -y \
    && yum install -y epel-release \
    && yum install -y --setopt=tsflags=nodocs python3-pip libstdc++ \
    && yum install -y --setopt=tsflags=nodocs gcc gcc-c++ python3-devel git

COPY . /opt/kuryr-kubernetes

RUN pip3 install -c $UPPER_CONSTRAINTS_FILE --no-cache-dir /opt/kuryr-kubernetes \
    && yum -y history undo last \
    && yum clean all \
    && rm -rf /opt/kuryr-kubernetes \
    && groupadd -r kuryr -g 711 \
    && useradd -u 711 -g kuryr \
         -d /opt/kuryr-kubernetes \
         -s /sbin/nologin \
         -c "Kuryr controller user" \
         kuryr

USER kuryr
CMD ["--config-dir", "/etc/kuryr"]
ENTRYPOINT [ "kuryr-k8s-controller" ]
