FROM nginx:1.27-alpine
COPY gateway/nginx.conf /etc/nginx/nginx.conf
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=4s --retries=5 CMD wget -q -O /dev/null http://127.0.0.1:8080/health || exit 1
