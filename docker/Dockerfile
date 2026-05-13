FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    clang-14 \
    llvm-14 \
    llvm-14-dev \
    llvm-14-tools \
    cmake \
    make \
    gcc \
    g++ \
    python3 \
    python3-pip \
    gcovr \
    lcov \
    git \
    curl \
    graphviz \
    clang-tools-14 \
    && rm -rf /var/lib/apt/lists/*

# Symlinks for convenience
RUN ln -sf /usr/bin/clang-14 /usr/bin/clang \
    && ln -sf /usr/bin/clang++-14 /usr/bin/clang++ \
    && ln -sf /usr/bin/opt-14 /usr/bin/opt \
    && ln -sf /usr/bin/llvm-dis-14 /usr/bin/llvm-dis \
    && ln -sf /usr/bin/scan-build-14 /usr/bin/scan-build

# Python deps
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# AFL++ for fuzzing
RUN git clone --depth 1 https://github.com/AFLplusplus/AFLplusplus /opt/aflpp \
    && cd /opt/aflpp \
    && make distrib \
    && make install \
    || echo "AFL++ install skipped (optional)"

WORKDIR /workspace
