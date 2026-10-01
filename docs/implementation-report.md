# Реализация плана улучшений DockTUI

Дата: 2026-10-01. Итоговый [PR #26](https://github.com/strmax195-hue/docktui/pull/26)
объединяет изменения промежуточных PR #16–25 и влит в `main`.

## Результат

| Пункты | Реализовано |
|---|---|
| 1–2 | Явные ошибки Docker, UNKNOWN при сбоях, сохранение stale snapshot, изоляция host/context и поколений подключения |
| 3–4 | Порядок Compose-аргументов и проверка путей, увеличенный build timeout, ограниченные потоки и завершение процессов |
| 5–6 | Фоновые отменяемые задания, стабильный selection, замена устаревших запросов, модули terminal/views и PTY-проверки |
| 7–8 | Атомарный конфиг, проверка исходных значений в doctor, coverage baseline, один проверенный wheel и opt-in PyPI |
| 9–10 | Health probe, ограниченные events/reconnect/dedup/removal, log windows/timestamps/presets и фильтры без потери истории |
| 11 | Prometheus с ограниченными labels и свежестью; multi-host с deadlines, независимыми результатами и приоритетом статусов |

## Проверка

Локально: `python -m unittest discover -s tests -q` — 215 тестов, 211 passed,
4 platform/integration skipped. Docker и native Windows
проверяются отдельными CI сценариями. GitHub Actions выполняет pytest/coverage
на Python 3.9/3.11/3.13/3.14 в Linux/macOS/Windows, ruff, mypy, реальный Compose
lifecycle с конечным/пустым log window, сборку/Twine и установку wheel в чистую
venv вне checkout. Измеренный baseline: 53.29% combined, 42.23% branches;
порог CI — 50% combined и 35% branches.

Независимое ревью выявило восемь существенных ошибок. Все получили
регрессионные тесты RED→GREEN: context switch, Windows descendants, смена
объекта во время запроса, сохранение global highlights, точность timestamp,
Compose until, stream startup completion и pin/follow для конечного окна.
Дополнительно проверены 100/1000 контейнеров при процессе с задержкой 10 с,
ошибки сохранения в CLI/TUI, удаление контейнера в events и сигнал Ctrl+C.

Сборка wheel/sdist, Twine и clean-venv smoke проверены в
[Release CI](https://github.com/strmax195-hue/docktui/actions/runs/36820300121).
Изменённые файлы локального checkout сверены с GitHub blob SHA: расхождений нет.
Итоговые проверки доступны в разделе Checks PR #26.

## Принятые решения и ограничения

- Утверждённый roadmap служит спецификацией; интерфейсы уточнялись по его критериям. Риск — дополнительные пожелания потребуют отдельного изменения.
- Shell proxy не позволил clone/install: локальный Git восстановлен из текстового upstream snapshot; удалённые commits создаются через GitHub API с сохранением binary assets. Локальные и удалённые SHA различаются.
- Форматирование/typecheck/build выполняются в CI; диагностические patches применяются локально. Это требует дополнительного CI цикла, но проверки не обходятся.
- Синхронные прямые методы dashboard сохранены для embeddings; работающий TUI использует jobs. Прямой вызов метода может блокировать вызывающий код.
- Renderers вынесены одним механическим изменением, с сохранением API и тем. Риск — более крупный diff для ревью.
- Некорректный active_endpoint остаётся явной ошибкой: fallback на другой Docker host запрещён. Пользователь исправляет настройку.
- PyPI ownership/name/Trusted Publisher не проверены через доступные инструменты: публикация в PyPI выключена до настройки владельцем. Wheel и sdist v1.5.0 опубликованы в GitHub Releases. Homebrew отложен до стабильного PyPI выпуска.
- Events встроены в Details: до ленты нужно прокрутить диагностические поля.
- Конечный Until отключает follow, включая pinned pane; для follow нужно очистить Until. Compose окна собираются через поддерживаемый docker logs каждого контейнера.
- Промежуточные PR заменяются одним итоговым PR; история коммитов и закрытых PR сохраняется. Итоговый diff крупнее, но слияние не требует цепочки зависимых веток.
- Native Windows и Docker проверяются CI; реальная SSH-инфраструктура и PyPI account setup остаются внешними. Специфические удалённые подключения требуют проверки в окружении владельца.

Отложенных мелких замечаний независимого ревью нет. PR #26 влит в `main`
с сохранением линейной истории. [GitHub Release v1.5.0](https://github.com/strmax195-hue/docktui/releases/tag/v1.5.0)
опубликован 2026-10-01 из commit `e4fe2b8384ee53d550d3cf0d003f11100d94dd6a`.
Release workflow проверил и приложил wheel и sdist; changelog и README
обновлены под опубликованный релиз. Публикация в PyPI не выполнялась.
