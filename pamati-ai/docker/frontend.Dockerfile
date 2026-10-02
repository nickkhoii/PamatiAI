FROM node:24-alpine
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN chown -R node:node /app
USER node
EXPOSE 3000
CMD ["npm", "run", "dev"]
