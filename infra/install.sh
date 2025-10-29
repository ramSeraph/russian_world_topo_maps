#!/bin/bash

uv pip install numpy pillow
GDAL_VERSION=$(gdal-config --version)
uv pip install gdal==$GDAL_VERSION topo-map-processor
