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
| [okppg-on-this-day](plugins/okppg-on-this-day) | 0.2.1 | Hook SessionStart que inyecta un saludo aleatorio con personalidad + una efeméride del día actual (API de Wikipedia "On This Day" con fallback offline en español) para que Claude abra la conversación con tono jocoso. |
