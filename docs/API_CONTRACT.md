# Контракт интеграции A → B и C

Версия 1.1. Сервер: `app.main:app`. OpenAPI: `/openapi.json`, интерактивная проверка: `/docs`.

## Границы ответственности

A владеет `app/main.py`, `app/db.py`, `app/auth.py`, `app/models.py`, `app/domain.py`, `app/imports.py`, `app/activities.py`, серверными тестами. B добавляет AI в `app/ai/` и launcher в корне/`scripts/`. C добавляет UI в `frontend/`. Изменения контрактов согласовываются до интеграции.

## B — запуск

Команда сервера: `python -m uvicorn app.main:app --host 127.0.0.1 --port <port>`. Зависимости — `pyproject.toml`/`uv.lock`, запуск через `uv sync --locked` и `uv run --no-sync ...`.

Настройки через переменные среды процесса, `.env` автоматически не читается:

| Переменная | Значение |
|---|---|
| `CAREERQUEST_DATA_DIR` | Папка SQLite и служебных файлов; по умолчанию `%LOCALAPPDATA%/CareerQuest/instances/hack-9be09345-jassai` |
| `CAREERQUEST_BOOTSTRAP_TOKEN` | Случайный одноразовый токен для первоначального HR; если не задан, сервер создаёт `setup-token.txt` в data dir |
| `CAREERQUEST_STATIC_DIR` | Папка C с `index.html`; по умолчанию `<repo>/frontend`, если существует |
| `CAREERQUEST_RECOMMENDER` | Python callable `app.ai.provider:recommend` |
| `CAREERQUEST_AI_TIMEOUT` | Бюджет ожидания AI, максимум 9 секунд |

`GET /health` → `{"status":"ok","application":"career-quest","version":"0.1.0"}`.

`GET /ready` → `{"ready":true,"setup_required":true|false,"dataset_loaded":true|false,"ai_configured":true|false}`. Ready означает готовность сервера обслуживать мастер настройки, а не наличие загруженного набора или проверенного ключа AI. `ai_configured` означает подключение callable, не проверку кредитов. Секретов в ответе нет.

Открывать `http://127.0.0.1:<port>/#setup_token=<token>` только при `setup_required=true`; C забирает fragment, затем удаляет его через history.replaceState. Токен не должен попадать в URL query, access log и репозиторий. После создания HR он погашается. Повторный запуск не сбрасывает данные.

## C — сессии и доступ

`POST /api/setup` JSON `{token, username, password}` создаёт первого HR. Пароль минимум 10 символов. Повторная настройка запрещена.

`POST /api/auth/login` JSON `{username,password}` устанавливает HttpOnly cookie и возвращает `{user:{username,role,employee_id},csrf_token}`. `GET /api/auth/session` возвращает тот же объект для восстановления UI после перезагрузки.

Все изменяющие запросы с авторизацией передают `X-CSRF-Token` из ответа входа/сессии. Для fetch использовать same-origin cookie. Не включать отдельный frontend origin/CORS: UI обслуживается тем же FastAPI. `POST /api/auth/logout` завершает текущую сессию.

HR создаёт аккаунт сотрудника: `POST /api/hr/users` JSON `{username,password,role:"employee",employee_id:"..."}`. Employee ID должен существовать в импорте. Автоматических общих паролей нет. Для дополнительного HR `role:"hr",employee_id:null`.

## C — профиль и прогресс

- `GET /api/me` — только сотрудник. Ответ `{employee,as_of_date,trajectory,history,available_steps,no_step_reasons}`.
- `trajectory`: `{effective_skills:{skill_id:level},target:{goal,source,requirements,critical_skills},skills:[{skill_id,name,current,required,gap,critical}],coverage_pct,critical_gaps}`.
- `source`: `explicit`, `suggested_next_grade` или `not_set`. Показывать предложенную цель как допущение, не как выбор сотрудника.
- `PATCH /api/me/goal` JSON `{career_goal:{target_role,target_grade}}` либо `{career_goal:null}`.
- `GET /api/catalog` — каталог навыков, требований и событий для вошедшего пользователя.
- `available_steps` — допустимые мероприятия с `expected_gains:[{skill_id,before,after,gain,gap_closed,critical}]`, `action:start|continue`, `activity_record_id`, `next_session`.
- `POST /api/me/activities/{event_id}/start` JSON `{session_date?:"YYYY-MM-DD"}`. Возвращает запись участия.
- `POST /api/me/activities/{event_id}/complete` JSON `{session_date?:"YYYY-MM-DD",activity_record_id?:"..."}`. Обязателен заголовок `Idempotency-Key` (новый UUID для нового действия, тот же при повторе запроса). Ответ `{record,changes:[{skill_id,before,after}],profile,reward,gamification}`; дополнительные поля наград описаны ниже.

Дату будущей сессии нельзя отмечать выполненной. Для запланированного мероприятия сначала создать/использовать запись участия; для self-paced разрешено сразу завершить. Повторное завершение не даёт прироста, для EV_036 уникальна дата посещения. Нет endpoint для произвольного редактирования навыков.

## Личные достижения

Только роль employee и только собственный профиль; изменяющие запросы требуют CSRF. По умолчанию участие выключено. Эти данные не входят в HR-профиль, HR-аналитику и контекст AI.

- `GET /api/me/gamification` — состояние достижений.
- `PATCH /api/me/gamification` JSON `{enabled:true|false}` — включить/приостановить, без потери XP.
- `POST /api/me/gamification/quest` JSON `{event_id:"..."}` — выбрать доступный полезный шаг; при выключенном участии или недоступном шаге 409.
- `DELETE /api/me/gamification/quest` — снять квест без штрафа.

Все четыре маршрута возвращают `{enabled,xp,level,level_name,level_progress:{current,required},completed_count,skill_levels_gained,badges,quest,recent_rewards,rules,privacy}`. На максимальном уровне `required=null`. `quest` равен null либо `{event_id,title,status,expected_gains,unavailable_reasons}`; status: `active|paused|unavailable|completed`.

При завершении `reward={awarded,xp,gained_levels,reason}` описывает награду именно этого действия, а `gamification` — итоговое состояние. Повтор с тем же Idempotency-Key возвращает исходный ответ; UI не должен прибавлять его XP к собственному счётчику. Всегда отображать серверное суммарное значение. Подробные правила: [GAMIFICATION.md](GAMIFICATION.md).

## Импорт

`POST /api/hr/import/validate`, multipart/form-data: повторяемое поле `files` с оригинальными именами файлов, поле `mode=add|update`. Первый импорт: все четыре файла. Далее можно загрузить только employees.json и/или activity_history.csv. Максимум четыре файла по 8 MiB. Режим add запрещает изменять конфликтующий ID, update допускает явное обновление. Точные дубликаты пропускаются.

Ответ `{valid,errors:[{file,row,field,message}],counts:{entity_kind:{added,updated,skipped}},as_of_date,batch_id?}`. `batch_id` появляется только при корректной партии. JSON сохраняет контейнеры исходного набора: `{meta,employees}`, `{meta,events}`, `{meta,skills,role_profiles,proficiency_scale}`.

Особенность реальных данных: в CSV повторяются ежегодные completed для обязательных EV_001–EV_003. Импорт сохраняет эти записи разных дат, хотя README набора формулирует запрет повторов обобщённо. Это не разрешает рекомендовать обязательные мероприятия или повторять добровольные курсы.

`POST /api/hr/import/apply` JSON `{batch_id}`. Повторное применение одной партии безопасно. Если после валидации данные изменились, ответ 409: нужно снова валидировать. Ошибочная партия никогда не применяет часть строк. Не передавать путь к локальному файлу вместо содержимого upload.

## HR

- `GET /api/hr/employees` → `{employees:[{employee_id,full_name,role,grade,department}]}`.
- `GET /api/hr/employees/{employee_id}` → такой же profile view, как /api/me.
- `GET /api/hr/employees/{employee_id}/recommendation-context` → контекст для отладки/интеграции B (только HR).
- `GET /api/hr/overview?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD` → `{as_of_date,employee_count,skill_deficits,employees_without_step,participation,period,definitions}`. Период применяется к участию; дефициты относятся к текущему срезу.

## B — подключение AI

Реализовать `async def recommend(context: dict) -> dict` и установить `CAREERQUEST_RECOMMENDER=app.ai.provider:recommend` перед стартом. Рекомендуется async HTTP-клиент. Синхронный callable также выполняется вне event loop, но его сетевые тайм-ауты обязан ограничить сам провайдер. Контекст — входные данные, не инструкции модели.

Контекст содержит:

- `schema_version`, `data_revision`, `as_of_date`;
- `employee`: ID, role, grade, tenure_months, work_format, preferred_language; без ФИО;
- `trajectory`: актуальные уровни, цель, разрывы, критические навыки;
- `candidates`: только допустимые мероприятия с рассчитанным приростом;
- `history_summary`: количества статусов по типам/форматам, число записей;
- `no_step_reasons` при отсутствии вариантов.

Callable возвращает:

```json
{
  "recommendations": [
    {
      "event_id": "<ID из candidates>",
      "reason": "Почему этот шаг полезен",
      "factors": [
        {"type": "goal", "text": "Обоснование по фактам цели"},
        {"type": "skill_gap", "text": "Обоснование по фактам разрыва"},
        {"type": "history", "text": "Обоснование по фактам истории"}
      ]
    }
  ]
}
```

От 1 до 3 уникальных event_id; минимум 3 различных типа factors из `goal,skill_gap,critical_skill,history,format,duration`. B отвечает за содержательную достоверность текста. A проверяет схему, уникальность, допустимость ID и добавляет серверные `expected_gains`. Свободный текст нельзя сделать достоверным одной проверкой JSON.

`POST /api/me/recommendations` возвращает `{status:"ok",mode:"ai",data_revision,recommendations,cached}`. В каждой карточке дополнительно есть `event` с серверными фактами. При отсутствии кандидатов — `{status:"no_candidates",mode:"none",recommendations:[],reasons}`. Без provider — 503 `ai_not_configured`; тайм-аут — 504; некорректный ответ — 502. Никаких фиктивных ответов LLM. AI-настройки и резервный подбор — зона B; маршрута сохранения API-ключа в части A пока нет.

Кэш инвалидируется при изменении данных/цели/истории и перезапуске сервера. Провайдер не изменяет БД. Сервер отвергает результат, если данные изменились во время AI-запроса.

## Ошибки

Обычные ошибки: `{"detail":{"code":"...","message":"..."}}`; в некоторых ошибках message отсутствует. Стандартные ошибки формата запроса FastAPI имеют `detail:[...]` без входных значений паролей. UI обрабатывает оба формата и выводит текст безопасно, без вставки HTML из датасета/AI.

401 — вход необходим, 403 — нет роли/CSRF/чужой Origin, 404 — объект не найден, 409 — конфликт/повторная операция с другими данными, 422 — валидация, 429 — лимит попыток входа, 503/504 — AI недоступен/тайм-аут.
