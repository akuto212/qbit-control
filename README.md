# qbt-control

Небольшая страница управления Alternative Speed Limits в **qBittorrent 5.2.3**: текущие Download/Upload, состояние лимита и одна кнопка включения/выключения. Python + FastAPI, обычный HTML/CSS/JS, без базы данных.

## Как устроено

```text
Internet → Traefik → существующий TinyAuth middleware → qbt-control:8000
                                                          ↓
                                            qbittorrent:8080 (Docker network)
```

Браузер обращается только к qbt-control. Ключ qBittorrent хранится в environment backend и добавляется в серверный `Authorization: Bearer …`. Ни ключ, ни исходные preferences, ни произвольные ответы API в браузер не передаются. Нет универсального proxy.

### Совместимость API

Реализация проверена по официальному исходному коду тега `release-5.2.3`:

| Задача | qBittorrent endpoint | Формат |
| --- | --- | --- |
| Скорости | GET `/api/v2/transfer/info` | `dl_info_speed`, `up_info_speed`, bytes/s |
| Текущий режим | GET `/api/v2/transfer/speedLimitsMode` | `0` или `1` |
| Установить режим | POST `/api/v2/transfer/setSpeedLimitsMode` | form `mode=1` / `mode=0` |
| Настроенные альтернативные лимиты | GET `/api/v2/app/preferences` | Только `alt_dl_limit`, `alt_up_limit`, bytes/s |

Источники: [transfercontroller.cpp](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.3/src/webui/api/transfercontroller.cpp), [appcontroller.cpp](https://github.com/qbittorrent/qBittorrent/blob/release-5.2.3/src/webui/api/appcontroller.cpp), [API key authentication](https://github.com/qbittorrent/qBittorrent/wiki/API-Key-Authentication-%28%E2%89%A5v5.2.0%29).

Ключи поддерживаются с 5.2.0. Username/password и cookie-login не используются. Fallback на toggle отсутствует. После каждого POST backend читает режим, чтобы подтвердить применение. Повторный `/on` оставляет режим включённым, повторный `/off` — выключенным.

`Unlimited` означает, что **альтернативные** лимиты отключены. Обычные лимиты qBittorrent всё ещё могут действовать. Расписание qBittorrent или другой клиент могут позднее изменить режим. Настроенные лимиты `0`/`-1` отображаются как `Unlimited`.

## Развёртывание с существующими Traefik и TinyAuth

1. В qBittorrent 5.2.3 откройте **Settings → Web UI → API Key** и создайте ключ. Включите WebUI на внутреннем порту, например 8080.
2. Убедитесь, что WebUI qBittorrent не имеет `ports:` на хосте, публичного Traefik-router, host networking и UPnP-проброса WebUI. В Docker-сети WebUI должен слушать интерфейс, доступный контейнеру qbt-control (обычно `0.0.0.0:8080` внутри контейнера, а не `127.0.0.1`).
3. Подключите qbt-control и qBittorrent к общей приватной сети. qBittorrent не требуется подключать к сети Traefik. В настройке **Server domains** qBittorrent разрешите hostname из `QBIT_URL`, например `qbittorrent`; не отключайте проверку Host целиком.
4. Скопируйте `.env.example` в `.env`, установите права `chmod 600 .env` и заполните значения. Реальный API key не нужно присылать в чат.
5. Укажите существующие имена Docker-сетей, entrypoint, TLS resolver и **полную цепочку middleware с TinyAuth**. Пример `tinyauth@docker,security-headers@file` нужно заменить на имена вашего окружения. Если security headers уже включены в общий chain middleware, укажите этот chain.
6. Направьте DNS `QBT_CONTROL_HOST` на Traefik и запустите:

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

Compose не публикует порты. Traefik получает порт 8000 из label и выбирает сеть через `traefik.docker.network`. Один router по hostname защищает **все** пути, в том числе `/`, `/static/*`, `/healthz` и все `/api/*`. Отдельных незащищённых routers для API создавать не нужно. HTTP → HTTPS redirect переиспользуется из существующей конфигурации Traefik.

Имена в `.env.example` — примеры, поскольку конфигурация вашего сервера отсутствует в этом проекте. Если TLS обеспечивается статическим сертификатом и resolver не используется, удалите label `tls.certresolver` и соответствующую переменную.

Не запускайте `docker compose config` без `--quiet` в публикуемых логах: полный вывод содержит environment, включая ключ. Ключ также доступен администраторам Docker через inspect — это свойство передачи секретов через environment.

### Сеть qBittorrent

Файл Compose использует две **существующие** сети: frontend-сеть Traefik и отдельную backend-сеть qBittorrent. Если приватной сети пока нет, её можно создать на сервере:

```bash
docker network create --internal qbit-internal
```

В существующий Compose qBittorrent добавьте сеть, сохранив его рабочую сеть для torrent-трафика:

```yaml
services:
  qbittorrent:
    # Остальные параметры существующего контейнера остаются на месте.
    networks:
      - default          # существующая сеть с исходящим доступом
      - qbit-internal
    labels:
      traefik.enable: "false"
    # Не добавляйте ports для WebUI/API.

networks:
  qbit-internal:
    external: true
```

Пример требует адаптации, если qBittorrent использует `network_mode: service:gluetun` или другое общее сетевое пространство: подключайте сеть к владельцу этого пространства и задайте его адрес в `QBIT_URL`. Не меняйте VPN-маршрутизацию вслепую. Полностью `internal`-сеть сама по себе не предоставляет torrent-клиенту исходящий интернет.

Приватная Docker-сеть не является авторизацией между её участниками. Подключайте только доверенные контейнеры; прямой доступ к qbt-control обходит TinyAuth. Не монтируйте Docker socket в qbt-control.

## Web security

- Изменения доступны только через POST `/api/limit/on` и `/api/limit/off`; GET `/api/status` выполняет только чтение.
- Каждый POST требует `X-QBT-Control: 1` и точного совпадения `Origin` с `APP_ORIGIN`. Только при отсутствии Origin используется same-origin Referer. `Origin: null`, отсутствие обоих источников и cross-site Fetch Metadata отклоняются до обращения к qBittorrent.
- Заголовок `X-QBT-Control` не является секретом: он запрещает обычную cross-site HTML-форму; сторонний JS потребует CORS preflight, который сервис не разрешает. CORS middleware отсутствует.
- `APP_ORIGIN` формируется как `https://${QBT_CONTROL_HOST}`. Проверка не опирается на присланные Host / X-Forwarded-Host / X-Forwarded-Proto.
- Uvicorn запускается с `--no-proxy-headers`: приложение не нуждается в восстановлении внешнего URL или клиентского IP. Все ссылки относительные, redirects при добавлении slash отключены. Если позже понадобится доверять proxy headers, разрешайте только реальные адреса доверенного Traefik.
- Сессией управляет существующий TinyAuth. Проверьте его cookie-флаги `Secure`, `HttpOnly` и `SameSite=Lax` (либо `Strict`, если это совместимо с вашей схемой входа). CSRF-защита приложения не полагается только на SameSite. Имена cookie-настроек TinyAuth зависят от установленной версии.
- Ответы имеют CSP без inline script/style, запрет iframe, `nosniff`, `Referrer-Policy: same-origin`, `Cache-Control: no-store`. HSTS/TLS остаются у вашего Traefik/security middleware.
- HTTP-запросы к qBittorrent не следуют redirects и не используют системные proxy-переменные. Backend не пересылает пользовательские заголовки, cookie или тело в qBittorrent.

Документация: [Traefik Docker routing](https://doc.traefik.io/traefik/routing/providers/docker/), [FastAPI behind a proxy](https://fastapi.tiangolo.com/advanced/behind-a-proxy/), [TinyAuth configuration](https://tinyauth.app/docs/reference/configuration/).

## API и ошибки

`GET /api/status` возвращает, например:

```json
{
  "online": true,
  "speed_limit_enabled": true,
  "download_speed": 18234567,
  "upload_speed": 1845223,
  "download_speed_formatted": "17.4 MiB/s",
  "upload_speed_formatted": "1.8 MiB/s",
  "alt_download_limit": 20971520,
  "alt_upload_limit": 2097152,
  "alt_download_limit_formatted": "20 MiB/s",
  "alt_upload_limit_formatted": "2 MiB/s"
}
```

Если preferences недоступны или имеют неожиданный формат, дополнительные поля лимитов опускаются. Для основных данных timeout, connection refused, 401/403, HTTP-ошибки и некорректные ответы дают **HTTP 503**:

```json
{"online": false, "error": "qBittorrent unavailable"}
```

Успешный POST возвращает `{"online": true, "speed_limit_enabled": true}` для `/on` и `false` для `/off`. После него frontend сразу перечитывает status. При неподтверждённом результате возвращается 503; если POST уже дошёл до qBittorrent, изменение могло примениться даже при потере ответа. Поэтому frontend перечитывает состояние и после ошибки, а повтор команды остаётся безопасным.

Connect timeout — 2 секунды, timeout операций HTTP — 4 секунды, общий deadline API — 8 секунд, максимум ответа upstream — 1 MiB. Для необязательных preferences действует отдельный общий deadline 4 секунды: медленная передача настроек не скрывает уже полученные скорости и режим. Клиент автоматически восстанавливается после доступности qBittorrent. Ошибки не содержат upstream-body, ключа и traceback. Access log отключён, логирование заголовков/ответов отсутствует.

`GET /healthz` — liveness самого приложения, независимо от доступности qBittorrent. Контейнер запускается от UID/GID 10001, с read-only filesystem, без capabilities, с `no-new-privileges`, ограниченным tmpfs и ротацией логов. Healthcheck помечает контейнер unhealthy; `restart: unless-stopped` перезапускает завершившийся процесс, а не любой unhealthy-контейнер.

## Интерфейс

Тёмная адаптивная страница, без внешних шрифтов, CDN, frontend framework и service worker. Поддерживаются iPhone safe areas и standalone meta-теги для «На экран Домой». Браузер опрашивает статус через 3 секунды после предыдущего запроса; в скрытой вкладке polling приостановлен, при возвращении статус обновляется сразу. При загрузке/перезагрузке выполняются только GET. Во время POST и подтверждающего GET кнопка заблокирована и показывает `Applying...`.

## Локальная разработка и тесты

Нужны Python 3.12+ и [uv](https://docs.astral.sh/uv/). Зависимости зафиксированы в `uv.lock`; образ использует этот lock без dev-пакетов.

```bash
uv sync --extra dev --frozen
uv run --extra dev pytest -q
uv run --extra dev ruff check .
node --check app/static/app.js
```

Для локального запуска задайте `APP_ORIGIN=http://127.0.0.1:8000`, `QBIT_URL` и `QBIT_API_KEY` через environment либо отдельный приватный env-файл. Приложение само не читает `.env`; Compose загружает его для подстановок. Для разработки uv умеет загружать env-файл:

```bash
uv run --env-file .env.local uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-proxy-headers --no-access-log
```

Открывайте именно `http://127.0.0.1:8000`, соответствующий APP_ORIGIN. Локальный процесс не защищён TinyAuth, поэтому привязан только к loopback. Тесты используют httpx MockTransport, реальный ключ/сервер не нужны и лимиты вашего qBittorrent не меняются.

Для просмотра и браузерной проверки с тестовыми скоростями и тестовым состоянием:

```bash
uv run --extra dev python -m tests.preview
```

В другом терминале (требуется Node.js и браузер для Playwright):

```bash
npx --yes --package @playwright/cli playwright-cli -s=qbt-control open http://127.0.0.1:8000
npx --yes --package @playwright/cli playwright-cli -s=qbt-control run-code --filename tests/browser-check.js
npx --yes --package @playwright/cli playwright-cli -s=qbt-control close
```

Скрипт проверяет загрузку без POST, polling, оба действия, двойные клики, блокировку кнопки, ошибки и восстановление, истечение сессии, отсутствие внешних запросов и размеры 1440/390/320 px. Скриншоты сохраняются в `output/playwright/`. Preview — отдельный тестовый запуск, в Docker-образ он не входит.

Перед эксплуатацией проверьте в приватном окне, что TinyAuth закрывает страницу и API; после входа проверьте оба явных действия и восстановление статуса при временном отключении qBittorrent. Интеграция с реальным сервером требует запуска в вашей Docker-сети.
