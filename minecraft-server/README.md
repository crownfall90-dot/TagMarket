# The Harpy Express: Extended — сервер

Minecraft **1.21.1**, Fabric loader **0.18.4**, сборка [The Harpy Express: Extended 3.8.141](https://modrinth.com/modpack/the-harpy-express-extended) (Modrinth).

## Запуск

Нужны Java 21+, python3, curl.

```bash
./install.sh               # скачивает моды (с проверкой sha512), Fabric и карту
./start.sh --accept-eula   # принимая EULA Mojang: https://aka.ms/MinecraftEULA
```

На Windows: `start.bat --accept-eula` (из архива сервера, `install.sh` там не нужен; Java 21+ должна быть в PATH).

Память: `JAVA_OPTS="-Xms4G -Xmx6G" ./start.sh`. Настройки — в `server.properties` (шаблон: `server.properties.example`).
Стать оператором: введите `op <ник>` в консоли сервера.

## Порты

| Порт | Протокол | Зачем |
|------|----------|-------|
| 25565 | TCP | игра |
| 24454 | UDP | Simple Voice Chat (игра в сборке завязана на голосовой чат) |

## Клиент

Игрокам нужна та же сборка: импортируйте `.mrpack` с Modrinth в Prism Launcher / Modrinth App (**Extended 3.8.141**, не оригинальную 1.4.1).

## Что установлено на сервере

Моды из `modrinth.index.json` сборки, помеченные как серверные (Wathe, Wathe Extended, Noelle's Roles, Supplementaries, Simple Voice Chat и др.); клиентские (Sodium, Iris, ModMenu и т.д.) пропущены. Дополнительно ставится Carpet (`EXTRA_MODS`, на клиенте необязателен). Карта из сборки копируется в `world/`.

Обновление сборки: поправьте `PACK_URL` в `install.sh` (или `PACK_URL=... ./install.sh`). `mods/` пересоздаётся, `config/` и существующий `world/` не перезаписываются.
