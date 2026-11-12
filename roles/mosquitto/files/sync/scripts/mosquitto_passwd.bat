@echo off

setlocal
cd %~dp0

@echo on
copy pwfile.source.txt pwfile.txt
"C:\Program Files\Mosquitto\mosquitto_passwd" -U pwfile.txt


