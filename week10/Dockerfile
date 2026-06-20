FROM mcr.microsoft.com/playwright/python:v1.47.0-noble

# Use pipefail so the build correctly fails if curl fails
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Install Xvfb, D-Bus, C-headers for lxml, a11y tools, and desktop applications
RUN apt-get update && apt-get install -y \
    xvfb \
    dbus-x11 \
    at-spi2-core \
    libatk-bridge2.0-0 \
    gnome-calculator \
    libreoffice-calc \
    libreoffice-gtk3 \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    curl \
    npm \
    wmctrl \
    xdotool \
    openbox \
    python3-gi \
    gir1.2-atspi-2.0 \
    && rm -rf /var/lib/apt/lists/*

# Install cua-driver directly from GitHub releases to bypass cua.to DNS issues
RUN curl -fsSL "https://github.com/trycua/cua/releases/download/cua-driver-rs-v0.5.7/cua-driver-rs-0.5.7-linux-x86_64.tar.gz" | tar xz && \
    mv cua-driver-rs-0.5.7-linux-x86_64/cua-driver /usr/local/bin/cua-driver && \
    chmod +x /usr/local/bin/cua-driver

# Install uv (Python package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="/usr/local/bin" sh

# Set up the working directory
WORKDIR /app

# Copy the code and llm_gatewayV9 directories, plus the .env file
COPY .env /app/.env
COPY code/ /app/code/
COPY llm_gatewayV9/ /app/llm_gatewayV9/

# Setup the environment inside code/
WORKDIR /app/code
RUN uv sync --frozen

# Setup the entrypoint
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh && \
    echo 'export GDK_BACKEND=x11' >> /root/.bashrc && \
    mkdir -p /root/.config/libreoffice/4/user/ && \
    echo '<?xml version="1.0" encoding="UTF-8"?><oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="ShowTipOfTheDay" oor:op="fuse"><value>false</value></prop></item></oor:items>' > /root/.config/libreoffice/4/user/registrymodifications.xcu

ENV GDK_BACKEND=x11
ENV SAL_USE_VCLPLUGIN=gtk3

ENTRYPOINT ["/app/entrypoint.sh"]
