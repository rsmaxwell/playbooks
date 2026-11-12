#!/bin/bash

kubectl wait --for=condition=ready pod -l app=jenkins --timeout=5m
