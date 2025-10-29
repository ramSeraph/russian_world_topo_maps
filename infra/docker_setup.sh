
docker build -t test .
docker run -v $(pwd):/local --rm -i -t -w /local test sh -c "./install.sh"
