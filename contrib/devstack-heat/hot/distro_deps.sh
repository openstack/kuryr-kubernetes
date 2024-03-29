distro=$(awk -F'=' '/^ID=/ {print $2}' /etc/os-release)
distro="${distro%\"}"
distro="${distro#\"}"

if [[ "$distro" =~ centos|fedora ]]; then
    yum install -y git python-devel
    yum group install -y Development Tools
    if [[ "$distro" == "centos" ]]; then
        yum install -y epel-release
        sed -i -e '/Defaults    requiretty/{ s/.*/# Defaults    requiretty/ }' /etc/sudoers
    fi
    yum install -y jq
    yum install -y python-pip
    pip install -U setuptools
elif [[ "$distro" =~ ubuntu|debian ]]; then
    apt update -y
    apt upgrade -y
    apt-get install -y build-essential git python-dev jq
fi
