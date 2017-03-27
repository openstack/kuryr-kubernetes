#!/bin/sh

getent passwd vagrant > /dev/null
if [ $? -eq 0 ]; then
    export OS_USER=vagrant
else
    getent passwd ubuntu > /dev/null
    if [ $? -eq 0 ]; then
        export OS_USER=ubuntu
    fi
fi

set -ex

export HOST_IP=127.0.0.1

# run script
bash /vagrant/devstack.sh "$1"

#set environment variables for kuryr
su "$OS_USER" -c "echo 'source /vagrant/config/kuryr_rc' >> ~/.bash_profile"
