#!/bin/bash

rm -rf build
mkdir build
python3 -m pip install -t $PWD/build/pkgs --ignore-installed click canvasapi mosspy markdownify markdown
mkdir build/canvas_tool.app
mv $(find build/pkgs -maxdepth 1 -mindepth 1 -type d)  build/canvas_tool.app
cp -r commands md2fhtml.py core.py canvas_tool.py __main__.py build/canvas_tool.app
python3 -m zipapp build/canvas_tool.app
