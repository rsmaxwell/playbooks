#!/bin/bash

directory="/home/gradle"

mkdir -p "${directory}/.gradle"
chown 1000:1000 "${directory}" "${directory}/.gradle"
chmod 0700 "${directory}"
chmod 0755 "${directory}/.gradle"
