FROM nginx:1.27-alpine
COPY front/index.html /usr/share/nginx/html/index.html
COPY front/default.conf /etc/nginx/conf.d/default.conf
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD wget -q -O /dev/null http://127.0.0.1:80/health || exit 1
