# syntax=docker/dockerfile:1.4
# Firefox JS-shell project image
# Extends the shared anypoc base image with Firefox source and a JS-shell build

FROM zzjas/anypoc-common:latest

# Firefox-specific environment variables
ENV MOZ_CRASHREPORTER_DISABLE=1
ENV MOZ_DISABLE_CONTENT_SANDBOX=1
ENV PATH="/opt/searchfox/bin:${PATH}"

USER root
RUN cargo install --root /opt/searchfox searchfox-cli@0.2.0 && \
    mkdir -p /opt/firefox-js && \
    chown -R playground:playground /opt/firefox-js

USER playground
WORKDIR /opt/firefox-js

# Cache bust argument - change this value to force re-download/rebuild
ARG CACHE_BUST=1

# Download Firefox source code (shallow clone)
RUN git clone --depth 1 https://github.com/mozilla-firefox/firefox.git .

# Bootstrap Firefox build environment (skip system package installation;
# anypoc-common already provides the required build tooling, and the playground
# user may not have passwordless sudo for apt).
RUN yes Y | ./mach bootstrap --application-choice "Firefox for Desktop" --no-system-changes

# Write mozconfig for js-asan build
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
    > /opt/firefox-js/mozconfig

# Build SpiderMonkey js-asan variant
RUN MOZCONFIG=/opt/firefox-js/mozconfig ./mach build

# Simple build verification test
RUN test -f /opt/firefox-js/obj-js-asan/dist/bin/js && \
    echo "Build verification: SpiderMonkey js binary exists" || \
    (echo "Build verification failed: SpiderMonkey js binary not found" && exit 1)

WORKDIR /opt/firefox-js
CMD ["/bin/bash"]
