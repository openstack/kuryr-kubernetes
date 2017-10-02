FROM centos:centos6
LABEL authors="Antoni Segura Puimedon<toni@kuryr.org>, Vikas Choudhary<vichoudh@redhat.com>"

RUN yum install --setopt=tsflags=nodocs --assumeyes \
        net-tools \
        patch \
        gcc \
        python-devel \
        wget \
        openssl-devel \
        zlib-devel \
        git; \
    yum clean all

ENV LANG en_US.UTF-8
ARG CNI_CONFIG_DIR_PATH=/etc/cni/net.d
ENV CNI_CONFIG_DIR_PATH ${CNI_CONFIG_DIR_PATH}
ARG CNI_BIN_DIR_PATH=/opt/cni/bin
ENV CNI_BIN_DIR_PATH ${CNI_BIN_DIR_PATH}

RUN cd /usr/src \
    && wget https://www.python.org/ftp/python/3.5.3/Python-3.5.3.tgz \
    && tar zxf Python-3.5.3.tgz \
    && cd Python-3.5.3 && ./configure --enable-shared && make altinstall \
    && ln -s /usr/local/lib/libpython3.5m.so.1.0 /usr/lib64/libpython3.5m.so.1.0

COPY . /opt/kuryr-kubernetes

# Installing from dev because of this issue, https://github.com/pyinstaller/pyinstaller/issues/2434
RUN cd /opt/kuryr-kubernetes \
    && patch -b kuryr_kubernetes/k8s_client.py < k8s_client.patch \
    && patch -b kuryr_kubernetes/cni/main.py < cni_main.patch \
    && pip3.5 install --no-cache-dir . \
    && pip3.5 install git+https://github.com/pyinstaller/pyinstaller.git \
    && pip3.5 install pyroute2 \
    && sed -i -e "s/self.bytebuffer + newdata/self.bytebuffer + newdata.encode()/" /usr/local/lib/python3.5/codecs.py

COPY cni_builder /usr/bin/cni_builder
COPY hooks/* /usr/local/lib/python3.5/site-packages/PyInstaller/hooks/
COPY cni.spec /
RUN pyinstaller cni.spec
CMD ["cni_builder"]
ENTRYPOINT [ "/bin/bash" ]
