ARG BUILD_FROM=docker.io/library/ubuntu:24.04
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data \
    INGRESS_PORT=8099 \
    LOCAL_UTC_OFFSET=7 \
    DEBIAN_FRONTEND=noninteractive

# cups + cups-client: IPP server and the AirPrint (mDNS/DNS-SD) advertisement
# printer-driver-escpr: exact Epson PPD that renders PDF/JPEG into ESC/P-R
# ghostscript/poppler: filters the AirPrint clients' PDF jobs go through
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      cups \
      cups-client \
      cups-filters \
      printer-driver-escpr \
      ghostscript \
      poppler-utils \
      libavahi-client3 \
      avahi-daemon \
      avahi-utils \
      dbus \
      python3 \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY app/ /app/
COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8099 631
CMD ["/run.sh"]
