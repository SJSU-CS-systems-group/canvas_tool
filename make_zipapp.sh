#!/bin/bash

rm -rf build
mkdir build
PYTHONUSERBASE=$PWD/build python3 -m pip install --ignore-installed click canvasapi mosspy markdownify
mkdir build/canvas_tool.app
mv build/lib/*/site-packages/* build/canvas_tool.app
cp -r commands md2fhtml.py core.py canvas_tool.py __main__.py build/canvas_tool.app
python3 -m zipapp build/canvas_tool.app
