FROM ghcr.io/osgeo/gdal:ubuntu-small-3.11.4

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt update && apt install build-essential python3-dev -y
