# Первый локальный ИИ на Windows: Ollama + Qwen3 1.7B

Дата подготовки: 2026-10-17. Пользователь подтвердил исправление 1I и поручил
попробовать настоящий ИИ. Подключение в игре уже есть. Ollama и весов на его
Windows пока не было; агент не может выполнить установку на удалённом компьютере.
Команды ниже выполняет пользователь. В облаке установщик/веса не скачивались.

## Что выбираем

- Ollama: локальная программа, исходный код под MIT.
- `qwen3:1.7b`: конкретный небольшой тег, ориентировочно 1,4 ГБ весов.
  Qwen3 README заявляет Apache 2.0 для открытых весов. Размер именно текущего тега
  в реестре из облака не проверен; после загрузки сохраняем фактические сведения.
- Резерв при недостаточной скорости — `qwen3:0.6b`, но сейчас его не скачиваем.
- Нужен Windows 10 22H2 или новее, включая Windows 11. Графический ускоритель
  для выбранного режима игры не требуется: уже заданы CPU и четыре потока.
- Программа, установщик, временная распаковка и модели — на D:. Официальная
  документация требует минимум 4 ГБ для бинарной установки; дополнительно нужны
  установщик, распаковка и веса. В этих командах требуем 12 ГиБ свободного D: с запасом.
  Это запас для первого запуска, не обещание точного конечного размера.
- Конфигурация/журналы Ollama и последующие обновления могут использовать C:.
  Нулевое использование C: не обещается. Перед установкой проверьте его свободное место.
- Учётная запись, карта и подписка не нужны. Облачные функции явно отключены.

**Далее идёт загрузка стороннего установщика и более гигабайта весов. Выполняйте
шаги установки только если согласны с этим объёмом и размещением на D:.**
Сначала можно выполнить только чтение свободного места из следующего раздела.

## 1. Проверить диски и получить инструкцию из проекта

Закройте игру с сохранением. В PowerShell:

```powershell
Set-Location D:\Projects\DND-NCFU -ErrorAction Stop
Get-PSDrive C, D | Select-Object Name, @{Name='FreeGB';Expression={[math]::Round($_.Free / 1GB, 1)}}
[Environment]::OSVersion.VersionString
```

Если на D: меньше 12 ГиБ, сначала освободите место самостоятельно; ничего
автоматически не удаляем. Если Windows слишком старая, сначала уточнить версию.

Документ можно открыть локально после `git pull --ff-only`:

```powershell
notepad docs\INSTALL_LOCAL_AI_WINDOWS.md
```

## 2. Установить Ollama на D: и задать папку весов

Весь блок вставить целиком. Он откроет обычный установщик; дождитесь окончания.
Он не загружает модель и не запускает генерацию текста. Если подпись установщика
не проходит проверку, выполнение прекращается — не отключайте проверку подписи/TLS.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    if ((Get-PSDrive D).Free -lt 12GB) {
        throw 'На D: нужно не менее 12 ГиБ свободного места для этого способа установки.'
    }
    New-Item -ItemType Directory -Force -Path 'D:\AI\Installers', 'D:\AI\Models', 'D:\AI\Temp' | Out-Null

    [Environment]::SetEnvironmentVariable('OLLAMA_MODELS', 'D:\AI\Models', 'User')
    [Environment]::SetEnvironmentVariable('OLLAMA_NO_CLOUD', '1', 'User')
    $env:OLLAMA_MODELS = 'D:\AI\Models'
    $env:OLLAMA_NO_CLOUD = '1'

    $installer = 'D:\AI\Installers\OllamaSetup.exe'
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://ollama.com/download/OllamaSetup.exe' -OutFile $installer
    $signature = Get-AuthenticodeSignature $installer
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Ollama') {
        throw 'Подпись или издатель установщика не подтверждены. Установка остановлена.'
    }
    Get-FileHash -Algorithm SHA256 $installer

    $previousTemp = $env:TEMP
    $previousTmp = $env:TMP
    try {
        $env:TEMP = 'D:\AI\Temp'
        $env:TMP = 'D:\AI\Temp'
        Start-Process -FilePath $installer -ArgumentList '/DIR="D:\AI\Ollama"' -Wait
    }
    finally {
        $env:TEMP = $previousTemp
        $env:TMP = $previousTmp
    }
}
```

При несовпадении имени издателя сохраните вывод для проверки; не запускайте
неподтверждённый файл. Имя издателя не проверялось на скачанном EXE в облаке.
Установщик и его интерфейс на Windows этим документом не считаются протестированными.

Установка обычно запускает Ollama в фоне. Если нет — открыть Ollama через меню
«Пуск». Если она была запущена до задания переменных, сначала полностью выйти из
значка в трее и запустить заново: работающий процесс не получает новые переменные.

## 3. Скачать только выбранную модель

Откройте **новое окно PowerShell**. Не закрывайте работающую Ollama.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $ollamaExe = 'D:\AI\Ollama\ollama.exe'
    if (!(Test-Path $ollamaExe)) {
        throw 'Ollama не найдена в D:\AI\Ollama. Проверьте завершение установки.'
    }
    $version = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 10
    $version
    & $ollamaExe pull qwen3:1.7b
    if ($LASTEXITCODE -ne 0) {
        throw 'Модель не загрузилась. Сохраните текст ошибки, игру пока оставьте автономной.'
    }
    & $ollamaExe list
}
```

Дождаться 100% и успешного завершения pull. В списке должна появиться
`qwen3:1.7b`. Её файлы должны лежать в `D:\AI\Models` (подпапки blobs/manifests).
При обрыве сети повторный pull той же модели может продолжить загрузку; не удаляйте
веса и не выбирайте другой крупный тег ради устранения сетевой ошибки.

## 4. Сохранить лицензию и фактические сведения для проекта

Это небольшой локальный запрос к уже работающей Ollama, без новой загрузки весов.
Результат сохраняется вне Git под уникальным именем; прежние результаты не затираются.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $modelInfo = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:11434/api/show' -ContentType 'application/json' -Body '{"model":"qwen3:1.7b"}' -TimeoutSec 15
    if ($modelInfo.license -notmatch 'Apache' -or $modelInfo.license -notmatch '2\.0') {
        throw 'Лицензия конкретной модели не подтверждена. Сохраните сообщение для проверки.'
    }
    $runId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + ([guid]::NewGuid().ToString('N').Substring(0,8))
    $recordDir = 'D:\AI\Checks\' + $runId
    New-Item -ItemType Directory -Path $recordDir | Out-Null
    $modelInfo | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 ($recordDir + '\model-info.json')
    $modelInfo.license | Set-Content -Encoding UTF8 ($recordDir + '\LICENSE.txt')
    Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 10 | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 ($recordDir + '\models.json')
    Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 10 | ConvertTo-Json | Set-Content -Encoding UTF8 ($recordDir + '\ollama-version.json')
    Write-Host "Сведения сохранены: $recordDir"
}
```

models.json содержит фактический digest/размер, model-info.json — сведения о
квантовании/модели/лицензии. Это метаданные первого подключения, не A/B-эксперимент
и не измерение качества русского текста. Для полноценных исследований нужен
отдельный протокол входов/ответов/метрик.

## 5. Первый рассказ в игре

```powershell
Set-Location D:\Projects\DND-NCFU
.\.venv\Scripts\python.exe scripts\run_game.py
```

1. Загрузить пробную сессию или создать героя. Открыть «Раздел → Рассказчик».
2. Нажать «Найти установленные модели», включить локального рассказчика и выбрать
   **qwen3:1.7b**. Для первого опыта снять «Дополнять новые игровые действия автоматически».
3. Нажать «Рассказать текущую сцену» и дождаться ответа (до 90 с). Можно отменить.
4. В журнале появится «ИИ-рассказчик · qwen3:1.7b». Проверить русский текст,
   соответствие месту/участникам и отсутствие выдуманных наград/урона.
5. Записать приблизительное время ожидания и расход RAM по диспетчеру задач.
   Не считать его точным бенчмарком. При тайм-ауте сохранить сообщение, а не
   увеличивать лимиты/скачивать более тяжёлую модель без разбора.
6. Сохранить ячейку, перезапустить игру, загрузить: текст ИИ восстановится без
   новой генерации. Автоматический режим можно включить после первого успешного ответа.
7. После установки отдельно повторить с отключённым интернетом. Сеть была нужна
   для скачивания, выполнение локальной модели не должно зависеть от сайта.

Пока ИИ пишет художественное дополнение. Создание новых предметов, существ,
локаций/спавна и свободный разбор любых действий остаются следующими системами.

## Проверенные источники и пределы проверки

17.10.2026 доступны исходные документы официальных репозиториев:

- https://raw.githubusercontent.com/ollama/ollama/main/docs/windows.mdx —
  Windows 10 22H2+, минимум 4 ГБ, `/DIR`, `OLLAMA_MODELS`, перезапуск процесса.
- https://raw.githubusercontent.com/ollama/ollama/main/docs/faq.mdx —
  `OLLAMA_NO_CLOUD=1`, локальный адрес по умолчанию, дополнительные файлы на C:.
- https://raw.githubusercontent.com/ollama/ollama/main/LICENSE — MIT.
- https://raw.githubusercontent.com/ollama/ollama/main/README.md — официальный URL EXE.
- https://raw.githubusercontent.com/QwenLM/Qwen3/main/README.md — размеры 0.6B/1.7B
  и заявление Apache 2.0 для открытых весов.

HTML docs.ollama.com/ollama.com, реестр тегов и Hugging Face из облака отвечали 403;
точный текущий размер/лицензия конкретного квантованного тега здесь не получены.
Ожидаемые 1,4 ГБ — ориентир из мастер-документа, не живое измерение реестра.
Подпись EXE, установка, команды PowerShell и настоящий ответ модели на Windows
агентом не выполнялись. Пользователь должен предоставить фактический результат.
