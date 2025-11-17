# ---------- Build stage ----------
FROM node:20-alpine AS build

WORKDIR /app

# Копируем манифесты отдельно для кеширования
COPY front-main/package*.json ./
RUN npm install

# Копируем исходники
COPY front-main/ ./

# Аргумент для API base URL
ARG VITE_API_BASE_URL=http://backend:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# Сборка
RUN npm run build

# ---------- Runtime stage ----------
FROM nginx:1.27-alpine AS runtime

# Копируем наш конфиг
COPY front-main/nginx.conf /etc/nginx/conf.d/default.conf

# Копируем билд
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]