FROM node:20-alpine AS build
WORKDIR /app

COPY services/web/package*.json ./
RUN npm ci
COPY services/web/. .

RUN --mount=type=secret,id=env,target=/tmp/.env \
    sh -c 'export $(cat /tmp/.env | xargs) && npm run build'

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY services/web/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80