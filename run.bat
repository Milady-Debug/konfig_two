@echo off
rem Запуск depviz из корня репозитория: run.bat [аргументы]
python src\depviz.py --config config.csv %*
