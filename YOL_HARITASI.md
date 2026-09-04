# UniBox — Üretime Hazırlık Yol Haritası ve Durum

> # 📍 ROADMAP'İN TÜM FAZLARI TAMAMLANDI (0-7) — kalan: gerçek domain/sunucu
>
> **Bitenler:** Faz 0-7 tamamı — zemin, ölçüm, güvenlik, chunking, sorgu,
> öğrenci UI, dağıtım paketi (Docker/CI/Caddy/yedekleme), reranker (ölçüldü,
> kapalı kalıyor).
> **Kalan tek şey kod değil, bilgi:** `Caddyfile` + `docker-compose.prod.yml`
> gerçek bir domain/sunucu YER TUTUCUSUYLA yazıldı
> (`unibox.universite.edu.tr`). Gerçek değerler belli olunca ikisinde de
> (birbiriyle TUTARLI şekilde) güncellenip `docker compose -f
> docker-compose.prod.yml up -d --build` ile devreye alınabilir.
>
> Faz 6 detayları için: [Faz 6 — Dağıtım paketi](#faz-6--dağıtım-paketi-2-3-gün) ·
> Faz 7 için: [Faz 7 — Reranker](#faz-7--reranker-kill-criterionlı)

**Son güncelleme:** 4 Eylül 2026
**Çalışma dalı:** `feat/uretim-hazirlik` (main'den 15 commit ileride)

---

## ✅ Bu oturumda kapatıldı — uydurma bug'ı (prompt + kök neden)

Önceki oturumda `email_workflow.py`'ye eklenen uydurma-karşıtı kurallar
(`SYSTEM_PROMPTS["general"]`) **doğrulanmamış** durumdaydı. Doğrulanınca aynı
soru ("doktora yeterlik şartları nelerdir?") **hâlâ** mevzuatta hiç geçmeyen
bir liste uyduruyordu — prompt düzeltmesi tek başına yeterli değildi.

**Gerçek kök neden:** `llm_provider.py`'deki `OllamaProvider.generate()`
Ollama'ya `num_ctx` **hiç göndermiyordu**, dolayısıyla sunucu varsayılanı
(2048 token) kullanılıyordu. RAG bağlamı (7 chunk × ~500 kelime) rahatlıkla
2048'i aşıyor; Ollama fazlasını mesajın **başından** sessizce atıyor —
hem uydurma-karşıtı kurallar hem MADDE 31'in metni kayboluyordu.

Ölçüldü (aynı soru, aynı context):
| | prompt token | yanıt |
|---|---|---|
| num_ctx yok (varsayılan 2048) | 2050 (kırpılmış) | 10 maddelik tamamen uydurma liste (yabancı dil belgesi, motivasyon mektubu, referans — mevzuatta yok) |
| num_ctx=8192 | 4885 (tam) | MADDE 31'in birebir doğru özeti |

**Düzeltme:** `config.py`'ye `OLLAMA_NUM_CTX: int = 8192` eklendi (llama_cpp
yolunun `LLAMA_CPP_N_CTX` değeriyle aynı), `llm_provider.py`'de Ollama
isteğine `options.num_ctx` olarak geçiliyor. `.env.example` senkron edildi.
203/203 test geçti; gerçek sunucu üzerinden uçtan uca doğrulandı.

**Not — henüz kapatılmayan artık kılavuz sınır:** Sohbet ve gelen e-posta
yolları (`email_analyzer.py`), taslak yolunun aksine (`DRAFT_CONTEXT_MAX_CHARS
= 2500`), `query_spec()`'i **karakter sınırı olmadan** çağırıyor. Worst-case
7 chunk × ~2500 karakter ≈ 17500 karakter (~7000 token) tek başına context'e
girebilir; 8192'lik num_ctx'i yine de aşıp aynı sessiz kırpmayı
tetikleyebilir. Bu oturumda ölçülen soru için sorun çıkarmadı ama
sistematik olarak kapatılmadı — ya `azami_karakter` sınırı eklenmeli ya da
`RAG_TOP_K`/`num_ctx` birlikte daha büyük bir bütçeye göre kalibre edilmeli.

---

## Nerede kaldık

| Faz | Konu | Durum |
|---|---|---|
| 0 | Zemin: commit, env/belge tutarlılığı, DB doğrulama | ✅ Bitti |
| 1 | Ölçüm zemini: fixture korpusu, pytest, baseline | ✅ Bitti |
| 2 | Kritik hata + güvenlik düzeltmeleri | ✅ Bitti |
| 3 | RAG çekirdeği: madde-farkındalıklı chunking + füzyon | ✅ Bitti |
| 4 | Sorgu birleştirme + bağlam bütünlüğü | ✅ Bitti |
| 5 | Öğrenci sohbet arayüzü | ✅ Bitti |
| 6 | Dağıtım paketi (Docker, CI, Caddy, yedekleme) | ✅ Bitti (domain yer tutucu) |
| 7 | Reranker (ölçüldü, kill-criterion geçilemedi — kapalı) | ✅ Bitti |

---

## Ölçülen sonuçlar

Sabit fixture korpusu: **28 doküman / 109 chunk**, damga `37589fde`.
Ölçüm ayrı bir veritabanında (`unibox_eval`) koşar; geliştirme verisi karışmaz.

### Yönetmelik madde geri getirimi (n=55)

| | @1 | @3 | @7 | MRR |
|---|---|---|---|---|
| Başlangıç | %31 | %60 | %67 | 0.449 |
| **Şimdi** | **%42** | **%69** | **%78** | **0.555** |
| | +11 | +9 | +11 | |

### Rehber doküman geri getirimi (n=25)

| | @1 | @3 | @7 |
|---|---|---|---|
| Başlangıç | %68 | %76 | %100 |
| **Şimdi** | %60 | %76 | %96 |

`@3` (planın gerileme koruma ölçütü) sabit kaldı. `@1`'deki düşüşün bir kısmı
gold etiketin fazla katı olmasından: "bu dönemin ödemesini ne zaman yapmam
gerekiyor?" sorusunu *Kayıt Yenileme* rehberi kazanıyor ve metni birebir
"öğrenci harcını yatırıp..." diyor — yanlış değil, etiket başka dokümanı
gösteriyor.

### Gerçek e-posta gövdeleri (n=18, Faz 4'te eklendi)

| | @1 | @3 | @7 | MRR |
|---|---|---|---|---|
| Ham gövde (eski) | %56 | %67 | %67 | 0.602 |
| **Temizlenmiş (yeni)** | **%67** | **%78** | **%78** | **0.713** |

Eşleştirilmiş: **2 düzeldi, 0 bozuldu.**

---

## Test altyapısı

**203 test.** 34'ü servis gerektirmiyor (CI'da her commit'te koşabilir).

```bash
cd backend
uv run pytest tests/ -q                                  # hepsi
uv run pytest tests/ -q -m "not rag_eval and not slow"   # DB/Ollama gerekmez
UNIBOX_WRITE_BASELINE=1 uv run pytest tests/rag/ -s      # baseline dondur
UNIBOX_EVAL_REBUILD=1 uv run pytest tests/rag/ -s        # korpusu zorla kur
```

Servis kapalıysa testler **başarısız olmaz, atlanır**.

**Baseline politikası:** yüzde farkı değil, *eşleştirilmiş* karşılaştırma.
`eval_regulation` n=16'da binom standart hatası 10.8 puan; "%75 → %81" farkı
ölçülemez, "5 düzeldi 0 bozuldu" ise anlamlıdır.

---

## Testlerin bulduğu, planda olmayan gerçek buglar

Bunlar aranmadı; yazılan testler ortaya çıkardı.

1. **`+90` formatlı telefonlar hiç maskelenmiyordu** — `\b` ile `+` arasında
   kelime sınırı oluşamaz, alternatif hiç eşleşmiyordu. (KVKK)
2. **`passlib` + `bcrypt` 4.x uyumsuz** — `hash_password` kurulu sürümlerle
   **hiç çalışmıyordu**. bcrypt'e doğrudan bağlandı.
3. **Türkçe parola girişte 500 veriyordu** — `secrets.compare_digest` str'de
   yalnızca ASCII kabul ediyor.
4. **PII temizliği meşru cümleleri yok ediyordu** — "ad soyad" geçen her satır
   komple siliniyordu.
5. **`sanitize_draft_body(None)` çöküyordu** — LLM `{"body": null}` dönerse.
6. **Boş sorgu 500 veriyordu** — pgvector boş vektörü reddediyor.
7. **Yükleme doğrulamasında iki açık** — "application/pdf" diye bildirilen
   `.exe` kabul ediliyordu; kısa ikili başlıklar (ELF) NUL içermeden geçiyordu.
8. **`email_logs.recipient_display`'e öğrencinin kişisel adresi düz metin
   yazılıyordu** — `sender_email_enc` KVKK gereği silinirken.
9. **Korpus damgası chunker sürümünü içermiyordu** — chunking değişince damga
   değişmedi, ölçüm sessizce eski chunk'lara karşı yapıldı.
10. **Sohbet promptunda uydurma-karşıtı kural yoktu** (yukarıda düzeltildi).
11. **Ollama'ya `num_ctx` hiç gönderilmiyordu** — sunucu varsayılanı (2048)
    RAG bağlamını sessizce kırpıyordu; #10'un asıl kök nedeni buydu (bkz.
    yukarıdaki bölüm).
12. **`POST /drafts/{id}/retry` her zaman 500 veriyordu** — fonksiyon içinde
    `EmailDraftStatus`'u gölgeleyen kullanılmayan bir yerel `import` vardı;
    Python bir ismi fonksiyon içinde HERHANGİ bir yerde atarsa (yerel import
    dahil) tüm kapsamda yerel sayar, kullanım importtan önce çalışınca
    `UnboundLocalError`. Ruff (`F823`) buldu, hiç test kapsamıyordu.
13. **Admin bir taslağı onaylayıp/reddedince diğer admin sekmelerinin
    bekleyen sayacı güncellenmiyordu** — frontend `"email_approved"`/
    `"email_rejected"` event'lerini dinliyordu ama backend bunları hiç
    yayınlamıyordu. `next build`'in tip denetiminde ortaya çıktı.
14. **Yanıtı 20 saniyeden uzun süren her sohbet mesajında WS bağlantısı
    sunucu tarafından kesiliyordu.** uvicorn'un varsayılan
    `--ws-ping-timeout`'u (20sn), `chat_websocket`'in tek bir yavaş LLM
    yanıtını işlerken (ölçüldü: 88-95sn — RAG bağlamı büyükse daha da
    uzayabilir) dolduğu için sunucu bağlantıyı kendisi 1011 "keepalive ping
    timeout" ile kapatıyordu. Yanıt DB'ye kaydediliyordu (konuşma geçmişinde
    görünüyordu) ama öğrenciye CANLI hiç ulaşmıyordu — sayfa yenilenmeden
    fark edilmezdi. Gerçek uçtan uca testte (WS ile gerçek bir soru sorup
    yanıt beklerken) ortaya çıktı. `--ws-ping-timeout 300`
    (`llm_provider.py`'nin kendi httpx timeout'uyla aynı üst sınır) ile
    düzeltildi — `backend/Dockerfile` CMD'sine ve `CLAUDE.md`'deki dev
    komutuna eklendi. Aynı sorguyla düzeltme sonrası uçtan uca doğrulandı.

### Planın öngörüp gerçekleşmeyen bulgusu

**tsquery çökmesi gerçekleşmedi.** PostgreSQL `http://` önekini tüketiyor, `:`
lexeme'e girmiyor. Tırnaklama yine de yapıldı ama gerekçesi *doğruluk*,
aciliyet değil.

---

## ✅ Faz 5 — Öğrenci sohbet arayüzü

`frontend/src/app/chat/page.tsx` eklendi — `(dashboard)` route group'unun
dışında, JWT guard'a takılmıyor. Yeni dosyalar: `lib/chatApi.ts` (admin
`request()`'ten KASITLI ayrı — auth header eklemiyor, 401'de `/login`'e
yönlendirmiyor; bir öğrenci asla admin login'ine fırlatılmamalı),
`components/chat/{MessageBubble,DraftPreviewCard}.tsx`. `useWebSocket.ts`'e
geriye uyumlu bir `onClose` callback'i eklendi (admin `WsContext.tsx`
etkilenmedi).

- Oturum: `sessionStorage["unibox_chat_token"]`; yoksa `POST /chat/session`
  ile sunucu-üretimli jeton alınır.
- WS 4401 (geçersiz/silinmiş oturum) → jeton temizlenir, sohbete bilgi notu
  düşülür, arka planda yeni oturum açılıp otomatik yeniden bağlanılır — sonsuz
  yeniden bağlanma döngüsüne düşmeden ve öğrenciyi çıkmaz ekranda bırakmadan.
- `DRAFT_CREATED` durumunda `draft_preview` bir kart olarak gösteriliyor;
  "Evet, gönder" / "Hayır, iptal" butonları backend'in anladığı anahtar
  kelimeleri normal kullanıcı mesajı gibi gönderiyor (yapılandırılmış bir
  "approve" eylemi backend'de yok).
- KVKK: üstte "verileriniz N gün saklanır" notu + "Sohbetimi sil" butonu
  (`window.confirm` — kod tabanındaki tek onay deseni, `emails/[id]/page.tsx:51`
  ile aynı) → `DELETE /chat/session/{token}`.
- Doğrulama: `tsc --noEmit` temiz (yeni dosyalarda 0 hata — repo'da zaten var
  olan 5 ilgisiz hata var, bkz. not). Gerçek backend+frontend+Ollama ile uçtan
  uca test edildi: session açma → genel soru (RAG) → `certificate_request`
  intent'i → `COLLECTING_INFO` → `DRAFT_CREATED` (`draft_preview` dolu) →
  "evet, gönder" → `PENDING_APPROVAL` → KVKK silme → yeniden bağlanınca 4401.

**Not — bu oturumda dokunulmadı, ayrı bir backend sorunu:** Aynı testte
`certificate_request` akışı `REQUIRED_FIELDS`'te olmayan "öğrenci numaranız
nedir?" diye sordu ve taslak gövdesine boş alanlar (`Talep edilen belge
türü: .`) yazdı — `_ask_next_field`/`_handle_collecting` prompt'larının küçük
modelde güvenilirlik sorunu, Faz 5 kapsamı dışında.

**Not — `npm run lint` çalışmıyor:** Next.js 16 `next lint` komutunu kaldırdı;
`package.json`'daki `lint` script'i güncellenmemiş. Bu oturumda `tsc --noEmit`
ile tip kontrolü yapıldı; `lint` script'inin ESLint CLI'a taşınması (`eslint .`)
ayrı, küçük bir iş.

## Faz 6 — Dağıtım paketi (2-3 gün)

### ✅ Güvenlik/kod düzeltmeleri (bu oturumda bitti)

- **WS token'ı artık URL'de değil.** Tarayıcı WebSocket API'si el sıkışmaya
  özel header ekleyemediği için gerçek bir "header'a taşıma" mümkün değildi;
  pratik eşdeğeri uygulandı: `monitor.py` artık `?token=` almıyor, bağlantı
  kurulduktan SONRA ilk çerçeve olarak `{"type":"auth","token":...}` bekliyor.
  `ws_manager.connect_admin()` artık `accept()` çağırmıyor (çağıran —
  `monitor.py` — auth çerçevesini okuyabilmek için önce kendisi accept ediyor).
  Frontend: `useWebSocket.ts`'e `getInitialMessage` eklendi, `WsContext.tsx`
  jetonu `tokenRef`'te tutup bağlantı açılınca gönderiyor.
- **`monitor.py`'ye Origin kontrolü eklendi** — `settings.cors_origin_listesi`
  (main.py'deki CORSMiddleware ile aynı liste) kullanılıyor; üretimde
  `CORS_ORIGINS` ayarlanmamışsa liste boş döner ve TÜM bağlantılar reddedilir
  (sessiz açık sistem yerine gürültülü hata — kod tabanındaki mevcut felsefeyle
  tutarlı, bkz. `config.py::_uretimde_guvenli_mi`).
- **Connection pool ayarları `Settings`'e taşındı**: `DB_POOL_SIZE`,
  `DB_MAX_OVERFLOW`, ve eskiden hiç olmayan `DB_POOL_RECYCLE`/`DB_POOL_TIMEOUT`
  eklendi (`db/session.py`, `.env.example`).
- **`alembic.ini`'deki hardcoded parola temizlendi** — placeholder'a çevrildi;
  doğrulandı ki bu değer zaten hiç kullanılmıyordu (`alembic/env.py`,
  `config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)` ile hem
  online hem offline modda üzerine yazıyor).
- Doğrulama: 4 senaryo gerçek WS bağlantısıyla test edildi — doğru
  origin+auth (açık kalır), yanlış origin (el sıkışmada HTTP 403), auth
  çerçevesi gelmezse 10 sn sonra 4001, geçersiz token 4001. `alembic current`
  gerçek DB'ye bağlandığını doğruladı. 203/203 backend testi, `tsc --noEmit`
  temiz.

### ✅ Docker + CI paketi (bu oturumda bitti)

- `backend/Dockerfile` — uv, iki aşamalı (önce yalnızca `pyproject.toml`+
  `uv.lock` ile bağımlılık katmanı cache'lenir, sonra kod kopyalanır).
  Migration'lar imajda OTOMATİK ÇALIŞMAZ (kasıtlı — hata container'ı
  restart döngüsüne sokar); deploy adımı olarak elle:
  `docker compose -f docker-compose.prod.yml run --rm backend uv run alembic upgrade head`
- `frontend/Dockerfile` — Next standalone (`next.config.ts`'e `output:
  "standalone"` eklendi).
- **Kritik bulgu:** `NEXT_PUBLIC_*`'in build-time'da göründüğü biliniyordu,
  ama **`BACKEND_URL` de öyle çıktı** — `next.config.ts`'deki `rewrites()`
  derleme sırasında BİR KEZ değerlendirilip standalone çıktıya gömülüyor;
  `docker run -e BACKEND_URL=...` (çalışma zamanı) SESSİZCE yok sayılıyor,
  proxy build zamanındaki varsayılana (`localhost:8000`) düşüp gerçek
  backend'e hiç ulaşamıyordu (500). Ölçüldü: build-arg olmadan `/api/backend/*`
  her zaman 500, build-arg ile (backend servis adı `http://backend:8000`)
  doğru şekilde 401/200 dönüyor. Üçü de artık `frontend/Dockerfile`'da build
  ARG'ı — **domain değişirse frontend imajı yeniden derlenmeli.**
- `docker-compose.prod.yml` — 4 servis (postgres, ollama, backend, frontend;
  mailhog yok), healthcheck + `restart: unless-stopped`, portlar yalnızca
  `127.0.0.1`'e bağlı (dev compose'daki KVKK kuralıyla aynı — dışa açılım
  nginx/Caddy ile, aşağıya bkz). `docker compose ... config` ile doğrulandı.
- GitHub Actions (`.github/workflows/ci.yml`): backend (ruff + pytest) ve
  frontend (tsc + `next build`) ayrı job'lar.
- **Ruff CI'a eklenirken 288 mevcut bulgu çıktı** (çoğu `Optional[X]`→
  `X | None` gibi salt stil — ruff'ın örtük geniş varsayılanı, pyproject.toml'da
  açık `select` yoktu). Kullanıcıyla görüşüldü: CI'a dar bir kural seti
  (`select = ["E9", "F"]` — syntax + pyflakes) eklendi, geniş stil taraması
  **bilinçli olarak ertelendi** (bazı bulgular zaten `pytest.ini_options`'ta
  "ayrı bir iş" diye not düşülmüştü, ör. `DTZ003`/datetime.utcnow).
- **Ruff'ın bulduğu 2 gerçek bug, düzeltildi:**
  1. `email_drafts.py::retry` — fonksiyon içinde `EmailDraftStatus`'u
     GÖLGELEYEN yerel bir `import` vardı (`VALID_TRANSITIONS` için eklenmiş,
     kullanılmıyordu). Python'da bir isim fonksiyon içinde HERHANGİ bir
     yerde atanırsa (yerel import dahil) tüm fonksiyon kapsamında yerel
     sayılır — satır 263'teki kullanım importtan ÖNCE çalıştığı için **her
     `/drafts/{id}/retry` çağrısı `UnboundLocalError` ile 500 veriyordu.**
     Hiç test kapsamıyordu. Yerel import silindi (modül seviyesinde zaten
     import edili).
  2. `rag_engine.py` içinde asla okunmayan bir `görünür` tuple'ı (ölü kod,
     gerçek filtre mantığı zaten başka yerde satır içi kuruluyordu) —
     davranış etkisi yok, kaldırıldı.
- **Yan ürün:** `WsContext.tsx` `"email_approved"`/`"email_rejected"`
  event'lerini dinliyordu ama backend bunları **hiç yayınlamıyordu** (tip
  hatası ruff/tsc değil `next build`'de TS derleyicisinden çıktı, ayrıca
  incelenince fark edildi) — admin bir taslağı onaylayıp/reddedince diğer
  admin sekmelerinin bekleyen taslak sayacı gerçek zamanlı güncellenmiyordu.
  `approve_draft`/`reject_draft`'a mevcut `email_pending_approval` deseniyle
  birebir aynı şekilde eksik broadcast'ler eklendi.
- Doğrulama: her iki imaj gerçekten derlendi VE çalıştırıldı (gerçek
  postgres/ollama container'larına bağlanarak, `/health` `/ready` healthy),
  `docker compose config` ile compose dosyası doğrulandı, 203/203 backend
  testi, `tsc --noEmit` ve `next build` temiz.

### ✅ Ters proxy + yedekleme (bu oturumda bitti — domain hâlâ YER TUTUCU)

Kullanıcıyla netleşti: Caddy (nginx değil — TLS'i otomatik alıp yeniliyor,
config çok daha kısa), gerçek domain henüz yok → `unibox.universite.edu.tr`
yer tutucusuyla hazırlandı, yedekleme yalnızca DB için otomatik +
`FERNET_KEY` için rehberlik (otomatik saklama YOK).

- **[`Caddyfile`](Caddyfile)** (repo kökü) — gerçek Caddy imajıyla
  `caddy validate` ile doğrulandı ("Valid configuration"). İçerik:
  - HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, CSP
    (`default-src 'self'` — sıkı, WS de aynı origin'den gittiği için
    ayrıca gevşetmeye gerek yok), `Server` header'ı kaldırılıyor.
  - `request_body { max_size 25MB }` — `MAX_UPLOAD_SIZE_MB=20`'nin üzerinde
    pay bırakılmış bir ön kapı; asıl sınırı uygulama zaten uyguluyor.
  - **WS yönlendirmesi kritik:** `/api/v1/chat/ws/*` ve `/api/v1/monitor/ws`
    DOĞRUDAN `backend:8000`'e gider (tarayıcı bu yollara `NEXT_PUBLIC_WS_URL`
    ile frontend proxy'sini ATLAYARAK bağlanıyor, bkz. `WsContext.tsx` /
    `chat/page.tsx`). Geri kalan her şey (sayfalar + `/api/backend/*` REST
    proxy'si) `frontend:3000`'e. Caddy'de nginx'in aksine WS upgrade için
    özel bir yönerge gerekmiyor — `reverse_proxy` otomatik algılıyor.
  - Let's Encrypt e-posta ve domain'in **ikisi de yer tutucu** — gerçek
    sunucu/domain belli olunca burada VE `docker-compose.prod.yml`'deki
    `NEXT_PUBLIC_API_URL`/`NEXT_PUBLIC_WS_URL`'de TUTARLI şekilde
    güncellenmeli (ikisi uyuşmazsa tarayıcı yanlış origin'e bağlanır).
- **`docker-compose.prod.yml`** — 5. servis olarak `caddy` eklendi (imaj
  `caddy:2-alpine`). Tek kamuya açık servis bu — 80/443 **0.0.0.0**'a
  bağlı (diğer tüm servisler KVKK gereği `127.0.0.1`'de kalmaya devam
  ediyor). `docker compose config` ile yeniden doğrulandı.
- **[`scripts/backup_db.sh`](scripts/backup_db.sh)** (yeni, bash — repodaki
  diğer script'ler Python ama bu doğası gereği bir cron/ops betiği) —
  `pg_dump` alıp gzip'ler, **önce `.tmp` dosyasına yazıp atomik `mv` yapar**
  (yarıda kesilirse bozuk bir yedek kalmasın diye), `RETENTION_DAYS`
  (varsayılan 30) üzerini siler. `BACKUP_DIR`/`RETENTION_DAYS`/
  `POSTGRES_CONTAINER` ortam değişkenleriyle ayarlanabilir.
  - **`FERNET_KEY` bu script'e KASITLI OLARAK dahil değil** — script'in
    başında büyük bir uyarı var: DB yedeğiyle aynı yerde saklanırsa KVKK
    şifrelemesi anlamsızlaşır, ayrı bir kasada (parola yöneticisi/secrets
    vault) saklanmalı. Otomatik hiçbir yere kopyalanmıyor.
  - Header yorumunda cron örneği var (`0 3 * * * .../backup_db.sh`).
  - **Doğrulama:** gerçek `unibox_postgres` container'ına karşı çalıştırıldı
    — geçerli, 739 satırlık bir pg_dump çıktısı üretti (gzip açılıp
    kontrol edildi). Retention temizliği de test edildi: 40 günlük sahte
    bir yedek dosyası `RETENTION_DAYS=30` ile doğru şekilde silindi, taze
    dosyalar kaldı.
  - **Bulunan gerçek hata:** ilk yazımda geçici dosya değişkeni Türkçe
    karakterli (`geçici`) adlandırılmıştı — POSIX kabuk değişken adları
    yalnızca ASCII kabul ediyor, bash bunu komut sanıp "command not found"
    ile patlıyordu. `gecici` olarak düzeltildi. (Python kod tabanındaki
    Türkçe tanımlayıcı kuralı bash'e taşınmıyor.)

## Faz 7 — Reranker (kill-criterion'lı) — ✅ ÖLÇÜLDÜ, KAPALI KALIYOR

**Sonuç: kill-criterion GEÇİLEMEDİ.** `bge-reranker-base`, Türkçe yönetmelik
sorularında sonucu düzeltmek yerine **kötüleştirdi**:

| | düzelen | bozulan | net |
|---|---|---|---|
| madde@1 | 6 | 13 | **-7** |
| madde@3 | 5 | 13 | **-8** |
| madde@7 | 2 | 9 | **-7** |

(n=55, `regulation_madde.jsonl`, reranker'sız dondurulmuş baseline'a karşı
`paired_diff`.) Hedef "+10 puan" değil, tam tersi yönde büyük bir gerilemeydi.
Muhtemel sebep: `bge-reranker-base` esasen İngilizce/Çince için eğitilmiş,
çok dilli değil — `bge-m3` (embedding) ile karıştırılmamalı. Roadmap'in
önerdiği yükseltme yolu `bge-reranker-v2-m3` (çok dilli) bu makinede
denenemedi: **VRAM ≥ 16GB** şartı, geliştirme makinesi RTX 3050 Ti 4GB.

**Karar (kullanıcıyla netleşti):** Kod kalıyor, `RERANKER_ENABLED=False`
varsayılanı korunuyor — production davranışına sıfır etki. İleride
`bge-reranker-v2-m3` uygun donanımda tekrar denenebilir; entegrasyon zaten
hazır, yalnızca `RERANKER_URL`'in işaret ettiği model değişir.

**Nasıl entegre edildi (kapalıyken de kod yolu duruyor):**
- `docker-compose.yml`: `reranker` servisi (HF TEI, CPU imajı
  `ghcr.io/huggingface/text-embeddings-inference:cpu-latest`). **Healthcheck
  yok** — imaj scratch tabanlı, içinde sh/curl/wget hiçbiri yok (ölçüldü);
  hazır olup olmadığı host'tan `curl http://localhost:8090/health` ile
  kontrol edilir.
- `app/services/reranker.py` — `POST /rerank` istemcisi. API şeması gerçek
  container'a karşı doğrulandı: `{"query","texts"}` → `[{"index","score"}]`,
  skorlar zaten azalan sırada. Hata/timeout → `None`, çağıran RRF sırasına
  düşer — istek asla düşmez.
- `app/services/rag_engine.py::_siralayip_sec` — rerank adımı intent-bonuslu
  RRF sıralamasından SONRA, doküman-çeşitliliği kapısından ÖNCE (roadmap'in
  şartı). Yalnızca ilk `RERANKER_TOP_N` (20) aday gönderilir, kalanı RRF
  sırasında arkada kalır.
- `app/config.py`: `RERANKER_ENABLED=False`, `RERANKER_URL`,
  `RERANKER_TIMEOUT_MS=800` (tek bütçe — ≤800ms zaten ≤5sn'yi de sağlıyor,
  akışa özel ayrı bütçe gerekmedi), `RERANKER_TOP_N=20`.
- `tests/rag/test_reranker_eval.py` — kalıcı bir regresyon testi DEĞİL, tek
  seferlik karar ölçümü aracı; reranker container'ı kapalıyken sessizce
  atlanır. İleride farklı bir modelle yeniden ölçmek için hazır.
- **Ölçüm sırasında bulunan gerçek metodolojik hata:** ilk denemede
  `RERANKER_TIMEOUT_MS=800` (üretim bütçesi) ile koşuldu ve 55 sorunun
  **55'i de** zaman aşımına uğrayıp sessizce RRF'ye düştü — "reranked" ölçüm
  aslında rerank'siz ölçümle birebirdi, anlamsızdı. Ölçüm scripti bunun için
  timeout'u geçici olarak 30sn'ye çıkarıyor (kalite tavanını bulmak, üretim
  gecikme bütçesinden bağımsız) — üstteki tablo BU koşumun sonucu.
- Doğrulama: `RERANKER_ENABLED=False` iken 203/203 test + tüm RAG
  baseline'ları DEĞİŞMEDEN geçti (sıfır regresyon kanıtı), ruff temiz.

---

## Mimari notlar (devam ederken bilinmesi gerekenler)

### Hibrit arama

```
soru → ┬→ anlamsal: bge-m3 → pgvector cosine (HNSW)  ─┐
       └→ sözcüksel: 'turkish' FTS → ts_rank (GIN)   ─┴→ RRF
                                                        ↓
                        kapsam kapısı (VE koşulu) → intent bonusu
                                                        ↓
                        doküman çeşitliliği + doldurma turu → top-K
```

- **`search()` ALAKA sırasını korur.** Belge sırasına dizme yalnızca LLM
  bağlamı kurulurken (`_baglam_kur`) uygulanır. Bu ayrım ölçümle öğrenildi:
  dizmeyi `search()`'e koyunca `recall@1` %42→%24 düştü (gerçek kayıp değil,
  sıralamayı bilinçli bozduğumuz için metrik anlamını yitirdi).
- **Kapsam kapısı füzyondan SONRA ve VE koşulu:** soru ancak hem anlamsal
  olarak uzaksa hem de hiçbir sözcüksel eşleşme yoksa kapsam dışı sayılır.
- **İki geri getirim bağımsız arıza alanı:** Ollama kapalıysa yalnız-FTS
  ile devam eder; sohbet 500 vermez.

### Madde-farkındalıklı chunking (`app/services/chunking.py`)

- "1 chunk = 1 madde". Mod seçimi otomatik: 3'ten az madde bulunan metin
  eski sabit bölücüye düşer (rehber/SSS/DOCX geri uyumlu).
- Regex dört gerçek PDF'te doğrulandı: üç tire varyantı (`-` `–` `—`), harf
  ekli numara (`41/A`), `GEÇİCİ MADDE` ayrı serisi, title-case `Madde 1 -`.
- **Üst bilgiye BÖLÜM ADI EKLENMEZ** — ölçümle elendi. PDF'te bölüm açıklaması
  çok satıra yayıldığı için yalnızca ilk kelimesi yakalanıyor ve
  "YEDİNCİ BÖLÜM — Çeşitli Ek süre" gibi bozuk çıkıyordu.
- **Doküman adı da eklenmez** — eklenirse o dokümanın tüm chunk'ları başlık
  kelimeleriyle eşleşip havuzu doldurur.

### Kalibrasyon notları nerede

`config.py` ve `chunking.py` içindeki yorumlar, **denenip elenmiş** ayarları
kaydediyor (ör. 150 kelimelik chunk recall@3'ü %70→%50 düşürdü). Bunlar bu
repodaki en değerli dokümantasyon — **sessizce üzerine yazmayın.**

---

## Ortam

```bash
docker compose up -d       # postgres :5432, ollama :11435, mailhog :8025
```

**Uygulama HOST'taki Ollama'yı kullanır (`:11434`)** çünkü `bge-m3` orada
yüklü. Container'da yok — `.env`'i 11435'e çevirirseniz önce modelleri
indirin, yoksa RAG hiçbir sonuç döndürmez.

Migration zinciri: `0001 → 0008`. Son ikisi bu çalışmada eklendi:
- `0007` — `conversations.session_token` kısmi tekillik indeksi
- `0008` — `document_chunks.meta_json` (JSONB) + `chunk_index` tekilliği
  **Bu migration'dan sonra tam yeniden indeksleme gerekir.**

```bash
cd backend && uv run python ../scripts/reindex_documents.py
```
