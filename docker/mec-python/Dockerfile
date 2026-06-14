FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    iproute2 \
    iputils-ping \
    procps \
    curl \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

CMD ["/bin/bash"]
