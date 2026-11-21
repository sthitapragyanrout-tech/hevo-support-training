# Shared by http.conf and https.conf.

client_max_body_size 1100m;   # video uploads (MEDIA_MAX_UPLOAD_MB defaults to 1024)

# The API, Django Admin and the health check go to Django.
location ~ ^/(api|django-admin|healthz)(/|$) {
    proxy_pass http://web:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $forwarded_proto;
    proxy_read_timeout 120s;
    proxy_request_buffering off;   # stream big uploads instead of buffering them twice
}

# Django Admin's CSS and JS (collected by the web container).
location /static/ {
    alias /var/static/;
    expires 7d;
}

# Videos and attachments: Django checks who may see a file, then hands it to nginx
# with X-Accel-Redirect. Never reachable directly from outside.
location /protected-media/ {
    internal;
    alias /var/media/;
}

# The built React app. Hashed assets cache for a long time; everything else falls back
# to index.html so client-side routes (/progress, /admin/...) work on refresh.
location /assets/ {
    root /usr/share/nginx/html;
    expires 1y;
    add_header Cache-Control "public, immutable";
}

location / {
    root /usr/share/nginx/html;
    try_files $uri /index.html;
    add_header Cache-Control "no-cache";
}
