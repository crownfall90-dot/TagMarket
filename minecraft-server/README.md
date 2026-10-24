# The Last Voyage of the Harpy Express — сервер

Minecraft **1.21.1**, Fabric loader **0.17.2**, сборка [harpy-express 1.4.1](https://modrinth.com/modpack/harpy-express) (Modrinth).

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

Игрокам нужна та же сборка: импортируйте `.mrpack` с Modrinth в Prism Launcher / Modrinth App (версия 1.4.1).

## Что установлено на сервере

Fabric API, Wathe (Train Murder Mystery), Simple Voice Chat, Sound Physics Remastered, Carpet, Cloth Config, Placeholder API, Ratatouille.
Клиентские `modmenu` и `InvMove` пропущены. Карта `The Harpy Express` копируется в `world/`.

Обновление сборки: поправьте `PACK_URL` в `install.sh`; существующий `world/` не перезаписывается.
