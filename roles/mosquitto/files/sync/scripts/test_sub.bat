@echo off

setlocal
cd %~dp0

@echo on
"C:\Program Files\Mosquitto\mosquitto_sub" -i subscriber -h localhost -u richard -P secret -t "pages/#" -v 