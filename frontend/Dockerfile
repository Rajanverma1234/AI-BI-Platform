# Development image for the Vite dev server.
FROM node:22-alpine

WORKDIR /app

# Dependency layer first so source edits do not invalidate the install cache.
COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 5173

# --host binds 0.0.0.0 so the port is reachable from outside the container.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
