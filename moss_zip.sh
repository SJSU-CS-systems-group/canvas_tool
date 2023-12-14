#!/bin/bash
#
# simple script to zip match results according to match numbers
# multiple can be specified. for example:
#
# ./moss_zip.sh moss.stanford.edu/results/7/35796342564 3 8 9 10
#
# will zipp the 3, 8, 9, and 10 matches from the results downloaded to moss.stanford.edu/results/7/35796342564
# that directory structure is what you get when you do the wget that is suggested by canvas_tool for pulling
# the moss results.
#

if [ $# -lt 2 ]
then
    echo USAGE: $0 prefix match_numbers ...
    exit 1
fi

list=""
prefix="$1"
shift
for arg in "$@"
do
    list="$list $prefix/match$arg.html $prefix/match$arg-*"
done
eval zip matches $list
