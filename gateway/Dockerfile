FROM nginx:1.27-alpine
# Solo sustituir la clave; conservar variables Nginx como $host/$request_id.
ENV NGINX_ENVSUBST_OUTPUT_DIR=/etc/nginx NGINX_ENVSUBST_FILTER=^EP3_API_KEY$
COPY gateway/nginx.conf /etc/nginx/templates/nginx.conf.template
COPY gateway/15-check-api-key.sh /docker-entrypoint.d/15-check-api-key.sh
RUN chmod +x /docker-entrypoint.d/15-check-api-key.sh
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=4s --retries=5 CMD wget -q -O /dev/null http://127.0.0.1:8080/health || exit 1
