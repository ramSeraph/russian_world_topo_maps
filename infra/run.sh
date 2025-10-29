#!/bin/bash

docker run -v $(pwd):/local --rm -i -t -w /local test uv run tile --name Soviet-GS-200k --description "Soviet GenShtab 1:200,000 Topographic Maps" --attribution-file attribution.txt --tiles-dir data/export/tiles --tiffs-dir data/export/gtiffs --max-zoom 5
