FROM node:20-alpine

WORKDIR /app

# package-lock.json is intentionally not copied.
# Some Windows/Docker/npm combinations can leave a broken lock/node_modules state.
COPY package.json ./

RUN npm install -g npm@9.9.4 \
    && npm config set registry https://registry.npmjs.org/ \
    && npm install --no-audit --no-fund --legacy-peer-deps \
    && test -x ./node_modules/.bin/vite

COPY . .

EXPOSE 3000

CMD ["sh", "-c", "./node_modules/.bin/vite --host 0.0.0.0 --port 3000"]
