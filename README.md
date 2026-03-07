### Hotspot MS

 

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app hotspot_ms
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/hotspot_ms
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### Hotspot Portal CSS (Tailwind)

Hotspot portal pages under `hotspot_ms/www/hotspot/` now use a locally compiled Tailwind build:

- Source: `hotspot_ms/public/tailwind/hotspot_portal.css`
- Output: `hotspot_ms/public/css/hotspot_portal.css`
- Tailwind config: `tailwind.config.js`

Build once:

```bash
cd apps/hotspot_ms
npm install
npm run build:css
```

Watch during UI edits:

```bash
cd apps/hotspot_ms
npm run watch:css
```

### License

mit
