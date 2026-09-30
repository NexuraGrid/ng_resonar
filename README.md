# Resonar

Un reproductor de música propio, tipo Spotify / YouTube Music, sin anuncios y
autohospedado.

- **Backend** — FastAPI + `ytmusicapi` (búsqueda) + `yt-dlp` + `ffmpeg`
  (streams y descargas).
- **Postgres** — usuarios, playlists, favoritos, historial, ajustes y el
  índice de videos guardados.
- **Redis** — sesiones, límite de intentos de login, caché de URLs de stream y
  estado de las descargas en segundo plano.
- **Frontend** — React + Vite + Plyr, servido por nginx que hace de proxy al API.
- **Todo dockerizado** — `docker compose up` y listo.

```
 internet ─▶ Cloudflare ─▶ cloudflared ─▶ 127.0.0.1:${PORT}
                                               │
                                        ┌──────▼─────┐  /api/*  ┌──────────┐  yt-dlp / ytmusicapi  ┌─────────┐
                                        │  frontend  │─────────▶│ backend  │──────────────────────▶│ YouTube │
                                        │   nginx    │          │ FastAPI  │                       └─────────┘
                                        └────────────┘          └────┬─────┘
                                                        red interna │ "data" (sin salida a internet)
                                                          ┌─────────┴─────────┐
                                                     ┌────▼─────┐        ┌────▼────┐
                                                     │ postgres │        │  redis  │
                                                     └──────────┘        └─────────┘
```

Solo nginx publica un puerto, y solo en `127.0.0.1`: desde fuera se entra por
el túnel de Cloudflare, no directamente por la LAN. Postgres y Redis no
publican puertos y solo los ve el backend. Detalles de despliegue, backups,
restauración y seguridad: **[docs/OPERATIONS.md](docs/OPERATIONS.md)**.

## Arranque rápido

```bash
git clone <este-repo> resonar && cd resonar
cp .env.example .env
# Obligatorio: pon una contraseña en POSTGRES_PASSWORD (sin ella compose no arranca)
#   openssl rand -hex 24
# Recomendado: BOOTSTRAP_TOKEN para proteger la creación del primer superadmin.
docker compose up -d --build
```

Abre <http://localhost:8080> (o el `PORT` que pongas en `.env`) **desde la
misma máquina**: el puerto solo escucha en `127.0.0.1`. Para entrar desde
otros dispositivos usa el túnel de Cloudflare.

> ⚠️ Nunca uses `docker compose down -v`: borra el volumen de Postgres (todos
> los usuarios, playlists, favoritos e historial). Para actualizar basta con
> `docker compose up -d --build`.

## Desarrollo (sin Docker)

Backend:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# necesitas ffmpeg en el PATH
uvicorn app.main:app --reload --port 8000
```

Necesitas un Postgres y un Redis locales (`DATABASE_URL`, `REDIS_URL`).

Frontend (proxya `/api` a `localhost:8000`):

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

## API

| Método | Ruta                      | Descripción                                        |
| ------ | ------------------------- | ------------------------------------------------- |
| GET    | `/api/search?q=&type=`    | Busca canciones (`type`: songs/videos/albums/…)    |
| GET    | `/api/suggest?q=`         | Autocompletado de búsqueda                         |
| GET    | `/api/related/{videoId}`  | Cola tipo "radio" a partir de una canción          |
| GET    | `/api/videos/search?q=`   | Busca videos en YouTube (yt-dlp flat search)       |
| GET    | `/api/videos/stream/{videoId}` | Video en streaming (proxy, soporta `Range`)   |
| GET    | `/api/stream/{videoId}`   | Audio en streaming (proxy, soporta `Range`)        |
| GET    | `/api/download/{videoId}?format=mp3` | Descarga el audio (`mp3`/`m4a`/`opus`/`flac`) con carátula y metadatos |
| GET    | `/api/sponsorblock/{videoId}` | Segmentos a saltar (proxy de SponsorBlock, cacheado) |
| GET    | `/api/lyrics?artist=&title=&album=&duration=` | Letra (proxy de LRCLIB; sincronizada si existe) |
| —      | `/api/playlists` (GET/POST) · `/api/playlists/{id}` (GET/PATCH/DELETE) · `.../tracks` (POST/PUT) · `.../tracks/{tid}` (DELETE) | CRUD de playlists (`POST` con `fromUrl` importa desde una URL de YouTube / YT Music; solo se aceptan esos dominios) |
| GET    | `/api/playlists/{id}/export` | Descarga la playlist como archivo `<nombre>.resonar.json` para compartirla |
| POST   | `/api/playlists/import`   | Crea en tu cuenta una copia de una playlist exportada (el cuerpo es el JSON del archivo) |
| POST   | `/api/download/batch` `{ids,name,format}` | Inicia un ZIP de varias pistas (máx. 100; 2 trabajos activos por usuario); devuelve `jobId` |
| GET    | `/api/download/batch/{jobId}` · `.../file` | Estado del ZIP · descarga del ZIP (solo quien lo pidió) |
| GET/PUT | `/api/settings`          | Credenciales de scrobbling (los secretos se ocultan en el GET) |
| POST   | `/api/scrobble/now-playing` · `/api/scrobble/submit` | Envía "reproduciendo ahora" / registra el listen |
| GET    | `/api/scrobble/lastfm/auth-url?callback=` · `.../callback` | Flujo de autorización de Last.fm |
| GET    | `/api/library/videos`     | Lista los videos guardados (con estado del trabajo) |
| POST   | `/api/library/videos/{videoId}?quality=1080` | Descarga+une video en HD y lo guarda (`force=true` para rehacer: solo quien lo guardó o un admin) |
| GET    | `/api/library/videos/{videoId}/file` | Reproduce el video guardado (soporta `Range`) |
| GET    | `/api/library/videos/{videoId}/download` | Descarga el archivo MP4 guardado |
| DELETE | `/api/library/videos/{videoId}` | Borra el video guardado (solo quien lo guardó o un admin) |
| GET    | `/api/health`             | Healthcheck                                        |

**Videos en HD / guardados:** la vista rápida (`/api/videos/stream`) es baja
resolución. `POST /api/library/videos/{id}` baja el mejor video + audio por
separado y los une con ffmpeg a un MP4 (hasta 1080p+), lo guarda en el volumen
`./media` y lo registra en la tabla `saved_videos` de Postgres. El trabajo corre
en segundo plano y su progreso vive en Redis (sobrevive a reinicios; si el
backend se cae a mitad, la descarga aparece como interrumpida y se puede
reintentar). La videoteca es compartida entre usuarios, pero solo quien guardó
un video (o un superadmin) puede quitarlo o cambiarle la calidad. Ojo con el
espacio en disco: los archivos se acumulan en `./media` hasta que los borras.

El endpoint `/api/stream` resuelve la URL real con `yt-dlp`, la cachea (usa el
`expire=` de la propia URL como TTL) y hace de proxy de los bytes para que
funcione el *seek* y no haya problemas de CORS ni de IP.

**Videos:** `/api/videos/stream` usa el cliente `android` de yt-dlp para obtener
un MP4 combinado (audio+video en un solo archivo) que el `<video>` reproduce
directo. Eso limita la calidad a 360p (a veces 720p); resoluciones mayores en
YouTube son *adaptive* y necesitarían MSE/DASH en el cliente o un remux con
ffmpeg en el servidor.

## Atajos de teclado (música)

`Espacio` play/pausa · `←` / `→` ±5s · `N` siguiente · `P` anterior · `M` mute.
Cuando hay un video en pantalla, las teclas controlan el video.

**Radio infinita:** botón "Radio" en la barra inferior. Al acabar la última
canción de la cola, añade ~20 similares vía `/api/related` y sigue sola.

**Cola:** botón con el número de pistas → panel lateral para saltar, reordenar
(↑/↓) y quitar.

**SponsorBlock:** en la vista de video, salta patrocinios/intros/outros
automáticamente. Se puede apagar con el chip "SponsorBlock".

**Playlists:** sección propia. Se guardan en Postgres, por usuario, así que se
ven igual desde cualquier dispositivo (y un usuario nunca ve las playlists de
otro). Se crean vacías, se importan desde una URL de playlist/álbum de YouTube
o YT Music, y desde la búsqueda se añaden canciones con el botón ＋. "Descargar
todo (MP3)" arma un ZIP en segundo plano.

**Compartir playlists:** en una playlist, "Compartir (exportar)" descarga un
archivo `<nombre>.resonar.json`. Pásaselo a otra persona (WhatsApp, correo…) y
en *Playlists → Importar archivo* obtiene su propia copia con las mismas
canciones. Es una copia: si luego uno la cambia, la del otro no cambia. Al
importar, el archivo se valida (máx. 1000 canciones, solo IDs de YouTube,
campos desconocidos descartados).

**Letra:** botón de letra en la barra → panel con la letra sincronizada
(resalta la línea actual; toca una línea para saltar ahí). Fuente: LRCLIB.

**Nivelar volumen:** botón en la barra. Pasa el audio por un compresor Web Audio
para que no salten los niveles entre canciones. Se recuerda encendido/apagado.

**PWA:** con `manifest.webmanifest` + `sw.js` la web es instalable (Añadir a la
pantalla de inicio → ventana propia sin barra del navegador). El service worker
cachea solo el "shell" y nunca toca `/api/`. Requiere HTTPS (tu túnel de
Cloudflare ya lo da). Controles en pantalla de bloqueo / auriculares vía
MediaSession (play/pausa, anterior/siguiente, ±10s, barra de progreso).

**Scrobbling (Ajustes):** ListenBrainz (pega tu *user token*) y Last.fm (crea una
API account, pega key + secret y pulsa "Conectar cuenta"). Se manda
"reproduciendo ahora" al empezar y el scrobble tras ~4 min o la mitad. Todo se
guarda en Postgres, por usuario (los secretos no se devuelven por la API).

## Autenticación

En el primer arranque, con la tabla de usuarios vacía, la web muestra una
pantalla única de "crear superadmin". No hay registro: solo el superadmin puede
crear más usuarios después (desde Ajustes). Cada usuario tiene su propia
biblioteca, playlists, favoritos e historial.

Las variables de sesión (`SESSION_COOKIE_NAME`, `SESSION_COOKIE_SECURE`,
`SESSION_*_TTL`, `BOOTSTRAP_TOKEN`, `DATABASE_URL`, `CORS_ORIGINS`) están
documentadas en `.env.example` con sus valores por defecto de `docker-compose.yml`.

**Acceso local por HTTP plano:** los valores por defecto usan el prefijo
`__Host-` con `Secure=true`, correcto detrás de HTTPS (incluido el túnel de
Cloudflare). Pero el navegador rechaza esa cookie sobre `http://` (todo lo que
no sea HTTPS ni `localhost` a secas) y el login falla en silencio. Para acceder
en local por HTTP plano poné `SESSION_COOKIE_NAME=resonar_session` y
`SESSION_COOKIE_SECURE=false`; mantené el nombre `__Host-` y `secure=true` en
cualquier despliegue con HTTPS.

## Notas de operación

- **`yt-dlp` se rompe con frecuencia** cuando YouTube cambia algo. Va sin fijar
  versión: `docker compose build --no-cache backend` para actualizarlo.
- **Bot checks** ("Sign in to confirm you're not a bot"): exporta un
  `cookies.txt` (formato Netscape) de una sesión con login, ponlo en
  `./config/cookies.txt` y descomenta `YTDLP_COOKIES` en `docker-compose.yml`.
- **Redis es obligatorio**: guarda las sesiones, el límite de intentos de
  login y el estado de las descargas. Tiene un volumen propio (`redis-data`),
  así que las sesiones sobreviven a `docker compose down && up`.
- Un solo worker de uvicorn por defecto. El estado de las descargas ya está en
  Redis, pero el límite de descargas simultáneas es por proceso: con más
  workers habría más descargas a la vez.
- **Backups:** `scripts/backup.sh` (dump de Postgres + `./data`) y
  `scripts/install-backup-timer.sh` para programarlo a diario. Restauración y
  rotación de secretos en [docs/OPERATIONS.md](docs/OPERATIONS.md).
- **Seguridad:** contenedores sin root, con capacidades eliminadas y sistema de
  archivos de solo lectura; nginx envía CSP/HSTS y demás cabeceras
  (`frontend/security-headers.conf`: si añades un `<script>` inline a
  `index.html`, actualiza su hash en el CSP); el backend rechaza escrituras
  con cookie que vengan de otro origen.

## Legal

Pensado para **uso personal y autohospedado**. Reproducir/descargar contenido con
copyright puede infringir los Términos de YouTube y la ley de tu país. Para algo
público, apunta a fuentes con licencia libre (Jamendo, Audius, Free Music
Archive, Internet Archive).
