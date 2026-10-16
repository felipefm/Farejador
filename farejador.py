#!/usr/bin/env python3
"""Ponto de entrada da CLI. Uso: python farejador.py @canal"""
import sys

from farejador.cli import main

if __name__ == "__main__":
    sys.exit(main())
