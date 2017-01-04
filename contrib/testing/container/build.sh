#!/bin/bash

set -o errexit


function install_busybox {
    if [[ -x $(command -v apt-get 2> /dev/null) ]]; then
        sudo apt-get update
        sudo apt-get install -y busybox-static gcc
    elif [[ -x $(command -v dnf 2> /dev/null) ]]; then
        sudo dnf install -y busybox gcc
    elif [[ -x $(command -v yum 2> /dev/null) ]]; then
        sudo yum install -y busybox gcc
    elif [[ -x $(command -v pacman 2> /dev/null) ]]; then
        sudo pacman -S --noconfirm busybox gcc
    else
        echo "unknown distro" 1>2
        exit 1
    fi
    return 0
}

function make_root {
    local root_dir
    local binary

    root_dir=$(mktemp -d)
    mkdir -p "${root_dir}/bin" "${root_dir}/usr/bin"
    binary=$(command -v busybox)
    cp "$binary" "${root_dir}/bin/busybox"
    "${root_dir}/bin/busybox" --install "${root_dir}/bin"
    gcc --static hostname.c -o "${root_dir}/usr/bin/kuryr_hostname"
    tar -C "$root_dir" -czvf kuryr_testing_rootfs.tar.gz bin usr
    return 0
}

function build_container {
    docker build -t kuryr/test_container .
}

install_busybox
make_root
build_container
