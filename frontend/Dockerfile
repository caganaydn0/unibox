# syntax=docker/dockerfile:1
#
# Next.js standalone çok aşamalı derleme. Faz 6 (dağıtım paketi) — YOL_HARİTASI.md.
#
# ÖNEMLİ: NEXT_PUBLIC_* değişkenleri istemci JS paketine BUILD ZAMANINDA
# gömülür — çalışma zamanı `environment:` değişikliğinin hiçbir etkisi olmaz.
# Ölçüldü: BACKEND_URL de aynı kaderi paylaşıyor — next.config.ts'deki
# rewrites() derleme sırasında BİR KEZ değerlendirilip standalone çıktıya
# gömülüyor; `docker run -e BACKEND_URL=...` ile verilen çalışma zamanı
# değeri SESSİZCE yok sayılıyor ve proxy build zamanındaki (yanlış)
# varsayılana (localhost:8000) düşüyor. Bu yüzden ÜÇÜ DE build ARG'ı.

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_WS_URL
ARG BACKEND_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL} \
    BACKEND_URL=${BACKEND_URL}

RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
# rewrites() build zamanında donduğu için bunun burada tekrar tanımlanması
# davranışı değiştirmez — yalnızca process.env üzerinden okuyan başka bir
# runtime kod yolu olursa diye tutarlılık amacıyla.
ARG BACKEND_URL
ENV BACKEND_URL=${BACKEND_URL}

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD node -e "fetch('http://localhost:3000/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
