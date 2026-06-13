#!/bin/bash
declare -a RULES
RULES=( $(ls . | grep .xml ) )
for RULE in "${RULES[@]}"; do
    SERVICE="${RULE%%.*}"
    if ! firewall-cmd --list-services | grep $RULE; then
    cp -f "${RULE}" /etc/firewalld/services/
    firewall-cmd --add-service="${SERVICE}"  --zone public --permanent
    fi
done 
firewall-cmd --reload