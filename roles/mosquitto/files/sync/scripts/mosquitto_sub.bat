@echo off

setlocal
cd %~dp0

@echo on
"C:\Program Files\Mosquitto\mosquitto_sub" -i subscriber -h localhost -t test -u richard -P secret