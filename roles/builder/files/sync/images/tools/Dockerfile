FROM ubuntu:20.04

ARG USER=builder
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/London

RUN apt-get update && apt-get install -y \
    git \
    jq \
    tree \
    zip \
    unzip \
    gettext \
    python3 \
    python3-pip && \
#
    pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir pyyaml && \
#
    useradd --create-home -s /bin/bash $USER && \
    passwd --lock $USER


USER $USER
