#!/bin/sh
# Запуск depviz из корня репозитория: ./run.sh [аргументы]
python3 src/depviz.py --config config.csv "$@"
