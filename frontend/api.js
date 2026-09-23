export class ApiError extends Error {
  constructor(message, status=0, details=[]) { super(message); this.status=status; this.details=details; }
}
export function errorMessage(data, status) {
  const codes={ai_not_configured:'AI-провайдер пока не подключён. Настройте его в разделе HR.',ai_timeout:'AI не ответил за отведённое время. Попробуйте позже.',invalid_credentials:'Неверный логин или пароль.',setup_forbidden:'Настройка уже выполнена или токен запуска недействителен.',employee_not_found:'Сотрудник с таким ID не найден.',user_already_exists:'Этот логин уже занят.',stale_import:'Данные изменились. Проверьте файлы заново.',future_session:'Эта сессия ещё не состоялась. Завершение пока недоступно.',already_completed:'Активность уже завершена. Обновите профиль.',invalid_ai_response:'Ответ AI не прошёл проверку. Повторите запрос.',ai_provider_failed:'Провайдер AI недоступен. Повторите позже.'};
  const detail = codes[data?.detail?.code] ?? data?.error?.message ?? data?.message ?? data?.detail?.message ?? data?.detail;
  if (typeof detail === 'string') return detail;
  return ({401:'Сессия завершена. Войдите снова.',403:'У вашей учётной записи нет доступа.',404:'Этот раздел пока недоступен на сервере.',409:'Данные изменились. Обновите страницу и повторите проверку.',413:'Файл слишком большой.',422:'Проверьте заполненные поля.',429:'Слишком много запросов. Повторите позже.'})[status] || 'Не удалось выполнить действие. Попробуйте ещё раз.';
}
export function createApi({fetchImpl=globalThis.fetch, getCsrf=()=>null, mock=null}={}) {
  return async function request(path,{method='GET',body,timeout=12000,idempotencyKey}={}) {
    if (mock) return mock(path,{method,body,idempotencyKey});
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),timeout);
    const headers={Accept:'application/json'};
    const csrf=getCsrf();
    if (csrf) headers['X-CSRF-Token']=csrf;
    if (idempotencyKey) headers['Idempotency-Key']=idempotencyKey;
    const isForm=typeof FormData!=='undefined' && body instanceof FormData;
    if(body!==undefined && !isForm) headers['Content-Type']='application/json';
    try {
      const response=await fetchImpl(path,{method,body:body===undefined?undefined:isForm?body:JSON.stringify(body),headers,credentials:'same-origin',signal:controller.signal,cache:'no-store'});
      const raw=await response.text();
      let data;
      try {data=raw?JSON.parse(raw):{};} catch {throw new ApiError('Сервер вернул ответ неизвестного формата.',response.status);}
      if(!response.ok) throw new ApiError(errorMessage(data,response.status),response.status,data.errors || data.error?.details || (Array.isArray(data.detail)?data.detail:[]));
      return data;
    } catch(error) {
      if(error instanceof ApiError) throw error;
      if(error.name==='AbortError') throw new ApiError('Время ожидания истекло. Для сохранения данных проверьте результат перед повтором.',408);
      throw new ApiError('Нет связи с локальным приложением. Проверьте, что окно запуска открыто.');
    } finally {clearTimeout(timer);}
  };
}
