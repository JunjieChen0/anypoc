# syntax=docker/dockerfile:1.4
# Firefox project image
# Extends the shared anypoc base image with Firefox source and build

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

# Firefox-specific environment variables
ENV MOZ_CRASHREPORTER_DISABLE=1
ENV MOZ_DISABLE_CONTENT_SANDBOX=1
ENV PATH="/opt/searchfox/bin:${PATH}"

RUN cargo install --root /opt/searchfox searchfox-cli@0.2.0 && \
    mkdir -p /opt/firefox && \
    chown -R playground:playground /opt/firefox

USER playground
WORKDIR /opt/firefox

# Optional: copy .gitcookies for authenticated access to chromium.googlesource.com (higher rate limits)
# See https://chromium.googlesource.com/new-password to generate your own
# COPY --chown=playground:playground projects/chromium/.gitcookies /home/playground/.gitcookies
# RUN git config --global http.cookiefile /home/playground/.gitcookies

# Cache bust argument - change this value to force re-download/rebuild
ARG CACHE_BUST=1

# Download Firefox source code (shallow clone)
RUN git clone --depth 1 https://github.com/mozilla-firefox/firefox.git .

# Bootstrap Firefox build environment (skip system package installation;
# anypoc-common already provides the required build tooling, and the playground
# user may not have passwordless sudo for apt). Use pipe rather than bash
# process substitution so /bin/sh works.
RUN yes Y | ./mach bootstrap --application-choice "Firefox for Desktop" --no-system-changes

# Write mozconfig for asan build
RUN printf '%s\n' \
    '# ASan Build Configuration' \
    'mk_add_options MOZ_OBJDIR=@TOPSRCDIR@/obj-ff-asan' \
    '' \
    'ac_add_options --enable-project=browser' \
    'ac_add_options --enable-address-sanitizer' \
    '' \
    'ac_add_options --disable-jemalloc' \
    'ac_add_options --disable-crashreporter' \
    'ac_add_options --disable-elf-hack' \
    'ac_add_options --disable-install-strip' \
    'ac_add_options --enable-debug-symbols=-gline-tables-only' \
    '#ac_add_options --enable-debug' \
    > /opt/firefox/mozconfig

# Build Firefox asan variant
RUN MOZCONFIG=/opt/firefox/mozconfig ./mach build

# Simple build verification test
RUN test -f /opt/firefox/obj-ff-asan/dist/bin/firefox && \
    echo "Build verification: Firefox binary exists" || \
    (echo "Build verification failed: Firefox binary not found" && exit 1)

# --- SpiderMonkey (JS shell) ASan build ------------------------------------
# Placed AFTER the browser build so edits above don't invalidate the cache of
# the JS shell layers (and vice versa). Uses a separate mozconfig and a
# separate MOZ_OBJDIR so the two builds coexist in the same source tree.
RUN printf '%s\n' \
    '# JavaScript Shell ASan Build Configuration' \
    'mk_add_options MOZ_OBJDIR=@TOPSRCDIR@/obj-js-asan' \
    '' \
    'ac_add_options --enable-project=js' \
    '' \
    'ac_add_options --enable-debug' \
    'ac_add_options --enable-optimize="-O1"' \
    'ac_add_options --enable-debug-symbols' \
    '' \
    '# Enable ASan specific code and build workarounds' \
    'ac_add_options --enable-address-sanitizer' \
    '' \
    '# Mandatory options required for ASan builds' \
    'ac_add_options --disable-install-strip' \
    'ac_add_options --disable-jemalloc' \
    'ac_add_options --disable-profiling' \
    > /opt/firefox/mozconfig-js

# Build SpiderMonkey js-asan variant
RUN MOZCONFIG=/opt/firefox/mozconfig-js ./mach build

# Verify JS shell binary exists
RUN test -f /opt/firefox/obj-js-asan/dist/bin/js && \
    echo "Build verification: SpiderMonkey js binary exists" || \
    (echo "Build verification failed: SpiderMonkey js binary not found" && exit 1)

WORKDIR /opt/firefox
CMD ["/bin/bash"]
