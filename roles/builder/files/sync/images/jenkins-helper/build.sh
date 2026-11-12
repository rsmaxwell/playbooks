#!/bin/bash

docker build --tag rsmaxwell/jenkins-helper .

docker login

docker push rsmaxwell/jenkins-helper

docker logout
