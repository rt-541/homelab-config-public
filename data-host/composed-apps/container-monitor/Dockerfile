FROM alpine:latest

RUN apk add --no-cache docker-cli curl jq yq

COPY monitor.sh /monitor.sh
COPY status-report.sh /status-report.sh
COPY mod-monitor.sh /mod-monitor.sh
COPY config.yml /config.yml
COPY lib/ /lib/

RUN chmod +x /monitor.sh /status-report.sh /mod-monitor.sh /lib/*.sh

CMD ["/bin/sh", "/monitor.sh"]
