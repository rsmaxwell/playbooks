@echo off

setlocal
cd %~dp0

@echo on
"C:\Program Files\Mosquitto\mosquitto_sub" -h localhost --remove-retained -t # -W 1 -u richard -P secret


