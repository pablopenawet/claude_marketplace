# okppg-marketplace

Marketplace de plugins de [Claude Code](https://docs.claude.com/en/docs/claude-code/overview).

## Estructura

```
.
├── .claude-plugin/
│   └── marketplace.json   # Manifest del marketplace
└── plugins/               # Cada subdirectorio aquí es un plugin
```

## Instalación

Desde Claude Code:

```
/plugin marketplace add pablopenawet/claude_marketplace
```

Luego instala plugins con:

```
/plugin install <nombre-del-plugin>@okppg-marketplace
```

## Plugins

| Plugin | Versión | Descripción |
|---|---|---|
| [okppg-on-this-day](plugins/okppg-on-this-day) | 0.4.1 | Hook SessionStart que inyecta un saludo aleatorio con personalidad + una efeméride del día actual con sesgo cultural (cine/música/arte/literatura; API de Wikipedia "On This Day" con fallback offline en español), y de vez en cuando una efeméride de la cultura gallega, para que Claude abra la conversación con tono jocoso. |
