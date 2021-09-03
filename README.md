# canvas_tool
a command-line python based tool for teachers who use canvas. 

you can download from canvas_tool.pyz from https://github.com/SJSU-CS-systems-group/canvas_tool/releases/download/v0.1/canvas_tool.pyz

run it with `python3 canvas_tool.pyz` or `python canvas_tool.pyz`.

you will need to grab a "token" from your canvas account. go to the canvas webpage -> click on Account in the upper left -> click Settings -> scroll down and click the New Access Token button. you will need to put the token in a configuration file. `python3 canvas_tool.pyz help-me-setup` will tell you how and where to create that configuration file.

at this point the main thing this tool does is grade discussion assignments for participation: 1 point for posting and 1 point for replying.

it also will collect names and categories of assignments that past students excelled at for writing future letters of recommendation.
