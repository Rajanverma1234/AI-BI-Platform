# Frontend image. Two targets:
#
#   development  Vite dev server with HMR
#   production   static build served by nginx; no dev server, no node runtime
#
# Build the production target explicitly:
#   docker build --target production -t aibi-frontend:prod ./frontend
FROM node:22-alpine AS base

WORKDIR /app

# Dependency layer first so source edits do not invalidate the install cache.
COPY package.json package-lock.json* ./


# --- Development -------------------------------------------------------------
FROM base AS development

RUN npm install

COPY . .

EXPOSE 5173

# --host binds 0.0.0.0 so the port is reachable from outside the container.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]


# --- Build -------------------------------------------------------------------
FROM base AS build

# `npm ci` installs exactly the lockfile, which is what a release needs.
RUN npm ci

COPY . .

# Vite inlines VITE_* variables at build time, so the API URL is a build
# argument rather than a runtime environment variable. Rebuild to change it.
ARG VITE_API_BASE_URL
ARG VITE_API_VERSION_PREFIX=/api/v1
ARG VITE_APP_NAME="AI BI Platform"
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_API_VERSION_PREFIX=$VITE_API_VERSION_PREFIX \
    VITE_APP_NAME=$VITE_APP_NAME

RUN npm run build


# --- Production --------------------------------------------------------------
FROM nginx:1.27-alpine AS production

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/conf.d/security-headers.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
