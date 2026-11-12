@echo off

setlocal
cd %~dp0

@echo on
"C:\Program Files\Mosquitto\mosquitto_pub" -i publisher -h localhost -u richard -P secret -t "pages/999" -m "hello world"


