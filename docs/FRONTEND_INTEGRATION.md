# Часть C — подключение интерфейса к A/B

Статус: реализован frontend. Контракт ниже предложен C; пока backend A/B не подключён, совместимость и настоящий AI не считаются проверенными. Все пути относительны origin локального приложения. Никаких запросов из браузера к OpenAI/NVIDIA.

## Подключение за несколько минут

1. Отдавать `web/index.html` на `/`, каталог `web/` как локальную статику (CSS/JS — по URL из HTML). API маршруты зарегистрировать раньше catch-all static mount.
2. Пример FastAPI после объявления API: `app.mount('/', StaticFiles(directory='web', html=True), name='web')`. Путь вычислять от расположения проекта, не текущей директории launcher. Директории БД и исходные датасеты не монтировать.
3. Реализовать перечисленные ниже DTO. Если у A уже другой контракт — изменить адаптацию в `web/app.js`/`web/api.js`, не создавать второй сервер.
4. Сессия: HttpOnly cookie, SameSite, серверные проверки Origin/CSRF. Сервер возвращает csrf_token через session; UI отправляет X-CSRF-Token. Проверки ролей в UI только для удобства, права обеспечивает A на каждом маршруте.
5. Launcher передаёт токен: `http://127.0.0.1:PORT/#setup_token=TOKEN`. UI забирает его в память и сразу удаляет из адреса. После bootstrap токен гасит сервер. Bootstrap создаёт сессию HR; если A выбирает иной процесс — согласовать адаптацию.

## Предпросмотр до интеграции

Из корня репозитория при наличии Python: `python -m http.server 8765 --bind 127.0.0.1 --directory web`.

- `http://127.0.0.1:8765/?preview=employee` — сотрудник.
- `http://127.0.0.1:8765/?preview=hr` — HR, импорт, настройки.
- `http://127.0.0.1:8765/?preview=setup` — первый запуск.
- `http://127.0.0.1:8765/?preview=login` — вход, произвольные вымышленные данные.

Яркая плашка обозначает предпросмотр. Данные полностью вымышленные, не взяты из датасета организаторов. Перезагрузка сбрасывает изменения. Ключи в предпросмотре не принимаются. Без параметра preview интерфейс требует настоящий API и НЕ подменяет его fixtures при ошибках. Это команда предпросмотра для разработчика, не обещание готового пользовательского launcher.

## Общий ответ ошибки

HTTP 4xx/5xx с JSON:

```json
{"error":{"code":"validation_failed","message":"Исправьте ошибки файла"},"errors":[{"file":"employees.json","object":"NEW_ID","field":"skills.SK_X","message":"Уровень должен быть от 0 до 5"}]}
```

422 поддерживает также стандартный FastAPI detail[]. Не возвращать stack trace, ключи, пароли или полный запрос к LLM.

## Setup и session

- `GET /api/setup/status`: `{setup_required: bool, dataset_loaded: bool, as_of_date: "2026-10-01"|null, ai_status: "ready"|"not_configured"}`.
- `POST /api/setup/bootstrap`: `{username,password,setup_token}` → создаёт HR и cookie-сессию; повтор закрыт.
- `POST /api/auth/login`: `{username,password}` → cookie-сессия.
- `POST /api/auth/logout`: `{}` → уничтожить сессию.
- `GET /api/auth/session`: `{user:{user_id,username,display_name,role:"employee"|"hr",employee_id?},csrf_token}`; без сессии 401.

## Профиль и цель

`GET /api/me`, `GET /api/hr/employees/{employee_id}` возвращают одинаковую форму (HR только читает):

```json
{
  "employee":{"employee_id":"DEMO","full_name":"Пример","role":"Backend Engineer","grade":"Middle","tenure_months":32},
  "goal":{"target_role":"Backend Engineer","target_grade":"Senior","source":"explicit"},
  "goal_options":[{"target_role":"Backend Engineer","target_grade":"Senior"}],
  "coverage_pct":72,
  "critical_gap_count":2,
  "completed_count":12,
  "version":1,
  "skills":[{"skill_id":"SK_SYSTEM_DESIGN","name":"System Design","current":2,"required":4,"critical":true}],
  "history":[{"record_id":"R1","event_id":"EV_X","title":"Название","date":"2026-10-01","status":"in_progress","completion_pct":0,"can_complete":true}],
  "recommendations":null
}
```

Цель может быть null, source — explicit/suggested; список допустимых целей строит A из role_profiles. coverage_pct=null если нет требований. history — новые записи первыми. Рекомендации в GET только актуальные, иначе null; чтение профиля не вызывает новый LLM-запрос. Права HR на любые данные не означают право изменять активность от имени сотрудника.

`PATCH /api/me/goal`: `{target_role,target_grade}` → успех; сервер инвалидирует кэш, UI заново читает профиль и запрашивает рекомендации на главном экране.

## Рекомендации

`POST /api/me/recommendations`: `{refresh:true}`. UI даёт 11 секунд на HTTP (10 серверной операции + передача ответа), не выполняет скрытых повторов. B должен ограничить весь путь, включая резерв, до 10 секунд.

```json
{
 "status":"ready","source":"ai","provider":"openai","model_id":"configured-model","cached":false,"data_version":1,
 "items":[{
   "event_id":"EV_X","title":"Название","format":"self_paced","duration_hours":6,
   "session_date":null,"action":"start","record_id":null,"can_complete":true,
   "gains":[{"skill_id":"SK_SYSTEM_DESIGN","name":"System Design","before":2,"after":3}],
   "factors":[{"text":"Факт 1","fact_ids":["goal"]},{"text":"Факт 2","fact_ids":["gap"]},{"text":"Факт 3","fact_ids":["history"]}],
   "alternative":null
 }]
}
```

Числа и допустимость проверяет A/B. UI не отображает карточки с менее чем тремя непустыми факторами, но не может проверить их истинность. Ожидаемый прирост должен учитывать max_level. action=continue требует record_id. can_complete=false отключает выполнение до разрешения сервером. Для scheduled start выбранная сессия берётся из проверенной рекомендации; self_paced передаёт null.

Пустые статусы: no_goal, goal_achieved, no_candidates; при no_candidates `reasons:[{code:"audience"|"prerequisites"|"no_gain"|"no_sessions"|"goal_outside_catalog"}]`.

Резерв по правилам: `source:"fallback", reason:"timeout"|"not_configured"|"unavailable"`, проверенные items. source ai только после успешного проверенного вызова. source preview используется исключительно локальным предпросмотром.

## Активности

- `POST /api/me/activities`: `{event_id,session_date}` + `Idempotency-Key` → `{record_id,status}`.
- `POST /api/me/activities/{record_id}/complete`: `{}` + `Idempotency-Key` → `{applied:true|false,changes:[{skill_id,name,before,after}],coverage_before,coverage_after}`.

После успешного выполнения UI перечитывает профиль; отказ последующего AI не отменяет выполнение. Ключ повтора сохраняется в sessionStorage только для незавершённого запроса и удаляется после успеха. Сервер обеспечивает идемпотентность, владение записью, транзакцию и запрет повторного завершения даже с новым ключом. EV_036: отдельный record_id на отдельное посещение. При повторной регистрации сервер возвращает существующую активную запись или контролируемый конфликт.

## Импорт

`POST /api/hr/import/validate`: multipart поля `employees.json`, `activity_history.csv`; initial дополнительно `skills.json`,`events.json`; `kind=initial|additional`, `mode=add|update`.

Ответ: `{valid,batch_id,counts:{added,updated,skipped},errors:[],conflicts:[{id,message}]}`. valid=true только если сервер разрешает применение с выбранным режимом; конфликты в режиме add не должны давать valid=true. batch_id привязан к файлам, режиму и версии состояния. UI снимает результат валидации после изменения файла/режима.

`POST /api/hr/import/apply`: `{batch_id,mode}` + Idempotency-Key. Ответ: `{counts:{added,updated,skipped},employee_ids:[],account_instructions?}`. Применение атомарно и повторно проверяет конфликты.

**Обязательное согласование A:** как новый сотрудник жюри получает аккаунт. UI умеет открыть HR-read-only профиль по возвращённому ID, но завершение требует входа сотрудника. Статический переключатель employee_id без авторизации не вводить.

## HR

`GET /api/hr/overview`:

```json
{
 "employee_count":200,"no_step_count":0,
 "period":{"from":"2024-10-01","to":"2026-09-30"},
 "skill_gaps":[{"skill_id":"SK_X","name":"Навык","count":12,"denominator":40,"percentage":30,"critical_count":4}],
 "no_next_step":[{"employee_id":"E_X","full_name":"Имя","goal_label":"Роль · Грейд","reason":"audience","reason_message":"Нет мероприятия для текущей роли"}],
 "participation":[{"event_id":"EV_X","title":"Название","completed":1,"in_progress":2,"dropped":0,"no_show":0,"declined":0,"overdue":0,"total":3}]
}
```

Знаменатель skill_gaps — сотрудники, у которых навык требуется целевым профилем. no_step_count — число сотрудников с дефицитом без доступного шага, не все Lead без цели и не сотрудники с покрытой целью. participation — количество записей истории за указанный период.

## OpenAI и NVIDIA — интерфейс готов, исполнение B

- `GET /api/hr/settings/ai`: `{providers:{openai:{configured,model_id,latency_ms?},nvidia:{configured,model_id,latency_ms?}},primary_provider,fallback_provider}`. Никогда не возвращать секрет или его часть.
- `POST /api/hr/settings/ai`: `{provider:"openai"|"nvidia",model_id,api_key?,persist:bool}`. Отсутствующий api_key означает сохранить текущий; пустую строку UI не отправляет. Короткая проверка без датасета → `{valid:true,latency_ms}` либо контролируемая ошибка. Сохранение только после успешной проверки. persist=false — память процесса; persist=true — Windows DPAPI/Credential Manager, не plaintext JSON. При недоступности защищённого хранилища вернуть ошибку, не сохранять открыто.
- `PATCH /api/hr/settings/ai/policy`: `{primary_provider,fallback_provider:null|"openai"|"nvidia",total_timeout_ms:10000}`. Основной и резервный должны отличаться, быть настроены и поддерживать модель.

Не выполнять два API-запроса на каждую рекомендацию автоматически. Основной провайдер — один; резерв использовать в оставшемся общем бюджете после быстрого отказа. Для сравнения скорости B отдельно выполняет небольшую одинаковую выборку запросов. $50 на аккаунте — сообщённый бюджет, не известный приложению текущий баланс. Не объединять ключи разных участников и не ротировать их ради обхода лимитов.

Ускорение: короткий контекст без ФИО, только допустимые кандидаты, небольшой структурированный ответ с 1–3 шагами, async HTTP, кэш по версии профиля/цели/истории/каталога/модели/prompt, без повторных вызовов на чтение страницы. Конкретную модель выбрать по доступности ключа и замерам качества/латентности; UI не захардкоживает неподтверждённый model ID.

Официальные источники проверены 23.09.2026:

- https://developers.openai.com/api/docs/guides/structured-outputs
- https://docs.api.nvidia.com/nim/re/reference/llm-apis

У NVIDIA документирован `https://integrate.api.nvidia.com/v1/chat/completions`; OpenAI поддерживает структурированный ответ по JSON Schema на совместимых моделях. Поддержку response_format у конкретной NVIDIA-модели проверяет B; совместимый endpoint не гарантирует одинаковые параметры всех моделей.
