# MyTube

Упрощённый видеохостинг: FastAPI, PostgreSQL и MinIO. Страницы отдаёт само приложение.

## Запуск одной командой

На чистой Ubuntu скрипт ставит Docker Engine и плагин Compose, если их ещё нет, копирует `.env.example` в `.env` и поднимает PostgreSQL, MinIO и API.

```bash
chmod +x deploy.sh
./deploy.sh
```

После старта:

- приложение — http://localhost:8000
- консоль MinIO — http://localhost:9001

Контейнер API сам применяет миграции Alembic перед запуском uvicorn.

Остановка:

```bash
docker compose down
```

Данные PostgreSQL и MinIO остаются в томах `postgres_data` и `minio_data`.

## Что запускает Compose

| Сервис | Порт | Назначение |
|---|---|---|
| api | 8000 | FastAPI, страницы и поток видео |
| postgres | 5432 | База `mytube` |
| minio | 9000, 9001 | Хранилище видео и консоль |

Образы MinIO берутся с зеркала Timeweb. Каталог `bitnami/minio` с Docker Hub снят, поэтому Compose использует `dockerhub.timeweb.cloud/bitnamilegacy/minio` и `dockerhub.timeweb.cloud/bitnamilegacy/minio-client`. Сервер Bitnami сам запускает `minio server`, данные лежат в томе `/bitnami/minio/data`, процесс работает от пользователя `1001`. Бакет `mytube` создаётся при старте.

Внутри сети Compose API ходит в базу по адресу `postgres:5432`, а в MinIO — по `minio:9000`. Эти адреса заданы в `docker-compose.yml` и не берутся из локального `.env`.

## Учётные данные для разработки

Их нужно сменить перед выкладкой наружу.

| | |
|---|---|
| PostgreSQL | пользователь `mytube`, пароль `mytube`, база `mytube` |
| MinIO | `minioadmin` / `minioadmin`, бакет `mytube` |
| JWT | `JWT_SECRET_KEY` в `.env` и в `docker-compose.yml`, не короче 32 символов |

Регистрация на http://localhost:8000/login создаёт обычного пользователя. Роли модератора и администратора через форму не выдаются.

## Локальная разработка

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

Для ручного запуска без контейнера API нужны доступные PostgreSQL и MinIO. Адреса для хоста лежат в `.env.example`.

```bash
alembic upgrade head
uvicorn app.main:app --reload
```
