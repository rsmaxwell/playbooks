@echo off

setlocal
cd %~dp0

@echo on
"C:\Program Files\Mosquitto\mosquitto_pub" -i publisher -h localhost -t test -m "hello world"  -u richard -P secret


