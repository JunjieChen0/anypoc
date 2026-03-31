# syntax=docker/dockerfile:1.4
# Chromium project image
# Extends the shared anypoc base image with Chromium source and build

FROM zzjas/anypoc-common:latest

# === Desktop environment for browser testing ===
USER root
RUN apt-get update && apt-get install -y \
    xrdp \
    xfce4 \
    xfce4-goodies \
    xfce4-terminal \
    dbus-x11 \
    systemd \
    xvfb \
    scrot \
    && rm -rf /var/lib/apt/lists/*

# Add playground user to xrdp group
RUN usermod -aG xrdp playground

# Configure xrdp and xfce4 session
RUN echo "xfce4-session" > /home/playground/.xsession && \
    chown playground:playground /home/playground/.xsession && \
    chmod +x /home/playground/.xsession

# Create startup script for xfce4
RUN mkdir -p /home/playground/.config/xfce4 && \
    echo "#!/bin/bash" > /home/playground/.xsessionrc && \
    echo "export LANG=en_US.UTF-8" >> /home/playground/.xsessionrc && \
    echo "export LC_ALL=en_US.UTF-8" >> /home/playground/.xsessionrc && \
    echo "export XDG_RUNTIME_DIR=/run/user/\$(id -u)" >> /home/playground/.xsessionrc && \
    echo "export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/\$(id -u)/bus" >> /home/playground/.xsessionrc && \
    echo "mkdir -p \$XDG_RUNTIME_DIR" >> /home/playground/.xsessionrc && \
    echo "chmod 700 \$XDG_RUNTIME_DIR" >> /home/playground/.xsessionrc && \
    echo "dbus-launch --exit-with-session xfce4-session" >> /home/playground/.xsessionrc && \
    chown -R playground:playground /home/playground/.config && \
    chown playground:playground /home/playground/.xsessionrc && \
    chmod +x /home/playground/.xsessionrc

# Update .xsession to source .xsessionrc
RUN echo "#!/bin/bash" > /home/playground/.xsession && \
    echo "[ -f ~/.xsessionrc ] && . ~/.xsessionrc" >> /home/playground/.xsession && \
    echo "exec xfce4-session" >> /home/playground/.xsession && \
    chown playground:playground /home/playground/.xsession && \
    chmod +x /home/playground/.xsession

# Configure xrdp logging
RUN sed -i 's/^LogLevel=.*/LogLevel=ERROR/' /etc/xrdp/xrdp.ini && \
    sed -i 's/^SyslogLevel=.*/SyslogLevel=ERROR/' /etc/xrdp/xrdp.ini && \
    sed -i 's/^EnableSyslog=.*/EnableSyslog=false/' /etc/xrdp/xrdp.ini && \
    sed -i 's/^LogLevel=.*/LogLevel=ERROR/' /etc/xrdp/sesman.ini && \
    sed -i 's/^SyslogLevel=.*/SyslogLevel=ERROR/' /etc/xrdp/sesman.ini && \
    sed -i 's/^EnableSyslog=.*/EnableSyslog=false/' /etc/xrdp/sesman.ini

# Enable desktop services
RUN systemctl enable dbus && \
    systemctl enable xrdp

# Drop-in entrypoint script for desktop services (xrdp + dbus). Inlined here
# because the anypoc build context is the repo root, not the project config dir.
RUN mkdir -p /docker-entrypoint.d && \
    printf '%s\n' \
        '#!/bin/bash' \
        '# Start desktop (xrdp) services for browser projects' \
        'nohup bash -c "service dbus start" >/tmp/dbus.log 2>&1 &' \
        'nohup bash -c "service xrdp start" >/tmp/xrdp.log 2>&1 &' \
        'sleep 1  # Give services time to start' \
        > /docker-entrypoint.d/01-desktop.sh && \
    chmod 755 /docker-entrypoint.d/01-desktop.sh

EXPOSE 3389

# Chromium-specific environment variables
ENV CHROME_DEVEL_SANDBOX=""

RUN mkdir -p /opt/chromium/tools && chown -R playground:playground /opt/chromium

USER playground
WORKDIR /opt/chromium

# Optional: copy .gitcookies for authenticated access to chromium.googlesource.com (higher rate limits)
# See https://chromium.googlesource.com/new-password to generate your own
# COPY --chown=playground:playground projects/chromium/.gitcookies /home/playground/.gitcookies
# RUN git config --global http.cookiefile /home/playground/.gitcookies

# Cache bust argument - change this value to force re-download/rebuild
ARG CACHE_BUST=1

# Setup depot_tools
RUN git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git /opt/chromium/tools/depot_tools
ENV PATH="/opt/chromium/tools/depot_tools:${PATH}"

# Download Chromium source code (shallow clone)
RUN fetch --nohooks --no-history chromium

# Install build dependencies and run gclient hooks
RUN cd /opt/chromium/src && \
    ./build/install-build-deps.sh --no-prompt || true
RUN cd /opt/chromium/src && \
    gclient runhooks -j 4

# Write args.gn for asan build
RUN mkdir -p /opt/chromium/src/out/Asan && \
    printf '%s\n' \
        '# ASan Build Configuration (with full debug symbols)' \
        'is_debug = false' \
        'is_asan = true' \
        'is_lsan = false' \
        'symbol_level = 2' \
        'is_component_build = false' \
        'is_clang = true' \
        'use_lld = true' \
        'v8_enable_sandbox = false' \
        > /opt/chromium/src/out/Asan/args.gn

# Generate build files and build Chromium asan variant
RUN cd /opt/chromium/src && \
    gn gen out/Asan && \
    autoninja -C out/Asan chrome

# Simple build verification test
RUN test -f /opt/chromium/src/out/Asan/chrome && \
    echo "Build verification: Chromium binary exists" || \
    (echo "Build verification failed: Chromium binary not found" && exit 1)

WORKDIR /opt/chromium/src
CMD ["/bin/bash"]
